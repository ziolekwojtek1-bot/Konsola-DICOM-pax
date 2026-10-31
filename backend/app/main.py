import logging
import re
import statistics
import threading
from collections import Counter
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from . import escalation, ingest
from .db import Base, SessionLocal, engine, get_db
from .escalation import LEVELS, _as_utc, raise_alert
from .models import (ROLE_GROUPS, ROLES, AuditLog, CriticalAlert, Notification, Physician, ReportTemplate,
                     Study, StudyNote)
from .notify import notify, notify_patient
from .config import settings
from .demo_seed import seed_demo_staff
from .templates_seed import seed_templates

logging.basicConfig(level=logging.INFO)
STATIC = Path(__file__).parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        seed_templates(db)
        if settings.demo_mode:
            seed_demo_staff(db)
    stop = threading.Event()
    for target in (ingest.run_forever, escalation.run_forever):
        threading.Thread(target=target, args=(stop,), daemon=True).start()
    yield
    stop.set()


app = FastAPI(title="PACS wewnętrzny", lifespan=lifespan)


def current_user(x_remote_user: str = Header(default="")) -> str:
    # Uwierzytelnienie robi nginx; backend nie jest dostępny z zewnątrz bez niego.
    return x_remote_user or "anonim"


def audit(db: Session, actor: str, action: str, study_id: int | None = None, details: str = "") -> None:
    db.add(AuditLog(actor=actor, action=action, study_id=study_id, details=details))


def person_for(db: Session, login: str) -> Physician | None:
    return db.scalar(select(Physician).where(Physician.login == login, Physician.active.is_(True)))


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ---------- modele wejściowe ----------

class PhysicianIn(BaseModel):
    name: str
    role: str
    dicom_name: str = ""
    email: str = ""
    phone: str = ""
    modalities: str = ""
    login: str = ""
    on_call: bool = False
    is_head: bool = False
    active: bool = True


class AssignIn(BaseModel):
    radiologist_id: int


class CriticalIn(BaseModel):
    note: str


class ReportIn(BaseModel):
    text: str
    critical: bool = False


class ContactIn(BaseModel):
    phone: str
    sms_consent: bool


class SecondOpinionIn(BaseModel):
    radiologist_id: int
    request: str


class TextIn(BaseModel):
    text: str


class TemplateIn(BaseModel):
    name: str
    modality: str = ""
    body: str


NOTE_PURPOSES = {
    "informacja": "Informacja",
    "pytanie": "Pytanie",
    "prosba_o_badanie": "Prośba o dodatkowe badanie / projekcję",
    "powtorz_badanie": "Powtórzenie badania",
    "kontakt_z_pacjentem": "Kontakt z pacjentem",
    "pilne": "Pilne",
}
NOTE_GROUPS = ["Pracownia diagnostyczna", "Rejestracja", "Wszyscy lekarze"]
MENTION_RE = re.compile(r"@([\w.\-]+)")


class NoteIn(BaseModel):
    text: str
    purpose: str
    recipient_physician_id: int | None = None
    recipient_group: str = ""


# ---------- serializacja ----------

def alert_out(a: CriticalAlert) -> dict:
    return {"id": a.id, "raised_by": a.raised_by, "note": a.note, "created_at": a.created_at,
            "level": a.level, "level_label": LEVELS[a.level],
            "acknowledged_at": a.acknowledged_at, "acknowledged_by": a.acknowledged_by}


