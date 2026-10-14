import enum
import uuid

from sqlalchemy import Boolean, CheckConstraint, DateTime, Enum, ForeignKey, Integer, JSON, String, Text, UniqueConstraint, Index, text, Float
from sqlalchemy.orm import Mapped, mapped_column

from app.core.clock import now
from app.core.db import Base


class Role(str, enum.Enum):
    PATIENT = "PATIENT"
    FAMILY = "FAMILY"
    HOUSEHELP = "HOUSEHELP"
    NURSE = "NURSE"
    DOCTOR = "DOCTOR"
    ADMIN = "ADMIN"


class TeamRole(str, enum.Enum):
    PATIENT_SELF = "PATIENT_SELF"
    COORDINATOR = "COORDINATOR"
    FAMILY = "FAMILY"
    HOUSEHELP = "HOUSEHELP"
    NURSE = "NURSE"
    DOCTOR = "DOCTOR"


def uuid_pk():
    return mapped_column(primary_key=True, default=uuid.uuid4)


class User(Base):
    __tablename__ = "users"
    __table_args__ = (CheckConstraint("email = lower(email)", name="ck_users_email_lowercase"),)
    id: Mapped[uuid.UUID] = uuid_pk()
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(160))
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[Role] = mapped_column(Enum(Role, native_enum=False), default=Role.FAMILY)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_synthetic: Mapped[bool] = mapped_column(Boolean, default=False)
    token_version: Mapped[int] = mapped_column(Integer, default=0)
    language_pref: Mapped[str] = mapped_column(String(8), default="en")
    created_at: Mapped[object] = mapped_column(DateTime(timezone=True), default=now)


class Patient(Base):
    __tablename__ = "patients"
    __table_args__ = (CheckConstraint("birth_year IS NULL OR (birth_year >= 1900 AND birth_year <= 2100)", name="ck_patients_birth_year"), CheckConstraint("mobility_level IN ('INDEPENDENT','NEEDS_AID','WHEELCHAIR','BEDBOUND')", name="ck_patients_mobility"))
    id: Mapped[uuid.UUID] = uuid_pk()
    name: Mapped[str] = mapped_column(String(160))
    birth_year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    care_notes: Mapped[str] = mapped_column(Text, default="")
    clinical_notes: Mapped[str] = mapped_column(Text, default="")
    mobility_level: Mapped[str] = mapped_column(String(20), default="INDEPENDENT")
    language_pref: Mapped[str] = mapped_column(String(8), default="en")
    continuity_status: Mapped[str] = mapped_column(String(24), default="UNKNOWN")
    is_synthetic: Mapped[bool] = mapped_column(Boolean, default=True)
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[object] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[object] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)


class CareTeamMember(Base):
    __tablename__ = "care_team_members"
    __table_args__ = (UniqueConstraint("patient_id", "user_id"),)
    id: Mapped[uuid.UUID] = uuid_pk()
    patient_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("patients.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    team_role: Mapped[TeamRole] = mapped_column(Enum(TeamRole, native_enum=False))
    is_primary_coordinator: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[object] = mapped_column(DateTime(timezone=True), default=now)


class ActivityHistory(Base):
    __tablename__ = "activity_history"
    id: Mapped[uuid.UUID] = uuid_pk()
    occurred_at: Mapped[object] = mapped_column(DateTime(timezone=True), default=now, index=True)
    event_type: Mapped[str] = mapped_column(String(80))
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    patient_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("patients.id", ondelete="SET NULL"), nullable=True, index=True)
    entity_type: Mapped[str] = mapped_column(String(80))
    entity_id: Mapped[str] = mapped_column(String(36))
    summary: Mapped[str] = mapped_column(String(500))
    outcome: Mapped[str] = mapped_column(String(40), default="SUCCESS")
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    request_id: Mapped[str] = mapped_column(String(80), default="")


