from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def now() -> datetime:
    return datetime.now(timezone.utc)


# Role personelu. Grupa to adresat zbiorczy uwag (np. cała pracownia).
ROLES = {
    "radiologist": "Radiolog",
    "attending": "Lekarz prowadzący",
    "technician": "Technik / pracownia",
    "registration": "Rejestracja",
}
ROLE_GROUPS = {"technician": "Pracownia diagnostyczna", "registration": "Rejestracja"}


class Physician(Base):
    """Personel: lekarze, technicy, rejestracja."""

    __tablename__ = "physicians"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    # Nazwisko w formacie DICOM (Nazwisko^Imię), do dopasowania ReferringPhysicianName
    dicom_name: Mapped[str] = mapped_column(String(200), default="", index=True)
    email: Mapped[str] = mapped_column(String(200), default="")
    phone: Mapped[str] = mapped_column(String(50), default="")
    role: Mapped[str] = mapped_column(String(20))
    # Modalności opisywane przez radiologa, np. "CT,MR"; puste = wszystkie
    modalities: Mapped[str] = mapped_column(String(100), default="")
    login: Mapped[str] = mapped_column(String(100), default="", index=True)
    on_call: Mapped[bool] = mapped_column(Boolean, default=False)  # dyżurny - 2. stopień eskalacji
    is_head: Mapped[bool] = mapped_column(Boolean, default=False)  # ordynator - 3. stopień eskalacji
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class Study(Base):
    __tablename__ = "studies"

    id: Mapped[int] = mapped_column(primary_key=True)
    orthanc_id: Mapped[str] = mapped_column(String(64), unique=True)
    study_instance_uid: Mapped[str] = mapped_column(String(128), index=True)
    patient_id: Mapped[str] = mapped_column(String(64), default="", index=True)
    patient_name: Mapped[str] = mapped_column(String(200), default="")
    patient_phone: Mapped[str] = mapped_column(String(30), default="")
    patient_sms_consent: Mapped[bool] = mapped_column(Boolean, default=False)
    modality: Mapped[str] = mapped_column(String(20), default="")
    description: Mapped[str] = mapped_column(String(300), default="")
    study_date: Mapped[str] = mapped_column(String(8), default="")
    referring_physician: Mapped[str] = mapped_column(String(200), default="")
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    priority: Mapped[str] = mapped_column(String(10), default="routine")  # routine | urgent
    status: Mapped[str] = mapped_column(String(20), default="new")  # new | assigned | reported
    repeat_requested: Mapped[bool] = mapped_column(Boolean, default=False)
    critical_finding: Mapped[bool] = mapped_column(Boolean, default=False)
    critical_note: Mapped[str] = mapped_column(Text, default="")
    report: Mapped[str] = mapped_column(Text, default="")
    reported_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reported_by: Mapped[str] = mapped_column(String(100), default="")

    # Druga opinia
    second_reader_id: Mapped[int | None] = mapped_column(ForeignKey("physicians.id"), nullable=True)
    second_request: Mapped[str] = mapped_column(Text, default="")
    second_report: Mapped[str] = mapped_column(Text, default="")
    second_reported_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    radiologist_id: Mapped[int | None] = mapped_column(ForeignKey("physicians.id"), nullable=True)
    attending_id: Mapped[int | None] = mapped_column(ForeignKey("physicians.id"), nullable=True)
    radiologist: Mapped[Physician | None] = relationship(foreign_keys=[radiologist_id])
    attending: Mapped[Physician | None] = relationship(foreign_keys=[attending_id])
    second_reader: Mapped[Physician | None] = relationship(foreign_keys=[second_reader_id])
    notes: Mapped[list["StudyNote"]] = relationship(order_by="StudyNote.created_at")
    alerts: Mapped[list["CriticalAlert"]] = relationship(order_by="CriticalAlert.created_at")


class CriticalAlert(Base):
    """Wynik krytyczny czekający na potwierdzenie odbioru. Bez potwierdzenia jest eskalowany."""

    __tablename__ = "critical_alerts"

    id: Mapped[int] = mapped_column(primary_key=True)
    study_id: Mapped[int] = mapped_column(ForeignKey("studies.id"), index=True)
    raised_by: Mapped[str] = mapped_column(String(100))
    note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    # 0 = e-mail do prowadzącego, 1 = SMS do prowadzącego, 2 = dyżurny, 3 = ordynator
    level: Mapped[int] = mapped_column(Integer, default=0)
    last_escalated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    acknowledged_by: Mapped[str] = mapped_column(String(100), default="")


class Notification(Base):
    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(primary_key=True)
    study_id: Mapped[int] = mapped_column(ForeignKey("studies.id"), index=True)
    physician_id: Mapped[int | None] = mapped_column(ForeignKey("physicians.id"), nullable=True)
    recipient: Mapped[str] = mapped_column(String(200), default="")
    channel: Mapped[str] = mapped_column(String(20))  # email | sms
    reason: Mapped[str] = mapped_column(String(50))
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    success: Mapped[bool] = mapped_column(Boolean, default=False)
    error: Mapped[str] = mapped_column(Text, default="")


class AuditLog(Base):
    """Kto i kiedy oglądał / zmieniał badanie (wymóg RODO dla danych medycznych)."""

    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(primary_key=True)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)
    actor: Mapped[str] = mapped_column(String(100))
    action: Mapped[str] = mapped_column(String(50))
    study_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    details: Mapped[str] = mapped_column(Text, default="")


class IngestState(Base):
    __tablename__ = "ingest_state"

    id: Mapped[int] = mapped_column(primary_key=True)
    last_change_seq: Mapped[int] = mapped_column(Integer, default=0)


class StudyNote(Base):
    """Uwaga do badania. Usunięcie jest miękkie: zostaje ślad, kto i kiedy ją usunął."""

    __tablename__ = "study_notes"

    id: Mapped[int] = mapped_column(primary_key=True)
    study_id: Mapped[int] = mapped_column(ForeignKey("studies.id"), index=True)
    author: Mapped[str] = mapped_column(String(100))
    # Adresat: konkretna osoba albo grupa (np. "Pracownia diagnostyczna", "Rejestracja")
    recipient_physician_id: Mapped[int | None] = mapped_column(ForeignKey("physicians.id"), nullable=True)
    recipient_group: Mapped[str] = mapped_column(String(100), default="")
    # Loginy osób oznaczonych przez @login w treści, rozdzielone przecinkami
    mentions: Mapped[str] = mapped_column(String(500), default="")
    purpose: Mapped[str] = mapped_column(String(30))
    text: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    done_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    done_by: Mapped[str] = mapped_column(String(100), default="")
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deleted_by: Mapped[str] = mapped_column(String(100), default="")
    recipient: Mapped[Physician | None] = relationship()


class ReportTemplate(Base):
    __tablename__ = "report_templates"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    modality: Mapped[str] = mapped_column(String(20), default="")  # puste = dowolna
    body: Mapped[str] = mapped_column(Text)
    created_by: Mapped[str] = mapped_column(String(100), default="system")
