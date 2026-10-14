"""Persistence adapter for the pure escalation machine."""
from datetime import timedelta
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.clock import now
from app.engine.escalation_machine import DEFAULT_POLICY, deadline_minutes, next_action
from app.engine.task_watch import detect_task_incidents
from app.models import ActivityHistory, CareActivity, CareAssignment, CareTeamMember, Caregiver, EscalationPolicy, Incident, IncidentEvent, Notification, Patient, TeamRole, User


def policy_for(db: Session, patient_id) -> dict:
    specific = db.scalar(select(EscalationPolicy).where(EscalationPolicy.patient_id == patient_id))
    system = specific or db.scalar(select(EscalationPolicy).where(EscalationPolicy.patient_id.is_(None)))
    return {**DEFAULT_POLICY, **(system.config if system else {})}


def set_deadline(incident: Incident, policy: dict, deadline_kind: str, at, scale: float) -> None:
    incident.deadline_kind = deadline_kind
    minutes = deadline_minutes(policy, incident.current_level, deadline_kind, incident.severity, scale)
    incident.current_deadline_at = at + timedelta(minutes=minutes)


def _recipients(db: Session, patient_id, level: int):
    if level == 0: return []
    rows = db.execute(select(CareTeamMember, User).join(User).where(CareTeamMember.patient_id == patient_id)).all()
    roles = ({TeamRole.CARETAKER} if level == 1 else {TeamRole.PRIMARY_CONTACT} if level == 2 else {TeamRole.PROFESSIONAL} if level in (3, 4) else {TeamRole.PRIMARY_CONTACT, TeamRole.CARETAKER, TeamRole.PROFESSIONAL})
    recipients = [user for member, user in rows if member.team_role in roles and user.is_active]
    # No healthcare professional on the team yet: route to the primary contact instead of notifying nobody.
    if level in (3, 4) and not recipients:
        recipients = [user for member, user in rows if member.team_role == TeamRole.PRIMARY_CONTACT and user.is_active]
    return recipients


def _notify(db: Session, incident: Incident, recipients, title: str, *, emergency=False):
    if not recipients:
        db.add(IncidentEvent(incident_id=incident.id, kind="NO_RECIPIENTS", level=incident.current_level,
                             actor_user_id=None, note="No recipient for this level"))
        return
    for user in recipients:
        db.add(Notification(user_id=user.id, patient_id=incident.patient_id, incident_id=incident.id,
                            kind="INCIDENT", severity=incident.severity, title=title,
                            body=incident.safe_summary, requires_ack=True))
    db.add(IncidentEvent(incident_id=incident.id, kind="NOTIFIED", level=incident.current_level,
                         actor_user_id=None, recipient_user_ids=[str(user.id) for user in recipients],
                         note="Emergency routing" if emergency else None))


def _create_task_incidents(db: Session, current, scale: float) -> int:
    activities = db.scalars(select(CareActivity).where(CareActivity.lifecycle_status == "SCHEDULED", CareActivity.requires_caregiver.is_(True))).all()
    snapshots=[]; caregivers={}
    for activity in activities:
        assignment=db.scalar(select(CareAssignment).where(CareAssignment.activity_id==activity.id, CareAssignment.role=="PRIMARY", CareAssignment.status=="CONFIRMED"))
        if not assignment: continue
        caregiver=db.get(Caregiver,assignment.caregiver_id)
        if not caregiver or not caregiver.user_id: continue
        caregivers[str(activity.id)]=caregiver.user_id
        snapshots.append({"id":str(activity.id),"patient_id":activity.patient_id,"lifecycle_status":activity.lifecycle_status,
                          "primary_confirmed":True,"importance":activity.importance,"acknowledged_at":activity.acknowledged_at,
                          "scheduled_start":activity.scheduled_start,"scheduled_end":activity.scheduled_end})
    created=0
    feed_source={str(a.id):a.source for a in activities}
    for found in detect_task_incidents(snapshots,current):
        # Doses and appointment misses are owned by the status engine (care_status.mark_missed); avoid double alerts.
        if feed_source.get(found["activity_id"])=="PRESCRIPTION": continue
        if feed_source.get(found["activity_id"])=="APPOINTMENT" and found["kind"]=="TASK_OVERDUE": continue
        if db.scalar(select(Incident.id).where(Incident.patient_id==found["patient_id"],Incident.dedupe_key==found["dedupe_key"])):
            continue
        patient=db.get(Patient,found["patient_id"])
        if not patient: continue
        level=found["level"]
        recipients=[db.get(User,caregivers.get(found["activity_id"]))] if level==1 else _recipients(db,patient.id,level)
        recipients=[user for user in recipients if user and user.is_active]
        incident=Incident(patient_id=patient.id,related_activity_id=uuid.UUID(found["activity_id"]),source=found["kind"],category="TASK",
                          importance=next((a.importance for a in activities if str(a.id)==found["activity_id"]),"MEDIUM"),
                          initial_level=level,current_level=level,severity="HIGH" if level==2 else "MEDIUM",status="OPEN",
                          title="Scheduled care activity needs a response",safe_summary=f"{patient.name} has a scheduled care activity needing a response.",
                          dedupe_key=found["dedupe_key"],classification={"rule_ids":[found["kind"]],"reasons":["Confirmed primary assignment needs acknowledgement"],"classifier_version":"task-watch-1"})
        db.add(incident);db.flush()
        if level>0: set_deadline(incident,policy_for(db,patient.id),"ACK",current,scale)
        _notify(db,incident,recipients,"Scheduled care needs acknowledgement")
        db.add(IncidentEvent(incident_id=incident.id,kind="CREATED",level=level,actor_user_id=None,recipient_user_ids=[str(user.id) for user in recipients],meta={"rule_id":found["kind"]}))
        db.add(ActivityHistory(actor_user_id=None,patient_id=patient.id,event_type="INCIDENT_CREATED",entity_type="incident",entity_id=str(incident.id),summary="A scheduled activity needs a response",payload={"source":found["kind"]},request_id=""))
        if not recipients: incident.current_deadline_at=current
        created+=1
    return created


