import enum
import uuid

from sqlalchemy import Boolean, CheckConstraint, Date, DateTime, Enum, ForeignKey, Integer, JSON, String, Text, UniqueConstraint, Index, text, Float
from sqlalchemy.orm import Mapped, mapped_column

from app.core.clock import now
from app.core.db import Base


class Role(str, enum.Enum):
    """The four people CareCircle serves."""
    PATIENT = "PATIENT"
    PRIMARY_CONTACT = "PRIMARY_CONTACT"  # blood relative who registers and oversees
    CARETAKER = "CARETAKER"  # carries out doses and appointments
    PROFESSIONAL = "PROFESSIONAL"  # hospital side: prescribes and schedules


class TeamRole(str, enum.Enum):
    PATIENT_SELF = "PATIENT_SELF"
    PRIMARY_CONTACT = "PRIMARY_CONTACT"
    CARETAKER = "CARETAKER"
    PROFESSIONAL = "PROFESSIONAL"


def uuid_pk():
    return mapped_column(primary_key=True, default=uuid.uuid4)


class User(Base):
    __tablename__ = "users"
    __table_args__ = (CheckConstraint("email = lower(email)", name="ck_users_email_lowercase"),)
    id: Mapped[uuid.UUID] = uuid_pk()
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(160))
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[Role] = mapped_column(Enum(Role, native_enum=False, length=24), default=Role.PRIMARY_CONTACT)
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
    # Shared by the family with the hospital: a professional finds the patient with this ID plus the birth year.
    care_code: Mapped[str | None] = mapped_column(String(12), unique=True, index=True, nullable=True)
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
    team_role: Mapped[TeamRole] = mapped_column(Enum(TeamRole, native_enum=False, length=24))
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
    __table_args__ = (CheckConstraint("max_activities_per_day >= 0"), CheckConstraint("max_hours_per_week >= 0"), CheckConstraint("kind IN ('CARETAKER','PRIMARY_CONTACT')", name="ck_caregiver_kind"))
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
    # The patient's regular caretaker: new doses and appointments are assigned to them when they can do them.
    is_main_caretaker: Mapped[bool] = mapped_column(Boolean, default=False)
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
    __table_args__ = (CheckConstraint("scheduled_end > scheduled_start"), CheckConstraint("deadline IS NULL OR deadline >= scheduled_start"), CheckConstraint("buffer_before_min >= 0 AND buffer_after_min >= 0"), CheckConstraint("category IN ('APPOINTMENT','TRANSPORT','PRESCRIPTION','MEDICATION','FOLLOW_UP','DAILY_ROUTINE','MOBILITY','LAB','SUPPLIES','POST_APPOINTMENT','OTHER')", name="ck_activity_category"), CheckConstraint("importance IN ('LOW','MEDIUM','HIGH','CRITICAL')", name="ck_activity_importance"), CheckConstraint("lifecycle_status IN ('SCHEDULED','COMPLETED','MISSED','CANCELLED')", name="ck_activity_lifecycle"), CheckConstraint("source IN ('MANUAL','PRESCRIPTION','APPOINTMENT')", name="ck_activity_source"), CheckConstraint("coverage_status IN ('UNASSESSED','SUPPORTED','UNSUPPORTED','PARTIAL')", name="ck_activity_coverage"))
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
    lifecycle_status: Mapped[str] = mapped_column(String(16), default="SCHEDULED", index=True)  # SCHEDULED = pending
    # Where the activity came from: a professional's prescription (one row per dose) or appointment, or added by hand.
    source: Mapped[str] = mapped_column(String(16), default="MANUAL", index=True)
    source_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True, index=True)
    completed_at: Mapped[object | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    completed_late: Mapped[bool] = mapped_column(Boolean, default=False)
    missed_at: Mapped[object | None] = mapped_column(DateTime(timezone=True), nullable=True)
    is_synthetic: Mapped[bool] = mapped_column(Boolean, default=False)
    coverage_status: Mapped[str] = mapped_column(String(16), default="UNASSESSED")
    gap_reason: Mapped[str | None] = mapped_column(String(120), nullable=True)
    acknowledged_at: Mapped[object | None] = mapped_column(DateTime(timezone=True), nullable=True)
    acknowledged_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True)
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


