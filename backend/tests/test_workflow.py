import os
import tempfile

# Plik, a nie baza w pamięci: TestClient korzysta z bazy z innego wątku.
os.environ["DATABASE_URL"] = "sqlite:///" + os.path.join(tempfile.mkdtemp(), "test.db")

from app.db import Base, SessionLocal, engine  # noqa: E402
from app.ingest import register_study  # noqa: E402
from app.models import Notification, Physician  # noqa: E402
from app.routing import is_urgent  # noqa: E402


def setup_function():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)


def test_is_urgent():
    assert is_urgent({"RequestedProcedurePriority": "STAT"})
    assert is_urgent({"StudyDescription": "CT glowy CITO"})
    assert not is_urgent({"StudyDescription": "RTG klatki"})


def test_register_routes_to_least_loaded_radiologist_and_notifies_urgent():
    with SessionLocal() as db:
        ct = Physician(name="Anna Nowak", role="radiologist", modalities="CT,MR", email="a@x")
        rtg = Physician(name="Piotr Lis", role="radiologist", modalities="CR,DX")
        att = Physician(name="Jan Kowalski", dicom_name="Kowalski^Jan", role="attending", email="j@x")
        db.add_all([ct, rtg, att])
        db.flush()

        s = register_study(db, "o1", {"StudyInstanceUID": "1.2.3", "Modality": "CT",
                                      "StudyDescription": "CT glowy PILNE",
                                      "ReferringPhysicianName": "KOWALSKI^JAN"})
        assert s.radiologist_id == ct.id
        assert s.attending_id == att.id
        assert s.priority == "urgent" and s.status == "assigned"
        assert db.query(Notification).count() == 1  # SMTP brak -> zapisane jako nieudane
        assert register_study(db, "o1", {}) is None  # duplikat ignorowany

        s2 = register_study(db, "o2", {"StudyInstanceUID": "1.2.4", "Modality": "DX"})
        assert s2.radiologist_id == rtg.id and s2.priority == "routine"


def test_notes_soft_delete_keeps_author_and_deleter():
    from fastapi.testclient import TestClient
    from app import main

    client = TestClient(main.app)  # bez "with": nie startuje wątku pobierania z Orthanc
    with SessionLocal() as db:
        db.add(Physician(name="Jan Kowalski", role="attending"))
        register_study(db, "o9", {"StudyInstanceUID": "9", "Modality": "CT"})
        db.commit()
    h = {"X-Remote-User": "anna.nowak"}
    r = client.post("/api/studies/1/notes", headers=h,
                    json={"text": "Proszę o dodatkową projekcję", "purpose": "prosba_o_badanie",
                          "recipient_group": "Pracownia diagnostyczna"})
    assert r.status_code == 200
    assert r.json()["author"] == "anna.nowak" and r.json()["recipient"] == "Pracownia diagnostyczna"
    assert client.post("/api/studies/1/notes", headers=h, json={"text": "x", "purpose": "pytanie"}).status_code == 400
    r = client.delete("/api/studies/1/notes/1", headers={"X-Remote-User": "piotr.lis"})
    assert r.json()["deleted_by"] == "piotr.lis"
    assert client.get("/api/studies/1").json()["open_notes"] == 0
    assert len(client.get("/api/studies/1/notes").json()) == 1
