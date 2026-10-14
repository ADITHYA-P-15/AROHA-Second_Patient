import uuid

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.db import SessionLocal
from app.core.security import hash_password
from app.main import app
from app.models import Role, User

H = {"X-Requested-With": "second-patient"}


def _user(role, name):
    email = f"fix-{uuid.uuid4().hex}@example.com"
    with SessionLocal() as db:
        db.add(User(email=email, name=name, role=role, password_hash=hash_password("SafePass!123"), is_synthetic=True)); db.commit()
    client = TestClient(app)
    assert client.post("/api/v1/auth/login", headers=H, json={"email": email, "password": "SafePass!123"}).status_code == 200
    return client, email


def _patient():
    coord = TestClient(app)
    assert coord.post("/api/v1/auth/register", headers=H, json={"name": "Coordinator", "email": f"fix-{uuid.uuid4().hex}@example.com", "password": "SafePass!123"}).status_code == 201
    return coord, coord.post("/api/v1/patients", headers=H, json={"name": "Synthetic fix patient"}).json()["id"]


def test_level_three_escalation_falls_back_to_coordinator():
    from app.main import incident_recipients
    from app.services.escalation import _recipients
    coord, pid = _patient()
    with SessionLocal() as db:
        me = coord.get("/api/v1/auth/me").json()["id"]
        assert [str(u.id) for u in incident_recipients(db, uuid.UUID(pid), 3)] == [me]
        assert [str(u.id) for u in _recipients(db, uuid.UUID(pid), 3)] == [me]


def test_nurse_cannot_resolve_incident_they_cannot_see_and_history_rejects_negative_offset():
    coord, pid = _patient()
    nurse, email = _user(Role.NURSE, "Synthetic nurse")
    assert coord.post(f"/api/v1/patients/{pid}/care-team", headers=H, json={"email": email, "team_role": "NURSE"}).status_code == 201
    low = coord.post(f"/api/v1/patients/{pid}/messages", headers=H, json={"body": "I need water", "channel": "TEXT", "on_behalf": True}).json()
    assert low["current_level"] < 3
    assert nurse.get(f"/api/v1/incidents/{low['id']}").status_code == 403
    assert nurse.post(f"/api/v1/incidents/{low['id']}/resolve", headers=H, json={"code": "HANDLED"}).status_code == 403
    assert coord.get(f"/api/v1/patients/{pid}/history", params={"offset": -1}).status_code == 422


def test_help_summary_uses_app_timezone(monkeypatch):
    from datetime import UTC, datetime
    import app.main as main
    monkeypatch.setattr(main, "now", lambda: datetime(2026, 10, 14, 6, 0, tzinfo=UTC))
    coord, pid = _patient()
    sent = coord.post(f"/api/v1/patients/{pid}/messages", headers=H, json={"body": "I need water", "channel": "TEXT", "on_behalf": True}).json()
    assert sent["safe_summary"].endswith("at 11:30")  # 06:00 UTC in Asia/Kolkata
