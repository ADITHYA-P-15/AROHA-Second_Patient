"""Core care coordination domain."""
from alembic import op
import sqlalchemy as sa
from app.models import Base

revision = "0003_phase2_core_domain"
down_revision = "0002_synthetic_users"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    existing = set(sa.inspect(bind).get_table_names())
    for name in ("patients",):
        cols = {c["name"] for c in sa.inspect(bind).get_columns(name)}
        if name == "patients":
            if "mobility_level" not in cols:
                op.add_column(name, sa.Column("mobility_level", sa.String(20), nullable=False, server_default="INDEPENDENT"))
            if "language_pref" not in cols:
                op.add_column(name, sa.Column("language_pref", sa.String(8), nullable=False, server_default="en"))
            if "continuity_status" not in cols:
                op.add_column(name, sa.Column("continuity_status", sa.String(24), nullable=False, server_default="UNKNOWN"))
            checks = {c.get("name") for c in sa.inspect(bind).get_check_constraints(name)}
            if "ck_patients_mobility" not in checks:
                with op.batch_alter_table(name) as batch:
                    batch.create_check_constraint("ck_patients_mobility", "mobility_level IN ('INDEPENDENT','NEEDS_AID','WHEELCHAIR','BEDBOUND')")
    for table in Base.metadata.sorted_tables:
        if table.name not in existing and table.name not in {"users", "patients", "care_team_members", "activity_history"}:
            table.create(bind, checkfirst=True)


def downgrade():
    bind = op.get_bind()
    for name in reversed(["care_assignments", "activity_dependencies", "care_activities", "availability_overrides", "caregiver_weekly_schedule", "caregiver_patient_links", "caregivers", "patient_support_needs"]):
        if sa.inspect(bind).has_table(name):
            Base.metadata.tables[name].drop(bind, checkfirst=True)
    cols = {c["name"] for c in sa.inspect(bind).get_columns("patients")}
    with op.batch_alter_table("patients") as batch:
        for name in ("continuity_status", "language_pref", "mobility_level"):
            if name in cols:
                batch.drop_column(name)