def run_escalation_tick(db: Session, tick_now=None, *, scale: float = 1.0) -> int:
    """Apply due transitions in deadline order; returns the number of incidents changed."""
    current = tick_now or now()
    scale = max(0.01, min(float(scale), 100.0))
    created = _create_task_incidents(db,current,scale)
    due = db.scalars(select(Incident).where(Incident.status.in_(("OPEN", "ACKNOWLEDGED")),
                      Incident.current_deadline_at.is_not(None), Incident.current_deadline_at <= current)
                      .order_by(Incident.current_deadline_at.asc()).with_for_update(skip_locked=True)).all()
    changed = created
    for incident in due:
        policy = policy_for(db, incident.patient_id)
        previous_deadline = incident.current_deadline_at
        if previous_deadline.tzinfo is None:
            previous_deadline = previous_deadline.replace(tzinfo=current.tzinfo)
            incident.current_deadline_at = previous_deadline
        for _ in range(8):
            action = next_action({"status": incident.status, "current_level": incident.current_level,
                                  "severity": incident.severity, "category": incident.category,
                                  "importance": incident.importance,
                                  "deadline_kind": incident.deadline_kind, "current_deadline_at": incident.current_deadline_at,
                                  "acknowledged_at": incident.acknowledged_at, "created_at": incident.created_at,
                                  "emergency_unacknowledged": incident.emergency_unacknowledged}, policy, current, scale=scale)
            if action is None: break
            old_level = incident.current_level
            incident.current_level = action.to_level
            incident.version += 1
            if action.kind == "UNACKNOWLEDGED_EMERGENCY": incident.emergency_unacknowledged = True
            if action.kind == "AUTO_ESCALATED":
                incident.status = "OPEN"; incident.owner_user_id = None; incident.acknowledged_at = None
            elif action.deadline_kind == "RESOLVE":
                incident.status = "ACKNOWLEDGED"
            recipients = _recipients(db, incident.patient_id, incident.current_level)
            title = "UNACKNOWLEDGED EMERGENCY" if action.show_emergency_banner else "Care request escalated" if action.to_level > old_level else "Care request needs attention"
            _notify(db, incident, recipients, title, emergency=incident.current_level == 5)
            event_kind = "AUTO_ESCALATED" if action.kind == "AUTO_ESCALATED" else "REMINDER_SENT"
            db.add(IncidentEvent(incident_id=incident.id, kind=event_kind, level=incident.current_level,
                                 actor_user_id=None, recipient_user_ids=[str(user.id) for user in recipients], note=action.reason,
                                 meta={"action": action.kind, "from_level": old_level, "to_level": action.to_level,
                                       "show_emergency_banner": action.show_emergency_banner}))
            set_deadline(incident, policy, action.deadline_kind, previous_deadline, scale)
            if not recipients and action.kind == "AUTO_ESCALATED" and incident.current_level < 4:
                incident.current_deadline_at = previous_deadline
                previous_deadline = incident.current_deadline_at
                continue
            # Reminders do not replay missed intervals; level transitions do catch up in order.
            if action.kind != "AUTO_ESCALATED":
                set_deadline(incident, policy, action.deadline_kind, current, scale)
                break
            previous_deadline = incident.current_deadline_at
            if incident.current_deadline_at > current: break
        changed += 1
    if changed: db.commit()
    return changed
