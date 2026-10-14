import enum
import uuid

from sqlalchemy import Boolean, CheckConstraint, DateTime, Enum, ForeignKey, Integer, JSON, String, Text, UniqueConstraint
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
    __table_args__ = (CheckConstraint("birth_year IS NULL OR (birth_year >= 1900 AND birth_year <= 2100)", name="ck_patients_birth_year"),)
    id: Mapped[uuid.UUID] = uuid_pk()
    name: Mapped[str] = mapped_column(String(160))
    birth_year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    care_notes: Mapped[str] = mapped_column(Text, default="")
    clinical_notes: Mapped[str] = mapped_column(Text, default="")
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
