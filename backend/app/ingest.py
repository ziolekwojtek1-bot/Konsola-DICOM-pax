"""Pobiera nowe, kompletne badania z Orthanc i wprowadza je do obiegu opisów."""

import logging
import threading
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import orthanc_client
from .config import settings
from .db import SessionLocal
from .models import AuditLog, IngestState, Study
from .notify import notify
from .routing import find_attending, is_urgent, pick_radiologist

log = logging.getLogger("pacs.ingest")


def due_date(study: Study) -> datetime:
    if study.priority == "urgent":
        return study.received_at + timedelta(minutes=settings.sla_urgent_minutes)
    return study.received_at + timedelta(hours=settings.sla_routine_hours)


def register_study(db: Session, orthanc_id: str, tags: dict[str, str]) -> Study | None:
    if db.scalar(select(Study).where(Study.orthanc_id == orthanc_id)):
        return None
    study = Study(
        orthanc_id=orthanc_id,
        study_instance_uid=tags.get("StudyInstanceUID", ""),
        patient_id=tags.get("PatientID", ""),
        patient_name=tags.get("PatientName", ""),
        modality=tags.get("Modality", "") or tags.get("ModalitiesInStudy", "").split("\\")[0],
        description=tags.get("StudyDescription", ""),
        study_date=tags.get("StudyDate", ""),
        referring_physician=tags.get("ReferringPhysicianName", ""),
        priority="urgent" if is_urgent(tags) else "routine",
    )
    study.received_at = datetime.now(timezone.utc)
    study.due_at = due_date(study)
    study.radiologist = pick_radiologist(db, study.modality)
    study.attending = find_attending(db, study.referring_physician)
    study.status = "assigned" if study.radiologist else "new"
    db.add(study)
    db.flush()
    db.add(AuditLog(actor="system", action="study_received", study_id=study.id,
                    details=f"priority={study.priority} radiologist={study.radiologist_id}"))
    if study.priority == "urgent":
        notify(db, study.radiologist, study, "urgent_study")
    return study


def poll_once() -> int:
    with SessionLocal() as db, orthanc_client.client() as c:
        state = db.get(IngestState, 1) or IngestState(id=1, last_change_seq=0)
        db.add(state)
        changes = orthanc_client.get_changes(c, state.last_change_seq)
        count = 0
        for change in changes["Changes"]:
            if change["ChangeType"] == "StableStudy":
                if register_study(db, change["ID"], orthanc_client.get_study_tags(c, change["ID"])):
                    count += 1
        state.last_change_seq = changes["Last"]
        db.commit()
        return count


def run_forever(stop: threading.Event) -> None:
    while not stop.is_set():
        try:
            n = poll_once()
            if n:
                log.info("Przyjęto %d nowych badań", n)
        except Exception:
            log.exception("Błąd pobierania zmian z Orthanc")
        stop.wait(settings.poll_interval_seconds)
