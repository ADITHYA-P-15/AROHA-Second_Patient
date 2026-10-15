"""Hire requests: a primary contact asks a directory caretaker to join a care team. Additive and guarded."""
import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision = "0019_hire_requests"
down_revision = "0018_care_preferences"
branch_labels = None
depends_on = None


def upgrade():
    if "hire_requests" in inspect(op.get_bind()).get_table_names(): return
    op.create_table(
        "hire_requests",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("patient_id", sa.Uuid(), sa.ForeignKey("patients.id", ondelete="CASCADE"), nullable=False),
        sa.Column("caregiver_id", sa.Uuid(), sa.ForeignKey("caregivers.id", ondelete="CASCADE"), nullable=False),
        sa.Column("requested_by", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("intended_role", sa.String(8), nullable=False, server_default="BACKUP"),
        sa.Column("message", sa.String(300), nullable=False, server_default=""),
        sa.Column("status", sa.String(12), nullable=False, server_default="PENDING"),
        sa.Column("idempotency_key", sa.String(80), nullable=True),
        sa.Column("decline_reason", sa.String(300), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("responded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.CheckConstraint("status IN ('PENDING','ACCEPTED','DECLINED','WITHDRAWN','EXPIRED')", name="ck_hire_request_status"),
        sa.CheckConstraint("intended_role IN ('MAIN','BACKUP')", name="ck_hire_request_role"),
        sa.CheckConstraint("length(message) <= 300", name="ck_hire_request_message"),
        sa.UniqueConstraint("requested_by", "idempotency_key", name="uq_hire_request_idempotency"),
    )
    op.create_index("ix_hire_requests_patient_id", "hire_requests", ["patient_id"])
    op.create_index("ix_hire_requests_status", "hire_requests", ["status"])
    op.create_index("ix_hire_request_caregiver_status", "hire_requests", ["caregiver_id", "status"])
    op.create_index("uq_hire_request_open", "hire_requests", ["patient_id", "caregiver_id"], unique=True,
                    postgresql_where=sa.text("status = 'PENDING'"), sqlite_where=sa.text("status = 'PENDING'"))


def downgrade():
    if "hire_requests" in inspect(op.get_bind()).get_table_names(): op.drop_table("hire_requests")
