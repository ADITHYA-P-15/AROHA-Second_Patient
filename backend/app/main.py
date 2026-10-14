import logging
import json
import re
import time
import uuid
from collections import defaultdict, deque
from datetime import UTC
from pathlib import Path

import jwt
from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.core.clock import now
from app.core.config import settings
from app.core.db import Base, engine, get_db
from app.core.security import create_token, hash_password, verify_password
from app.core.permissions import require_patient_access
from app.models import ActivityHistory, CareTeamMember, Patient, Role, TeamRole, User
from app.schemas import LoginIn, PasswordIn, PatientIn, PatientPatch, RegisterIn, TeamIn
from app.seed import run_seed

logging.basicConfig(level=settings.log_level, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("second_patient")
app = FastAPI(title="The Second Patient", version="0.1.0", openapi_url="/api/openapi.json", docs_url="/docs", redoc_url=None)
if settings.app_env == "prod" and settings.secret_key == "change-me-before-production":
    raise RuntimeError("SECRET_KEY must be changed before starting in production")
Base.metadata.create_all(bind=engine)
CSRF = "second-patient"
COOKIE = "sp_session"
login_attempts: dict[str, deque[float]] = defaultdict(deque)


@app.middleware("http")
async def request_context(request: Request, call_next):
    supplied = request.headers.get("X-Request-ID", "")
    request.state.request_id = supplied[:80] if re.fullmatch(r"[A-Za-z0-9._:-]{1,80}", supplied) else str(uuid.uuid4())
    if request.method not in {"GET", "HEAD", "OPTIONS"} and request.headers.get("X-Requested-With") != CSRF:
        response = JSONResponse(status_code=403, content={"error": {"code": "csrf_required", "message": "A valid request header is required", "details": {}, "request_id": request.state.request_id}})
    else:
        started = time.monotonic()
        response = await call_next(request)
        log.info(json.dumps({"event": "http_request", "request_id": request.state.request_id, "method": request.method, "path": request.url.path, "status": response.status_code, "duration_ms": round((time.monotonic()-started)*1000, 2)}))
    response.headers["X-Request-ID"] = request.state.request_id
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Content-Security-Policy"] = "default-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'self'; img-src 'self' data:; connect-src 'self'"
    if request.url.path.startswith("/assets/"):
        response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
    return response


@app.exception_handler(HTTPException)
async def http_error(request: Request, exc: HTTPException):
    code, message = ("request_error", str(exc.detail))
    return JSONResponse({"error": {"code": code, "message": message, "details": {}, "request_id": getattr(request.state, "request_id", "")}}, status_code=exc.status_code, headers=exc.headers)


@app.exception_handler(RequestValidationError)
async def validation_error(request: Request, exc: RequestValidationError):
    details = [{"field": ".".join(map(str, e["loc"][1:])), "message": e["msg"]} for e in exc.errors()]
    return JSONResponse({"error": {"code": "validation_error", "message": "Request validation failed", "details": details, "request_id": getattr(request.state, "request_id", "")}}, status_code=422)


@app.exception_handler(Exception)
async def unexpected_error(request: Request, exc: Exception):
    log.exception("request failed request_id=%s", getattr(request.state, "request_id", ""))
    return JSONResponse({"error": {"code": "internal_error", "message": "An internal error occurred", "details": {}, "request_id": getattr(request.state, "request_id", "")}}, status_code=500)


def audit(db, actor, patient, event, entity_type, entity_id, summary, request_id=""):
    db.add(ActivityHistory(actor_user_id=actor.id if actor else None, patient_id=patient, event_type=event, entity_type=entity_type, entity_id=str(entity_id), summary=summary, request_id=request_id))


def current_user(request: Request, db: Session = Depends(get_db)):
    token = request.cookies.get(COOKIE)
    if not token:
        raise HTTPException(401, "Authentication required")
    try:
        claims = jwt.decode(token, settings.secret_key, algorithms=["HS256"])
        user = db.get(User, uuid.UUID(claims["sub"]))
    except Exception:
        raise HTTPException(401, "Authentication required") from None
    if not user or not user.is_active or user.token_version != claims.get("tv"):
        raise HTTPException(401, "Authentication required")
    return user


def patient_access(db, user, patient_id, action="read"):
    permission = "patient:update" if action == "update" else "patient:read"
    return require_patient_access(db, user, patient_id, permission)


def user_dict(u):
    return {"id": u.id, "email": u.email, "name": u.name, "role": u.role.value, "is_synthetic": u.is_synthetic}


def patient_dict(p, show_clinical):
    created_at = p.created_at.replace(tzinfo=UTC) if p.created_at.tzinfo is None else p.created_at
    return {"id": p.id, "name": p.name, "birth_year": p.birth_year, "care_notes": p.care_notes, "clinical_notes": p.clinical_notes if show_clinical else None, "is_synthetic": p.is_synthetic, "created_at": created_at}


def can_see_clinical(user, member):
    return user.role in (Role.ADMIN, Role.PATIENT, Role.FAMILY, Role.NURSE, Role.DOCTOR) and (user.role == Role.ADMIN or member is not None)


@app.get("/api/health")
def health(db: Session = Depends(get_db)):
    db.execute(text("SELECT 1"))
    return {"status": "ok", "database": "ok"}


@app.get("/api/v1/meta")
def meta():
    return {"app_name": "The Second Patient", "version": "0.1.0", "git_sha": settings.git_sha, "phase": 1, "demo_mode": settings.demo_mode, "server_time": now().isoformat(), "timezone": settings.app_timezone, "ai_enabled": False}


@app.post("/api/v1/auth/register", status_code=201)
def register(body: RegisterIn, response: Response, db: Session = Depends(get_db)):
    email = str(body.email).lower()
    if not password_is_strong(body.password, body.name, email):
        raise HTTPException(422, "Password does not meet basic strength requirements")
    if db.scalar(select(User).where(User.email == email)):
        raise HTTPException(409, "An account with this email already exists")
    user = User(email=email, name=body.name.strip(), password_hash=hash_password(body.password), role=Role.FAMILY)
    db.add(user); db.commit(); db.refresh(user)
    response.set_cookie(COOKIE, create_token(user), httponly=True, secure=settings.cookie_secure, samesite="lax", max_age=settings.session_hours * 3600, path="/")
    return user_dict(user)


@app.post("/api/v1/auth/login")
def login(body: LoginIn, request: Request, response: Response, db: Session = Depends(get_db)):
    ip = request.client.host if request.client else "unknown"
    key = ip + ":" + str(body.email).lower()
    attempts = login_attempts[key]
    cutoff = time.monotonic() - 60
    while attempts and attempts[0] < cutoff: attempts.popleft()
    if len(attempts) >= 10: raise HTTPException(429, "Too many login attempts", headers={"Retry-After": "60"})
    attempts.append(time.monotonic())
    user = db.scalar(select(User).where(User.email == str(body.email).lower()))
    if not user or not user.is_active or not verify_password(body.password, user.password_hash):
        raise HTTPException(401, "Invalid credentials")
    response.set_cookie(COOKIE, create_token(user), httponly=True, secure=settings.cookie_secure, samesite="lax", max_age=settings.session_hours * 3600, path="/")
    return user_dict(user)


@app.post("/api/v1/auth/logout", status_code=204)
def logout(response: Response, user: User = Depends(current_user), db: Session = Depends(get_db)):
    user.token_version += 1
    db.commit()
    response.delete_cookie(COOKIE, path="/")
    response.status_code = 204
    return response


@app.get("/api/v1/auth/me")
def me(user: User = Depends(current_user)):
    return user_dict(user)


@app.post("/api/v1/auth/change-password")
def change_password(body: PasswordIn, response: Response, user: User = Depends(current_user), db: Session = Depends(get_db)):
    if not verify_password(body.current_password, user.password_hash): raise HTTPException(400, "Current password is incorrect")
    if not password_is_strong(body.new_password, user.name, user.email): raise HTTPException(422, "Password does not meet basic strength requirements")
    user.password_hash = hash_password(body.new_password); user.token_version += 1; db.commit(); response.delete_cookie(COOKIE, path="/")
    return {"status": "password_changed"}


def password_is_strong(password: str, name: str, email: str) -> bool:
    lowered = password.lower()
    return len(password) >= 8 and any(c.isalpha() for c in password) and any(c.isdigit() for c in password) and lowered not in {name.lower(), email.lower(), "password", "password123"}


@app.get("/api/v1/patients")
def list_patients(limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0), user: User = Depends(current_user), db: Session = Depends(get_db)):
    stmt = select(Patient) if user.role == Role.ADMIN else select(Patient).join(CareTeamMember).where(CareTeamMember.user_id == user.id)
    total = len(db.scalars(stmt).all())
    patients = db.scalars(stmt.order_by(Patient.created_at.desc()).offset(offset).limit(limit)).all()
    return {"items": [patient_dict(p, can_see_clinical(user, True)) for p in patients], "total": total, "limit": limit, "offset": offset}


