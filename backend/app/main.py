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
from app.models import ActivityHistory, CareTeamMember, Patient, Role, TeamRole, User, Caregiver, CaregiverPatientLink, CaregiverWeeklySchedule, AvailabilityOverride, CareActivity, ActivityDependency, CareAssignment, PatientSupportNeed, PatientMessage, Incident, IncidentEvent, Notification, EscalationPolicy, AppSetting, ActionItem
from app.schemas import LoginIn, PasswordIn, PatientIn, PatientLookupIn, PatientPatch, RegisterIn, TeamIn
from app.services.care_team import ensure_care_profile, new_care_code, normalise_code, unlink_care_profile
from app.engine.escalation_classifier import classify_message
from app.engine.escalation_machine import DEFAULT_POLICY, deadline_minutes
from app.services.escalation import policy_for, run_escalation_tick, set_deadline
from app.services.command_center import reconcile_patient, run_command_center_tick
from app.services.backup_matcher import run_cover_tick
from app.services.coverage_planner import run_planner_tick
from app.services.care_feeds import roll_forward
from app.services.care_status import mark_missed
from app.services.auto_cover import run_auto_coordination
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


ROLE_LABELS = {"PATIENT": "Patient", "PRIMARY_CONTACT": "Primary contact", "CARETAKER": "Caretaker", "PROFESSIONAL": "Healthcare professional", "PATIENT_SELF": "Patient"}


def user_dict(u, db=None):
    return {"id": u.id, "email": u.email, "name": u.name, "role": u.role.value, "role_label": role_label(u.role.value), "is_synthetic": u.is_synthetic}


def role_label(role, team_role=None):
    return ROLE_LABELS.get(team_role or role, role)


def patient_dict(p, show_clinical, show_code=False):
    created_at = p.created_at.replace(tzinfo=UTC) if p.created_at.tzinfo is None else p.created_at
    return {"id": p.id, "name": p.name, "care_code": p.care_code if show_code else None, "birth_year": p.birth_year, "care_notes": p.care_notes, "clinical_notes": p.clinical_notes if show_clinical else None, "is_synthetic": p.is_synthetic, "created_at": created_at}


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


def can_see_clinical(user, member):
    if user.role == Role.PROFESSIONAL: return member is not None
    return (user.role == Role.PATIENT and member is not None and member.team_role == TeamRole.PATIENT_SELF) or (user.role == Role.PRIMARY_CONTACT and member is not None and member.team_role == TeamRole.PRIMARY_CONTACT)


@app.get("/api/health")
def health(db: Session = Depends(get_db)):
    db.execute(text("SELECT 1"))
    return {"status": "ok", "database": "ok"}


@app.get("/api/v1/meta")
def meta(db: Session = Depends(get_db)):
    scale = current_escalation_scale(db)
    return {"app_name": "CareCircle", "version": "0.5.0", "git_sha": settings.git_sha, "phase": 5, "demo_mode": settings.demo_mode, "escalation_time_scale": scale, "escalation_scaled": settings.demo_mode and scale != 1.0, "server_time": now().isoformat(), "timezone": settings.app_timezone, "ai_enabled": False}


def incident_recipients(db, patient_id, level):
    if level == 0: return []
    members = db.execute(select(CareTeamMember, User).join(User).where(CareTeamMember.patient_id == patient_id)).all()
    roles = ({TeamRole.CARETAKER} if level == 1 else {TeamRole.PRIMARY_CONTACT} if level == 2 else {TeamRole.PROFESSIONAL} if level in (3, 4) else {TeamRole.PRIMARY_CONTACT, TeamRole.CARETAKER, TeamRole.PROFESSIONAL})
    recipients = [u for m, u in members if m.team_role in roles and u.is_active]
    # No healthcare professional on the team yet: route to the primary contact instead of notifying nobody.
    if level in (3, 4) and not recipients:
        recipients = [u for m, u in members if m.team_role == TeamRole.PRIMARY_CONTACT and u.is_active]
    return recipients


# Plain words for the care team; the message text itself stays private to the routing record.
REQUEST_TOPICS = {"DAILY_HELP": "daily help", "MEDICATION": "medicines", "LOGISTICS": "a care arrangement", "HEALTH_CONCERN": "a health concern",
                  "EMERGENCY": "an emergency", "INFO": "an update"}