class PatientMessage(Base):
    __tablename__ = "patient_messages"
    __table_args__ = (UniqueConstraint("sender_user_id", "idempotency_key", name="uq_message_sender_idempotency"), CheckConstraint("length(body) <= 1000"), CheckConstraint("channel IN ('TEXT','SOS_BUTTON','QUICK_REPLY','VOICE')"))
    id: Mapped[uuid.UUID] = uuid_pk()
    patient_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("patients.id", ondelete="CASCADE"), index=True)
    sender_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    on_behalf: Mapped[bool] = mapped_column(Boolean, default=False)
    reported_role: Mapped[str] = mapped_column(String(32), default="PATIENT")
    channel: Mapped[str] = mapped_column(String(16), default="TEXT")
    body: Mapped[str] = mapped_column(String(1000))
    language_hint: Mapped[str | None] = mapped_column(String(8), nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(120), nullable=True)
    incident_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("incidents.id"), nullable=True)
    created_at: Mapped[object] = mapped_column(DateTime(timezone=True), default=now)


class Incident(Base):
    __tablename__ = "incidents"
    __table_args__ = (CheckConstraint("current_level >= 0 AND current_level <= 5"), CheckConstraint("initial_level >= 0 AND initial_level <= 5"), CheckConstraint("status IN ('OPEN','ACKNOWLEDGED','RESOLVED','CANCELLED')"), CheckConstraint("category IN ('EMERGENCY','HEALTH_CONCERN','MEDICATION','DAILY_HELP','LOGISTICS','TASK','INFO','UNCLASSIFIED')"), CheckConstraint("source IN ('PATIENT_MESSAGE','SOS','TASK_UNACKNOWLEDGED','TASK_OVERDUE','CARETAKER_REPORT','MANUAL','CARE_GAP','STRAIN')"), CheckConstraint("severity IN ('LOW','MEDIUM','HIGH')"), CheckConstraint("importance IN ('LOW','MEDIUM','HIGH','CRITICAL')", name="ck_incidents_importance"), CheckConstraint("deadline_kind IS NULL OR deadline_kind IN ('ACK','RESOLVE')", name="ck_incidents_deadline_kind"), CheckConstraint("repeat_count >= 1", name="ck_incidents_repeat_count"), UniqueConstraint("patient_id", "dedupe_key", name="uq_incident_patient_dedupe"), Index("ix_incident_patient_status", "patient_id", "status"))
    id: Mapped[uuid.UUID] = uuid_pk()
    patient_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("patients.id", ondelete="CASCADE"), index=True)
    source: Mapped[str] = mapped_column(String(32), default="PATIENT_MESSAGE")
    category: Mapped[str] = mapped_column(String(32))
    importance: Mapped[str] = mapped_column(String(16), default="MEDIUM")
    initial_level: Mapped[int] = mapped_column(Integer)
    current_level: Mapped[int] = mapped_column(Integer)
    severity: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(20), default="OPEN", index=True)
    title: Mapped[str] = mapped_column(String(200))
    safe_summary: Mapped[str] = mapped_column(String(500))
    dedupe_key: Mapped[str] = mapped_column(String(120), index=True)
    classification: Mapped[dict] = mapped_column(JSON, default=dict)
    owner_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    related_activity_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("care_activities.id", ondelete="SET NULL"), nullable=True, index=True)
    current_deadline_at: Mapped[object | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    deadline_kind: Mapped[str | None] = mapped_column(String(8), nullable=True)
    repeat_count: Mapped[int] = mapped_column(Integer, default=1)
    emergency_unacknowledged: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[object] = mapped_column(DateTime(timezone=True), default=now, index=True)
    acknowledged_at: Mapped[object | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolved_at: Mapped[object | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolution_code: Mapped[str | None] = mapped_column(String(32), nullable=True)
    resolution_note: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    version: Mapped[int] = mapped_column(Integer, default=1)


class IncidentEvent(Base):
    __tablename__ = "incident_events"
    __table_args__ = (CheckConstraint("level >= 0 AND level <= 5"), CheckConstraint("kind IN ('CREATED','CLASSIFIED','NOTIFIED','ACKNOWLEDGED','AUTO_ESCALATED','MANUAL_ESCALATED','LEVEL_LOWERED','NO_RECIPIENTS','BACKUP_OFFERED','DECISION_TAKEN','VISIT_ADDED','INSTRUCTION_ISSUED','REMINDER_SENT','MERGED_MESSAGE','RESOLVED','CANCELLED')"))
    id: Mapped[uuid.UUID] = uuid_pk()
    incident_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("incidents.id", ondelete="CASCADE"), index=True)
    at: Mapped[object] = mapped_column(DateTime(timezone=True), default=now, index=True)
    kind: Mapped[str] = mapped_column(String(32))
    level: Mapped[int] = mapped_column(Integer)
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    recipient_user_ids: Mapped[list] = mapped_column(JSON, default=list)
    note: Mapped[str | None] = mapped_column(String(500), nullable=True)
    meta: Mapped[dict] = mapped_column(JSON, default=dict)


class Notification(Base):
    __tablename__ = "notifications"
    __table_args__ = (CheckConstraint("kind IN ('INCIDENT','REMINDER','DECISION','INSTRUCTION','DIGEST','STATUS')"), CheckConstraint("severity IN ('LOW','MEDIUM','HIGH')"), CheckConstraint("channel IN ('ALERT','INBOX','DIGEST')", name="ck_notifications_channel"))
    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    patient_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("patients.id", ondelete="CASCADE"), index=True)
    incident_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("incidents.id", ondelete="CASCADE"), nullable=True, index=True)
    kind: Mapped[str] = mapped_column(String(20), default="INCIDENT")
    severity: Mapped[str] = mapped_column(String(16))
    title: Mapped[str] = mapped_column(String(160))
    body: Mapped[str] = mapped_column(String(500))
    requires_ack: Mapped[bool] = mapped_column(Boolean, default=False)
    channel: Mapped[str] = mapped_column(String(12), default="ALERT")
    acked_at: Mapped[object | None] = mapped_column(DateTime(timezone=True), nullable=True)
    read_at: Mapped[object | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[object] = mapped_column(DateTime(timezone=True), default=now, index=True)


class EscalationPolicy(Base):
    __tablename__ = "escalation_policies"
    id: Mapped[uuid.UUID] = uuid_pk()
    patient_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("patients.id", ondelete="CASCADE"), nullable=True, unique=True)
    config: Mapped[dict] = mapped_column(JSON, default=dict)
    version: Mapped[int] = mapped_column(Integer, default=1)
    updated_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    updated_at: Mapped[object] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)


