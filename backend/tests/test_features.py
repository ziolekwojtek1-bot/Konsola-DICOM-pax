from datetime import timedelta

from fastapi.testclient import TestClient

from app import main
from app.db import Base, SessionLocal, engine
from app.escalation import check_once
from app.ingest import register_study
from app.models import CriticalAlert, Notification, Physician, Study

client = TestClient(main.app)  # bez "with": nie startują wątki pobierania z Orthanc


def as_user(login):
    return {"X-Remote-User": login}


def setup_function():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        db.add_all([
            Physician(name="Anna Nowak", login="anna", role="radiologist", modalities="CT"),
            Physician(name="Piotr Lis", login="piotr", role="radiologist"),
            Physician(name="Jan Kowalski", login="jan", dicom_name="Kowalski^Jan", role="attending",
                      email="j@x", phone="500"),
            Physician(name="Dyżurny", login="dyz", role="attending", on_call=True),
            Physician(name="Ordynator", login="ord", role="attending", is_head=True),
            Physician(name="Technik CT", login="tech", role="technician"),
        ])
        db.flush()
        register_study(db, "o1", {"StudyInstanceUID": "1", "Modality": "CT", "PatientID": "P1",
                                  "StudyDescription": "CT glowy CITO", "ReferringPhysicianName": "Kowalski^Jan"})
        register_study(db, "o0", {"StudyInstanceUID": "0", "Modality": "CT", "PatientID": "P1",
                                  "StudyDescription": "CT glowy kontrolne"})
        db.commit()


def test_sla_due_date_depends_on_priority():
    with SessionLocal() as db:
        urgent, routine = db.get(Study, 1), db.get(Study, 2)
        assert urgent.due_at - urgent.received_at == timedelta(minutes=60)
        assert routine.due_at - routine.received_at == timedelta(hours=72)


def test_critical_escalates_until_acknowledged():
    r = client.post("/api/studies/1/report", headers=as_user("anna"), json={"text": "krwiak", "critical": True})
    assert r.json()["critical_unacknowledged"]
    assert [a["study"]["id"] for a in client.get("/api/inbox", headers=as_user("jan")).json()["critical"]] == [1]

    with SessionLocal() as db:
        alert = db.get(CriticalAlert, 1)
        start = alert.last_escalated_at
        for minutes, level in ((16, 1), (32, 2), (48, 3), (64, 3)):
            check_once(db, at=start + timedelta(minutes=minutes))
            assert db.get(CriticalAlert, 1).level == level
    # na poziomie 2 i 3 widzą to dyżurny i ordynator
    assert client.get("/api/inbox", headers=as_user("dyz")).json()["critical"]
    assert client.get("/api/inbox", headers=as_user("ord")).json()["critical"]

    r = client.post("/api/studies/1/critical/ack", headers=as_user("jan"))
    assert r.json()["alerts"][0]["acknowledged_by"] == "jan"
    assert not client.get("/api/inbox", headers=as_user("jan")).json()["critical"]
    assert client.post("/api/studies/1/critical/ack", headers=as_user("jan")).status_code == 400


def test_mentions_and_inbox_done():
    r = client.post("/api/studies/1/notes", headers=as_user("anna"),
                    json={"text": "@piotr zerknij proszę, @nikt", "purpose": "pytanie", "recipient_physician_id": 3})
    assert r.json()["mentions"] == ["piotr"]
    for login in ("piotr", "jan"):
        assert len(client.get("/api/inbox", headers=as_user(login)).json()["notes"]) == 1
    assert client.get("/api/inbox", headers=as_user("tech")).json()["notes"] == []
    client.post("/api/studies/1/notes/1/done", headers=as_user("jan"))
    assert client.get("/api/inbox", headers=as_user("piotr")).json()["notes"] == []


def test_repeat_request_goes_to_lab_and_clears_when_done():
    r = client.post("/api/studies/1/repeat", headers=as_user("anna"), json={"text": "artefakty ruchowe"})
    assert r.json()["repeat_requested"]
    notes = client.get("/api/inbox", headers=as_user("tech")).json()["notes"]
    assert notes[0]["purpose"] == "powtorz_badanie"
    client.post(f"/api/studies/1/notes/{notes[0]['id']}/done", headers=as_user("tech"))
    assert not client.get("/api/studies/1").json()["repeat_requested"]


def test_priors_second_opinion_and_patient_sms():
    assert [s["id"] for s in client.get("/api/studies/1/priors").json()] == [2]
    assert client.post("/api/studies/1/second-opinion", headers=as_user("anna"),
                       json={"radiologist_id": 1, "request": "?"}).status_code == 400
    client.post("/api/studies/1/second-opinion", headers=as_user("anna"), json={"radiologist_id": 2, "request": "?"})
    r = client.post("/api/studies/1/second-report", headers=as_user("piotr"), json={"text": "zgadzam się"})
    assert r.json()["second_reader"] == "Piotr Lis" and r.json()["second_report"] == "zgadzam się"

    client.patch("/api/studies/1/patient-contact", headers=as_user("rej"), json={"phone": "600", "sms_consent": True})
    client.post("/api/studies/1/report", headers=as_user("anna"), json={"text": "ok"})
    with SessionLocal() as db:
        assert db.query(Notification).filter_by(reason="patient_result_ready").count() == 1


def test_templates_and_stats():
    names = [t["name"] for t in client.get("/api/templates?modality=DX").json()]
    assert all("CT" not in n for n in names)
    client.post("/api/templates", headers=as_user("anna"), json={"name": "Mój", "modality": "ct", "body": "x"})
    assert any(t["name"] == "Mój" for t in client.get("/api/templates?modality=CT").json())
    client.post("/api/studies/1/report", headers=as_user("anna"), json={"text": "ok"})
    s = client.get("/api/stats").json()
    assert s["total"] == 2 and s["by_status"]["reported"] == 1 and s["on_time_pct"] == 100
