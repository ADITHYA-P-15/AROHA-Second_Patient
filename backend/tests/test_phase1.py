import uuid
from app.core.permissions import allowed
from app.models import Role, TeamRole
from fastapi.testclient import TestClient
from app.main import app, seed
from app.core.db import SessionLocal
from sqlalchemy import select, func
from app.models import ActivityHistory, CareTeamMember, Patient, User

client = TestClient(app)
H = {"X-Requested-With": "second-patient"}

def test_permission_matrix():
    assert allowed(Role.FAMILY, TeamRole.COORDINATOR, "patient:update")
    assert not allowed(Role.HOUSEHELP, TeamRole.HOUSEHELP, "clinical_notes:read")
    assert allowed(Role.ADMIN, None, "any:future-action")

def test_public_health_meta_and_csrf():
    assert client.get("/api/health").json()["database"] == "ok"
    assert client.get("/api/v1/meta").json()["phase"] == 1
    response = client.post("/api/v1/auth/register", json={"name":"No CSRF","email":"csrf@example.test","password":"LongSafe!42"})
    assert response.status_code == 403
    assert "request_id" in response.json()["error"]

def test_register_role_is_not_client_controlled():
    response = client.post("/api/v1/auth/register", headers=H, json={"name":"Escalation","email":"escalation@example.test","password":"LongSafe!42","role":"ADMIN"})
    assert response.status_code == 422

def test_auth_patient_crud_and_idor():
    suffix=uuid.uuid4().hex
    email=f"owner-{suffix}@example.com"
    response=client.post("/api/v1/auth/register",headers=H,json={"name":"Owner","email":email,"password":"LongSafe!42"})
    assert response.status_code==201 and response.json()["role"]=="FAMILY"
    patient=client.post("/api/v1/patients",headers=H,json={"name":"Fictional Person","birth_year":1950,"care_notes":"Care","clinical_notes":"Private fictional note"})
    assert patient.status_code==201
    pid=patient.json()["id"]
    assert patient.json()["is_synthetic"] is True
    assert client.get(f"/api/v1/patients/{pid}").status_code==200
    other=TestClient(app)
    reg=other.post("/api/v1/auth/register",headers=H,json={"name":"Other","email":f"other-{suffix}@example.com","password":"LongSafe!42"})
    assert reg.status_code==201
    assert other.get(f"/api/v1/patients/{pid}").status_code==403

def test_unknown_api_route_is_json_404():
    response=client.get('/api/does-not-exist')
    assert response.status_code==404
    assert response.headers['content-type'].startswith('application/json')

def test_seed_is_idempotent_and_labels_all_demo_people():
    with SessionLocal() as db:
        db.query(ActivityHistory).delete()
        db.query(CareTeamMember).delete()
        db.query(Patient).delete()
        db.query(User).delete()
        db.commit()
    seed()
    seed()
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(Patient)) == 2
        assert db.scalar(select(func.count()).select_from(CareTeamMember).where(CareTeamMember.user_id == select(User.id).where(User.email == "savitha@secondpatient.demo").scalar_subquery())) == 2
        assert db.scalar(select(func.count()).select_from(User).where(User.email.like("%@secondpatient.demo"), User.is_synthetic.is_(True))) == 8

def test_househelp_sees_no_clinical_notes_or_team_emails():
    seed()
    demo_client=TestClient(app)
    logged=demo_client.post("/api/v1/auth/login",headers=H,json={"email":"savitha@secondpatient.demo","password":"Demo@1234"})
    assert logged.status_code==200
    patients=demo_client.get("/api/v1/patients").json()["items"]
    assert len(patients)==2 and all(p["clinical_notes"] is None for p in patients)
    team=demo_client.get(f"/api/v1/patients/{patients[0]['id']}/care-team").json()["items"]
    assert all(person["email"] is None for person in team)

def test_change_password_invalidates_existing_session():
    c=TestClient(app); email=f"password-{uuid.uuid4().hex}@example.com"; old="OldPass!123"; new="NewPass!456"
    assert c.post("/api/v1/auth/register",headers=H,json={"name":"Password Test","email":email,"password":old}).status_code==201
    changed=c.post("/api/v1/auth/change-password",headers=H,json={"current_password":old,"new_password":new})
    assert changed.status_code==200
    assert c.get("/api/v1/auth/me").status_code==401
    assert c.post("/api/v1/auth/login",headers=H,json={"email":email,"password":old}).status_code==401
    assert c.post("/api/v1/auth/login",headers=H,json={"email":email,"password":new}).status_code==200

def test_login_rate_limit():
    c=TestClient(app); email=f"missing-{uuid.uuid4().hex}@example.com"
    for _ in range(10):
        assert c.post("/api/v1/auth/login",headers=H,json={"email":email,"password":"WrongPass!123"}).status_code==401
    limited=c.post("/api/v1/auth/login",headers=H,json={"email":email,"password":"WrongPass!123"})
    assert limited.status_code==429 and limited.headers["retry-after"]=="60"

def test_care_team_role_compatibility_and_last_coordinator():
    seed()
    c=TestClient(app); email=f"coordinator-{uuid.uuid4().hex}@example.com"
    assert c.post("/api/v1/auth/register",headers=H,json={"name":"Coordinator","email":email,"password":"SafePass!123"}).status_code==201
    patient=c.post("/api/v1/patients",headers=H,json={"name":"Team Test Patient"}).json(); pid=patient["id"]
    mismatch=c.post(f"/api/v1/patients/{pid}/care-team",headers=H,json={"email":"savitha@secondpatient.demo","team_role":"COORDINATOR"})
    assert mismatch.status_code==422
    members=c.get(f"/api/v1/patients/{pid}/care-team").json()["items"]
    only_coordinator=next(m for m in members if m["is_primary_coordinator"])
    blocked=c.delete(f"/api/v1/patients/{pid}/care-team/{only_coordinator['id']}",headers=H)
    assert blocked.status_code==409

def test_demo_reset_is_admin_only_and_reseeds():
    seed()
    family=TestClient(app); family.post("/api/v1/auth/login",headers=H,json={"email":"anita.iyer@secondpatient.demo","password":"Demo@1234"})
    assert family.post("/api/v1/admin/demo/reset",headers=H).status_code==403
    admin=TestClient(app); admin.post("/api/v1/auth/login",headers=H,json={"email":"admin@secondpatient.demo","password":"Demo@1234"})
    assert admin.post("/api/v1/admin/demo/reset",headers=H).json()=={"status":"reset"}
    assert len(admin.get("/api/v1/patients").json()["items"])==2
