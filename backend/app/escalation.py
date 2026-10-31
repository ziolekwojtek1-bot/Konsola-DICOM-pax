"""Eskalacja niepotwierdzonych wyników krytycznych oraz ostrzeżenia o zbliżającym się terminie opisu."""

import logging
import threading
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import settings
from .db import SessionLocal
from .models import AuditLog, CriticalAlert, Notification, Physician, Study
from .notify import notify

log = logging.getLogger("pacs.escalation")
LEVELS = {0: "e-mail do lekarza prowadzącego", 1: "SMS do lekarza prowadzącego",
          2: "lekarz dyżurny", 3: "ordynator"}


def _as_utc(dt: datetime) -> datetime:
    # SQLite zwraca daty bez strefy; PostgreSQL ze strefą.
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def raise_alert(db: Session, study: Study, actor: str, note: str) -> CriticalAlert:
    alert = CriticalAlert(study_id=study.id, raised_by=actor, note=note)
    db.add(alert)
    db.flush()
    notify(db, study.attending, study, "critical_finding", f"Uwagi: {note}")
    return alert


def _escalate(db: Session, alert: CriticalAlert, study: Study) -> None:
    alert.level += 1
    alert.last_escalated_at = datetime.now(timezone.utc)
    if alert.level == 1:
        notify(db, study.attending, study, "critical_escalation", channel="sms")
    else:
        flag = Physician.on_call if alert.level == 2 else Physician.is_head
        for p in db.scalars(select(Physician).where(flag.is_(True), Physician.active.is_(True))):
            notify(db, p, study, "critical_escalation", f"Uwagi: {alert.note}")
            notify(db, p, study, "critical_escalation", channel="sms")
    db.add(AuditLog(actor="system", action="critical_escalated", study_id=study.id,
                    details=f"level={alert.level} ({LEVELS[alert.level]})"))


def check_once(db: Session, at: datetime | None = None) -> None:
    at = _as_utc(at or datetime.now(timezone.utc))
    step = timedelta(minutes=settings.critical_escalation_minutes)
    for alert in db.scalars(select(CriticalAlert).where(CriticalAlert.acknowledged_at.is_(None),
                                                        CriticalAlert.level < 3)):
        if at - _as_utc(alert.last_escalated_at) >= step:
            _escalate(db, alert, db.get(Study, alert.study_id))

    # Ostrzeżenie o terminie opisu: raz, gdy zostało mniej niż 20% czasu.
    open_studies = db.scalars(select(Study).where(Study.status != "reported", Study.due_at.is_not(None)))
    for study in open_studies:
        due, received = _as_utc(study.due_at), _as_utc(study.received_at)
        if at < due - (due - received) * 0.2:
            continue
        warned = db.scalar(select(Notification.id).where(Notification.study_id == study.id,
                                                         Notification.reason == "sla_warning"))
        if not warned:
            notify(db, study.radiologist, study, "sla_warning", f"Termin: {due:%d.%m.%Y %H:%M} UTC")
    db.commit()


def run_forever(stop: threading.Event) -> None:
    while not stop.is_set():
        try:
            with SessionLocal() as db:
                check_once(db)
        except Exception:
            log.exception("Błąd sprawdzania eskalacji")
        stop.wait(30)