class PatientSupportNeed(Base):
    __tablename__ = "patient_support_needs"
    __table_args__ = (UniqueConstraint("patient_id", "support_code"), CheckConstraint("support_code IN ('TRANSPORT','MEDICATION_ASSIST','PRESCRIPTION_PICKUP','DAILY_ASSIST','MOBILITY_ASSIST','LAB_ESCORT','SUPPLIES','CLINICAL_VISIT','APPOINTMENT_ESCORT')", name="ck_support_need_code"))
    id: Mapped[uuid.UUID] = uuid_pk()
    patient_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("patients.id", ondelete="CASCADE"), index=True)
    support_code: Mapped[str] = mapped_column(String(40))
    notes: Mapped[str] = mapped_column(Text, default="")


class Caregiver(Base):
    __tablename__ = "caregivers"
    __table_args__ = (CheckConstraint("max_activities_per_day >= 0"), CheckConstraint("max_hours_per_week >= 0"), CheckConstraint("kind IN ('FAMILY','HOUSEHELP','NURSE','NEIGHBOUR','VOLUNTEER','OTHER')", name="ck_caregiver_kind"))
    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), unique=True, nullable=True)
    name: Mapped[str] = mapped_column(String(160))
    kind: Mapped[str] = mapped_column(String(24))
    phone: Mapped[str | None] = mapped_column(String(40), nullable=True)
    capabilities: Mapped[list] = mapped_column(JSON, default=list)
    max_activities_per_day: Mapped[int] = mapped_column(Integer, default=3)
    max_hours_per_week: Mapped[float] = mapped_column(Float, default=40)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    notes: Mapped[str] = mapped_column(Text, default="")
    is_synthetic: Mapped[bool] = mapped_column(Boolean, default=True)
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[object] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[object] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)


class CaregiverPatientLink(Base):
    __tablename__ = "caregiver_patient_links"
    __table_args__ = (UniqueConstraint("caregiver_id", "patient_id"),)
    id: Mapped[uuid.UUID] = uuid_pk()
    caregiver_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("caregivers.id", ondelete="CASCADE"), index=True)
    patient_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("patients.id", ondelete="CASCADE"), index=True)
    relationship: Mapped[str] = mapped_column(String(120), default="")
    is_designated_backup: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[object] = mapped_column(DateTime(timezone=True), default=now)


class CaregiverWeeklySchedule(Base):
    __tablename__ = "caregiver_weekly_schedule"
    __table_args__ = (CheckConstraint("weekday >= 0 AND weekday <= 6"), CheckConstraint("start_min >= 0 AND start_min < end_min AND end_min <= 1440"),)
    id: Mapped[uuid.UUID] = uuid_pk()
    caregiver_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("caregivers.id", ondelete="CASCADE"), index=True)
    weekday: Mapped[int] = mapped_column(Integer)
    start_min: Mapped[int] = mapped_column(Integer)
    end_min: Mapped[int] = mapped_column(Integer)


class AvailabilityOverride(Base):
    __tablename__ = "availability_overrides"
    __table_args__ = (CheckConstraint("end_at > start_at"), CheckConstraint("status IN ('UNAVAILABLE','AVAILABLE')", name="ck_override_status"), CheckConstraint("reason IN ('WORK','ILLNESS','TRAVEL','PERSONAL','EMERGENCY','OTHER')", name="ck_override_reason"))
    id: Mapped[uuid.UUID] = uuid_pk()
    caregiver_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("caregivers.id", ondelete="CASCADE"), index=True)
    start_at: Mapped[object] = mapped_column(DateTime(timezone=True))
    end_at: Mapped[object] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(16))
    reason: Mapped[str] = mapped_column(String(24))
    note: Mapped[str] = mapped_column(Text, default="")
    cancelled_at: Mapped[object | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))