REQUEST_TITLES = {"DAILY_HELP": "Daily help request", "MEDICATION": "Medicine help request", "LOGISTICS": "Care arrangement problem", "HEALTH_CONCERN": "Health concern", "INFO": "Update from the patient"}


def _utc_out(value):
    return value.replace(tzinfo=UTC) if value is not None and value.tzinfo is None else value


def incident_payload(item):
    return {"id": item.id, "patient_id": item.patient_id, "current_level": item.current_level, "category": item.category, "severity": item.severity, "status": item.status, "title": item.title, "safe_summary": item.safe_summary, "owner_user_id": item.owner_user_id, "created_at": _utc_out(item.created_at), "current_deadline_at": _utc_out(item.current_deadline_at), "deadline_kind": item.deadline_kind, "emergency_unacknowledged": item.emergency_unacknowledged, "acknowledged_at": item.acknowledged_at, "resolved_at": item.resolved_at}


def current_escalation_scale(db=None):
    if not settings.demo_mode: return 1.0
    if db is not None:
        setting = db.get(AppSetting, "escalation_time_scale")
        if setting: return max(0.01, min(float(setting.value.get("scale", settings.escalation_time_scale)), 10.0))
    return max(0.01, min(float(settings.escalation_time_scale), 10.0))


def may_act_on_incident(db, incident, user, member):
    if (member and member.team_role == TeamRole.PRIMARY_CONTACT): return True
    event = db.scalar(select(IncidentEvent).where(IncidentEvent.incident_id == incident.id, IncidentEvent.level == incident.current_level, IncidentEvent.kind.in_(("CREATED", "MANUAL_ESCALATED", "AUTO_ESCALATED"))).order_by(IncidentEvent.at.desc()))
    return bool(event and str(user.id) in (event.recipient_user_ids or []))


def may_read_incident(db, incident, user, member):
    if user.role == Role.PATIENT and member and member.team_role == TeamRole.PATIENT_SELF: return True
    if member and member.team_role == TeamRole.PRIMARY_CONTACT: return True
    if user.role == Role.PROFESSIONAL: return incident.current_level >= 3  # health concerns and emergencies
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
    topic = REQUEST_TOPICS.get(classification.category, "something that needs a person to read the message")
    safe_summary = f"{patient.name} asked for help with {topic} at {now().astimezone(ZoneInfo(settings.app_timezone)).strftime('%H:%M')}"
    source = "SOS" if body.channel == "SOS_BUTTON" else "CARETAKER_REPORT" if body.on_behalf else "PATIENT_MESSAGE"
    inc = Incident(patient_id=patient.id, source=source, category=classification.category, initial_level=level, current_level=level, severity=classification.severity, title="Emergency report" if level == 5 else REQUEST_TITLES.get(classification.category, "Message to read"), safe_summary=safe_summary, dedupe_key=f"message:{uuid.uuid4()}", classification=classification.as_dict())
    db.add(inc); db.flush()
    if level > 0:
        created_at = now()
        set_deadline(inc, policy_for(db, patient.id), "ACK", created_at, current_escalation_scale(db))
        if not recipients: inc.current_deadline_at = created_at
    msg = PatientMessage(patient_id=patient.id, sender_user_id=user.id, on_behalf=body.on_behalf, reported_role=user.role.value, channel=body.channel, body=safe_body, language_hint=body.language_hint, idempotency_key=key, incident_id=inc.id)
    db.add(msg)
    missing_doctor = level == 4 and db.scalar(select(CareTeamMember.id).where(CareTeamMember.patient_id == patient.id, CareTeamMember.team_role == TeamRole.PROFESSIONAL)) is None
    notice_title = "No doctor on this care team" if missing_doctor else inc.title
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
    else:
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
    if not member: raise HTTPException(403, "Permission denied")
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
    privileged = bool(member and member.team_role == TeamRole.PRIMARY_CONTACT) or (user.role == Role.PROFESSIONAL and may_read_incident(db, inc, user, member))
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
        # Someone has it now: the alerts about this request are answered for everyone; the others get one "being handled" note.
        for notice in db.scalars(select(Notification).where(Notification.incident_id == inc.id, Notification.read_at.is_(None))): notice.read_at = now()
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
    if not may_act_on_incident(db, inc, user, member) and not (user.role in (Role.PROFESSIONAL, Role.PROFESSIONAL) and may_read_incident(db, inc, user, member)): raise HTTPException(403, "Only an incident recipient or care professional can resolve")
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
    """Primary contacts, caretakers and healthcare professionals sign up; patients are registered by their primary contact."""
    email = str(body.email).lower()
    if not password_is_strong(body.password, body.name, email):
        raise HTTPException(422, "Password does not meet basic strength requirements")
    if db.scalar(select(User).where(User.email == email)):
        raise HTTPException(409, "An account with this email already exists")
    user = User(email=email, name=body.name.strip(), password_hash=hash_password(body.password), role=Role(body.role))
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