class AppSetting(Base):
    __tablename__ = "app_settings"
    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    value: Mapped[dict] = mapped_column(JSON, default=dict)


class ActionItem(Base):
    __tablename__ = "action_items"
    __table_args__ = (
        CheckConstraint("source IN ('DERIVED','MANUAL','INCIDENT','HANDOVER')", name="ck_action_item_source"),
        CheckConstraint("severity IN ('LOW','MEDIUM','HIGH','CRITICAL')", name="ck_action_item_severity"),
        CheckConstraint("status IN ('OPEN','SNOOZED','DONE','AUTO_RESOLVED','DISMISSED')", name="ck_action_item_status"),
        CheckConstraint("reopened_count >= 0 AND version >= 1", name="ck_action_item_counters"),
        Index("uq_action_item_active_dedupe", "patient_id", "dedupe_key", unique=True, postgresql_where=text("status IN ('OPEN','SNOOZED')"), sqlite_where=text("status IN ('OPEN','SNOOZED')")),
        Index("ix_action_item_patient_status", "patient_id", "status"),
        Index("ix_action_item_assignee_status", "assigned_to_user_id", "status"),
    )
    id: Mapped[uuid.UUID] = uuid_pk()
    patient_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("patients.id", ondelete="CASCADE"), index=True)
    dedupe_key: Mapped[str] = mapped_column(String(180))
    kind: Mapped[str] = mapped_column(String(48))
    source: Mapped[str] = mapped_column(String(16))
    title: Mapped[str] = mapped_column(String(200))
    reason: Mapped[str] = mapped_column(String(500), default="")
    reasons: Mapped[list] = mapped_column(JSON, default=list)
    severity: Mapped[str] = mapped_column(String(12), default="MEDIUM")
    related_activity_ids: Mapped[list] = mapped_column(JSON, default=list)
    related_incident_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("incidents.id", ondelete="SET NULL"), nullable=True)
    owner_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    assigned_to_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    due_at: Mapped[object | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(20), default="OPEN", index=True)
    snoozed_until: Mapped[object | None] = mapped_column(DateTime(timezone=True), nullable=True)
    suppressed_until: Mapped[object | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolution_note: Mapped[str | None] = mapped_column(String(500), nullable=True)
    resolution_reason: Mapped[str | None] = mapped_column(String(32), nullable=True)
    suggested_actions: Mapped[list] = mapped_column(JSON, default=list)
    first_seen_at: Mapped[object] = mapped_column(DateTime(timezone=True), default=now)
    last_seen_at: Mapped[object] = mapped_column(DateTime(timezone=True), default=now)
    resolved_at: Mapped[object | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolved_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    reopened_count: Mapped[int] = mapped_column(Integer, default=0)
    version: Mapped[int] = mapped_column(Integer, default=1)


class CommandCenterSetting(Base):
    __tablename__ = "command_center_settings"
    __table_args__ = (CheckConstraint("handover_autopublish_after_min BETWEEN 5 AND 1440", name="ck_cc_autopublish_minutes"), CheckConstraint("suppress_hours BETWEEN 1 AND 168", name="ck_cc_suppress_hours"))
    patient_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("patients.id", ondelete="CASCADE"), primary_key=True)
    morning_brief_time: Mapped[str] = mapped_column(String(5), default="07:00")
    handover_time: Mapped[str] = mapped_column(String(5), default="19:30")
    handover_autopublish_after_min: Mapped[int] = mapped_column(Integer, default=60)
    daypart_boundaries: Mapped[dict] = mapped_column(JSON, default=dict)
    routine_rules: Mapped[dict] = mapped_column(JSON, default=dict)
    snooze_max_minutes_by_severity: Mapped[dict] = mapped_column(JSON, default=dict)
    suppress_hours: Mapped[int] = mapped_column(Integer, default=12)
    updated_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    updated_at: Mapped[object] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)


