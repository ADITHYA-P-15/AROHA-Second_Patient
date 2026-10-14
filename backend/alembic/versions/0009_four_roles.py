"""Four roles (patient, primary contact, caretaker, healthcare professional) and CareCircle IDs.

Maps existing data: FAMILY -> PRIMARY_CONTACT, HOUSEHELP -> CARETAKER, NURSE/DOCTOR -> PROFESSIONAL.
Administrator accounts are deactivated, and the morning-brief / handover tables are dropped. Care profiles without an account, or belonging to a professional,
are deactivated: they stay in history, but are never offered work again.
"""
import secrets

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision = "0009_four_roles"
down_revision = "0008_coverage_planner"
branch_labels = None
depends_on = None

ALPHABET = "23456789ABCDEFGHJKMNPQRSTUVWXYZ"
USER_ROLES = {"FAMILY": "PRIMARY_CONTACT", "HOUSEHELP": "CARETAKER", "NURSE": "PROFESSIONAL", "DOCTOR": "PROFESSIONAL"}
TEAM_ROLES = {"COORDINATOR": "PRIMARY_CONTACT", "FAMILY": "PRIMARY_CONTACT", "HOUSEHELP": "CARETAKER", "NURSE": "PROFESSIONAL", "DOCTOR": "PROFESSIONAL"}


def upgrade():
    bind = op.get_bind()
    postgres = bind.dialect.name == "postgresql"
    if postgres:
        # Non-native enums were created as VARCHAR(len(longest old value)); the new values are longer.
        op.alter_column("users", "role", type_=sa.String(24), existing_nullable=False)
        op.alter_column("care_team_members", "team_role", type_=sa.String(24), existing_nullable=False)
    for old, new in USER_ROLES.items():
        bind.execute(sa.text("UPDATE users SET role = :new WHERE role = :old"), {"old": old, "new": new})
    bind.execute(sa.text("UPDATE users SET role = 'PRIMARY_CONTACT', is_active = :off, token_version = token_version + 1 WHERE role = 'ADMIN'"), {"off": False})
    for old, new in TEAM_ROLES.items():
        bind.execute(sa.text("UPDATE care_team_members SET team_role = :new WHERE team_role = :old"), {"old": old, "new": new})

    # SQLite rebuilds the table in batch mode; carry over its unnamed CHECKs so the rebuild keeps them.
    keep = (sa.CheckConstraint("max_activities_per_day >= 0"), sa.CheckConstraint("max_hours_per_week >= 0"))
    with op.batch_alter_table("caregivers", table_args=keep) as batch:
        batch.drop_constraint("ck_caregiver_kind", type_="check")
    bind.execute(sa.text("UPDATE caregivers SET kind = 'PRIMARY_CONTACT' WHERE kind = 'FAMILY'"))
    bind.execute(sa.text("UPDATE caregivers SET kind = 'CARETAKER' WHERE kind <> 'PRIMARY_CONTACT'"))
    bind.execute(sa.text("UPDATE caregivers SET is_active = :off WHERE user_id IS NULL OR user_id IN (SELECT id FROM users WHERE role IN ('PROFESSIONAL', 'PATIENT'))"), {"off": False})
    # Work held by a profile that can no longer be offered work is released, so the cover flow can reassign it.
    bind.execute(sa.text("UPDATE care_assignments SET status = 'CANCELLED' WHERE status IN ('PROPOSED','AWAITING_CONFIRMATION','CONFIRMED') "
                         "AND caregiver_id IN (SELECT id FROM caregivers WHERE is_active = :off) "
                         "AND activity_id IN (SELECT id FROM care_activities WHERE lifecycle_status = 'SCHEDULED')"), {"off": False})
    # Clinical visits are the hospital's work now; what remains for caretakers is escorting the patient.
    activities = sa.table("care_activities", sa.column("id", sa.Uuid()), sa.column("required_support", sa.JSON()), sa.column("lifecycle_status", sa.String()))
    for row in bind.execute(sa.select(activities.c.id, activities.c.required_support).where(activities.c.lifecycle_status == "SCHEDULED")).fetchall():
        support = list(row.required_support or [])
        if "CLINICAL_VISIT" in support:
            converted = sorted({"APPOINTMENT_ESCORT" if code == "CLINICAL_VISIT" else code for code in support})
            bind.execute(activities.update().where(activities.c.id == row.id).values(required_support=converted))

    with op.batch_alter_table("caregivers", table_args=keep) as batch:
        batch.create_check_constraint("ck_caregiver_kind", "kind IN ('CARETAKER','PRIMARY_CONTACT')")

    columns = {c["name"] for c in inspect(bind).get_columns("patients")}
    if "care_code" not in columns:
        op.add_column("patients", sa.Column("care_code", sa.String(12), nullable=True))
    used = {row[0] for row in bind.execute(sa.text("SELECT care_code FROM patients WHERE care_code IS NOT NULL"))}
    for (patient_id,) in bind.execute(sa.text("SELECT id FROM patients WHERE care_code IS NULL")).fetchall():
        code = None
        while code is None or code in used:
            code = "CC-" + "".join(secrets.choice(ALPHABET) for _ in range(6))
        used.add(code)
        bind.execute(sa.text("UPDATE patients SET care_code = :code WHERE id = :id"), {"code": code, "id": patient_id})
    if "ix_patients_care_code" not in {i["name"] for i in inspect(bind).get_indexes("patients")}:
        op.create_index("ix_patients_care_code", "patients", ["care_code"], unique=True)

    # Morning briefs and handovers are no longer part of the product.
    tables = set(inspect(bind).get_table_names())
    for table in ("handover_items", "brief_acknowledgements", "daily_briefs"):
        if table in tables:
            op.drop_table(table)


def downgrade():
    raise NotImplementedError("Role consolidation is one-way; restore from a backup to go back.")
