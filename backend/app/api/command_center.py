"""Patient-scoped command center, action-item, and brief endpoints."""
from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, PlainTextResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.clock import now
from app.core.db import get_db
from app.core.permissions import require_patient_access
from app.models import (ActionItem, ActivityHistory, BriefAcknowledgement, CareActivity,
                        CareAssignment, Caregiver, CareTeamMember, CommandCenterSetting,
                        DailyBrief, HandoverItem, Incident, Notification, Patient, Role, TeamRole)
from app.services.command_center import (DEFAULT_SETTINGS, create_brief, plan_and_attention,
                                         reconcile_patient, serialize_action, serialize_brief,
                                         settings_for)

router = APIRouter(prefix="/api/v1", tags=["caregiver command center"])


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ActionCreateIn(Input):
    title: str = Field(min_length=1, max_length=200)
    due_at: datetime | None = None
    related_activity_id: uuid.UUID | None = None
    assigned_to_user_id: uuid.UUID | None = None


class SnoozeIn(Input):
    until: datetime


class DismissIn(Input):
    reason: str = Field(min_length=1, max_length=300)


class ActIn(Input):
    option: Literal["ASSIGN_CAREGIVER", "REQUEST_CONFIRMATION", "CONFIRM_ASSIGNMENT", "PICK_BACKUP", "MARK_COMPLETE", "ACKNOWLEDGE_TASK", "I_WILL_HANDLE", "BATCH_ASSIGN", "OPEN_INCIDENT", "ACK_HANDOVER"]
    params: dict = Field(default_factory=dict)


class MorningIn(Input):
    for_date: date
    regenerate: bool = False


class HandoverDraftIn(Input):
    for_date: date
    notes: str = Field(default="", max_length=2000)


class HandoverUpdateIn(Input):
    notes: str = Field(default="", max_length=2000)
    to_user_id: uuid.UUID | None = None
    items: list[dict] = Field(default_factory=list, max_length=100)


class AckIn(Input):
    note: str | None = Field(default=None, max_length=500)


class SettingsIn(Input):
    morning_brief_time: str = Field(pattern=r"^(?:[01]\d|2[0-3]):[0-5]\d$")
    handover_time: str = Field(pattern=r"^(?:[01]\d|2[0-3]):[0-5]\d$")
    handover_autopublish_after_min: int = Field(ge=5, le=1440)
    daypart_boundaries: dict = Field(default_factory=dict)
    routine_rules: dict = Field(default_factory=dict)
    snooze_max_minutes_by_severity: dict = Field(default_factory=dict)
    suppress_hours: int = Field(ge=1, le=168)


def _current_user(request: Request, db: Session = Depends(get_db)):
    from app.main import current_user
    return current_user(request, db)


def _history(db, patient_id, user, event, entity_type, entity_id, summary):
    db.add(ActivityHistory(actor_user_id=user.id, patient_id=patient_id, event_type=event,
                           entity_type=entity_type, entity_id=str(entity_id), summary=summary, payload={}))


def _patient_scope(db: Session, user, patient_id, *, write=False):
    if user.role in {Role.PATIENT, Role.DOCTOR}:
        raise HTTPException(403, "Command Center is not available to this role")
    patient, member = require_patient_access(db, user, patient_id, "patient:read")
    if user.role == Role.ADMIN:
        return patient, member, "ADMIN"
    if user.role == Role.FAMILY:
        if member.team_role == TeamRole.COORDINATOR:
            return patient, member, "COORDINATOR"
        if member.team_role == TeamRole.FAMILY:
            if write: raise HTTPException(403, "Family contact view is read-only")
            return patient, member, "FAMILY"
    if user.role in {Role.HOUSEHELP, Role.NURSE}:
        expected = TeamRole.HOUSEHELP if user.role == Role.HOUSEHELP else TeamRole.NURSE
        if member.team_role == expected and db.scalar(select(Caregiver.id).where(Caregiver.user_id == user.id)):
            if write: raise HTTPException(403, "Use My Day task actions for your assigned work")
            return patient, member, "MY_DAY"
    raise HTTPException(403, "Command Center access denied")


