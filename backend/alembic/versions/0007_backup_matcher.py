"""Backup Matcher cover requests and their event trail."""
from alembic import op
from sqlalchemy import inspect
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0007_backup_matcher"
down_revision = "0006_command_center"
branch_labels = None
depends_on = None

JSON = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")
UUID = sa.Uuid()
OPEN = sa.text("status IN ('OPEN','OFFERED')")


def upgrade():
    # Fresh installs create current model tables in 0001 (see 0006); only upgrade older databases here.
    if "cover_requests" in inspect(op.get_bind()).get_table_names():
        return
    op.create_table("cover_requests",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("patient_id", UUID, sa.ForeignKey("patients.id", ondelete="CASCADE"), nullable=False),
        sa.Column("activity_id", UUID, sa.ForeignKey("care_activities.id", ondelete="CASCADE"), nullable=False),
        sa.Column("reason", sa.String(16), nullable=False), sa.Column("reason_note", sa.String(300), nullable=False, server_default=""),
        sa.Column("trigger_key", sa.String(120)),
        sa.Column("replaced_caregiver_id", UUID, sa.ForeignKey("caregivers.id", ondelete="SET NULL")),
        sa.Column("status", sa.String(16), nullable=False, server_default="OPEN"), sa.Column("resolution", sa.String(16)),
        sa.Column("offered_caregiver_id", UUID, sa.ForeignKey("caregivers.id", ondelete="SET NULL")),
        sa.Column("offered_at", sa.DateTime(timezone=True)), sa.Column("auto_advance", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("declined_caregiver_ids", JSON, nullable=False),
        sa.Column("covered_by_caregiver_id", UUID, sa.ForeignKey("caregivers.id", ondelete="SET NULL")),
        sa.Column("covered_assignment_id", UUID, sa.ForeignKey("care_assignments.id", ondelete="SET NULL")),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=False), sa.Column("closed_at", sa.DateTime(timezone=True)),
        sa.Column("opened_by", UUID, sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.CheckConstraint("reason IN ('DECLINED','ABSENCE','MANUAL')", name="ck_cover_request_reason"),
        sa.CheckConstraint("status IN ('OPEN','OFFERED','COVERED','CANCELLED','EXPIRED')", name="ck_cover_request_status"),
        sa.CheckConstraint("resolution IS NULL OR resolution IN ('MATCHER','MANUAL')", name="ck_cover_request_resolution"))
    op.create_index("ix_cover_requests_patient_id", "cover_requests", ["patient_id"])
    op.create_index("ix_cover_requests_activity_id", "cover_requests", ["activity_id"])
    op.create_index("ix_cover_requests_status", "cover_requests", ["status"])
    op.create_index("ix_cover_requests_trigger_key", "cover_requests", ["trigger_key"])
    op.create_index("ix_cover_request_patient_status", "cover_requests", ["patient_id", "status"])
    op.create_index("uq_open_cover_request_activity", "cover_requests", ["activity_id"], unique=True, postgresql_where=OPEN, sqlite_where=OPEN)
    op.create_table("cover_request_events",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("request_id", UUID, sa.ForeignKey("cover_requests.id", ondelete="CASCADE"), nullable=False),
        sa.Column("kind", sa.String(20), nullable=False), sa.Column("caregiver_id", UUID, sa.ForeignKey("caregivers.id", ondelete="SET NULL")),
        sa.Column("actor_user_id", UUID, sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("note", sa.String(300), nullable=False, server_default=""), sa.Column("at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("kind IN ('OPENED','OFFERED','OFFER_DECLINED','AUTO_ADVANCED','ACCEPTED','COVERED','CANCELLED','EXPIRED','NO_CANDIDATES')", name="ck_cover_event_kind"))
    op.create_index("ix_cover_request_events_request_id", "cover_request_events", ["request_id"])


def downgrade():
    op.drop_table("cover_request_events")
    op.drop_index("uq_open_cover_request_activity", table_name="cover_requests")
    op.drop_table("cover_requests")
