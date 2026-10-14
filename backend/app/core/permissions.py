from fastapi import HTTPException
from sqlalchemy import select

from app.models import CareTeamMember, Patient, Role, TeamRole

# Account role -> care-team roles that grant each action. Access always also requires membership of that patient's team.
PERMISSIONS = {
    "patient:read": {role: set(TeamRole) for role in Role},
    "patient:update": {Role.PRIMARY_CONTACT: {TeamRole.PRIMARY_CONTACT}},
    "careplan:manage": {Role.PRIMARY_CONTACT: {TeamRole.PRIMARY_CONTACT}},
    "assignment:confirm_own": {Role.PATIENT: {TeamRole.PATIENT_SELF}, Role.PRIMARY_CONTACT: {TeamRole.PRIMARY_CONTACT},
                               Role.CARETAKER: {TeamRole.CARETAKER}, Role.PROFESSIONAL: {TeamRole.PROFESSIONAL}},
    "clinical_notes:read": {Role.PATIENT: {TeamRole.PATIENT_SELF}, Role.PRIMARY_CONTACT: {TeamRole.PRIMARY_CONTACT},
                            Role.PROFESSIONAL: {TeamRole.PROFESSIONAL}},
    "history:read": {Role.PROFESSIONAL: {TeamRole.PROFESSIONAL}, Role.PRIMARY_CONTACT: {TeamRole.PRIMARY_CONTACT}},
}


def allowed(role: Role, team_role: TeamRole | None, action: str) -> bool:
    return team_role in PERMISSIONS.get(action, {}).get(role, set())


def require_role(user, *roles: Role):
    if user.role not in roles:
        raise HTTPException(403, "Permission denied")
    return user


def require_patient_access(db, user, patient_id, action="patient:read"):
    patient = db.get(Patient, patient_id)
    if not patient:
        raise HTTPException(404, "Patient not found")
    member = db.scalar(select(CareTeamMember).where(CareTeamMember.patient_id == patient_id, CareTeamMember.user_id == user.id))
    if not member or not allowed(user.role, member.team_role, action):
        raise HTTPException(403, "Patient access denied")
    return patient, member
