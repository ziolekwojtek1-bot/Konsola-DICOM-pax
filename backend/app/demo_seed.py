"""Wersja pokazowa: fikcyjny personel z loginami pasującymi do kont z tools/make_demo_logins.sh."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Physician

DEMO_STAFF = [
    dict(name="dr Anna Radiolog", login="radiolog", role="radiologist", modalities="CT,MR,MG",
         email="radiolog@demo.local"),
    dict(name="dr Piotr Radiolog", login="radiolog2", role="radiologist", modalities="DX,CR,US,CT",
         email="radiolog2@demo.local"),
    dict(name="dr Jan Kowalski", login="lekarz", dicom_name="Kowalski^Jan", role="attending",
         email="lekarz@demo.local"),
    dict(name="dr Ewa Wiśniewska", login="lekarz2", dicom_name="Wisniewska^Ewa", role="attending",
         email="lekarz2@demo.local"),
    dict(name="dr Marek Dyżurny", login="dyzurny", role="attending", on_call=True, email="dyzurny@demo.local"),
    dict(name="dr hab. Zofia Ordynator", login="ordynator", role="attending", is_head=True,
         email="ordynator@demo.local"),
    dict(name="Tomasz Technik", login="technik", role="technician", email="technik@demo.local"),
    dict(name="Rejestracja", login="rejestracja", role="registration"),
]


def seed_demo_staff(db: Session) -> None:
    if db.scalar(select(Physician.id).limit(1)):
        return
    db.add_all(Physician(**p) for p in DEMO_STAFF)
    db.commit()