class CoverRequest(Base):
    """A task that lost (or never had) dependable cover; the Backup Matcher ranks and offers replacements."""
    __tablename__ = "cover_requests"
    __table_args__ = (
        CheckConstraint("reason IN ('DECLINED','ABSENCE','MANUAL','UNASSIGNED')", name="ck_cover_request_reason"),
        CheckConstraint("status IN ('OPEN','OFFERED','COVERED','CANCELLED','EXPIRED')", name="ck_cover_request_status"),
        CheckConstraint("resolution IS NULL OR resolution IN ('MATCHER','MANUAL')", name="ck_cover_request_resolution"),
        Index("uq_open_cover_request_activity", "activity_id", unique=True,
              postgresql_where=text("status IN ('OPEN','OFFERED')"), sqlite_where=text("status IN ('OPEN','OFFERED')")),
        Index("ix_cover_request_patient_status", "patient_id", "status"),
    )
    id: Mapped[uuid.UUID] = uuid_pk()
    patient_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("patients.id", ondelete="CASCADE"), index=True)
    activity_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("care_activities.id", ondelete="CASCADE"), index=True)
    reason: Mapped[str] = mapped_column(String(16))
    reason_note: Mapped[str] = mapped_column(String(300), default="")
    # Deterministic source ("decline:<assignment>", "absence:<override>:<assignment>") so a trigger opens at most one request.
    trigger_key: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    replaced_caregiver_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("caregivers.id", ondelete="SET NULL"), nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="OPEN", index=True)
    resolution: Mapped[str | None] = mapped_column(String(16), nullable=True)
    offered_caregiver_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("caregivers.id", ondelete="SET NULL"), nullable=True)
    offered_at: Mapped[object | None] = mapped_column(DateTime(timezone=True), nullable=True)
    auto_advance: Mapped[bool] = mapped_column(Boolean, default=True)
    declined_caregiver_ids: Mapped[list] = mapped_column(JSON, default=list)
    covered_by_caregiver_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("caregivers.id", ondelete="SET NULL"), nullable=True)
    covered_assignment_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("care_assignments.id", ondelete="SET NULL"), nullable=True)
    opened_at: Mapped[object] = mapped_column(DateTime(timezone=True), default=now)
    closed_at: Mapped[object | None] = mapped_column(DateTime(timezone=True), nullable=True)
    opened_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    version: Mapped[int] = mapped_column(Integer, default=1)


