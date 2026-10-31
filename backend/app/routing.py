"""Wykrywanie pilności oraz wybór radiologa i lekarza prowadzącego dla nowego badania."""

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .config import settings
from .models import Physician, Study


def is_urgent(tags: dict[str, str]) -> bool:
    """Badanie jest pilne, gdy pracownia oznaczyła je priorytetem lub słowem kluczowym."""
    if tags.get("RequestedProcedurePriority", "").upper() in ("STAT", "HIGH"):
        return True
    text = " ".join(
        tags.get(k, "")
        for k in ("StudyDescription", "RequestedProcedureDescription",
                  "PerformedProcedureStepDescription", "ReasonForTheRequestedProcedure")
    ).upper()
    return any(k in text for k in settings.urgent_keyword_list)


def normalize_dicom_name(name: str) -> str:
    return " ".join(name.replace("^", " ").upper().split())


def pick_radiologist(db: Session, modality: str) -> Physician | None:
    """Aktywny radiolog opisujący daną modalność, z najmniejszą liczbą nieopisanych badań."""
    open_count = (
        select(func.count(Study.id))
        .where(Study.radiologist_id == Physician.id, Study.status != "reported")
        .correlate(Physician)
        .scalar_subquery()
    )
    candidates = db.execute(
        select(Physician, open_count)
        .where(Physician.role == "radiologist", Physician.active.is_(True))
        .order_by(open_count, Physician.id)
    ).all()
    for physician, _ in candidates:
        allowed = [m.strip().upper() for m in physician.modalities.split(",") if m.strip()]
        if not allowed or modality.upper() in allowed:
            return physician
    return None


def find_attending(db: Session, referring_physician: str) -> Physician | None:
    target = normalize_dicom_name(referring_physician)
    if not target:
        return None
    for p in db.scalars(select(Physician).where(Physician.role == "attending", Physician.active.is_(True))):
        if target in (normalize_dicom_name(p.dicom_name), normalize_dicom_name(p.name)):
            return p
    return None
