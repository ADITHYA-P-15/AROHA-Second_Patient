"""Medication and appointment data feeds, care-activity status (pending / completed / missed), main caretaker."""
import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision = "0010_care_feeds"
down_revision = "0009_four_roles"
branch_labels = None
depends_on = None

UUID = sa.Uuid()


def _columns(bind, table):
    return {c["name"] for c in inspect(bind).get_columns(table)}


def upgrade():
    bind = op.get_bind()
    tables = set(inspect(bind).get_table_names())
    if "prescriptions" not in tables:
        op.create_table("prescriptions",
            sa.Column("id", UUID, primary_key=True),
            sa.Column("patient_id", UUID, sa.ForeignKey("patients.id", ondelete="CASCADE"), nullable=False),
            sa.Column("medicine", sa.String(160), nullable=False), sa.Column("dose", sa.String(80), nullable=False),
            sa.Column("instructions", sa.String(500), nullable=False, server_default=""), sa.Column("times", sa.JSON(), nullable=False),
            sa.Column("start_date", sa.Date(), nullable=False), sa.Column("end_date", sa.Date()),
            sa.Column("status", sa.String(12), nullable=False, server_default="ACTIVE"),
            sa.Column("prescribed_by", UUID, sa.ForeignKey("users.id"), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False), sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("stopped_at", sa.DateTime(timezone=True)), sa.Column("stop_reason", sa.String(300), nullable=False, server_default=""),
            sa.CheckConstraint("status IN ('ACTIVE','STOPPED')", name="ck_prescription_status"))
        op.create_index("ix_prescriptions_patient_id", "prescriptions", ["patient_id"])
        op.create_index("ix_prescriptions_status", "prescriptions", ["status"])

    activity_columns = _columns(bind, "care_activities")
    keep = (sa.CheckConstraint("scheduled_end > scheduled_start"), sa.CheckConstraint("deadline IS NULL OR deadline >= scheduled_start"),
            sa.CheckConstraint("buffer_before_min >= 0 AND buffer_after_min >= 0"))
    with op.batch_alter_table("care_activities", table_args=keep) as batch:
        if "source" not in activity_columns:
            batch.add_column(sa.Column("source", sa.String(16), nullable=False, server_default="MANUAL"))
            batch.add_column(sa.Column("source_id", UUID))
            batch.add_column(sa.Column("completed_at", sa.DateTime(timezone=True)))
            batch.add_column(sa.Column("completed_by", UUID, sa.ForeignKey("users.id", name="fk_care_activities_completed_by")))
            batch.add_column(sa.Column("completed_late", sa.Boolean(), nullable=False, server_default=sa.false()))
            batch.add_column(sa.Column("missed_at", sa.DateTime(timezone=True)))
        batch.drop_constraint("ck_activity_lifecycle", type_="check")
        batch.create_check_constraint("ck_activity_lifecycle", "lifecycle_status IN ('SCHEDULED','COMPLETED','MISSED','CANCELLED')")
        if "source" not in activity_columns:
            batch.create_check_constraint("ck_activity_source", "source IN ('MANUAL','PRESCRIPTION','APPOINTMENT')")
    indexes = {i["name"] for i in inspect(bind).get_indexes("care_activities")}
    if "ix_care_activities_source" not in indexes: op.create_index("ix_care_activities_source", "care_activities", ["source"])
    if "ix_care_activities_source_id" not in indexes: op.create_index("ix_care_activities_source_id", "care_activities", ["source_id"])
    # Existing appointments become the appointment feed's.
    bind.execute(sa.text("UPDATE care_activities SET source = 'APPOINTMENT' WHERE category = 'APPOINTMENT' AND source = 'MANUAL'"))

    with op.batch_alter_table("cover_requests") as batch:
        batch.drop_constraint("ck_cover_request_reason", type_="check")
        batch.create_check_constraint("ck_cover_request_reason", "reason IN ('DECLINED','ABSENCE','MANUAL','UNASSIGNED')")

    if "is_main_caretaker" not in _columns(bind, "caregiver_patient_links"):
        op.add_column("caregiver_patient_links", sa.Column("is_main_caretaker", sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade():
    op.drop_column("caregiver_patient_links", "is_main_caretaker")
    op.drop_table("prescriptions")
