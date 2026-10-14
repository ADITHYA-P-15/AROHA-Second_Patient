import logging
import json
import re
import time
import uuid
import unicodedata
import asyncio
from collections import defaultdict, deque
from datetime import UTC, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import jwt
from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select, text, func
from sqlalchemy.orm import Session

from app.core.clock import now
from app.core.config import settings
from app.core.db import Base, engine, get_db, SessionLocal
from app.core.security import create_token, hash_password, verify_password
from app.core.permissions import require_patient_access
from app.models import ActivityHistory, CareTeamMember, Patient, Role, TeamRole, User, Caregiver, CaregiverPatientLink, CaregiverWeeklySchedule, AvailabilityOverride, CareActivity, ActivityDependency, CareAssignment, PatientSupportNeed, PatientMessage, Incident, IncidentEvent, Notification, EscalationPolicy, AppSetting, ActionItem, BriefAcknowledgement, DailyBrief, HandoverItem
from app.schemas import LoginIn, PasswordIn, PatientIn, PatientPatch, RegisterIn, TeamIn
from app.engine.escalation_classifier import classify_message
from app.engine.escalation_machine import DEFAULT_POLICY, deadline_minutes
from app.services.escalation import policy_for, run_escalation_tick, set_deadline
from app.services.command_center import reconcile_patient, run_command_center_tick
from app.services.backup_matcher import run_cover_tick
from app.services.coverage_planner import run_planner_tick
from pydantic import BaseModel, ConfigDict, Field, model_validator
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


def user_dict(u, db=None):
    label = role_label(u.role.value)
    if db is not None and u.role == Role.FAMILY:
        memberships = db.scalars(select(CareTeamMember.team_role).where(CareTeamMember.user_id == u.id)).all()
        if memberships and TeamRole.COORDINATOR not in memberships: label = "Family contact"
    return {"id": u.id, "email": u.email, "name": u.name, "role": u.role.value, "role_label": label, "is_synthetic": u.is_synthetic}


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


class SosIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    on_behalf: bool = False


class IncidentLevelIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    to_level: int = Field(ge=0, le=5)
    reason: str = Field(min_length=1, max_length=500)


class EscalationPolicyIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ack_minutes: dict[str, int]
    resolve_minutes: dict[str, int]
    family_contact_delay_fraction: float = Field(ge=0, le=1)
    quiet_hours: dict[str, str]

    @model_validator(mode="after")
    def bounds(self):
        required = {"1", "2", "3", "4", "5"}
        if set(self.ack_minutes) != required or set(self.resolve_minutes) != required:
            raise ValueError("Timer configuration must include levels 1 through 5")
        if any(not 1 <= value <= 1440 for value in (*self.ack_minutes.values(), *self.resolve_minutes.values())):
            raise ValueError("Timer values must be between 1 minute and 24 hours")
        if self.ack_minutes["5"] > 5:
            raise ValueError("Emergency acknowledgement cadence cannot exceed 5 minutes")
        if set(self.quiet_hours) != {"start", "end"} or any(not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", value) for value in self.quiet_hours.values()):
            raise ValueError("Quiet hours must contain start and end in HH:MM format")
        return self


class DemoEscalationSpeedIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scale: float = Field(gt=0, le=10)


def can_see_clinical(user, member):
    if user.role in (Role.ADMIN, Role.NURSE, Role.DOCTOR): return member is not None or user.role == Role.ADMIN
    return (user.role == Role.PATIENT and member is not None and member.team_role == TeamRole.PATIENT_SELF) or (user.role == Role.FAMILY and member is not None and member.team_role == TeamRole.COORDINATOR)


@app.get("/api/health")
def health(db: Session = Depends(get_db)):
    db.execute(text("SELECT 1"))
    return {"status": "ok", "database": "ok"}


@app.get("/api/v1/meta")
def meta(db: Session = Depends(get_db)):
    scale = current_escalation_scale(db)
    return {"app_name": "CareCircle", "version": "0.4.0", "git_sha": settings.git_sha, "phase": 4, "demo_mode": settings.demo_mode, "escalation_time_scale": scale, "escalation_scaled": settings.demo_mode and scale != 1.0, "server_time": now().isoformat(), "timezone": settings.app_timezone, "ai_enabled": False}


def incident_recipients(db, patient_id, level):
    if level == 0: return []
    members = db.execute(select(CareTeamMember, User).join(User).where(CareTeamMember.patient_id == patient_id)).all()
    roles = ({TeamRole.HOUSEHELP} if level == 1 else {TeamRole.COORDINATOR} if level == 2 else {TeamRole.NURSE} if level == 3 else {TeamRole.DOCTOR} if level == 4 else {TeamRole.COORDINATOR, TeamRole.FAMILY, TeamRole.HOUSEHELP, TeamRole.NURSE, TeamRole.DOCTOR})
    recipients = [u for m, u in members if m.team_role in roles and u.is_active]
    # No nurse (L3) or doctor (L4) on the team: route to the primary contact instead of notifying nobody.
    if level in (3, 4) and not recipients:
        recipients = [u for m, u in members if m.team_role == TeamRole.COORDINATOR and u.is_active]
    return recipients


def incident_payload(item):
    return {"id": item.id, "patient_id": item.patient_id, "current_level": item.current_level, "category": item.category, "severity": item.severity, "status": item.status, "title": item.title, "safe_summary": item.safe_summary, "owner_user_id": item.owner_user_id, "created_at": item.created_at, "current_deadline_at": item.current_deadline_at, "deadline_kind": item.deadline_kind, "emergency_unacknowledged": item.emergency_unacknowledged, "acknowledged_at": item.acknowledged_at, "resolved_at": item.resolved_at}


def current_escalation_scale(db=None):
    if not settings.demo_mode: return 1.0
    if db is not None:
        setting = db.get(AppSetting, "escalation_time_scale")
        if setting: return max(0.01, min(float(setting.value.get("scale", settings.escalation_time_scale)), 10.0))
    return max(0.01, min(float(settings.escalation_time_scale), 10.0))


def may_act_on_incident(db, incident, user, member):
    if user.role == Role.ADMIN or (member and member.team_role == TeamRole.COORDINATOR): return True
    event = db.scalar(select(IncidentEvent).where(IncidentEvent.incident_id == incident.id, IncidentEvent.level == incident.current_level, IncidentEvent.kind.in_(("CREATED", "MANUAL_ESCALATED", "AUTO_ESCALATED"))).order_by(IncidentEvent.at.desc()))
    return bool(event and str(user.id) in (event.recipient_user_ids or []))


def may_read_incident(db, incident, user, member):
    if user.role == Role.ADMIN or user.role == Role.PATIENT and member and member.team_role == TeamRole.PATIENT_SELF: return True
    if member and member.team_role == TeamRole.COORDINATOR: return True
    if user.role == Role.NURSE: return incident.current_level >= 3
    if user.role == Role.DOCTOR: return incident.current_level >= 4 or incident.current_level == 5
    return db.scalar(select(Notification.id).where(Notification.incident_id == incident.id, Notification.user_id == user.id)) is not None


def locked_incident(db, incident_id):
    return db.scalar(select(Incident).where(Incident.id == incident_id).with_for_update())


@app.post("/api/v1/patients/{patient_id}/messages", status_code=201)
def patient_message(patient_id: uuid.UUID, body: PatientMessageIn, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    patient, member = patient_access(db, user, patient_id)
    if user.role == Role.PATIENT:
        if not member or member.team_role != TeamRole.PATIENT_SELF: raise HTTPException(403, "Patient access denied")
        if body.on_behalf: raise HTTPException(422, "Patients cannot submit on behalf of another person")
    elif not body.on_behalf or not member:
        raise HTTPException(403, "Care team messages must be submitted on behalf of the patient")
    key = request.headers.get("Idempotency-Key")
    if key:
        if len(key) > 120: raise HTTPException(422, "Idempotency-Key is too long")
        prior = db.scalar(select(PatientMessage).where(PatientMessage.sender_user_id == user.id, PatientMessage.idempotency_key == key))
        if prior and prior.patient_id != patient.id: raise HTTPException(409, "Idempotency-Key was already used for another patient")
        if prior and prior.incident_id:
            return incident_payload(db.get(Incident, prior.incident_id))
    safe_body = "".join(ch for ch in body.body if unicodedata.category(ch)[0] != "C" or ch in "\n\t").strip()
    if not safe_body: raise HTTPException(422, "Message is empty")
    classification = classify_message(safe_body, language_hint=body.language_hint, context={"mobility_level": patient.mobility_level}, sos=body.channel == "SOS_BUTTON")
    level = classification.level
    no_recipients_levels = []
    recipients = incident_recipients(db, patient.id, level)
    if level == 1 and not recipients:
        no_recipients_levels.append(level)
        level = 2
        recipients = incident_recipients(db, patient.id, level)
    if level > 0 and not recipients:
        no_recipients_levels.append(level)
    safe_summary = f"{patient.name} asked for help with {classification.category.lower().replace('_', ' ')} at {now().astimezone(ZoneInfo(settings.app_timezone)).strftime('%H:%M')}"
    source = "SOS" if body.channel == "SOS_BUTTON" else "CARETAKER_REPORT" if body.on_behalf else "PATIENT_MESSAGE"
    inc = Incident(patient_id=patient.id, source=source, category=classification.category, initial_level=level, current_level=level, severity=classification.severity, title="Emergency report" if level == 5 else "Care request", safe_summary=safe_summary, dedupe_key=f"message:{uuid.uuid4()}", classification=classification.as_dict())
    db.add(inc); db.flush()
    if level > 0:
        created_at = now()
        set_deadline(inc, policy_for(db, patient.id), "ACK", created_at, current_escalation_scale(db))
        if not recipients: inc.current_deadline_at = created_at
    msg = PatientMessage(patient_id=patient.id, sender_user_id=user.id, on_behalf=body.on_behalf, reported_role=user.role.value, channel=body.channel, body=safe_body, language_hint=body.language_hint, idempotency_key=key, incident_id=inc.id)
    db.add(msg)
    missing_doctor = level == 4 and db.scalar(select(CareTeamMember.id).where(CareTeamMember.patient_id == patient.id, CareTeamMember.team_role == TeamRole.DOCTOR)) is None
    notice_title = "No doctor on this care team" if missing_doctor else "Emergency report" if level == 5 else "Care request"
    notice_body = "No doctor on this care team — contact the clinic, or call 108/112 if urgent." if missing_doctor else safe_summary
    for recipient in recipients:
        db.add(Notification(user_id=recipient.id, patient_id=patient.id, incident_id=inc.id, kind="INCIDENT", severity=classification.severity, title=notice_title, body=notice_body, requires_ack=level > 0))
    db.add(IncidentEvent(incident_id=inc.id, kind="CREATED", level=level, actor_user_id=user.id, recipient_user_ids=[str(x.id) for x in recipients], meta={"category": classification.category, "rule_ids": [x.id for x in classification.matched_rules]}))
    if recipients: db.add(IncidentEvent(incident_id=inc.id, kind="NOTIFIED", level=level, actor_user_id=None, recipient_user_ids=[str(x.id) for x in recipients]))
    db.add(IncidentEvent(incident_id=inc.id, kind="CLASSIFIED", level=level, actor_user_id=None, meta={"reasons": list(classification.reasons), "classifier_version": classification.classifier_version}))
    for no_recipient_level in no_recipients_levels: db.add(IncidentEvent(incident_id=inc.id, kind="NO_RECIPIENTS", level=no_recipient_level, meta={"advanced_to": level}))
    audit(db, user, patient.id, "INCIDENT_CREATED", "incident", inc.id, "Care request routed", request.state.request_id)
    db.flush(); reconcile_patient(db, patient.id)
    db.commit(); db.refresh(inc)
    return incident_payload(inc)


@app.post("/api/v1/patients/{patient_id}/sos", status_code=201)
def patient_sos(patient_id: uuid.UUID, request: Request, body: SosIn | None = None, user: User = Depends(current_user), db: Session = Depends(get_db)):
    return patient_message(patient_id, PatientMessageIn(body="SOS emergency report", channel="SOS_BUTTON", on_behalf=body.on_behalf if body else False), request, user, db)


@app.get("/api/v1/incidents")
def list_incidents(patient_id: uuid.UUID | None = None, status: str | None = None, user: User = Depends(current_user), db: Session = Depends(get_db)):
    query = select(Incident)
    if patient_id is not None:
        _, member = patient_access(db, user, patient_id)
        query = query.where(Incident.patient_id == patient_id)
    elif user.role != Role.ADMIN:
        ids = select(CareTeamMember.patient_id).where(CareTeamMember.user_id == user.id)
        query = query.where(Incident.patient_id.in_(ids))
    if status: query = query.where(Incident.status == status.upper())
    items = db.scalars(query.order_by(Incident.created_at.desc()).limit(200)).all()
    visible = []
    for item in items:
        _, member = patient_access(db, user, item.patient_id)
        if may_read_incident(db, item, user, member): visible.append(incident_payload(item))
    return {"items": visible[:100]}


@app.get("/api/v1/incidents/{incident_id}")
def get_incident(incident_id: uuid.UUID, user: User = Depends(current_user), db: Session = Depends(get_db)):
    inc = db.get(Incident, incident_id)
    if not inc: raise HTTPException(404, "Incident not found")
    _, member = patient_access(db, user, inc.patient_id)
    if not may_read_incident(db, inc, user, member): raise HTTPException(403, "Incident access denied")
    events = db.scalars(select(IncidentEvent).where(IncidentEvent.incident_id == inc.id).order_by(IncidentEvent.at.asc())).all()
    timeline = [{"at": event.at, "kind": event.kind, "level": event.level} if user.role == Role.PATIENT else {"at": event.at, "kind": event.kind, "level": event.level, "note": event.note, "meta": event.meta} for event in events]
    payload = {**incident_payload(inc), "timeline": timeline}
    if user.role != Role.PATIENT: payload["why_this_level"] = inc.classification.get("reasons", [])
    return payload


@app.post("/api/v1/incidents/{incident_id}/escalate")
def escalate_incident(incident_id: uuid.UUID, body: IncidentLevelIn, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    inc = locked_incident(db, incident_id)
    if not inc: raise HTTPException(404, "Incident not found")
    patient, member = patient_access(db, user, inc.patient_id)
    if not member and user.role != Role.ADMIN: raise HTTPException(403, "Permission denied")
    if inc.status in ("RESOLVED", "CANCELLED"): raise HTTPException(409, "Closed incidents cannot be escalated")
    if body.to_level <= inc.current_level: raise HTTPException(422, "Escalation level must be higher")
    inc.current_level = body.to_level; inc.version += 1
    set_deadline(inc, policy_for(db, patient.id), "ACK", now(), current_escalation_scale(db))
    recipients = incident_recipients(db, patient.id, inc.current_level)
    for recipient in recipients:
        db.add(Notification(user_id=recipient.id, patient_id=patient.id, incident_id=inc.id, kind="INCIDENT", severity=inc.severity, title="Care request escalated", body=inc.safe_summary, requires_ack=True))
    db.add(IncidentEvent(incident_id=inc.id, kind="MANUAL_ESCALATED", level=inc.current_level, actor_user_id=user.id, recipient_user_ids=[str(x.id) for x in recipients], note=body.reason))
    audit(db, user, patient.id, "INCIDENT_ESCALATED", "incident", inc.id, "Care request escalated", request.state.request_id)
    db.flush(); reconcile_patient(db, patient.id)
    db.commit(); db.refresh(inc)
    return incident_payload(inc)


@app.post("/api/v1/incidents/{incident_id}/lower")
def lower_incident(incident_id: uuid.UUID, body: IncidentLevelIn, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    inc = locked_incident(db, incident_id)
    if not inc: raise HTTPException(404, "Incident not found")
    patient, member = patient_access(db, user, inc.patient_id)
    privileged = user.role in (Role.ADMIN, Role.NURSE, Role.DOCTOR) or bool(member and member.team_role == TeamRole.COORDINATOR)
    if not privileged: raise HTTPException(403, "Permission denied")
    if inc.status in ("RESOLVED", "CANCELLED"): raise HTTPException(409, "Closed incidents cannot be lowered")
    if body.to_level >= inc.current_level: raise HTTPException(422, "Lowering level must be lower")
    if inc.current_level == 5 and inc.status == "OPEN": raise HTTPException(409, "Emergency must be acknowledged before lowering")
    inc.current_level = body.to_level; inc.version += 1
    set_deadline(inc, policy_for(db, patient.id), "ACK", now(), current_escalation_scale(db))
    db.add(IncidentEvent(incident_id=inc.id, kind="LEVEL_LOWERED", level=inc.current_level, actor_user_id=user.id, note=body.reason))
    audit(db, user, patient.id, "LEVEL_LOWERED", "incident", inc.id, "Care request routing level lowered", request.state.request_id)
    db.flush(); reconcile_patient(db, patient.id)
    db.commit(); db.refresh(inc)
    return incident_payload(inc)


@app.post("/api/v1/incidents/{incident_id}/acknowledge")
def acknowledge_incident(incident_id: uuid.UUID, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    inc = locked_incident(db, incident_id)
    if not inc: raise HTTPException(404, "Incident not found")
    patient, member = patient_access(db, user, inc.patient_id)
    if user.role == Role.PATIENT: raise HTTPException(403, "Patient cannot acknowledge incidents")
    if not may_act_on_incident(db, inc, user, member): raise HTTPException(403, "Only an incident recipient or primary contact can acknowledge")
    if inc.status in ("RESOLVED", "CANCELLED"): return incident_payload(inc)
    if inc.status == "OPEN":
        inc.status = "ACKNOWLEDGED"; inc.owner_user_id = user.id; inc.acknowledged_at = now(); inc.version += 1
        set_deadline(inc, policy_for(db, patient.id), "RESOLVE", inc.acknowledged_at, current_escalation_scale(db))
        db.add(IncidentEvent(incident_id=inc.id, kind="ACKNOWLEDGED", level=inc.current_level, actor_user_id=user.id, note="Recipient acknowledged"))
        db.add(Notification(user_id=user.id, patient_id=patient.id, incident_id=inc.id, kind="STATUS", severity=inc.severity, title="You are handling this request", body="The patient request is acknowledged.", requires_ack=False,channel="INBOX"))
        event = db.scalar(select(IncidentEvent).where(IncidentEvent.incident_id == inc.id, IncidentEvent.level == inc.current_level, IncidentEvent.kind.in_(("CREATED", "MANUAL_ESCALATED", "AUTO_ESCALATED"))).order_by(IncidentEvent.at.desc()))
        if event:
            recipient_ids=[uuid.UUID(item) for item in event.recipient_user_ids or []]
            for recipient in db.scalars(select(User).where(User.id.in_(recipient_ids), User.id != user.id)):
                db.add(Notification(user_id=recipient.id, patient_id=patient.id, incident_id=inc.id, kind="STATUS", severity=inc.severity, title="Care request is being handled", body=f"{user.name} is handling this request.", requires_ack=False,channel="INBOX"))
        audit(db, user, patient.id, "INCIDENT_ACKNOWLEDGED", "incident", inc.id, "Care request acknowledged", request.state.request_id)
        db.flush(); reconcile_patient(db, patient.id)
        db.commit(); db.refresh(inc)
    return incident_payload(inc)


@app.post("/api/v1/activities/{activity_id}/acknowledge")
def acknowledge_activity(activity_id: uuid.UUID, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    activity = db.get(CareActivity, activity_id)
    if not activity: raise HTTPException(404, "Activity not found")
    patient, _ = patient_access(db, user, activity.patient_id)
    assigned = db.scalar(select(CareAssignment.id).join(Caregiver).where(CareAssignment.activity_id == activity.id, CareAssignment.role == "PRIMARY", CareAssignment.status == "CONFIRMED", Caregiver.user_id == user.id))
    if not assigned: raise HTTPException(403, "Only the assigned primary caregiver can acknowledge this activity")
    if activity.acknowledged_at is None:
        activity.acknowledged_at = now(); activity.acknowledged_by = user.id
        incidents = db.scalars(select(Incident).where(Incident.related_activity_id == activity.id, Incident.source == "TASK_UNACKNOWLEDGED", Incident.status == "OPEN")).all()
        for inc in incidents:
            inc.status="ACKNOWLEDGED";inc.owner_user_id=user.id;inc.acknowledged_at=activity.acknowledged_at;inc.version+=1
            set_deadline(inc,policy_for(db,patient.id),"RESOLVE",inc.acknowledged_at,current_escalation_scale(db))
            db.add(IncidentEvent(incident_id=inc.id,kind="ACKNOWLEDGED",level=inc.current_level,actor_user_id=user.id,note="Assigned caregiver acknowledged the activity"))
        audit(db,user,patient.id,"TASK_ACKNOWLEDGED","care_activity",activity.id,"Assigned caregiver acknowledged activity",request.state.request_id)
        db.flush(); reconcile_patient(db, patient.id)
        db.commit()
    return {"activity_id":activity.id,"acknowledged_at":activity.acknowledged_at,"acknowledged_by":activity.acknowledged_by}


@app.get("/api/v1/notifications")
def list_notifications(unread: bool = False, user: User = Depends(current_user), db: Session = Depends(get_db)):
    query = select(Notification).where(Notification.user_id == user.id)
    if unread: query = query.where(Notification.read_at.is_(None))
    rows = db.scalars(query.order_by(Notification.created_at.desc()).limit(100)).all()
    unread_count=db.scalar(select(func.count(Notification.id)).where(Notification.user_id==user.id,Notification.read_at.is_(None))) or 0
    return {"items": [{"id": n.id, "patient_id": n.patient_id, "incident_id": n.incident_id, "kind": n.kind, "severity": n.severity, "title": n.title, "body": n.body, "requires_ack": n.requires_ack, "channel": n.channel, "read_at": n.read_at, "created_at": n.created_at} for n in rows], "unread_count": unread_count}


@app.post("/api/v1/notifications/{notification_id}/read")
def notification_read(notification_id: uuid.UUID, user: User = Depends(current_user), db: Session = Depends(get_db)):
    item = db.scalar(select(Notification).where(Notification.id == notification_id, Notification.user_id == user.id))
    if not item: raise HTTPException(404, "Notification not found")
    item.read_at = item.read_at or now(); db.commit()
    return {"id": item.id, "read_at": item.read_at}


@app.get("/api/v1/patients/{patient_id}/escalation-policy")
def get_escalation_policy(patient_id: uuid.UUID, user: User = Depends(current_user), db: Session = Depends(get_db)):
    patient_access(db, user, patient_id)
    row = db.scalar(select(EscalationPolicy).where(EscalationPolicy.patient_id == patient_id))
    system = row or db.scalar(select(EscalationPolicy).where(EscalationPolicy.patient_id.is_(None)))
    return {"patient_id": patient_id, "config": system.config if system else DEFAULT_POLICY, "version": system.version if system else 1, "is_system_default": row is None}


@app.put("/api/v1/patients/{patient_id}/escalation-policy")
def update_escalation_policy(patient_id: uuid.UUID, body: EscalationPolicyIn, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    patient, member = patient_access(db, user, patient_id, "update")
    if user.role != Role.ADMIN and (not member or member.team_role != TeamRole.COORDINATOR): raise HTTPException(403, "Coordinator permission required")
    row = db.scalar(select(EscalationPolicy).where(EscalationPolicy.patient_id == patient.id))
    if not row:
        row = EscalationPolicy(patient_id=patient.id, config=body.model_dump(), version=1, updated_by=user.id); db.add(row)
    else:
        row.config = body.model_dump(); row.version += 1; row.updated_by = user.id; row.updated_at = now()
    audit(db, user, patient.id, "POLICY_UPDATED", "escalation_policy", row.id or "new", "Escalation policy updated", request.state.request_id)
    db.commit(); db.refresh(row)
    return {"patient_id": patient.id, "config": row.config, "version": row.version, "is_system_default": False}


@app.post("/api/v1/patients/{patient_id}/escalation-policy/reset")
def reset_escalation_policy(patient_id: uuid.UUID, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    patient, member = patient_access(db, user, patient_id, "update")
    if user.role != Role.ADMIN and (not member or member.team_role != TeamRole.COORDINATOR): raise HTTPException(403, "Coordinator permission required")
    row = db.scalar(select(EscalationPolicy).where(EscalationPolicy.patient_id == patient.id))
    if row: db.delete(row)
    audit(db, user, patient.id, "POLICY_UPDATED", "escalation_policy", patient.id, "Escalation policy reset", request.state.request_id)
    db.commit()
    system = db.scalar(select(EscalationPolicy).where(EscalationPolicy.patient_id.is_(None)))
    return {"patient_id": patient.id, "config": system.config if system else DEFAULT_POLICY, "version": system.version if system else 1, "is_system_default": True}


@app.post("/api/v1/admin/demo/escalation-speed")
def set_demo_escalation_speed(body: DemoEscalationSpeedIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    if user.role != Role.ADMIN or not settings.demo_mode: raise HTTPException(404, "Not found")
    setting = db.get(AppSetting, "escalation_time_scale")
    if not setting:
        setting = AppSetting(key="escalation_time_scale", value={"scale": body.scale}); db.add(setting)
    else: setting.value = {"scale": body.scale}
    db.commit()
    return {"scale": body.scale, "demo_mode": True}


@app.post("/api/v1/admin/demo/scenarios/{scenario_name}")
def run_demo_escalation_scenario(scenario_name: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    if user.role != Role.ADMIN or not settings.demo_mode: raise HTTPException(404, "Not found")
    if scenario_name in {"command_center_messy_day", "command_center_clear_day"}:
        patient = db.scalar(select(Patient).where(Patient.is_synthetic.is_(True)).order_by(Patient.created_at.asc()))
        if not patient: raise HTTPException(404, "Synthetic demo patient not found")
        titles = ("Demo · unassigned same-day pickup", "Demo · awaiting caregiver confirmation")
        activities = db.scalars(select(CareActivity).where(CareActivity.patient_id == patient.id, CareActivity.title.in_(titles))).all()
        if scenario_name == "command_center_clear_day":
            for activity in activities: activity.lifecycle_status = "CANCELLED"
            db.commit()
            return {"scenario": scenario_name, "status": "cleared", "activities": len(activities)}
        if activities: return {"scenario": scenario_name, "status": "already_seeded", "patient_id": str(patient.id)}
        coordinator = db.scalar(select(CareTeamMember).where(CareTeamMember.patient_id == patient.id, CareTeamMember.team_role == TeamRole.COORDINATOR))
        caregiver = db.scalar(select(Caregiver).where(Caregiver.user_id.is_not(None), Caregiver.is_synthetic.is_(True)).order_by(Caregiver.name))
        if not coordinator or not caregiver: raise HTTPException(409, "Synthetic coordinator or caregiver is not seeded")
        zone = ZoneInfo(settings.app_timezone)
        local_start = now().astimezone(zone).replace(second=0, microsecond=0) + timedelta(hours=2)
        start = local_start.astimezone(UTC)
        first = CareActivity(patient_id=patient.id, title=titles[0], category="PRESCRIPTION", scheduled_start=start, scheduled_end=start + timedelta(minutes=45), deadline=start + timedelta(hours=3), importance="HIGH", requires_caregiver=True, required_support=["PRESCRIPTION_PICKUP"], lifecycle_status="SCHEDULED", is_synthetic=True, created_by=user.id)
        second = CareActivity(patient_id=patient.id, title=titles[1], category="DAILY_ROUTINE", scheduled_start=start + timedelta(hours=1), scheduled_end=start + timedelta(hours=1, minutes=30), deadline=start + timedelta(hours=2), importance="MEDIUM", requires_caregiver=True, required_support=["DAILY_ASSIST"], lifecycle_status="SCHEDULED", is_synthetic=True, created_by=user.id)
        db.add_all([first, second]); db.flush()
        db.add(CareAssignment(activity_id=second.id, caregiver_id=caregiver.id, role="PRIMARY", status="AWAITING_CONFIRMATION", assigned_by=user.id, assigned_at=now()))
        db.add(ActivityHistory(actor_user_id=user.id, patient_id=patient.id, event_type="command_center.demo_seeded", entity_type="care_activity", entity_id=str(first.id), summary="Synthetic command-center demo scenario added", payload={"is_synthetic": True}))
        db.flush(); reconcile_patient(db, patient.id); db.commit()
        return {"scenario": scenario_name, "status": "seeded", "patient_id": str(patient.id)}
    if scenario_name == "reset_incidents":
        patient_ids=list(db.scalars(select(Patient.id).where(Patient.is_synthetic.is_(True))))
        if patient_ids:
            incident_ids=list(db.scalars(select(Incident.id).where(Incident.patient_id.in_(patient_ids))))
            if incident_ids:
                db.query(Notification).filter(Notification.incident_id.in_(incident_ids)).delete(synchronize_session=False)
                db.query(IncidentEvent).filter(IncidentEvent.incident_id.in_(incident_ids)).delete(synchronize_session=False)
                db.query(PatientMessage).filter(PatientMessage.incident_id.in_(incident_ids)).delete(synchronize_session=False)
                db.query(Incident).filter(Incident.id.in_(incident_ids)).delete(synchronize_session=False)
            for patient_id in patient_ids: reconcile_patient(db, patient_id)
        db.commit()
        return {"scenario": scenario_name, "status": "reset"}
    scenarios={"daily_help":("DAILY_HELP",1,"Care request","A patient needs daily assistance."),
               "missed_task":("TASK",1,"TASK_OVERDUE","A scheduled care activity is overdue."),
               "health_concern":("HEALTH_CONCERN",3,"Health concern","A patient reported a health concern."),
               "logistics_failure":("LOGISTICS",2,"Coordination needed","A patient reported a support coordination gap."),
               "sos":("EMERGENCY",5,"Emergency report","A patient submitted an SOS report.")}
    if scenario_name not in scenarios: raise HTTPException(404, "Unknown demo scenario")
    patient=db.scalar(select(Patient).where(Patient.is_synthetic.is_(True)).order_by(Patient.created_at.asc()))
    if not patient: raise HTTPException(404, "Synthetic demo patient not found")
    category,level,title,summary=scenarios[scenario_name]
    recipients=incident_recipients(db,patient.id,level)
    if level==1 and not recipients: level=2;recipients=incident_recipients(db,patient.id,level)
    inc=Incident(patient_id=patient.id,source="SOS" if scenario_name=="sos" else "TASK_OVERDUE" if scenario_name=="missed_task" else "MANUAL",category=category,initial_level=level,current_level=level,importance="HIGH" if scenario_name=="missed_task" else "MEDIUM",severity="HIGH" if level>=3 else "MEDIUM",status="OPEN",title=title,safe_summary=f"{patient.name}: {summary}",dedupe_key=f"scenario:{scenario_name}:{uuid.uuid4()}",classification={"rule_ids":[f"scenario_{scenario_name}"],"reasons":["Created by an administrator demo scenario"],"classifier_version":"demo-scenario-1"})
    db.add(inc);db.flush()
    if level>0: set_deadline(inc,policy_for(db,patient.id),"ACK",now(),current_escalation_scale(db))
    for recipient in recipients:
        db.add(Notification(user_id=recipient.id,patient_id=patient.id,incident_id=inc.id,kind="INCIDENT",severity=inc.severity,title=title,body=inc.safe_summary,requires_ack=True))
    db.add(IncidentEvent(incident_id=inc.id,kind="CREATED",level=level,actor_user_id=user.id,recipient_user_ids=[str(person.id) for person in recipients],meta={"scenario":scenario_name}))
    if recipients: db.add(IncidentEvent(incident_id=inc.id,kind="NOTIFIED",level=level,actor_user_id=None,recipient_user_ids=[str(person.id) for person in recipients]))
    audit(db,user,patient.id,"INCIDENT_CREATED","incident",inc.id,"Synthetic demo scenario created")
    db.commit();db.refresh(inc)
    return {"scenario":scenario_name,"incident_id":inc.id,"incident":incident_payload(inc)}


@app.post("/api/v1/incidents/{incident_id}/resolve")
def resolve_incident(incident_id: uuid.UUID, body: IncidentResolveIn, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    inc = locked_incident(db, incident_id)
    if not inc: raise HTTPException(404, "Incident not found")
    patient, member = patient_access(db, user, inc.patient_id)
    if user.role == Role.PATIENT: raise HTTPException(403, "Patient cannot resolve incidents")
    if inc.status in ("RESOLVED", "CANCELLED"):
        if may_read_incident(db, inc, user, member): return incident_payload(inc)
        raise HTTPException(403, "Incident access denied")
    # Care professionals may resolve incidents they can see, not every incident on the care team.
    if not may_act_on_incident(db, inc, user, member) and not (user.role in (Role.NURSE, Role.DOCTOR) and may_read_incident(db, inc, user, member)): raise HTTPException(403, "Only an incident recipient or care professional can resolve")
    if inc.current_level == 5 and (inc.status == "OPEN" or not body.note): raise HTTPException(422, "Emergency resolution requires acknowledgement and a note")
    inc.status = "RESOLVED"; inc.resolved_at = now(); inc.resolution_code = body.code; inc.resolution_note = body.note; inc.version += 1
    inc.current_deadline_at = None; inc.deadline_kind = None
    db.add(IncidentEvent(incident_id=inc.id, kind="RESOLVED", level=inc.current_level, actor_user_id=user.id, note="Incident resolved"))
    patient_members=db.scalars(select(CareTeamMember).where(CareTeamMember.patient_id==patient.id,CareTeamMember.team_role==TeamRole.PATIENT_SELF)).all()
    for patient_member in patient_members:
        db.add(Notification(user_id=patient_member.user_id,patient_id=patient.id,incident_id=inc.id,kind="STATUS",severity=inc.severity,title="Your request was handled",body="Your care team marked your request as handled.",requires_ack=False,channel="INBOX"))
    audit(db, user, patient.id, "INCIDENT_RESOLVED", "incident", inc.id, "Care request resolved", request.state.request_id)
    db.flush(); reconcile_patient(db, patient.id)
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
    return user_dict(user, db)


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
    return user_dict(user, db)


@app.post("/api/v1/auth/logout", status_code=204)
def logout(response: Response, user: User = Depends(current_user), db: Session = Depends(get_db)):
    user.token_version += 1
    db.commit()
    response.delete_cookie(COOKIE, path="/")
    response.status_code = 204
    return response


@app.get("/api/v1/auth/me")
def me(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return user_dict(user, db)


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
from app.api.command_center import router as command_center_router
app.include_router(command_center_router)
from app.api.workload import router as workload_router
app.include_router(workload_router)
from app.api.backup_matcher import router as backup_matcher_router
app.include_router(backup_matcher_router)
from app.api.coverage_planner import router as coverage_planner_router
app.include_router(coverage_planner_router)


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
def history(patient_id: uuid.UUID, limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0), user: User = Depends(current_user), db: Session = Depends(get_db)):
    p, member = patient_access(db, user, patient_id)
    if user.role not in (Role.ADMIN, Role.DOCTOR) and not (member and member.team_role in (TeamRole.COORDINATOR, TeamRole.FAMILY)): raise HTTPException(403, "Permission denied")
    limit = max(1, min(limit, 100)); rows = db.scalars(select(ActivityHistory).where(ActivityHistory.patient_id == p.id).order_by(ActivityHistory.occurred_at.desc()).offset(offset).limit(limit)).all()
    return {"items": [{"id": e.id, "occurred_at": e.occurred_at.replace(tzinfo=UTC) if e.occurred_at.tzinfo is None else e.occurred_at, "event_type": e.event_type, "summary": e.summary, "outcome": e.outcome} for e in rows], "total": db.query(ActivityHistory).filter_by(patient_id=p.id).count(), "limit": limit, "offset": offset}


@app.post("/api/v1/admin/demo/reset")
def demo_reset(user: User = Depends(current_user), db: Session = Depends(get_db)):
    if user.role != Role.ADMIN: raise HTTPException(403, "Admin access required")
    if not settings.demo_mode: raise HTTPException(404, "Not found")
    db.query(ActivityHistory).delete()
    db.query(BriefAcknowledgement).delete(); db.query(HandoverItem).delete(); db.query(DailyBrief).delete(); db.query(ActionItem).delete()
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


def ensure_system_escalation_policy():
    db = SessionLocal()
    try:
        if db.scalar(select(EscalationPolicy).where(EscalationPolicy.patient_id.is_(None))) is None:
            db.add(EscalationPolicy(patient_id=None, config=DEFAULT_POLICY, version=1))
            db.commit()
    finally:
        db.close()


_last_command_center_tick = 0.0


def _run_escalation_tick():
    global _last_command_center_tick
    db = SessionLocal()
    try:
        changed = run_escalation_tick(db, now(), scale=current_escalation_scale(db))
        if time.monotonic() - _last_command_center_tick >= 60:
            run_command_center_tick(db, now())
            run_cover_tick(db, now())
            db.commit()  # commit cover/command-center work before the planner so it can never be rolled back by it
            run_planner_tick(db, now())
            db.commit()
            _last_command_center_tick = time.monotonic()
        return changed
    finally:
        db.close()


async def _escalation_worker():
    while True:
        await asyncio.sleep(15)
        try:
            await asyncio.to_thread(_run_escalation_tick)
        except Exception:
            log.exception("escalation tick failed")


@app.on_event("startup")
async def start_escalation_worker():
    ensure_system_escalation_policy()
    app.state.escalation_task = asyncio.create_task(_escalation_worker())


@app.on_event("shutdown")
async def stop_escalation_worker():
    task = getattr(app.state, "escalation_task", None)
    if task:
        task.cancel()
        try: await task
        except asyncio.CancelledError: pass

DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"
if DIST.is_dir():
    assets = DIST / "assets"
    if assets.is_dir(): app.mount("/assets", StaticFiles(directory=assets), name="assets")


@app.get("/{path:path}", include_in_schema=False)
def spa(path: str, request: Request):
    if path == "api" or path.startswith("api/"): return JSONResponse({"error": {"code": "not_found", "message": "Not found", "details": {}, "request_id": request.state.request_id}}, status_code=404)
    index = DIST / "index.html"
    if index.is_file(): return FileResponse(index, headers={"Cache-Control": "no-cache"})
    return {"message": "CareCircle API is running", "phase": 4}