def study_out(s: Study) -> dict:
    open_alert = next((a for a in s.alerts if a.acknowledged_at is None), None)
    overdue = s.status != "reported" and s.due_at is not None and _as_utc(s.due_at) < utcnow()
    return {
        "id": s.id, "study_instance_uid": s.study_instance_uid,
        "patient_id": s.patient_id, "patient_name": s.patient_name.replace("^", " "),
        "patient_phone": s.patient_phone, "patient_sms_consent": s.patient_sms_consent,
        "modality": s.modality, "description": s.description, "study_date": s.study_date,
        "received_at": s.received_at, "due_at": s.due_at, "overdue": overdue,
        "priority": s.priority, "status": s.status, "repeat_requested": s.repeat_requested,
        "critical_finding": s.critical_finding, "critical_note": s.critical_note,
        "critical_unacknowledged": open_alert is not None,
        "alerts": [alert_out(a) for a in s.alerts],
        "report": s.report, "reported_at": s.reported_at, "reported_by": s.reported_by,
        "referring_physician": s.referring_physician.replace("^", " "),
        "radiologist": s.radiologist.name if s.radiologist else None,
        "radiologist_id": s.radiologist_id,
        "attending": s.attending.name if s.attending else None,
        "second_reader": s.second_reader.name if s.second_reader else None,
        "second_request": s.second_request, "second_report": s.second_report,
        "second_reported_at": s.second_reported_at,
        "open_notes": sum(1 for n in s.notes if n.deleted_at is None and n.done_at is None),
        "viewer_url": f"/ohif/viewer?StudyInstanceUIDs={s.study_instance_uid}",
    }


def note_out(n: StudyNote) -> dict:
    return {
        "id": n.id, "study_id": n.study_id, "author": n.author, "purpose": n.purpose,
        "purpose_label": NOTE_PURPOSES.get(n.purpose, n.purpose), "text": n.text,
        "recipient": n.recipient.name if n.recipient else n.recipient_group,
        "mentions": [m for m in n.mentions.split(",") if m],
        "created_at": n.created_at, "done_at": n.done_at, "done_by": n.done_by,
        "deleted_at": n.deleted_at, "deleted_by": n.deleted_by,
    }


def get_study(db: Session, study_id: int) -> Study:
    study = db.get(Study, study_id)
    if not study:
        raise HTTPException(404, "Nie ma takiego badania")
    return study


def get_radiologist(db: Session, physician_id: int) -> Physician:
    p = db.get(Physician, physician_id)
    if not p or p.role != "radiologist":
        raise HTTPException(400, "Wybrana osoba nie jest radiologiem")
    return p


# ---------- strona i użytkownik ----------

@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


@app.get("/api/me")
def me(db: Session = Depends(get_db), user: str = Depends(current_user)):
    p = person_for(db, user)
    return {"login": user, "name": p.name if p else user, "physician_id": p.id if p else None,
            "role": p.role if p else None, "role_label": ROLES.get(p.role, "") if p else "",
            "demo": settings.demo_mode}


# ---------- badania ----------

@app.get("/api/studies")
def list_studies(status: str | None = None, mine: bool = False, q: str = "",
                 db: Session = Depends(get_db), user: str = Depends(current_user)):
    query = select(Study)
    if status:
        query = query.where(Study.status == status)
    if mine:
        p = person_for(db, user)
        pid = p.id if p else -1
        query = query.where(or_(Study.radiologist_id == pid, Study.second_reader_id == pid,
                                Study.attending_id == pid))
    if q:
        like = f"%{q}%"
        query = query.where(or_(Study.patient_name.ilike(like), Study.patient_id.ilike(like),
                                Study.description.ilike(like)))
    # Pilne na górze, potem najkrótszy termin opisu
    query = query.order_by((Study.priority == "urgent").desc(), (Study.status == "reported"),
                           Study.due_at, Study.received_at)
    return [study_out(s) for s in db.scalars(query.limit(500))]


@app.get("/api/studies/{study_id}")
def read_study(study_id: int, db: Session = Depends(get_db), user: str = Depends(current_user)):
    study = get_study(db, study_id)
    audit(db, user, "study_viewed", study.id)
    db.commit()
    return study_out(study)


@app.get("/api/studies/{study_id}/priors")
def prior_studies(study_id: int, db: Session = Depends(get_db)):
    study = get_study(db, study_id)
    if not study.patient_id:
        return []
    rows = db.scalars(select(Study).where(Study.patient_id == study.patient_id, Study.id != study.id)
                      .order_by(Study.received_at.desc()).limit(20))
    return [study_out(s) for s in rows]


