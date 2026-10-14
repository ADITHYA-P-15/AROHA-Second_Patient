"""Predictive Coverage Planner findings log."""
from alembic import op
from sqlalchemy import inspect
import sqlalchemy as sa

revision = "0008_coverage_planner"
down_revision = "0007_backup_matcher"
branch_labels = None
depends_on = None

UUID = sa.Uuid()
OPEN = sa.text("status = 'OPEN'")


def upgrade():
    # Fresh installs create current model tables in 0001 (see 0006); only upgrade older databases here.
    if "coverage_findings" in inspect(op.get_bind()).get_table_names():
        return
    op.create_table("coverage_findings",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("patient_id", UUID, sa.ForeignKey("patients.id", ondelete="CASCADE"), nullable=False),
        sa.Column("activity_id", UUID, sa.ForeignKey("care_activities.id", ondelete="CASCADE"), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False), sa.Column("worst_kind", sa.String(16), nullable=False), sa.Column("status", sa.String(12), nullable=False, server_default="OPEN"),
        sa.Column("outcome", sa.String(24)), sa.Column("headline", sa.String(500), nullable=False, server_default=""),
        sa.Column("activity_start", sa.DateTime(timezone=True), nullable=False), sa.Column("secure_by", sa.DateTime(timezone=True), nullable=False),
        sa.Column("first_secure_by", sa.DateTime(timezone=True), nullable=False),
        sa.Column("first_detected_at", sa.DateTime(timezone=True), nullable=False), sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("kind IN ('GAP','UNCONFIRMED','SINGLE_POINT')", name="ck_coverage_finding_kind"),
        sa.CheckConstraint("status IN ('OPEN','RESOLVED','MISSED','CLOSED')", name="ck_coverage_finding_status"),
        sa.CheckConstraint("outcome IS NULL OR outcome IN ('BEFORE_DEADLINE','AFTER_DEADLINE','STARTED_UNCOVERED','NO_BACKUP_SECURED','TASK_CLOSED','OUT_OF_SCOPE')", name="ck_coverage_finding_outcome"),
        sa.CheckConstraint("worst_kind IN ('GAP','UNCONFIRMED','SINGLE_POINT')", name="ck_coverage_finding_worst_kind"))
    op.create_index("ix_coverage_findings_patient_id", "coverage_findings", ["patient_id"])
    op.create_index("ix_coverage_findings_activity_id", "coverage_findings", ["activity_id"])
    op.create_index("ix_coverage_findings_status", "coverage_findings", ["status"])
    op.create_index("ix_coverage_finding_patient_detected", "coverage_findings", ["patient_id", "first_detected_at"])
    op.create_index("uq_open_coverage_finding", "coverage_findings", ["activity_id"], unique=True, postgresql_where=OPEN, sqlite_where=OPEN)


def downgrade():
    op.drop_index("uq_open_coverage_finding", table_name="coverage_findings")
    op.drop_table("coverage_findings")
