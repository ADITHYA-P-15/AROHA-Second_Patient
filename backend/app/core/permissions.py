from app.models import Role, TeamRole
from fastapi import HTTPException
from sqlalchemy import select
from app.models import CareTeamMember, Patient
PERMISSIONS = {
    "patient:read": {role: set(TeamRole) for role in Role},
    "patient:update": {Role.ADMIN: set(TeamRole), Role.FAMILY: {TeamRole.COORDINATOR}},
    "careplan:manage": {Role.ADMIN: set(TeamRole), Role.FAMILY: {TeamRole.COORDINATOR}},
    "assignment:confirm_own": {Role.PATIENT: {TeamRole.PATIENT_SELF}, Role.FAMILY: {TeamRole.COORDINATOR, TeamRole.FAMILY}, Role.HOUSEHELP: {TeamRole.HOUSEHELP}, Role.NURSE: {TeamRole.NURSE}, Role.DOCTOR: {TeamRole.DOCTOR}},
    "clinical_notes:read": {Role.ADMIN: set(TeamRole), Role.PATIENT: {TeamRole.PATIENT_SELF}, Role.FAMILY: {TeamRole.COORDINATOR, TeamRole.FAMILY}, Role.NURSE: {TeamRole.NURSE}, Role.DOCTOR: {TeamRole.DOCTOR}},
    "history:read": {Role.ADMIN: set(TeamRole), Role.DOCTOR: {TeamRole.DOCTOR}, Role.FAMILY: {TeamRole.COORDINATOR, TeamRole.FAMILY}},
}
def allowed(role: Role, team_role: TeamRole | None, action: str) -> bool:
    if role == Role.ADMIN: return True
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
    if user.role != Role.ADMIN and (not member or not allowed(user.role, member.team_role, action)):
        raise HTTPException(403, "Patient access denied")
    return patient, member
