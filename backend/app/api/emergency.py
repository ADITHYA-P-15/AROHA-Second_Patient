"""Ambulance call from a request that has reached a primary contact.

CareCircle never places a call itself. The button opens the phone's dialer (tel:108); this endpoint only records that a primary
contact is calling, and tells the rest of the care team so nobody duplicates the call.
"""
from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.clock import now
from app.core.db import get_db
from app.models import CareTeamMember, Incident, IncidentEvent, Notification, TeamRole, User

router = APIRouter(prefix="/api/v1", tags=["emergency"])
ACTION = "AMBULANCE_CALLED"
REPEAT_WINDOW = timedelta(minutes=10)


def _current_user(request: Request, db: Session = Depends(get_db)):
    from app.main import current_user
    return current_user(request, db)


def ambulance_calls_for(db: Session, incident_ids: list) -> dict:
    """Latest ambulance call per incident: {incident_id: {at, by}}."""
    if not incident_ids: return {}
    out: dict = {}
    rows = db.execute(select(IncidentEvent, User).outerjoin(User, User.id == IncidentEvent.actor_user_id)
                      .where(IncidentEvent.incident_id.in_(incident_ids), IncidentEvent.kind == "DECISION_TAKEN").order_by(IncidentEvent.at)).all()
    for event, actor in rows:
        if (event.meta or {}).get("action") != ACTION: continue
        at = event.at.replace(tzinfo=__import__("datetime").timezone.utc) if event.at.tzinfo is None else event.at
        out[event.incident_id] = {"at": at, "by": actor.name if actor else None}
    return out


@router.post("/incidents/{incident_id}/ambulance")
def ambulance_called(incident_id: str, request: Request, user=Depends(_current_user), db: Session = Depends(get_db)):
    import uuid
    from app.main import audit, patient_access
    try:
        incident = db.get(Incident, uuid.UUID(incident_id))
    except ValueError:
        incident = None
    if incident is None: raise HTTPException(404, "Request not found")
    patient, member = patient_access(db, user, incident.patient_id)
    if member is None or member.team_role != TeamRole.PRIMARY_CONTACT: raise HTTPException(403, "Only a primary contact can record an ambulance call")
    if incident.status in ("RESOLVED", "CANCELLED"): raise HTTPException(409, "This request is already closed")
    previous = ambulance_calls_for(db, [incident.id]).get(incident.id)
    if previous and now() - previous["at"] < REPEAT_WINDOW: return {"status": "already_recorded", "at": previous["at"], "by": previous["by"]}
    when = now()
    db.add(IncidentEvent(incident_id=incident.id, kind="DECISION_TAKEN", level=incident.current_level, actor_user_id=user.id, note=f"{user.name} is calling an ambulance (108)", meta={"action": ACTION}))
    others = db.scalars(select(User).join(CareTeamMember, CareTeamMember.user_id == User.id)
                        .where(CareTeamMember.patient_id == patient.id, User.id != user.id, User.is_active.is_(True))).all()
    for other in others:
        db.add(Notification(user_id=other.id, patient_id=patient.id, incident_id=incident.id, kind="STATUS", severity="HIGH", title=f"Ambulance being called for {patient.name}",
                            body=f"{user.name} is calling an ambulance (108). No need to call again; please check on {patient.name}.", requires_ack=False, channel="ALERT"))
    audit(db, user, patient.id, "AMBULANCE_CALL_STARTED", "incident", incident.id, f"{user.name} started an ambulance call from a care request", request.state.request_id)
    db.commit()
    return {"status": "recorded", "at": when, "by": user.name, "notified": len(others)}