def _brief_dict(db, row):
    data = serialize_brief(row)
    if data:
        acknowledgements = db.scalars(select(BriefAcknowledgement).where(BriefAcknowledgement.brief_id == row.id)).all()
        data["acknowledged_by"] = [str(x.user_id) for x in acknowledgements]
    return data


@router.get("/command-center")
def command_center(patient_id: uuid.UUID, day: date | None = Query(default=None, alias="date"), user=Depends(_current_user), db: Session = Depends(get_db)):
    patient, member, role_view = _patient_scope(db, user, patient_id)
    data = plan_and_attention(db, patient.id, day=day)
    snap, plan = data["snapshot"], data["plan"]
    actions = [serialize_action(x) for x in data["active_items"]]
    needs = [serialize_action(x) for x in data["needs_now"]]
    risk = [serialize_action(x) for x in data["at_risk"]]
    decisions = [serialize_action(x) for x in data["decisions_waiting"]]
    pending = [serialize_action(x) for x in data["pending_actions"]]
    handled = [serialize_action(x) for x in data["handled"]]
    if role_view == "FAMILY":
        actions = [x for x in actions if x["assigned_to_user_id"] in (None, str(user.id))]
        needs = [x for x in needs if x in actions]; risk = [x for x in risk if x in actions]
        decisions, pending = [], [x for x in pending if x["owner_user_id"] == str(user.id)]
        handled = [x for x in handled if x["owner_user_id"] == str(user.id)]
        plan = {**plan, "blocks": [], "timeline": [], "handled": [], "batching_suggestions": [], "load_today": {"hours": 0, "tasks": 0, "next_free_window": None}}
    elif role_view == "MY_DAY":
        my_caregivers = {str(x.id) for x in snap["caregivers"].values() if x.user_id == user.id}
        my_activity_ids = {str(x["activity_id"]) for x in snap["assignments"] if str(x["caregiver_id"]) in my_caregivers and x["status"] in {"PROPOSED", "AWAITING_CONFIRMATION", "CONFIRMED"}}
        def own_block(block): return block.get("activity_id") in my_activity_ids or bool(set(block.get("activity_ids", ())) & my_activity_ids)
        own_blocks = [x for x in plan["blocks"] if own_block(x)]
        own_activities = [activity for block in own_blocks for activity in block.get("activities", [])]
        own_activities.extend(block for block in own_blocks if block.get("activity_id"))
        own_hours = round(sum(max(0, (x["end"] - x["start"]).total_seconds()) for x in own_activities if x.get("start") and x.get("end")) / 3600, 2)
        plan = {**plan, "blocks": own_blocks, "timeline": [x for x in plan["timeline"] if own_block(x)], "handled": [x for x in plan["handled"] if x["activity_id"] in my_activity_ids], "batching_suggestions": [], "load_today": {"hours": own_hours, "tasks": len(own_activities), "next_free_window": None}}
        needs = [x for x in needs if set(x["related_activity_ids"]) & my_activity_ids or x["assigned_to_user_id"] == str(user.id)]
        risk = [x for x in risk if set(x["related_activity_ids"]) & my_activity_ids or x["assigned_to_user_id"] == str(user.id)]
        decisions, pending, handled = [], [x for x in pending if x["assigned_to_user_id"] == str(user.id)], [x for x in handled if x["assigned_to_user_id"] == str(user.id)]
    morning = _brief_dict(db, data["morning_brief"])
    handover = _brief_dict(db, data["handover_brief"])
    if role_view == "MY_DAY":
        morning = None
        if handover and handover["to_user_id"] != str(user.id): handover = None
    on_track = sum(len(x.get("activities", [])) for x in plan["blocks"] if x["kind"] == "ROUTINE_BLOCK")
    automated = on_track + sum(x["status"] == "AUTO_RESOLVED" for x in handled)
    payload = {
        "as_of": now().isoformat(), "basis_note": "Based on confirmed assignments, availability and logged updates. This does not check on the patient's wellbeing.",
        "role_view": role_view, "patient": {"id": str(patient.id), "name": patient.name, "is_synthetic": patient.is_synthetic},
        "summary": {"on_track": on_track, "needs_now": len(needs), "at_risk": len(risk), "decisions_waiting": len(decisions), "pending_actions": len(pending), "handled_today": len(handled), "automated_count": automated},
        "needs_now": needs, "at_risk": risk, "decisions_waiting": decisions,
        "todays_plan": {"blocks": plan["blocks"], "timeline": plan["timeline"]}, "handled": handled,
        "pending_actions": pending, "briefs": {"morning": morning, "handover": handover},
        "load_today": plan["load_today"], "batching_suggestions": plan["batching_suggestions"],
        "setup_hints": ["Add activities and confirm a primary caregiver to build today's plan."] if not snap["activities"] else [],
        "handled_actions": actions,
    }
    db.commit()
    return payload