# GET/PATCH /patients/{id} are served by the domain router (extended representation).
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
from app.api.care_feeds import router as care_feeds_router
app.include_router(care_feeds_router)


lookup_attempts: dict[str, deque[float]] = defaultdict(deque)


def _primary_contact(db, user, patient_id):
    patient, member = patient_access(db, user, patient_id)
    if user.role != Role.PRIMARY_CONTACT or member.team_role != TeamRole.PRIMARY_CONTACT: raise HTTPException(403, "Primary contact permission required")
    return patient, member


def _show_code(user, member) -> bool:
    return member is not None and member.team_role in (TeamRole.PRIMARY_CONTACT, TeamRole.PROFESSIONAL)


@app.get("/api/v1/patients")
def list_patients(limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0), user: User = Depends(current_user), db: Session = Depends(get_db)):
    stmt = select(Patient, CareTeamMember).join(CareTeamMember).where(CareTeamMember.user_id == user.id)
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.execute(stmt.order_by(Patient.name, Patient.created_at.desc()).offset(offset).limit(limit)).all()
    return {"items": [patient_dict(p, can_see_clinical(user, m), _show_code(user, m)) for p, m in rows], "total": total, "limit": limit, "offset": offset}


@app.post("/api/v1/patients", status_code=201)
def create_patient(body: PatientIn, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """A primary contact registers the patient. The patient gets a CareCircle ID to share with the hospital."""
    if user.role != Role.PRIMARY_CONTACT: raise HTTPException(403, "Only a primary contact can register a patient")
    values = body.model_dump(exclude={"patient_account"})
    p = Patient(**values, care_code=new_care_code(db), created_by=user.id, is_synthetic=settings.demo_mode)
    db.add(p); db.flush()
    db.add(CareTeamMember(patient_id=p.id, user_id=user.id, team_role=TeamRole.PRIMARY_CONTACT, is_primary_coordinator=True))
    if body.patient_account:
        email = str(body.patient_account.email).lower()
        if db.scalar(select(User).where(User.email == email)): raise HTTPException(409, "An account with this email already exists")
        if not password_is_strong(body.patient_account.password, body.name, email): raise HTTPException(422, "Patient password does not meet basic strength requirements")
        login = User(email=email, name=body.name.strip(), role=Role.PATIENT, password_hash=hash_password(body.patient_account.password), is_synthetic=settings.demo_mode)
        db.add(login); db.flush()
        db.add(CareTeamMember(patient_id=p.id, user_id=login.id, team_role=TeamRole.PATIENT_SELF))
    audit(db, user, p.id, "patient.created", "patient", p.id, "Patient registered", request.state.request_id)
    db.commit(); db.refresh(p)
    return patient_dict(p, True, True)


def _lookup(db, user, request, care_code: str, birth_year: int):
    if user.role != Role.PROFESSIONAL: raise HTTPException(403, "Only healthcare professionals can look up patients")
    attempts = lookup_attempts[str(user.id)]
    cutoff = time.monotonic() - 60
    while attempts and attempts[0] < cutoff: attempts.popleft()
    if len(attempts) >= 10: raise HTTPException(429, "Too many lookups; wait a minute", headers={"Retry-After": "60"})
    attempts.append(time.monotonic())
    patient = db.scalar(select(Patient).where(Patient.care_code == normalise_code(care_code)))
    # One message for a wrong ID or a wrong birth year, so IDs cannot be probed.
    if not patient or patient.birth_year != birth_year: raise HTTPException(404, "No patient matches that CareCircle ID and birth year")
    return patient


@app.post("/api/v1/patients/lookup")
def lookup_patient(body: PatientLookupIn, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    patient = _lookup(db, user, request, body.care_code, body.birth_year)
    member = db.scalar(select(CareTeamMember).where(CareTeamMember.patient_id == patient.id, CareTeamMember.user_id == user.id))
    return {"id": patient.id, "name": patient.name, "birth_year": patient.birth_year, "care_code": patient.care_code, "already_on_team": member is not None}


@app.post("/api/v1/patients/join", status_code=201)
def join_patient(body: PatientLookupIn, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """A healthcare professional joins the care team with the ID the family shared (the family's consent)."""
    patient = _lookup(db, user, request, body.care_code, body.birth_year)
    member = db.scalar(select(CareTeamMember).where(CareTeamMember.patient_id == patient.id, CareTeamMember.user_id == user.id))
    if not member:
        member = CareTeamMember(patient_id=patient.id, user_id=user.id, team_role=TeamRole.PROFESSIONAL); db.add(member)
        audit(db, user, patient.id, "care_team.professional_joined", "care_team_member", user.id, f"{user.name} (healthcare professional) joined the care team", request.state.request_id)
        for contact in db.scalars(select(CareTeamMember.user_id).where(CareTeamMember.patient_id == patient.id, CareTeamMember.team_role == TeamRole.PRIMARY_CONTACT)):
            db.add(Notification(user_id=contact, patient_id=patient.id, kind="STATUS", severity="LOW", title="A healthcare professional joined",
                                body=f"{user.name} joined {patient.name}'s care team using the CareCircle ID. If this is unexpected, remove them in Care team (this also issues a new ID).", requires_ack=False, channel="INBOX"))
        db.commit()
    return patient_dict(patient, True, True)


@app.get("/api/v1/patients/{patient_id}/care-team")
def care_team(patient_id: uuid.UUID, user: User = Depends(current_user), db: Session = Depends(get_db)):
    patient_access(db, user, patient_id)
    rows = db.execute(select(CareTeamMember, User).join(User).where(CareTeamMember.patient_id == patient_id)).all()
    contact_visible = user.role in (Role.PRIMARY_CONTACT, Role.PROFESSIONAL)
    return {"items": [{"id": m.id, "user_id": u.id, "name": u.name, "email": u.email if contact_visible else None, "role": u.role.value, "role_label": role_label(u.role.value, m.team_role.value), "team_role": m.team_role.value, "is_primary_coordinator": m.is_primary_coordinator} for m, u in rows]}


@app.post("/api/v1/patients/{patient_id}/care-team", status_code=201)
def add_team(patient_id: uuid.UUID, body: TeamIn, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """A primary contact invites a caretaker (or another relative as primary contact) by their CareCircle account email."""
    p, _ = _primary_contact(db, user, patient_id)
    team_role = TeamRole(body.team_role)
    target = db.scalar(select(User).where(User.email == str(body.email).lower()))
    if not target: raise HTTPException(404, "No CareCircle account uses that email; ask them to sign up first")
    if target.role.value != team_role.value: raise HTTPException(422, f"That account is registered as {role_label(target.role.value)}, not {role_label(team_role.value)}")
    if db.scalar(select(CareTeamMember).where(CareTeamMember.patient_id == p.id, CareTeamMember.user_id == target.id)): raise HTTPException(409, "User is already on this care team")
    m = CareTeamMember(patient_id=p.id, user_id=target.id, team_role=team_role); db.add(m)
    if team_role == TeamRole.CARETAKER:
        ensure_care_profile(db, target, p.id, created_by=user.id)
    audit(db, user, p.id, "care_team.member_added", "care_team_member", target.id, f"{role_label(team_role.value)} {target.name} added", request.state.request_id)
    db.commit(); db.refresh(m)
    return {"id": m.id, "user_id": target.id, "team_role": team_role.value, "role_label": role_label(target.role.value, team_role.value)}


@app.post("/api/v1/patients/{patient_id}/care-code/regenerate")
def regenerate_care_code(patient_id: uuid.UUID, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Issue a new CareCircle ID (e.g. it was shared by mistake). Professionals already on the team stay on it."""
    p, _ = _primary_contact(db, user, patient_id)
    p.care_code = new_care_code(db)
    audit(db, user, p.id, "patient.care_code_changed", "patient", p.id, "CareCircle ID changed", request.state.request_id)
    db.commit()
    return {"care_code": p.care_code}


@app.post("/api/v1/patients/{patient_id}/care-team/me/care-profile", status_code=201)
def opt_in_care_profile(patient_id: uuid.UUID, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """A primary contact who also carries out care activities (e.g. takes the patient to appointments)."""
    p, _ = _primary_contact(db, user, patient_id)
    profile = ensure_care_profile(db, user, p.id, created_by=user.id)
    audit(db, user, p.id, "care_team.care_profile", "caregiver", profile.id, f"{user.name} can now be assigned care activities", request.state.request_id)
    db.commit()
    return {"caregiver_id": profile.id}


@app.delete("/api/v1/patients/{patient_id}/care-team/{member_id}", status_code=204)
def remove_team(patient_id: uuid.UUID, member_id: uuid.UUID, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    p, _ = _primary_contact(db, user, patient_id)
    member = db.scalar(select(CareTeamMember).where(CareTeamMember.id == member_id, CareTeamMember.patient_id == p.id))
    if not member: raise HTTPException(404, "Care team member not found")
    if member.team_role == TeamRole.PRIMARY_CONTACT and db.scalar(select(CareTeamMember).where(CareTeamMember.patient_id == p.id, CareTeamMember.team_role == TeamRole.PRIMARY_CONTACT, CareTeamMember.id != member.id)) is None: raise HTTPException(409, "Cannot remove the last primary contact")
    if member.user_id != user.id and (member.is_primary_coordinator or member.team_role == TeamRole.PATIENT_SELF):
        raise HTTPException(409, "The person who registered the patient, and the patient's own login, can only leave by themselves")
    released = unlink_care_profile(db, member.user_id, p.id, actor=user)
    summary = "Care team member removed" + (f"; {released} upcoming tasks released for cover" if released else "")
    if member.team_role == TeamRole.PROFESSIONAL:
        # A new CareCircle ID stops the removed professional from simply joining again with the old one.
        p.care_code = new_care_code(db); summary += "; CareCircle ID changed"
    db.delete(member); audit(db, user, p.id, "care_team.member_removed", "care_team_member", member_id, summary, request.state.request_id)
    db.flush(); reconcile_patient(db, p.id); db.commit(); return Response(status_code=204)


@app.get("/api/v1/patients/{patient_id}/history")
def history(patient_id: uuid.UUID, limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0), user: User = Depends(current_user), db: Session = Depends(get_db)):
    p, member = patient_access(db, user, patient_id)
    if member.team_role not in (TeamRole.PRIMARY_CONTACT, TeamRole.PROFESSIONAL): raise HTTPException(403, "Permission denied")
    rows = db.scalars(select(ActivityHistory).where(ActivityHistory.patient_id == p.id).order_by(ActivityHistory.occurred_at.desc()).offset(offset).limit(limit)).all()
    return {"items": [{"id": e.id, "occurred_at": e.occurred_at.replace(tzinfo=UTC) if e.occurred_at.tzinfo is None else e.occurred_at, "event_type": e.event_type, "summary": e.summary, "outcome": e.outcome} for e in rows], "total": db.query(ActivityHistory).filter_by(patient_id=p.id).count(), "limit": limit, "offset": offset}


DEMO_ACCOUNTS = [
    ("anita.iyer@secondpatient.demo", "Anita Iyer", Role.PRIMARY_CONTACT),
    ("karthik.iyer@secondpatient.demo", "Karthik Iyer", Role.PRIMARY_CONTACT),
    ("meera.pai@secondpatient.demo", "Meera Pai", Role.PRIMARY_CONTACT),
    ("ramesh.iyer@secondpatient.demo", "Ramesh Iyer", Role.PATIENT),
    ("savitha@secondpatient.demo", "Savitha", Role.CARETAKER),
    ("lakshmi@secondpatient.demo", "Lakshmi Rao", Role.CARETAKER),
    ("suresh.kamath@secondpatient.demo", "Suresh Kamath", Role.CARETAKER),
    ("divya.menon@secondpatient.demo", "Divya Menon", Role.PROFESSIONAL),
    ("dr.arjun.nair@secondpatient.demo", "Dr. Arjun Nair", Role.PROFESSIONAL),
]


def seed(db=None):
    own = db is None
    if own:
        db = next(get_db())
    users = {}
    for email, name, role in DEMO_ACCOUNTS:
        user = db.scalar(select(User).where(User.email == email))
        if not user:
            user = User(email=email, name=name, role=role, is_synthetic=True, password_hash=hash_password(settings.demo_password)); db.add(user); db.flush()
        users[email] = user
    # Create the demo patients unless they already exist (other, real patients may share the database).
    if not db.scalar(select(Patient.id).where(Patient.care_code.in_(("CC-RAM354", "CC-SHA746")))) and not db.scalar(select(Patient.id).where(Patient.name == "Ramesh Iyer", Patient.is_synthetic.is_(True), Patient.created_by == users["anita.iyer@secondpatient.demo"].id)):
        p1 = Patient(name="Ramesh Iyer", birth_year=1954, care_code="CC-RAM354", care_notes="Mobility-limited; post-procedure follow-up support.", clinical_notes="Fictional demo note: follow-up plan discussed.", created_by=users["anita.iyer@secondpatient.demo"].id, is_synthetic=True)
        p2 = Patient(name="Sharada Pai", birth_year=1946, care_code="CC-SHA746", care_notes="Lives alone; Savitha helps daily.", clinical_notes="Fictional demo note.", created_by=users["meera.pai@secondpatient.demo"].id, is_synthetic=True)
        db.add_all([p1, p2]); db.flush()
        entries = [(p1, "anita.iyer@secondpatient.demo", TeamRole.PRIMARY_CONTACT, True), (p1, "karthik.iyer@secondpatient.demo", TeamRole.PRIMARY_CONTACT, False),
                   (p1, "ramesh.iyer@secondpatient.demo", TeamRole.PATIENT_SELF, False), (p1, "savitha@secondpatient.demo", TeamRole.CARETAKER, False),
                   (p1, "lakshmi@secondpatient.demo", TeamRole.CARETAKER, False), (p1, "suresh.kamath@secondpatient.demo", TeamRole.CARETAKER, False),
                   (p1, "divya.menon@secondpatient.demo", TeamRole.PROFESSIONAL, False), (p1, "dr.arjun.nair@secondpatient.demo", TeamRole.PROFESSIONAL, False),
                   (p2, "meera.pai@secondpatient.demo", TeamRole.PRIMARY_CONTACT, True), (p2, "savitha@secondpatient.demo", TeamRole.CARETAKER, False)]
        db.add_all([CareTeamMember(patient_id=p.id, user_id=users[email].id, team_role=role, is_primary_coordinator=primary) for p, email, role, primary in entries])
        db.flush()
    db.commit()
    from app.seed.phase2 import seed_phase2
    seed_phase2(db)
    db.commit()
    if own: db.close()


@app.post("/api/v1/demo/reset")
def reset_demo(request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Demo mode only, for the fictional demo accounts: rebuild the demo care circle from scratch, relative to now."""
    if not settings.demo_mode or not user.is_synthetic or not user.email.endswith("@secondpatient.demo"): raise HTTPException(403, "Permission denied")
    from app.services import demo
    if not demo.reset(db): raise HTTPException(409, "The demo patients are not present")
    db.commit()
    for patient in demo.demo_patients(db).values(): reconcile_patient(db, patient.id)
    run_planner_tick(db, now())
    db.commit()
    log.info("demo reset by %s request=%s", user.id, request.state.request_id)
    return {"status": "reset"}


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
            mark_missed(db, now())
            roll_forward(db)
            run_cover_tick(db, now())
            run_auto_coordination(db, now())
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
    return {"message": "CareCircle API is running", "phase": 5}
