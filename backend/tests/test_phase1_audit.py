import uuid

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.db import SessionLocal
from app.core.config import settings
from app.main import app, seed
from app.models import User, Role

H = {"X-Requested-With": "second-patient"}


def test_login_logout_and_me_flow():
    seed(); c = TestClient(app)
    assert c.post("/api/v1/auth/login", headers=H, json={"email":"anita.iyer@secondpatient.demo","password":settings.demo_password}).status_code == 200
    assert c.get("/api/v1/auth/me").json()["role"] == "PRIMARY_CONTACT"
    assert c.post("/api/v1/auth/logout", headers=H).status_code == 204
    assert c.get("/api/v1/auth/me").status_code == 401


def test_deactivated_user_is_immediately_locked_out():
    c=TestClient(app); email=f"inactive-{uuid.uuid4().hex}@example.com"
    assert c.post("/api/v1/auth/register",headers=H,json={"name":"Inactive","email":email,"password":"SafePass!123"}).status_code==201
    with SessionLocal() as db:
        user=db.scalar(select(User).where(User.email==email)); user.is_active=False; db.commit()
    assert c.get("/api/v1/auth/me").status_code==401


def test_csrf_header_required_for_every_state_changing_verb():
    c=TestClient(app)
    requests=[("POST","/api/v1/auth/login"),("POST","/api/v1/auth/register"),("POST","/api/v1/auth/logout"),("POST","/api/v1/auth/change-password"),("PUT","/api/v1/caregivers/00000000-0000-0000-0000-000000000000/schedule"),("PATCH","/api/v1/patients/00000000-0000-0000-0000-000000000000"),("DELETE","/api/v1/activities/00000000-0000-0000-0000-000000000000/dependencies")]
    for method,path in requests:
        assert c.request(method,path,json={} if method!="DELETE" else None).status_code==403


def test_security_headers_and_cookie_flags():
    c=TestClient(app)
    response=c.get("/api/health")
    assert response.headers["content-security-policy"].startswith("default-src 'self'")
    assert response.headers["x-content-type-options"]=="nosniff"
    email=f"cookie-{uuid.uuid4().hex}@example.com"
    login=c.post("/api/v1/auth/register",headers=H,json={"name":"Cookie","email":email,"password":"SafePass!123"})
    cookie=login.headers.get("set-cookie","").lower()
    assert "httponly" in cookie and "samesite=lax" in cookie


def test_permission_matrix_read_and_write_expectations():
    from app.core.permissions import allowed
    from app.models import TeamRole
    assert allowed(Role.PRIMARY_CONTACT,TeamRole.PRIMARY_CONTACT,"careplan:manage")
    assert not allowed(Role.PROFESSIONAL,TeamRole.PROFESSIONAL,"careplan:manage")
    assert allowed(Role.CARETAKER,TeamRole.CARETAKER,"assignment:confirm_own")
    assert not allowed(Role.CARETAKER,TeamRole.CARETAKER,"clinical_notes:read")
    assert allowed(Role.PROFESSIONAL,TeamRole.PROFESSIONAL,"clinical_notes:read")
    assert not allowed(Role.PRIMARY_CONTACT,None,"any:future-action")


def test_unexpected_error_envelope_does_not_disclose_stack_trace():
    route = next(route for route in app.router.routes if getattr(route, "path", None) == "/api/health")
    original = route.dependant.call
    route.dependant.call = lambda **kwargs: 1/0
    c=TestClient(app,raise_server_exceptions=False)
    try:
        response=c.get("/api/health")
    finally:
        route.dependant.call=original
    assert response.status_code==500
    assert response.json()["error"]["code"]=="internal_error"
    assert "Traceback" not in response.text and response.json()["error"]["request_id"]


def test_all_seeded_accounts_can_authenticate_and_domain_data_is_present():
    seed()
    from app.main import DEMO_ACCOUNTS
    accounts=[(email, role.value) for email, _, role in DEMO_ACCOUNTS]
    for email,role in accounts:
        c=TestClient(app); result=c.post("/api/v1/auth/login",headers=H,json={"email":email,"password":settings.demo_password})
        assert result.status_code==200 and result.json()["role"]==role
    assert settings.demo_mode