@router.get("/command-center/overview")
def command_center_overview(user=Depends(_current_user), db: Session = Depends(get_db)):
    if user.role == Role.ADMIN:
        patients = db.scalars(select(Patient).order_by(Patient.name)).all()
    elif user.role == Role.FAMILY:
        ids = db.scalars(select(CareTeamMember.patient_id).where(CareTeamMember.user_id == user.id, CareTeamMember.team_role == TeamRole.COORDINATOR)).all()
        patients = db.scalars(select(Patient).where(Patient.id.in_(ids)).order_by(Patient.name)).all()
    else:
        raise HTTPException(403, "Coordinator overview access required")
    rows = []
    for patient in patients:
        data = plan_and_attention(db, patient.id)
        active = data["active_items"]
        most_severe = max(active, key=lambda x: {"LOW": 0, "MEDIUM": 1, "HIGH": 2, "CRITICAL": 3}[x.severity], default=None)
        rows.append({"patient_id": str(patient.id), "patient_name": patient.name, "needs_now": len(data["needs_now"]), "at_risk": len(data["at_risk"]), "decisions_waiting": len(data["decisions_waiting"]), "most_severe_title": most_severe.title if most_severe else None})
    db.commit()
    return {"as_of": now().isoformat(), "items": rows}


@router.get("/action-items")
def list_action_items(patient_id: uuid.UUID, status: str | None = None, user=Depends(_current_user), db: Session = Depends(get_db)):
    _, _, role_view = _patient_scope(db, user, patient_id)
    query = select(ActionItem).where(ActionItem.patient_id == patient_id)
    if status: query = query.where(ActionItem.status == status)
    if role_view == "FAMILY": query = query.where((ActionItem.assigned_to_user_id == user.id) | (ActionItem.owner_user_id == user.id))
    elif role_view == "MY_DAY": query = query.where(ActionItem.assigned_to_user_id == user.id)
    rows = db.scalars(query.order_by(ActionItem.first_seen_at.desc()).limit(200)).all()
    return {"items": [serialize_action(x) for x in rows], "total": len(rows)}


@router.post("/action-items", status_code=201)
def create_action_item(patient_id: uuid.UUID, body: ActionCreateIn, request: Request, user=Depends(_current_user), db: Session = Depends(get_db)):
    _, _, role_view = _patient_scope(db, user, patient_id)
    if role_view not in {"ADMIN", "COORDINATOR", "MY_DAY"} or (role_view == "MY_DAY" and body.assigned_to_user_id not in (None, user.id)):
        raise HTTPException(403, "Only coordinators and assigned caregivers can add reminders")
    if body.related_activity_id and not db.scalar(select(CareActivity.id).where(CareActivity.id == body.related_activity_id, CareActivity.patient_id == patient_id)): raise HTTPException(404, "Activity not found")
    due = body.due_at
    if due and due.tzinfo is None: raise HTTPException(422, "due_at must include a timezone")
    item = ActionItem(id=uuid.uuid4(), patient_id=patient_id, dedupe_key=f"MANUAL:{uuid.uuid4()}", kind="MANUAL_REMINDER", source="MANUAL", title=body.title.strip(), reason="Created by a care-team member.", reasons=[], severity="MEDIUM", related_activity_ids=[str(body.related_activity_id)] if body.related_activity_id else [], owner_user_id=user.id, assigned_to_user_id=body.assigned_to_user_id or user.id, due_at=due, suggested_actions=[], first_seen_at=now(), last_seen_at=now())
    db.add(item); _history(db, patient_id, user, "ACTION_ITEM_CREATED", "action_item", item.id, "A manual reminder was added"); db.commit(); db.refresh(item)
    return serialize_action(item)