@app.patch("/api/studies/{study_id}/patient-contact")
def patient_contact(study_id: int, body: ContactIn, db: Session = Depends(get_db),
                    user: str = Depends(current_user)):
    study = get_study(db, study_id)
    study.patient_phone = body.phone.strip()
    study.patient_sms_consent = body.sms_consent
    audit(db, user, "patient_contact_changed", study.id, f"sms_consent={body.sms_consent}")
    db.commit()
    return study_out(study)


@app.post("/api/studies/{study_id}/assign")
def assign(study_id: int, body: AssignIn, db: Session = Depends(get_db), user: str = Depends(current_user)):
    study = get_study(db, study_id)
    study.radiologist = get_radiologist(db, body.radiologist_id)
    if study.status == "new":
        study.status = "assigned"
    audit(db, user, "study_assigned", study.id, f"radiologist={body.radiologist_id}")
    if study.priority == "urgent":
        notify(db, study.radiologist, study, "urgent_study")
    db.commit()
    return study_out(study)


def _flag_critical(db: Session, study: Study, note: str, user: str) -> None:
    study.critical_finding = True
    study.critical_note = note
    study.priority = "urgent"
    audit(db, user, "critical_finding", study.id, note)
    if not any(a.acknowledged_at is None for a in study.alerts):
        raise_alert(db, study, user, note)


@app.post("/api/studies/{study_id}/critical")
def flag_critical(study_id: int, body: CriticalIn, db: Session = Depends(get_db),
                  user: str = Depends(current_user)):
    study = get_study(db, study_id)
    _flag_critical(db, study, body.note, user)
    db.commit()
    db.refresh(study)
    return study_out(study)


@app.post("/api/studies/{study_id}/critical/ack")
def acknowledge_critical(study_id: int, db: Session = Depends(get_db), user: str = Depends(current_user)):
    study = get_study(db, study_id)
    open_alerts = [a for a in study.alerts if a.acknowledged_at is None]
    if not open_alerts:
        raise HTTPException(400, "Brak niepotwierdzonych wyników krytycznych")
    for a in open_alerts:
        a.acknowledged_at = utcnow()
        a.acknowledged_by = user
    audit(db, user, "critical_acknowledged", study.id)
    db.commit()
    return study_out(study)


@app.post("/api/studies/{study_id}/report")
def save_report(study_id: int, body: ReportIn, db: Session = Depends(get_db), user: str = Depends(current_user)):
    study = get_study(db, study_id)
    first_time = study.status != "reported"
    study.report = body.text
    study.status = "reported"
    study.reported_at = utcnow()
    study.reported_by = user
    audit(db, user, "report_saved", study.id)
    if body.critical:
        _flag_critical(db, study, "Wynik krytyczny wskazany w opisie", user)
    if first_time and study.patient_sms_consent:
        notify_patient(db, study)
    db.commit()
    db.refresh(study)
    return study_out(study)


@app.post("/api/studies/{study_id}/second-opinion")
def request_second_opinion(study_id: int, body: SecondOpinionIn, db: Session = Depends(get_db),
                           user: str = Depends(current_user)):
    study = get_study(db, study_id)
    reader = get_radiologist(db, body.radiologist_id)
    if reader.id == study.radiologist_id:
        raise HTTPException(400, "Druga opinia musi pochodzić od innego radiologa")
    study.second_reader = reader
    study.second_request = body.request
    study.second_report = ""
    study.second_reported_at = None
    audit(db, user, "second_opinion_requested", study.id, f"radiologist={reader.id}")
    notify(db, reader, study, "second_opinion", f"Pytanie: {body.request}")
    db.commit()
    return study_out(study)


