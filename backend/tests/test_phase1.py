import uuid

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.core.db import SessionLocal
from app.core.permissions import allowed
from app.main import app, lookup_attempts, seed
from app.models import (ActivityDependency, ActivityHistory, AvailabilityOverride, CareActivity, CareAssignment, Caregiver, CaregiverPatientLink,
                        CaregiverWeeklySchedule, CareTeamMember, Patient, PatientSupportNeed, Role, TeamRole, User)
from tests.helpers import H, PASSWORD, account, caretaker, primary_contact_with_patient

client = TestClient(app)


def test_permission_matrix_has_exactly_four_roles():
    assert {r.value for r in Role} == {"PATIENT", "PRIMARY_CONTACT", "CARETAKER", "PROFESSIONAL"}
    assert allowed(Role.PRIMARY_CONTACT, TeamRole.PRIMARY_CONTACT, "patient:update")
    assert not allowed(Role.CARETAKER, TeamRole.CARETAKER, "clinical_notes:read")
    assert allowed(Role.PROFESSIONAL, TeamRole.PROFESSIONAL, "clinical_notes:read")
    assert not allowed(Role.PROFESSIONAL, TeamRole.PROFESSIONAL, "patient:update")


def test_public_health_meta_and_csrf():
    assert client.get("/api/health").json()["database"] == "ok"
    response = client.post("/api/v1/auth/register", json={"name": "No CSRF", "email": "csrf@example.test", "password": "LongSafe!42"})
    assert response.status_code == 403 and "request_id" in response.json()["error"]


def test_sign_up_roles_are_limited():
    for role in ("PATIENT", "ADMIN", "DOCTOR"):
        response = client.post("/api/v1/auth/register", headers=H, json={"name": "X", "email": f"{uuid.uuid4().hex}@example.test", "password": "LongSafe!42", "role": role})
        assert response.status_code == 422, role
    for role in ("PRIMARY_CONTACT", "CARETAKER", "PROFESSIONAL"):
        assert account(role)[0].get("/api/v1/auth/me").json()["role"] == role


def test_primary_contact_registers_patient_with_care_code_and_patient_login():
    coord, email, _ = account("PRIMARY_CONTACT")
    patient_email = f"patient-{uuid.uuid4().hex}@example.com"
    created = coord.post("/api/v1/patients", headers=H, json={"name": "Fictional Person", "birth_year": 1950, "clinical_notes": "Private fictional note",
                                                              "patient_account": {"email": patient_email, "password": PASSWORD}})
    assert created.status_code == 201
    body = created.json()
    assert body["care_code"].startswith("CC-") and len(body["care_code"]) == 9 and body["is_synthetic"] is True
    patient = TestClient(app)
    assert patient.post("/api/v1/auth/login", headers=H, json={"email": patient_email, "password": PASSWORD}).json()["role"] == "PATIENT"
    seen = patient.get(f"/api/v1/patients/{body['id']}").json()
    assert seen["care_code"] is None and seen["clinical_notes"] == "Private fictional note"
    caretaker_client, _, _ = account("CARETAKER")
    assert caretaker_client.post("/api/v1/patients", headers=H, json={"name": "Not allowed"}).status_code == 403
    assert account("PRIMARY_CONTACT")[0].get(f"/api/v1/patients/{body['id']}").status_code == 403


def test_professional_finds_and_joins_with_care_code_and_birth_year():
    coord, pid = primary_contact_with_patient(birth_year=1948)
    code = coord.get(f"/api/v1/patients/{pid}").json()["care_code"]
    pro, _, _ = account("PROFESSIONAL")
    assert pro.get(f"/api/v1/patients/{pid}").status_code == 403
    assert pro.post("/api/v1/patients/lookup", headers=H, json={"care_code": code, "birth_year": 1949}).status_code == 404
    found = pro.post("/api/v1/patients/lookup", headers=H, json={"care_code": code.lower().replace("-", ""), "birth_year": 1948})
    assert found.status_code == 200 and found.json()["already_on_team"] is False
    assert pro.post("/api/v1/patients/join", headers=H, json={"care_code": code, "birth_year": 1948}).status_code == 201
    assert pro.get(f"/api/v1/patients/{pid}").status_code == 200
    roles = {m["team_role"] for m in coord.get(f"/api/v1/patients/{pid}/care-team").json()["items"]}
    assert roles == {"PRIMARY_CONTACT", "PROFESSIONAL"}
    assert any(n["title"] == "A healthcare professional joined" for n in coord.get("/api/v1/notifications").json()["items"])
    family_member, _, _ = account("PRIMARY_CONTACT")
    assert family_member.post("/api/v1/patients/lookup", headers=H, json={"care_code": code, "birth_year": 1948}).status_code == 403


def test_lookup_is_rate_limited():
    pro, _, user_id = account("PROFESSIONAL")
    lookup_attempts.pop(user_id, None)
    for _ in range(10):
        assert pro.post("/api/v1/patients/lookup", headers=H, json={"care_code": "CC-ZZZZZZ", "birth_year": 1950}).status_code == 404
    assert pro.post("/api/v1/patients/lookup", headers=H, json={"care_code": "CC-ZZZZZZ", "birth_year": 1950}).status_code == 429