def _action_row(db, item_id, user, write=True):
    row = db.get(ActionItem, item_id)
    if not row: raise HTTPException(404, "Action item not found")
    _, _, role_view = _patient_scope(db, user, row.patient_id)
    if role_view == "FAMILY" and row.assigned_to_user_id != user.id and row.owner_user_id != user.id: raise HTTPException(403, "Action item is not assigned to you")
    if role_view == "MY_DAY" and row.assigned_to_user_id != user.id: raise HTTPException(403, "Action item is not assigned to you")
    return row, role_view


@router.post("/action-items/{item_id}/snooze")
def snooze_action_item(item_id: uuid.UUID, body: SnoozeIn, request: Request, user=Depends(_current_user), db: Session = Depends(get_db)):
    row, view = _action_row(db, item_id, user)
    if view == "FAMILY": raise HTTPException(403, "Family contact view is read-only")
    until = body.until
    if until.tzinfo is None: raise HTTPException(422, "until must include a timezone")
    settings = settings_for(db, row.patient_id)
    max_minutes = settings["snooze_max_minutes_by_severity"].get(row.severity, 60)
    minutes = (until - now()).total_seconds() / 60
    if minutes <= 0 or minutes > max_minutes: raise HTTPException(422, f"Snooze duration must be between 1 and {max_minutes} minutes")
    row.status, row.snoozed_until, row.version = "SNOOZED", until, row.version + 1
    _history(db, row.patient_id, user, "ACTION_ITEM_SNOOZED", "action_item", row.id, "A coordination item was snoozed")
    db.commit(); db.refresh(row)
    return serialize_action(row)


@router.post("/action-items/{item_id}/done")
def done_action_item(item_id: uuid.UUID, request: Request, body: AckIn | None = None, user=Depends(_current_user), db: Session = Depends(get_db)):
    row, role_view = _action_row(db, item_id, user)
    if role_view == "FAMILY": raise HTTPException(403, "Family contact view is read-only")
    if row.source != "MANUAL" and role_view not in {"ADMIN", "COORDINATOR"}: raise HTTPException(403, "Only the coordinator can close a derived item")
    if row.source == "MANUAL" and row.owner_user_id != user.id and row.assigned_to_user_id != user.id and role_view not in {"ADMIN", "COORDINATOR"}: raise HTTPException(403, "Reminder is not assigned to you")
    row.status, row.resolution_reason, row.resolution_note, row.resolved_at, row.resolved_by = "DONE", "USER_DONE", (body.note.strip()[:500] if body and body.note else None), now(), user.id
    row.version += 1
    _history(db, row.patient_id, user, "ACTION_ITEM_RESOLVED", "action_item", row.id, "A manual reminder was completed")
    db.commit(); db.refresh(row)
    return serialize_action(row)


@router.post("/action-items/{item_id}/dismiss")
def dismiss_action_item(item_id: uuid.UUID, body: DismissIn, request: Request, user=Depends(_current_user), db: Session = Depends(get_db)):
    row, role_view = _action_row(db, item_id, user)
    if role_view not in {"ADMIN", "COORDINATOR"}: raise HTTPException(403, "Coordinator permission required")
    if row.severity in {"HIGH", "CRITICAL"}: raise HTTPException(422, "High and critical items cannot be dismissed; snooze or take action")
    row.status, row.resolution_reason, row.resolution_note = "DISMISSED", "USER_DISMISSED", body.reason.strip()
    row.suppressed_until, row.resolved_at, row.resolved_by = now() + timedelta(hours=settings_for(db, row.patient_id)["suppress_hours"]), now(), user.id
    row.version += 1
    _history(db, row.patient_id, user, "ACTION_ITEM_DISMISSED", "action_item", row.id, "A low-priority coordination item was suppressed")
    db.commit(); db.refresh(row)
    return serialize_action(row)