@app.post("/api/studies/{study_id}/second-report")
def save_second_report(study_id: int, body: TextIn, db: Session = Depends(get_db),
                       user: str = Depends(current_user)):
    study = get_study(db, study_id)
    if not study.second_reader_id:
        raise HTTPException(400, "Dla tego badania nie zlecono drugiej opinii")
    study.second_report = body.text
    study.second_reported_at = utcnow()
    audit(db, user, "second_report_saved", study.id)
    db.commit()
    return study_out(study)


@app.post("/api/studies/{study_id}/repeat")
def request_repeat(study_id: int, body: TextIn, db: Session = Depends(get_db), user: str = Depends(current_user)):
    study = get_study(db, study_id)
    study.repeat_requested = True
    db.add(StudyNote(study_id=study.id, author=user, purpose="powtorz_badanie", text=body.text,
                     recipient_group="Pracownia diagnostyczna"))
    audit(db, user, "repeat_requested", study.id, body.text)
    for tech in db.scalars(select(Physician).where(Physician.role == "technician", Physician.active.is_(True))):
        notify(db, tech, study, "repeat_request", f"Powód: {body.text}")
    db.commit()
    db.refresh(study)
    return study_out(study)


@app.get("/api/studies/{study_id}/notifications")
def study_notifications(study_id: int, db: Session = Depends(get_db)):
    rows = db.scalars(select(Notification).where(Notification.study_id == study_id).order_by(Notification.sent_at))
    return [{"recipient": n.recipient, "channel": n.channel, "reason": n.reason, "sent_at": n.sent_at,
             "success": n.success, "error": n.error} for n in rows]


# ---------- uwagi i skrzynka "Do mnie" ----------

@app.get("/api/note-options")
def note_options(db: Session = Depends(get_db)):
    people = db.scalars(select(Physician).where(Physician.active.is_(True)).order_by(Physician.name))
    return {"purposes": NOTE_PURPOSES, "groups": NOTE_GROUPS,
            "physicians": [{"id": p.id, "name": p.name, "login": p.login, "role": ROLES.get(p.role, p.role)}
                           for p in people]}


@app.get("/api/studies/{study_id}/notes")
def list_notes(study_id: int, db: Session = Depends(get_db)):
    get_study(db, study_id)
    rows = db.scalars(select(StudyNote).where(StudyNote.study_id == study_id).order_by(StudyNote.created_at))
    return [note_out(n) for n in rows]


@app.post("/api/studies/{study_id}/notes")
def add_note(study_id: int, body: NoteIn, db: Session = Depends(get_db), user: str = Depends(current_user)):
    study = get_study(db, study_id)
    if body.purpose not in NOTE_PURPOSES:
        raise HTTPException(400, "Nieznany cel uwagi")
    if not body.text.strip():
        raise HTTPException(400, "Uwaga nie może być pusta")
    if body.recipient_physician_id is None and body.recipient_group not in NOTE_GROUPS:
        raise HTTPException(400, "Wybierz adresata uwagi")
    recipient = db.get(Physician, body.recipient_physician_id) if body.recipient_physician_id else None
    if body.recipient_physician_id and not recipient:
        raise HTTPException(400, "Nie ma takiej osoby")
    mentioned = [p for p in (person_for(db, login) for login in dict.fromkeys(MENTION_RE.findall(body.text)))
                 if p]
    note = StudyNote(study_id=study.id, author=user, purpose=body.purpose, text=body.text.strip(),
                     recipient=recipient, recipient_group="" if recipient else body.recipient_group,
                     mentions=",".join(p.login for p in mentioned))
    db.add(note)
    db.flush()
    audit(db, user, "note_added", study.id, f"note={note.id}")
    for p in mentioned:
        notify(db, p, study, "mention", f"{user}: {note.text}")
    db.commit()
    return note_out(note)


def _get_note(db: Session, study_id: int, note_id: int) -> StudyNote:
    note = db.get(StudyNote, note_id)
    if not note or note.study_id != study_id:
        raise HTTPException(404, "Nie ma takiej uwagi")
    return note