class CareActivity(Base):
    __tablename__ = "care_activities"
    __table_args__ = (CheckConstraint("scheduled_end > scheduled_start"), CheckConstraint("deadline IS NULL OR deadline >= scheduled_start"), CheckConstraint("buffer_before_min >= 0 AND buffer_after_min >= 0"), CheckConstraint("category IN ('APPOINTMENT','TRANSPORT','PRESCRIPTION','MEDICATION','FOLLOW_UP','DAILY_ROUTINE','MOBILITY','LAB','SUPPLIES','POST_APPOINTMENT','OTHER')", name="ck_activity_category"), CheckConstraint("importance IN ('LOW','MEDIUM','HIGH','CRITICAL')", name="ck_activity_importance"), CheckConstraint("lifecycle_status IN ('SCHEDULED','COMPLETED','CANCELLED')", name="ck_activity_lifecycle"), CheckConstraint("coverage_status IN ('UNASSESSED','SUPPORTED','UNSUPPORTED','PARTIAL')", name="ck_activity_coverage"))
    id: Mapped[uuid.UUID] = uuid_pk()
    patient_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("patients.id", ondelete="CASCADE"), index=True)
    series_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True, index=True)
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    category: Mapped[str] = mapped_column(String(32))
    scheduled_start: Mapped[object] = mapped_column(DateTime(timezone=True), index=True)
    scheduled_end: Mapped[object] = mapped_column(DateTime(timezone=True))
    deadline: Mapped[object | None] = mapped_column(DateTime(timezone=True), nullable=True)
    importance: Mapped[str] = mapped_column(String(16), default="MEDIUM")
    requires_caregiver: Mapped[bool] = mapped_column(Boolean, default=True)
    required_support: Mapped[list] = mapped_column(JSON, default=list)
    buffer_before_min: Mapped[int] = mapped_column(Integer, default=0)
    buffer_after_min: Mapped[int] = mapped_column(Integer, default=0)
    location_note: Mapped[str] = mapped_column(Text, default="")
    lifecycle_status: Mapped[str] = mapped_column(String(16), default="SCHEDULED", index=True)
    is_synthetic: Mapped[bool] = mapped_column(Boolean, default=False)
    coverage_status: Mapped[str] = mapped_column(String(16), default="UNASSESSED")
    gap_reason: Mapped[str | None] = mapped_column(String(120), nullable=True)
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[object] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[object] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)


class ActivityDependency(Base):
    __tablename__ = "activity_dependencies"
    activity_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("care_activities.id", ondelete="CASCADE"), primary_key=True)
    depends_on_activity_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("care_activities.id", ondelete="CASCADE"), primary_key=True)


class CareAssignment(Base):
    __tablename__ = "care_assignments"
    __table_args__ = (CheckConstraint("role IN ('PRIMARY','BACKUP')", name="ck_assignment_role"), CheckConstraint("status IN ('PROPOSED','AWAITING_CONFIRMATION','CONFIRMED','DECLINED','REJECTED','CANCELLED','SUPERSEDED')", name="ck_assignment_status"), Index("uq_active_primary_activity", "activity_id", unique=True, postgresql_where=text("role = 'PRIMARY' AND status IN ('PROPOSED','AWAITING_CONFIRMATION','CONFIRMED')"), sqlite_where=text("role = 'PRIMARY' AND status IN ('PROPOSED','AWAITING_CONFIRMATION','CONFIRMED')")),)
    id: Mapped[uuid.UUID] = uuid_pk()
    activity_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("care_activities.id", ondelete="CASCADE"), index=True)
    caregiver_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("caregivers.id"), index=True)
    role: Mapped[str] = mapped_column(String(12))
    status: Mapped[str] = mapped_column(String(24), default="PROPOSED", index=True)
    assigned_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    assigned_at: Mapped[object] = mapped_column(DateTime(timezone=True), default=now)
    confirmed_at: Mapped[object | None] = mapped_column(DateTime(timezone=True), nullable=True)
    confirmed_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    confirmed_via: Mapped[str | None] = mapped_column(String(16), nullable=True)
    decline_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[object] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)


Index("ix_assignment_caregiver_status", CareAssignment.caregiver_id, CareAssignment.status)