@router.post("/action-items/{item_id}/act")
def act_on_action_item(item_id: uuid.UUID, body: ActIn, request: Request, user=Depends(_current_user), db: Session = Depends(get_db)):
    row, role_view = _action_row(db, item_id, user)
    if body.option == "I_WILL_HANDLE":
        if role_view not in {"ADMIN", "COORDINATOR"}: raise HTTPException(403, "Coordinator permission required")
        row.owner_user_id = row.assigned_to_user_id = user.id; row.version += 1
        _history(db, row.patient_id, user, "ACTION_ITEM_CREATED", "action_item", row.id, "A coordinator took ownership of an action")
        db.commit(); db.refresh(row); return {"item": serialize_action(row), "warnings": []}
    if body.option == "ACK_HANDOVER":
        brief_id = body.params.get("brief_id")
        return acknowledge_brief(uuid.UUID(str(brief_id)), request, AckIn(), user, db)
    if body.option == "ACKNOWLEDGE_TASK":
        activity_id = uuid.UUID(str(body.params.get("activity_id")))
        from app.main import acknowledge_activity
        result = acknowledge_activity(activity_id, request, user, db)
        reconcile_patient(db, row.patient_id); db.commit()
        return {"item": serialize_action(row), "warnings": [], "result": result}
    if body.option == "MARK_COMPLETE":
        activity_id = uuid.UUID(str(body.params.get("activity_id")))
        from app.api.domain import complete_activity
        result = complete_activity(activity_id, request, user, db)
        reconcile_patient(db, row.patient_id); db.commit()
        return {"item": serialize_action(row), "warnings": [], "result": result}
    if body.option in {"REQUEST_CONFIRMATION", "CONFIRM_ASSIGNMENT", "ASSIGN_CAREGIVER", "PICK_BACKUP"}:
        from app.api import domain
        if body.option == "REQUEST_CONFIRMATION": verb, aid = "request-confirmation", uuid.UUID(str(body.params.get("assignment_id")))
        elif body.option == "CONFIRM_ASSIGNMENT": verb, aid = "confirm", uuid.UUID(str(body.params.get("assignment_id")))
        else:
            activity_id = uuid.UUID(str(body.params.get("activity_id") or next(iter(row.related_activity_ids), "")))
            caregiver_id = uuid.UUID(str(body.params.get("caregiver_id", "")))
            assignment_body = domain.AssignmentIn(caregiver_id=caregiver_id, role="BACKUP" if body.option == "PICK_BACKUP" else "PRIMARY", confirm_now=bool(body.params.get("confirm_now", False)), scope="THIS")
            result = domain.add_assignment(activity_id, assignment_body, request, user, db)
            reconcile_patient(db, row.patient_id); db.commit()
            return {"item": serialize_action(row), "warnings": result.get("warnings", []), "result": result}
        result = domain._transition(aid, verb, {}, request, user, db)
        reconcile_patient(db, row.patient_id); db.commit()
        return {"item": serialize_action(row), "warnings": [], "result": result}
    raise HTTPException(422, "This one-tap option is not available for this item")


@router.get("/patients/{patient_id}/briefs")
def list_briefs(patient_id: uuid.UUID, kind: Literal["MORNING", "HANDOVER"] | None = None, for_date: date | None = Query(default=None, alias="date"), user=Depends(_current_user), db: Session = Depends(get_db)):
    _, _, view = _patient_scope(db, user, patient_id)
    query = select(DailyBrief).where(DailyBrief.patient_id == patient_id)
    if kind: query = query.where(DailyBrief.kind == kind)
    if for_date: query = query.where(DailyBrief.for_date == datetime.combine(for_date, datetime.min.time()))
    rows = db.scalars(query.order_by(DailyBrief.generated_at.desc()).limit(50)).all()
    if view == "MY_DAY": rows = [x for x in rows if x.to_user_id == user.id]
    return {"items": [_brief_dict(db, row) for row in rows], "total": len(rows)}