@app.post("/api/studies/{study_id}/notes/{note_id}/done")
def complete_note(study_id: int, note_id: int, db: Session = Depends(get_db), user: str = Depends(current_user)):
    note = _get_note(db, study_id, note_id)
    if note.done_at is None:
        note.done_at = utcnow()
        note.done_by = user
        audit(db, user, "note_done", study_id, f"note={note.id}")
        if note.purpose == "powtorz_badanie":
            study = get_study(db, study_id)
            study.repeat_requested = any(
                n.purpose == "powtorz_badanie" and n.done_at is None and n.deleted_at is None for n in study.notes)
        db.commit()
    return note_out(note)


@app.delete("/api/studies/{study_id}/notes/{note_id}")
def delete_note(study_id: int, note_id: int, db: Session = Depends(get_db), user: str = Depends(current_user)):
    note = _get_note(db, study_id, note_id)
    if note.deleted_at is None:
        note.deleted_at = utcnow()
        note.deleted_by = user
        audit(db, user, "note_deleted", study_id, f"note={note.id}")
        db.commit()
    return note_out(note)


@app.get("/api/inbox")
def inbox(include_done: bool = False, db: Session = Depends(get_db), user: str = Depends(current_user)):
    p = person_for(db, user)
    groups = []
    if p and p.role in ("radiologist", "attending"):
        groups.append("Wszyscy lekarze")
    if p and p.role in ROLE_GROUPS:
        groups.append(ROLE_GROUPS[p.role])
    conditions = [StudyNote.mentions.contains(user), StudyNote.recipient_group.in_(groups)]
    if p:
        conditions.append(StudyNote.recipient_physician_id == p.id)
    query = select(StudyNote).where(StudyNote.deleted_at.is_(None), or_(*conditions))
    if not include_done:
        query = query.where(StudyNote.done_at.is_(None))
    # contains() to dopasowanie podciągu, więc wzmianki sprawdzamy dokładnie jeszcze raz
    notes = [n for n in db.scalars(query.order_by(StudyNote.created_at.desc()))
             if (p and n.recipient_physician_id == p.id) or n.recipient_group in groups
             or user in n.mentions.split(",")]
    alerts = []
    if p:
        visible = [Study.attending_id == p.id]
        if p.on_call:
            visible.append(CriticalAlert.level >= 2)
        if p.is_head:
            visible.append(CriticalAlert.level >= 3)
        alerts = list(db.scalars(select(CriticalAlert).join(Study).where(
            CriticalAlert.acknowledged_at.is_(None), or_(*visible))))
    studies = {s.id: s for s in db.scalars(select(Study).where(
        Study.id.in_({n.study_id for n in notes} | {a.study_id for a in alerts})))} if notes or alerts else {}
    return {
        "critical": [alert_out(a) | {"study": study_out(studies[a.study_id])} for a in alerts],
        "notes": [note_out(n) | {"study_label": f"{studies[n.study_id].modality} {studies[n.study_id].description}",
                                 "patient": studies[n.study_id].patient_name.replace("^", " ")} for n in notes],
    }


# ---------- szablony opisów ----------

@app.get("/api/templates")
def list_templates(modality: str = "", db: Session = Depends(get_db)):
    query = select(ReportTemplate).order_by(ReportTemplate.name)
    if modality:
        query = query.where(or_(ReportTemplate.modality == modality, ReportTemplate.modality == ""))
    return [{"id": t.id, "name": t.name, "modality": t.modality, "body": t.body, "created_by": t.created_by}
            for t in db.scalars(query)]


@app.post("/api/templates")
def create_template(body: TemplateIn, db: Session = Depends(get_db), user: str = Depends(current_user)):
    t = ReportTemplate(name=body.name, modality=body.modality.upper(), body=body.body, created_by=user)
    db.add(t)
    db.commit()
    return {"id": t.id, "name": t.name, "modality": t.modality, "body": t.body, "created_by": t.created_by}


