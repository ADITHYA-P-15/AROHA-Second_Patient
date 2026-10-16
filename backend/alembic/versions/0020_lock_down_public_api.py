"""Block Supabase's public API roles from reading application tables.

Supabase's anon key is public by design. The application uses its backend
database connection for all data access, so the PostgREST anon/authenticated
roles do not need direct table privileges.
"""
from alembic import op
from sqlalchemy import text

revision = "0020_lock_down_public_api"
down_revision = "0019_hire_requests"
branch_labels = None
depends_on = None


APP_TABLES = (
    "users",
    "patients",
    "care_team_members",
    "activity_history",
    "patient_support_needs",
    "caregivers",
    "caregiver_patient_links",
    "caregiver_weekly_schedule",
    "availability_overrides",
    "care_activities",
    "activity_dependencies",
    "care_assignments",
    "patient_messages",
    "incidents",
    "incident_events",
    "notifications",
    "escalation_policies",
    "app_settings",
    "action_items",
    "command_center_settings",
    "cover_requests",
    "cover_request_events",
    "coverage_findings",
    "prescriptions",
    "voice_notes",
    "wellbeing_check_ins",
    "task_check_ins",
    "sectors",
    "sector_states",
    "agencies",
    "caretaker_profiles",
    "agency_ratings",
    "doctor_ratings",
    "reviews",
    "review_reports",
    "reputation_snapshots",
    "patient_care_preferences",
    "hire_requests",
)


def upgrade():
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    # CodeBlue authenticates through FastAPI and connects as the database
    # owner. Its public PostgREST roles must not read or write these tables.
    public_roles = [role for role in ("anon", "authenticated") if bind.scalar(text("SELECT to_regrole(:role) IS NOT NULL"), {"role": role})]
    for table in APP_TABLES:
        qualified = f'public."{table}"'
        op.execute(f"ALTER TABLE {qualified} ENABLE ROW LEVEL SECURITY")
        op.execute(f"REVOKE ALL ON TABLE {qualified} FROM PUBLIC")
        for role in public_roles:
            op.execute(f"REVOKE ALL ON TABLE {qualified} FROM {role}")

    for role in [*public_roles, "PUBLIC"]:
        op.execute(f"ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ON TABLES FROM {role}")
        op.execute(f"ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ON SEQUENCES FROM {role}")


def downgrade():
    # Do not restore public API access as a side effect of rolling back code.
    pass