@app.post("/api/v1/patients", status_code=201)
def create_patient(body: PatientIn, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    if user.role not in (Role.FAMILY, Role.ADMIN): raise HTTPException(403, "Permission denied")
    p = Patient(**body.model_dump(), created_by=user.id, is_synthetic=settings.demo_mode)
    db.add(p); db.flush()
    db.add(CareTeamMember(patient_id=p.id, user_id=user.id, team_role=TeamRole.COORDINATOR, is_primary_coordinator=True))
    audit(db, user, p.id, "patient.created", "patient", p.id, "Patient profile created", request.state.request_id)
    db.commit(); db.refresh(p)
    return patient_dict(p, True)


@app.get("/api/v1/patients/{patient_id}")
def get_patient(patient_id: uuid.UUID, user: User = Depends(current_user), db: Session = Depends(get_db)):
    p, m = patient_access(db, user, patient_id)
    return patient_dict(p, can_see_clinical(user, m))


@app.patch("/api/v1/patients/{patient_id}")
def patch_patient(patient_id: uuid.UUID, body: PatientPatch, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    p, m = patient_access(db, user, patient_id, "update")
    if user.role != Role.ADMIN and not m.is_primary_coordinator and m.team_role != TeamRole.COORDINATOR: raise HTTPException(403, "Coordinator permission required")
    for key, value in body.model_dump(exclude_unset=True).items(): setattr(p, key, value)
    p.updated_at = now(); audit(db, user, p.id, "patient.updated", "patient", p.id, "Patient profile updated", request.state.request_id); db.commit(); db.refresh(p)
    return patient_dict(p, can_see_clinical(user, m))


@app.get("/api/v1/patients/{patient_id}/care-team")
def care_team(patient_id: uuid.UUID, user: User = Depends(current_user), db: Session = Depends(get_db)):
    patient_access(db, user, patient_id)
    rows = db.execute(select(CareTeamMember, User).join(User).where(CareTeamMember.patient_id == patient_id)).all()
    contact_visible = user.role in (Role.ADMIN, Role.FAMILY, Role.DOCTOR)
    return {"items": [{"id": m.id, "user_id": u.id, "name": u.name, "email": u.email if contact_visible else None, "role": u.role.value, "team_role": m.team_role.value, "is_primary_coordinator": m.is_primary_coordinator} for m, u in rows]}


@app.post("/api/v1/patients/{patient_id}/care-team", status_code=201)
def add_team(patient_id: uuid.UUID, body: TeamIn, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    p, member = patient_access(db, user, patient_id, "update")
    if user.role != Role.ADMIN and (not member or member.team_role != TeamRole.COORDINATOR): raise HTTPException(403, "Coordinator permission required")
    try: team_role = TeamRole(body.team_role)
    except ValueError: raise HTTPException(422, "Invalid team role") from None
    target = db.scalar(select(User).where(User.email == str(body.email).lower()))
    if not target: raise HTTPException(404, "User not found")
    expected = {TeamRole.PATIENT_SELF: Role.PATIENT, TeamRole.COORDINATOR: Role.FAMILY, TeamRole.FAMILY: Role.FAMILY, TeamRole.HOUSEHELP: Role.HOUSEHELP, TeamRole.NURSE: Role.NURSE, TeamRole.DOCTOR: Role.DOCTOR}
    if target.role != expected[team_role]: raise HTTPException(422, "User role is incompatible with requested team role")
    if db.scalar(select(CareTeamMember).where(CareTeamMember.patient_id == p.id, CareTeamMember.user_id == target.id)): raise HTTPException(409, "User is already on this care team")
    m = CareTeamMember(patient_id=p.id, user_id=target.id, team_role=team_role); db.add(m); audit(db, user, p.id, "care_team.member_added", "care_team_member", target.id, "Care team member added", request.state.request_id); db.commit(); db.refresh(m)
    return {"id": m.id, "user_id": target.id, "team_role": team_role.value}


@app.delete("/api/v1/patients/{patient_id}/care-team/{member_id}", status_code=204)
def remove_team(patient_id: uuid.UUID, member_id: uuid.UUID, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    p, access = patient_access(db, user, patient_id, "update")
    if user.role != Role.ADMIN and (not access or access.team_role != TeamRole.COORDINATOR): raise HTTPException(403, "Coordinator permission required")
    member = db.scalar(select(CareTeamMember).where(CareTeamMember.id == member_id, CareTeamMember.patient_id == p.id))
    if not member: raise HTTPException(404, "Care team member not found")
    if member.team_role == TeamRole.COORDINATOR and db.scalar(select(CareTeamMember).where(CareTeamMember.patient_id == p.id, CareTeamMember.team_role == TeamRole.COORDINATOR, CareTeamMember.id != member.id)) is None: raise HTTPException(409, "Cannot remove the last coordinator")
    db.delete(member); audit(db, user, p.id, "care_team.member_removed", "care_team_member", member_id, "Care team member removed", request.state.request_id); db.commit(); return Response(status_code=204)


@app.get("/api/v1/patients/{patient_id}/history")
def history(patient_id: uuid.UUID, limit: int = 50, offset: int = 0, user: User = Depends(current_user), db: Session = Depends(get_db)):
    p, member = patient_access(db, user, patient_id)
    if user.role not in (Role.ADMIN, Role.DOCTOR) and not (member and member.team_role in (TeamRole.COORDINATOR, TeamRole.FAMILY)): raise HTTPException(403, "Permission denied")
    limit = max(1, min(limit, 100)); rows = db.scalars(select(ActivityHistory).where(ActivityHistory.patient_id == p.id).order_by(ActivityHistory.occurred_at.desc()).offset(offset).limit(limit)).all()
    return {"items": [{"id": e.id, "occurred_at": e.occurred_at.replace(tzinfo=UTC) if e.occurred_at.tzinfo is None else e.occurred_at, "event_type": e.event_type, "summary": e.summary, "outcome": e.outcome} for e in rows], "total": db.query(ActivityHistory).filter_by(patient_id=p.id).count(), "limit": limit, "offset": offset}


@app.post("/api/v1/admin/demo/reset")
def demo_reset(user: User = Depends(current_user), db: Session = Depends(get_db)):
    if user.role != Role.ADMIN: raise HTTPException(403, "Admin access required")
    if not settings.demo_mode: raise HTTPException(404, "Not found")
    db.query(ActivityHistory).delete(); db.query(CareTeamMember).delete(); db.query(Patient).delete(); db.commit()
    run_seed(db)
    audit(db, user, None, "demo.reset", "demo", "demo", "Synthetic demo data reset")
    db.commit()
    return {"status": "reset"}


def seed(db=None):
    own = db is None
    if own:
        db = next(get_db())
    accounts = [
        ("admin@secondpatient.demo", "Demo Administrator", Role.ADMIN),
        ("anita.iyer@secondpatient.demo", "Anita Iyer", Role.FAMILY),
        ("karthik.iyer@secondpatient.demo", "Karthik Iyer", Role.FAMILY),
        ("meera.pai@secondpatient.demo", "Meera Pai", Role.FAMILY),
        ("ramesh.iyer@secondpatient.demo", "Ramesh Iyer", Role.PATIENT),
        ("savitha@secondpatient.demo", "Savitha", Role.HOUSEHELP),
        ("divya.menon@secondpatient.demo", "Divya Menon", Role.NURSE),
        ("dr.arjun.nair@secondpatient.demo", "Dr. Arjun Nair", Role.DOCTOR),
    ]
    users = {}
    for email, name, role in accounts:
        user = db.scalar(select(User).where(User.email == email))
        if not user:
            user = User(email=email, name=name, role=role, is_synthetic=True, password_hash=hash_password(settings.demo_password)); db.add(user); db.flush()
        users[email] = user
    if not db.scalar(select(Patient)):
        p1 = Patient(name="Ramesh Iyer", birth_year=1954, care_notes="Mobility-limited; post-procedure follow-up support.", clinical_notes="Fictional demo note: follow-up plan discussed.", created_by=users["anita.iyer@secondpatient.demo"].id, is_synthetic=True)
        p2 = Patient(name="Sharada Pai", birth_year=1946, care_notes="Lives alone; Savitha helps daily.", clinical_notes="Fictional demo note.", created_by=users["meera.pai@secondpatient.demo"].id, is_synthetic=True)
        db.add_all([p1, p2]); db.flush()
        entries = [(p1, "anita.iyer@secondpatient.demo", TeamRole.COORDINATOR, True), (p1, "karthik.iyer@secondpatient.demo", TeamRole.FAMILY, False), (p1, "ramesh.iyer@secondpatient.demo", TeamRole.PATIENT_SELF, False), (p1, "savitha@secondpatient.demo", TeamRole.HOUSEHELP, False), (p1, "divya.menon@secondpatient.demo", TeamRole.NURSE, False), (p1, "dr.arjun.nair@secondpatient.demo", TeamRole.DOCTOR, False), (p2, "meera.pai@secondpatient.demo", TeamRole.COORDINATOR, True), (p2, "savitha@secondpatient.demo", TeamRole.HOUSEHELP, False)]
        db.add_all([CareTeamMember(patient_id=p.id, user_id=users[email].id, team_role=role, is_primary_coordinator=primary) for p, email, role, primary in entries])
        db.flush()
    db.commit()
    if own: db.close()


if settings.seed_demo:
    run_seed()

DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"
if DIST.is_dir():
    assets = DIST / "assets"
    if assets.is_dir(): app.mount("/assets", StaticFiles(directory=assets), name="assets")


@app.get("/{path:path}", include_in_schema=False)
def spa(path: str, request: Request):
    if path == "api" or path.startswith("api/"): return JSONResponse({"error": {"code": "not_found", "message": "Not found", "details": {}, "request_id": request.state.request_id}}, status_code=404)
    index = DIST / "index.html"
    if index.is_file(): return FileResponse(index, headers={"Cache-Control": "no-cache"})
    return {"message": "The Second Patient API is running", "phase": 1}