@router.post("/patients/{patient_id}/briefs/morning")
def generate_morning(patient_id: uuid.UUID, body: MorningIn, request: Request, user=Depends(_current_user), db: Session = Depends(get_db)):
    _patient_scope(db, user, patient_id, write=True)
    row = create_brief(db, patient_id, "MORNING", body.for_date, user.id, regenerate=body.regenerate)
    db.commit(); db.refresh(row)
    return serialize_brief(row)


@router.post("/patients/{patient_id}/briefs/handover/draft", status_code=201)
def create_handover(patient_id: uuid.UUID, body: HandoverDraftIn, request: Request, user=Depends(_current_user), db: Session = Depends(get_db)):
    _, _, view = _patient_scope(db, user, patient_id)
    if view not in {"ADMIN", "COORDINATOR", "MY_DAY"}: raise HTTPException(403, "Only the coordinator or outgoing caretaker can draft a handover")
    existing = db.scalar(select(DailyBrief).where(DailyBrief.patient_id == patient_id, DailyBrief.kind == "HANDOVER", DailyBrief.for_date == datetime.combine(body.for_date, datetime.min.time()), DailyBrief.status == "DRAFT"))
    row = existing or create_brief(db, patient_id, "HANDOVER", body.for_date, user.id, notes=body.notes)
    if body.notes: row.content = {**row.content, "notes": body.notes}; row.rendered_text = row.rendered_text + "\n\nOutgoing caretaker notes:\n" + body.notes[:2000]
    db.commit(); db.refresh(row)
    return serialize_brief(row)


@router.get("/briefs/{brief_id}")
def get_brief(brief_id: uuid.UUID, format: Literal["json", "text", "html"] = "json", user=Depends(_current_user), db: Session = Depends(get_db)):
    row = db.get(DailyBrief, brief_id)
    if not row: raise HTTPException(404, "Brief not found")
    _, _, view = _patient_scope(db, user, row.patient_id)
    if view == "MY_DAY" and row.to_user_id != user.id: raise HTTPException(403, "This handover is not addressed to you")
    if format == "text": return PlainTextResponse(row.rendered_text or "")
    if format == "html": return HTMLResponse(row.rendered_html or "")
    return _brief_dict(db, row)


@router.put("/briefs/{brief_id}")
def update_brief(brief_id: uuid.UUID, body: HandoverUpdateIn, request: Request, user=Depends(_current_user), db: Session = Depends(get_db)):
    row = db.get(DailyBrief, brief_id)
    if not row or row.kind != "HANDOVER": raise HTTPException(404, "Draft handover not found")
    _, _, view = _patient_scope(db, user, row.patient_id)
    if row.status != "DRAFT" or (row.author_user_id != user.id and view not in {"ADMIN", "COORDINATOR"}): raise HTTPException(403, "Only the draft author or coordinator can edit it")
    if body.to_user_id and not db.scalar(select(CareTeamMember.id).where(CareTeamMember.patient_id == row.patient_id, CareTeamMember.user_id == body.to_user_id)):
        raise HTTPException(422, "Handover recipient must be a member of this patient's care team")
    row.to_user_id = body.to_user_id
    safe_notes = "".join(c for c in body.notes if c in "\n\t" or ord(c) >= 32)[:2000]
    row.content = {**row.content, "notes": safe_notes}
    row.rendered_text = "\n\nOutgoing caretaker notes:\n".join([row.rendered_text.split("\n\nOutgoing caretaker notes:\n")[0], safe_notes])[:2000]
    import html
    row.rendered_html = "<article><h1>CareCircle end-of-day handover</h1><pre>" + html.escape(row.rendered_text) + "</pre></article>"
    for data in body.items:
        item = db.get(HandoverItem, uuid.UUID(str(data.get("id")))) if data.get("id") else None
        if item and item.brief_id == row.id and data.get("disposition") in {"DONE", "CARRY_OVER", "DROPPED", "FYI"}:
            item.disposition = data["disposition"]
            item.note = "".join(c for c in str(data.get("note", "")) if c in "\n\t" or ord(c) >= 32)[:500]
    db.commit(); db.refresh(row)
    return serialize_brief(row)


