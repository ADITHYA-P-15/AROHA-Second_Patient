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
from app.models import ActivityHistory, CareTeamMember, Patient, Role, TeamRole, User, Caregiver, CaregiverPatientLink, CaregiverWeeklySchedule, AvailabilityOverride, CareActivity, ActivityDependency, CareAssignment, PatientSupportNeed, PatientMessage, Incident, IncidentEvent, Notification
from app.schemas import LoginIn, PasswordIn, PatientIn, PatientPatch, RegisterIn, TeamIn
from app.engine.escalation_classifier import classify_message
from pydantic import BaseModel, ConfigDict, Field
from app.seed import run_seed

logging.basicConfig(level=settings.log_level, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("second_patient")
app = FastAPI(title="CareCircle", version="0.1.0", openapi_url="/api/openapi.json", docs_url="/docs", redoc_url=None)
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
    return {"id": u.id, "email": u.email, "name": u.name, "role": u.role.value, "role_label": role_label(u.role.value), "is_synthetic": u.is_synthetic}


def role_label(role, team_role=None):
    if team_role == TeamRole.COORDINATOR.value: return "Primary contact"
    if team_role == TeamRole.FAMILY.value: return "Family contact"
    return {"PATIENT": "Patient", "FAMILY": "Primary contact", "HOUSEHELP": "Personal caretaker", "NURSE": "Healthcare professional", "DOCTOR": "Doctor", "ADMIN": "Administrator"}.get(role, role)


def patient_dict(p, show_clinical):
    created_at = p.created_at.replace(tzinfo=UTC) if p.created_at.tzinfo is None else p.created_at
    return {"id": p.id, "name": p.name, "birth_year": p.birth_year, "care_notes": p.care_notes, "clinical_notes": p.clinical_notes if show_clinical else None, "is_synthetic": p.is_synthetic, "created_at": created_at}


class PatientMessageIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    body: str = Field(min_length=1, max_length=1000)
    channel: str = Field(default="TEXT", pattern="^(TEXT|SOS_BUTTON|QUICK_REPLY|VOICE)$")
    language_hint: str | None = Field(default=None, max_length=8)
    on_behalf: bool = False


class IncidentResolveIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: str = Field(pattern="^(HANDLED|FALSE_ALARM|REFERRED_TO_EMERGENCY|FOLLOWUP_SCHEDULED|OTHER)$")
    note: str | None = Field(default=None, max_length=1000)


def can_see_clinical(user, member):
    if user.role in (Role.ADMIN, Role.NURSE, Role.DOCTOR): return member is not None or user.role == Role.ADMIN
    return (user.role == Role.PATIENT and member is not None and member.team_role == TeamRole.PATIENT_SELF) or (user.role == Role.FAMILY and member is not None and member.team_role == TeamRole.COORDINATOR)


@app.get("/api/health")
def health(db: Session = Depends(get_db)):
    db.execute(text("SELECT 1"))
    return {"status": "ok", "database": "ok"}


@app.get("/api/v1/meta")
def meta():
    return {"app_name": "CareCircle", "version": "0.3.0", "git_sha": settings.git_sha, "phase": 3, "demo_mode": settings.demo_mode, "server_time": now().isoformat(), "timezone": settings.app_timezone, "ai_enabled": False}


def incident_recipients(db, patient_id, level):
    members = db.execute(select(CareTeamMember, User).join(User).where(CareTeamMember.patient_id == patient_id)).all()
    roles = ({TeamRole.HOUSEHELP} if level == 1 else {TeamRole.COORDINATOR} if level == 2 else {TeamRole.NURSE} if level == 3 else {TeamRole.DOCTOR} if level == 4 else {TeamRole.COORDINATOR, TeamRole.FAMILY, TeamRole.HOUSEHELP, TeamRole.NURSE, TeamRole.DOCTOR})
    return [u for m, u in members if m.team_role in roles and u.is_active]


def incident_payload(item):
    return {"id": item.id, "patient_id": item.patient_id, "current_level": item.current_level, "category": item.category, "severity": item.severity, "status": item.status, "title": item.title, "safe_summary": item.safe_summary, "owner_user_id": item.owner_user_id, "created_at": item.created_at, "acknowledged_at": item.acknowledged_at, "resolved_at": item.resolved_at, "reasons": item.classification.get("reasons", [])}


@app.post("/api/v1/patients/{patient_id}/messages", status_code=201)
def patient_message(patient_id: uuid.UUID, body: PatientMessageIn, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    patient, member = patient_access(db, user, patient_id)
    if user.role == Role.PATIENT:
        if not member or member.team_role != TeamRole.PATIENT_SELF: raise HTTPException(403, "Patient access denied")
    elif not body.on_behalf or not member:
        raise HTTPException(403, "Care team messages must be submitted on behalf of the patient")
    key = request.headers.get("Idempotency-Key")
    if key:
        if len(key) > 120: raise HTTPException(422, "Idempotency-Key is too long")
        prior = db.scalar(select(PatientMessage).where(PatientMessage.sender_user_id == user.id, PatientMessage.idempotency_key == key))
        if prior and prior.incident_id:
            return incident_payload(db.get(Incident, prior.incident_id))
    safe_body = "".join(ch for ch in body.body if ch >= " " or ch in "\n\t").strip()
    if not safe_body: raise HTTPException(422, "Message is empty")
    classification = classify_message(safe_body, language_hint=body.language_hint, context={"mobility_level": patient.mobility_level}, sos=body.channel == "SOS_BUTTON")
    level = classification.level
    recipients = incident_recipients(db, patient.id, level)
    if level == 1 and not recipients:
        level = 2
        recipients = incident_recipients(db, patient.id, level)
    safe_summary = f"{patient.name} asked for help with {classification.category.lower().replace('_', ' ')} at {now().astimezone().strftime('%H:%M')}"
    inc = Incident(patient_id=patient.id, source="SOS" if body.channel == "SOS_BUTTON" else "PATIENT_MESSAGE", category=classification.category, initial_level=level, current_level=level, severity=classification.severity, title="Emergency report" if level == 5 else "Care request", safe_summary=safe_summary, dedupe_key=f"message:{uuid.uuid4()}", classification=classification.as_dict())
    db.add(inc); db.flush()
    msg = PatientMessage(patient_id=patient.id, sender_user_id=user.id, on_behalf=body.on_behalf, reported_role=user.role.value, channel=body.channel, body=safe_body, language_hint=body.language_hint, idempotency_key=key, incident_id=inc.id)
    db.add(msg)
    for recipient in recipients:
        db.add(Notification(user_id=recipient.id, patient_id=patient.id, incident_id=inc.id, kind="INCIDENT", severity=classification.severity, title="Emergency report" if level == 5 else "Care request", body=safe_summary, requires_ack=level > 0))
    db.add(IncidentEvent(incident_id=inc.id, kind="CREATED", level=level, actor_user_id=user.id, recipient_user_ids=[str(x.id) for x in recipients], meta={"category": classification.category, "rule_ids": [x.id for x in classification.matched_rules]}))
    db.add(IncidentEvent(incident_id=inc.id, kind="CLASSIFIED", level=level, actor_user_id=None, meta={"reasons": list(classification.reasons), "classifier_version": classification.classifier_version}))
    audit(db, user, patient.id, "INCIDENT_CREATED", "incident", inc.id, "Care request routed", request.state.request_id)
    db.commit(); db.refresh(inc)
    return incident_payload(inc)


@app.post("/api/v1/patients/{patient_id}/sos", status_code=201)
def patient_sos(patient_id: uuid.UUID, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    return patient_message(patient_id, PatientMessageIn(body="SOS emergency report", channel="SOS_BUTTON"), request, user, db)


@app.get("/api/v1/incidents")
def list_incidents(patient_id: uuid.UUID | None = None, status: str | None = None, user: User = Depends(current_user), db: Session = Depends(get_db)):
    query = select(Incident)
    if patient_id is not None:
        patient_access(db, user, patient_id)
        query = query.where(Incident.patient_id == patient_id)
    elif user.role != Role.ADMIN:
        ids = select(CareTeamMember.patient_id).where(CareTeamMember.user_id == user.id)
        query = query.where(Incident.patient_id.in_(ids))
    if status: query = query.where(Incident.status == status.upper())
    return {"items": [incident_payload(x) for x in db.scalars(query.order_by(Incident.created_at.desc()).limit(100)).all()]}


@app.post("/api/v1/incidents/{incident_id}/acknowledge")
def acknowledge_incident(incident_id: uuid.UUID, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    inc = db.get(Incident, incident_id)
    if not inc: raise HTTPException(404, "Incident not found")
    patient, _ = patient_access(db, user, inc.patient_id)
    if user.role == Role.PATIENT: raise HTTPException(403, "Patient cannot acknowledge incidents")
    if inc.status in ("RESOLVED", "CANCELLED"): return incident_payload(inc)
    if inc.status == "OPEN":
        inc.status = "ACKNOWLEDGED"; inc.owner_user_id = user.id; inc.acknowledged_at = now(); inc.version += 1
        db.add(IncidentEvent(incident_id=inc.id, kind="ACKNOWLEDGED", level=inc.current_level, actor_user_id=user.id, note="Recipient acknowledged"))
        db.add(Notification(user_id=user.id, patient_id=patient.id, incident_id=inc.id, kind="STATUS", severity=inc.severity, title="You are handling this request", body="The patient request is acknowledged.", requires_ack=False))
        audit(db, user, patient.id, "INCIDENT_ACKNOWLEDGED", "incident", inc.id, "Care request acknowledged", request.state.request_id)
        db.commit(); db.refresh(inc)
    return incident_payload(inc)


@app.post("/api/v1/incidents/{incident_id}/resolve")
def resolve_incident(incident_id: uuid.UUID, body: IncidentResolveIn, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    inc = db.get(Incident, incident_id)
    if not inc: raise HTTPException(404, "Incident not found")
    patient, _ = patient_access(db, user, inc.patient_id, "update")
    if user.role == Role.PATIENT: raise HTTPException(403, "Patient cannot resolve incidents")
    if inc.current_level == 5 and (inc.status == "OPEN" or not body.note): raise HTTPException(422, "Emergency resolution requires acknowledgement and a note")
    inc.status = "RESOLVED"; inc.resolved_at = now(); inc.resolution_code = body.code; inc.resolution_note = body.note; inc.version += 1
    db.add(IncidentEvent(incident_id=inc.id, kind="RESOLVED", level=inc.current_level, actor_user_id=user.id, note="Incident resolved"))
    audit(db, user, patient.id, "INCIDENT_RESOLVED", "incident", inc.id, "Care request resolved", request.state.request_id)
    db.commit(); db.refresh(inc)
    return incident_payload(inc)


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


# Extended patient representations and the Phase 2 domain API are registered
# ahead of the original foundation routes sharing patient URL paths.
from app.api.domain import router as domain_router
app.include_router(domain_router)


@app.get("/api/v1/patients")
def list_patients(limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0), user: User = Depends(current_user), db: Session = Depends(get_db)):
    stmt = select(Patient) if user.role == Role.ADMIN else select(Patient).join(CareTeamMember).where(CareTeamMember.user_id == user.id)
    total = len(db.scalars(stmt).all())
    patients = db.scalars(stmt.order_by(Patient.created_at.desc()).offset(offset).limit(limit)).all()
    return {"items": [patient_dict(p, can_see_clinical(user, db.scalar(select(CareTeamMember).where(CareTeamMember.patient_id == p.id, CareTeamMember.user_id == user.id)))) for p in patients], "total": total, "limit": limit, "offset": offset}


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
    return {"items": [{"id": m.id, "user_id": u.id, "name": u.name, "email": u.email if contact_visible else None, "role": u.role.value, "role_label": role_label(u.role.value, m.team_role.value), "team_role": m.team_role.value, "is_primary_coordinator": m.is_primary_coordinator} for m, u in rows]}


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
    return {"id": m.id, "user_id": target.id, "team_role": team_role.value, "role_label": role_label(target.role.value, team_role.value)}


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
    db.query(ActivityHistory).delete()
    db.query(CareAssignment).delete(); db.query(ActivityDependency).delete(); db.query(CareActivity).delete(); db.query(AvailabilityOverride).delete(); db.query(CaregiverWeeklySchedule).delete(); db.query(CaregiverPatientLink).delete(); db.query(Caregiver).delete(); db.query(PatientSupportNeed).delete()
    db.query(CareTeamMember).delete(); db.query(Patient).delete(); db.commit()
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
    from app.seed.phase2 import seed_phase2
    seed_phase2(db)
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
    return {"message": "CareCircle API is running", "phase": 3}