def test_caretaker_invite_creates_care_profile_and_roles_must_match():
    coord, pid = primary_contact_with_patient()
    cid, helper = caretaker(coord, pid, "Helper", caps=("MEDICATION_ASSIST",))
    assert [c["id"] for c in helper.get(f"/api/v1/patients/{pid}/caregivers").json()["items"]] == [cid]
    pro, pro_email, _ = account("PROFESSIONAL")
    mismatch = coord.post(f"/api/v1/patients/{pid}/care-team", headers=H, json={"email": pro_email, "team_role": "CARETAKER"})
    assert mismatch.status_code == 422 and "registered as Healthcare professional" in mismatch.json()["error"]["message"]
    assert coord.post(f"/api/v1/patients/{pid}/care-team", headers=H, json={"email": "nobody@example.com", "team_role": "CARETAKER"}).status_code == 404
    members = coord.get(f"/api/v1/patients/{pid}/care-team").json()["items"]
    only_contact = next(m for m in members if m["team_role"] == "PRIMARY_CONTACT")
    assert coord.delete(f"/api/v1/patients/{pid}/care-team/{only_contact['id']}", headers=H).status_code == 409
    helper_member = next(m for m in members if m["team_role"] == "CARETAKER")
    assert coord.delete(f"/api/v1/patients/{pid}/care-team/{helper_member['id']}", headers=H).status_code == 204
    assert coord.get(f"/api/v1/patients/{pid}/caregivers").json()["items"] == []
    assert helper.post(f"/api/v1/patients/{pid}/care-team", headers=H, json={"email": pro_email, "team_role": "CARETAKER"}).status_code == 403


def test_primary_contact_can_opt_in_to_care_activities():
    coord, pid = primary_contact_with_patient()
    assert coord.post(f"/api/v1/patients/{pid}/care-team/me/care-profile", headers=H).status_code == 201
    profiles = coord.get(f"/api/v1/patients/{pid}/caregivers").json()["items"]
    assert len(profiles) == 1 and profiles[0]["kind"] == "PRIMARY_CONTACT"


def test_unknown_api_route_is_json_404():
    response = client.get("/api/does-not-exist")
    assert response.status_code == 404 and response.headers["content-type"].startswith("application/json")


def test_seed_is_idempotent_and_labels_all_demo_people():
    with SessionLocal() as db:
        for model in (ActivityHistory, CareAssignment, ActivityDependency, CareActivity, AvailabilityOverride, CaregiverWeeklySchedule, CaregiverPatientLink, Caregiver, PatientSupportNeed, CareTeamMember, Patient, User):
            db.query(model).delete()
        db.commit()
    seed(); seed()
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(Patient)) == 2
        assert {p.care_code for p in db.scalars(select(Patient))} == {"CC-RAM354", "CC-SHA746"}
        savitha = select(User.id).where(User.email == "savitha@secondpatient.demo").scalar_subquery()
        assert db.scalar(select(func.count()).select_from(CareTeamMember).where(CareTeamMember.user_id == savitha)) == 2
        assert db.scalar(select(func.count()).select_from(User).where(User.email.like("%@secondpatient.demo"), User.is_synthetic.is_(True))) == 9
        assert {u.role for u in db.scalars(select(User))} == set(Role)
        assert db.scalar(select(func.count()).select_from(Caregiver).where(Caregiver.user_id.is_(None))) == 0


def test_caretaker_sees_no_clinical_notes_or_team_emails():
    seed()
    demo = TestClient(app)
    assert demo.post("/api/v1/auth/login", headers=H, json={"email": "savitha@secondpatient.demo", "password": "Demo@1234"}).status_code == 200
    patients = demo.get("/api/v1/patients").json()["items"]
    assert len(patients) == 2 and all(p["clinical_notes"] is None and p["care_code"] is None for p in patients)
    team = demo.get(f"/api/v1/patients/{patients[0]['id']}/care-team").json()["items"]
    assert all(person["email"] is None for person in team)


def test_change_password_invalidates_existing_session():
    c = TestClient(app); email = f"password-{uuid.uuid4().hex}@example.com"; old = "OldPass!123"; new = "NewPass!456"
    assert c.post("/api/v1/auth/register", headers=H, json={"name": "Password Test", "email": email, "password": old}).status_code == 201
    assert c.post("/api/v1/auth/change-password", headers=H, json={"current_password": old, "new_password": new}).status_code == 200
    assert c.get("/api/v1/auth/me").status_code == 401
    assert c.post("/api/v1/auth/login", headers=H, json={"email": email, "password": old}).status_code == 401
    assert c.post("/api/v1/auth/login", headers=H, json={"email": email, "password": new}).status_code == 200


def test_login_rate_limit():
    c = TestClient(app); email = f"missing-{uuid.uuid4().hex}@example.com"
    for _ in range(10):
        assert c.post("/api/v1/auth/login", headers=H, json={"email": email, "password": "WrongPass!123"}).status_code == 401
    limited = c.post("/api/v1/auth/login", headers=H, json={"email": email, "password": "WrongPass!123"})
    assert limited.status_code == 429 and limited.headers["retry-after"] == "60"