@app.delete("/api/templates/{template_id}")
def delete_template(template_id: int, db: Session = Depends(get_db), user: str = Depends(current_user)):
    t = db.get(ReportTemplate, template_id)
    if not t:
        raise HTTPException(404, "Nie ma takiego szablonu")
    db.delete(t)
    audit(db, user, "template_deleted", details=t.name)
    db.commit()
    return {"ok": True}


# ---------- personel ----------

def physician_out(p: Physician) -> dict:
    return PhysicianIn.model_validate(p, from_attributes=True).model_dump() | {
        "id": p.id, "role_label": ROLES.get(p.role, p.role)}


@app.get("/api/physicians")
def list_physicians(db: Session = Depends(get_db)):
    return [physician_out(p) for p in db.scalars(select(Physician).order_by(Physician.role, Physician.name))]


@app.post("/api/physicians")
def create_physician(body: PhysicianIn, db: Session = Depends(get_db), user: str = Depends(current_user)):
    if body.role not in ROLES:
        raise HTTPException(400, f"Rola musi być jedną z: {', '.join(ROLES)}")
    p = Physician(**body.model_dump())
    db.add(p)
    db.flush()
    audit(db, user, "physician_created", details=f"id={p.id}")
    db.commit()
    return physician_out(p)


@app.put("/api/physicians/{physician_id}")
def update_physician(physician_id: int, body: PhysicianIn, db: Session = Depends(get_db),
                     user: str = Depends(current_user)):
    p = db.get(Physician, physician_id)
    if not p:
        raise HTTPException(404, "Nie ma takiej osoby")
    if body.role not in ROLES:
        raise HTTPException(400, f"Rola musi być jedną z: {', '.join(ROLES)}")
    for key, value in body.model_dump().items():
        setattr(p, key, value)
    audit(db, user, "physician_updated", details=f"id={p.id}")
    db.commit()
    return physician_out(p)


# ---------- statystyki ----------

@app.get("/api/stats")
def stats(days: int = 30, db: Session = Depends(get_db)):
    since = utcnow() - timedelta(days=days)
    studies = list(db.scalars(select(Study).where(Study.received_at >= since)))
    now = utcnow()

    def minutes(a, b):
        return (_as_utc(b) - _as_utc(a)).total_seconds() / 60

    turnaround = {}
    for prio in ("urgent", "routine"):
        values = [minutes(s.received_at, s.reported_at) for s in studies if s.priority == prio and s.reported_at]
        turnaround[prio] = round(statistics.median(values)) if values else None
    reported_in_time = [s for s in studies if s.reported_at and s.due_at]
    alerts = list(db.scalars(select(CriticalAlert).where(CriticalAlert.created_at >= since)))
    ack = [minutes(a.created_at, a.acknowledged_at) for a in alerts if a.acknowledged_at]
    open_load = Counter(s.radiologist.name for s in studies if s.status != "reported" and s.radiologist)
    per_day = Counter(_as_utc(s.received_at).date().isoformat() for s in studies)
    return {
        "days": days,
        "total": len(studies),
        "by_status": dict(Counter(s.status for s in studies)),
        "by_modality": dict(Counter(s.modality for s in studies)),
        "overdue_open": sum(1 for s in studies if s.status != "reported" and s.due_at and _as_utc(s.due_at) < now),
        "on_time_pct": round(100 * sum(1 for s in reported_in_time if _as_utc(s.reported_at) <= _as_utc(s.due_at))
                             / len(reported_in_time)) if reported_in_time else None,
        "median_turnaround_minutes": turnaround,
        "critical": {"total": len(alerts), "acknowledged": len(ack),
                     "median_ack_minutes": round(statistics.median(ack), 1) if ack else None,
                     "escalated": sum(1 for a in alerts if a.level > 0)},
        "open_per_radiologist": dict(open_load),
        "per_day": dict(sorted(per_day.items())),
        "repeat_requests": sum(1 for s in studies if s.repeat_requested),
    }