class CoverRequestEvent(Base):
    __tablename__ = "cover_request_events"
    __table_args__ = (CheckConstraint("kind IN ('OPENED','OFFERED','OFFER_DECLINED','AUTO_ADVANCED','ACCEPTED','COVERED','CANCELLED','EXPIRED','NO_CANDIDATES')", name="ck_cover_event_kind"),)
    id: Mapped[uuid.UUID] = uuid_pk()
    request_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("cover_requests.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(20))
    caregiver_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("caregivers.id", ondelete="SET NULL"), nullable=True)
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    note: Mapped[str] = mapped_column(String(300), default="")
    at: Mapped[object] = mapped_column(DateTime(timezone=True), default=now)


class CoverageFinding(Base):
    """One task's forecast risk, tracked from first detection to outcome (kind can change while it stays open)."""
    __tablename__ = "coverage_findings"
    __table_args__ = (
        CheckConstraint("kind IN ('GAP','UNCONFIRMED','SINGLE_POINT')", name="ck_coverage_finding_kind"),
        CheckConstraint("status IN ('OPEN','RESOLVED','MISSED','CLOSED')", name="ck_coverage_finding_status"),
        CheckConstraint("outcome IS NULL OR outcome IN ('BEFORE_DEADLINE','AFTER_DEADLINE','STARTED_UNCOVERED','NO_BACKUP_SECURED','TASK_CLOSED','OUT_OF_SCOPE')", name="ck_coverage_finding_outcome"),
        CheckConstraint("worst_kind IN ('GAP','UNCONFIRMED','SINGLE_POINT')", name="ck_coverage_finding_worst_kind"),
        Index("uq_open_coverage_finding", "activity_id", unique=True,
              postgresql_where=text("status = 'OPEN'"), sqlite_where=text("status = 'OPEN'")),
        Index("ix_coverage_finding_patient_detected", "patient_id", "first_detected_at"),
    )
    id: Mapped[uuid.UUID] = uuid_pk()
    patient_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("patients.id", ondelete="CASCADE"), index=True)
    activity_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("care_activities.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(16))  # latest kind seen
    worst_kind: Mapped[str] = mapped_column(String(16))  # GAP > UNCONFIRMED > SINGLE_POINT while open
    status: Mapped[str] = mapped_column(String(12), default="OPEN", index=True)
    outcome: Mapped[str | None] = mapped_column(String(24), nullable=True)
    headline: Mapped[str] = mapped_column(String(500), default="")
    activity_start: Mapped[object] = mapped_column(DateTime(timezone=True))
    secure_by: Mapped[object] = mapped_column(DateTime(timezone=True))
    first_secure_by: Mapped[object] = mapped_column(DateTime(timezone=True))  # deadline when first flagged; measures use this
    first_detected_at: Mapped[object] = mapped_column(DateTime(timezone=True), default=now)
    last_seen_at: Mapped[object] = mapped_column(DateTime(timezone=True), default=now)
    resolved_at: Mapped[object | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Prescription(Base):
    """Medication data feed: a professional's prescription, expanded into one care activity per dose."""
    __tablename__ = "prescriptions"
    __table_args__ = (CheckConstraint("status IN ('ACTIVE','STOPPED')", name="ck_prescription_status"),)
    id: Mapped[uuid.UUID] = uuid_pk()
    patient_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("patients.id", ondelete="CASCADE"), index=True)
    medicine: Mapped[str] = mapped_column(String(160))
    dose: Mapped[str] = mapped_column(String(80))
    instructions: Mapped[str] = mapped_column(String(500), default="")
    times: Mapped[list] = mapped_column(JSON, default=list)  # local "HH:MM" due times each day
    start_date: Mapped[object] = mapped_column(Date)
    end_date: Mapped[object | None] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(String(12), default="ACTIVE", index=True)
    prescribed_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[object] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[object] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)
    stopped_at: Mapped[object | None] = mapped_column(DateTime(timezone=True), nullable=True)
    stop_reason: Mapped[str] = mapped_column(String(300), default="")
