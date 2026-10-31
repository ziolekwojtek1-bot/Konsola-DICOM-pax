import logging
import smtplib
from email.message import EmailMessage

import httpx
from sqlalchemy.orm import Session

from .config import settings
from .models import Notification, Physician, Study

log = logging.getLogger("pacs.notify")

SUBJECTS = {
    "urgent_study": "[PILNE] Nowe badanie do opisu",
    "critical_finding": "[ZAGROŻENIE ŻYCIA] Wynik krytyczny pacjenta - potwierdź odbiór",
    "critical_escalation": "[ZAGROŻENIE ŻYCIA] Niepotwierdzony wynik krytyczny - eskalacja",
    "mention": "Oznaczono Cię w uwadze do badania",
    "second_opinion": "Prośba o drugą opinię",
    "repeat_request": "Prośba o powtórzenie badania",
    "sla_warning": "Zbliża się termin opisu badania",
}


def _send_email(to: str, subject: str, body: str) -> None:
    msg = EmailMessage()
    msg["From"] = settings.smtp_from
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)
    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15) as smtp:
        smtp.starttls()
        if settings.smtp_user:
            smtp.login(settings.smtp_user, settings.smtp_password)
        smtp.send_message(msg)


def _send_sms(phone: str, text: str) -> None:
    # Format zgodny z SMSAPI.pl; inny dostawca = zmiana tej funkcji.
    httpx.post(settings.sms_api_url, timeout=15,
               headers={"Authorization": f"Bearer {settings.sms_api_token}"},
               data={"to": phone, "message": text, "from": settings.sms_sender, "format": "json"},
               ).raise_for_status()


def _deliver(db: Session, n: Notification, send) -> bool:
    try:
        send()
        n.success = True
    except Exception as exc:  # powiadomienie nie może zatrzymać pracy systemu
        n.error = str(exc)
        log.error("Powiadomienie %s (%s) do %s nieudane: %s", n.reason, n.channel, n.recipient, exc)
    db.add(n)
    return n.success


def notify(db: Session, physician: Physician | None, study: Study, reason: str, extra: str = "",
           channel: str = "email") -> bool:
    if physician is None:
        log.warning("Brak adresata powiadomienia (%s) dla badania %s", reason, study.id)
        return False
    # Dane pacjenta nie trafiają do treści - tylko link do systemu wewnętrznego.
    link = f"{settings.public_base_url}/#study-{study.id}"
    n = Notification(study_id=study.id, physician_id=physician.id, channel=channel, reason=reason,
                     recipient=physician.name)
    if channel == "sms":
        text = f"{SUBJECTS[reason]}. {study.modality} {link}"

        def send():
            if not settings.sms_api_url:
                raise RuntimeError("Bramka SMS nie jest skonfigurowana")
            if not physician.phone:
                raise RuntimeError("brak numeru telefonu")
            _send_sms(physician.phone, text)
    else:
        body = (f"{SUBJECTS[reason]}\n\nModalność: {study.modality}\nBadanie: {study.description}\n"
                f"{extra}\n\nOtwórz w systemie: {link}\n")

        def send():
            if not settings.smtp_host:
                raise RuntimeError("SMTP nie jest skonfigurowany")
            if not physician.email:
                raise RuntimeError("brak adresu e-mail")
            _send_email(physician.email, SUBJECTS[reason], body)
    return _deliver(db, n, send)


def notify_patient(db: Session, study: Study) -> bool:
    n = Notification(study_id=study.id, channel="sms", reason="patient_result_ready", recipient="pacjent")

    def send():
        if not (study.patient_sms_consent and study.patient_phone):
            raise RuntimeError("brak zgody pacjenta lub numeru telefonu")
        if not settings.sms_api_url:
            raise RuntimeError("Bramka SMS nie jest skonfigurowana")
        _send_sms(study.patient_phone, settings.patient_result_sms)
    return _deliver(db, n, send)