@router.post("/briefs/{brief_id}/publish")
def publish_brief(brief_id: uuid.UUID, request: Request, user=Depends(_current_user), db: Session = Depends(get_db)):
    row = db.get(DailyBrief, brief_id)
    if not row: raise HTTPException(404, "Brief not found")
    _, _, view = _patient_scope(db, user, row.patient_id)
    if row.status != "DRAFT": return serialize_brief(row)
    if row.author_user_id != user.id and view not in {"ADMIN", "COORDINATOR"}: raise HTTPException(403, "Only the author or coordinator can publish")
    row.status = "PUBLISHED"; row.rendered_text = (row.rendered_text or "")[:2000]
    _history(db, row.patient_id, user, "BRIEF_PUBLISHED", "daily_brief", row.id, "A handover was published")
    if row.to_user_id:
        db.add(Notification(user_id=row.to_user_id, patient_id=row.patient_id, kind="DIGEST", severity="LOW", title="Care handover ready", body="A care-team member shared a handover for your review.", requires_ack=True, channel="DIGEST"))
    db.commit(); db.refresh(row)
    return serialize_brief(row)


@router.post("/briefs/{brief_id}/acknowledge")
def acknowledge_brief(brief_id: uuid.UUID, request: Request, body: AckIn | None = None, user=Depends(_current_user), db: Session = Depends(get_db)):
    row = db.get(DailyBrief, brief_id)
    if not row or row.status != "PUBLISHED": raise HTTPException(404, "Published brief not found")
    _, _, view = _patient_scope(db, user, row.patient_id)
    if view == "FAMILY" and row.to_user_id != user.id: raise HTTPException(403, "Only the handover recipient can acknowledge it")
    if view == "MY_DAY" and row.to_user_id != user.id: raise HTTPException(403, "This handover is not addressed to you")
    ack = db.scalar(select(BriefAcknowledgement).where(BriefAcknowledgement.brief_id == row.id, BriefAcknowledgement.user_id == user.id))
    if not ack:
        ack = BriefAcknowledgement(brief_id=row.id, user_id=user.id, acknowledged_at=now(), note=(body.note.strip()[:500] if body and body.note else None)); db.add(ack)
        _history(db, row.patient_id, user, "BRIEF_ACKNOWLEDGED", "daily_brief", row.id, "A handover was acknowledged")
    db.commit()
    return {"brief_id": str(row.id), "acknowledged": True, "acknowledged_at": ack.acknowledged_at.isoformat()}


@router.get("/patients/{patient_id}/command-center/settings")
def get_settings(patient_id: uuid.UUID, user=Depends(_current_user), db: Session = Depends(get_db)):
    _patient_scope(db, user, patient_id)
    return settings_for(db, patient_id)


@router.put("/patients/{patient_id}/command-center/settings")
def put_settings(patient_id: uuid.UUID, body: SettingsIn, request: Request, user=Depends(_current_user), db: Session = Depends(get_db)):
    _patient_scope(db, user, patient_id, write=True)
    row = db.get(CommandCenterSetting, patient_id)
    if not row: row = CommandCenterSetting(patient_id=patient_id); db.add(row)
    for key, value in body.model_dump().items(): setattr(row, key, value)
    row.updated_by = user.id; row.updated_at = now()
    _history(db, patient_id, user, "SETTINGS_UPDATED", "command_center_settings", patient_id, "Command Center settings updated")
    db.commit()
    return settings_for(db, patient_id)
