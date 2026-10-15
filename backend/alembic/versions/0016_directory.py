"""Caretaker directory: sectors, the state -> sector map, agencies and caretaker profiles. Additive and guarded."""
import json
import uuid
from pathlib import Path

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision = "0016_directory"
down_revision = "0014_wellbeing_check_ins"
branch_labels = None
depends_on = None

CONFIG = Path(__file__).resolve().parents[2] / "app" / "seed" / "sector_states.json"


def upgrade():
    bind = op.get_bind()
    tables = set(inspect(bind).get_table_names())
    if "sectors" not in tables:
        op.create_table(
            "sectors",
            sa.Column("id", sa.Uuid(), primary_key=True),
            sa.Column("code", sa.String(8), nullable=False, unique=True),
            sa.Column("name", sa.String(60), nullable=False),
            sa.CheckConstraint("code IN ('NORTH','SOUTH','EAST','WEST')", name="ck_sector_code"),
        )
    if "sector_states" not in tables:
        op.create_table(
            "sector_states",
            sa.Column("state", sa.String(60), primary_key=True),
            sa.Column("sector_id", sa.Uuid(), sa.ForeignKey("sectors.id", ondelete="CASCADE"), nullable=False),
        )
        op.create_index("ix_sector_states_sector_id", "sector_states", ["sector_id"])
    if "agencies" not in tables:
        op.create_table(
            "agencies",
            sa.Column("id", sa.Uuid(), primary_key=True),
            sa.Column("name", sa.String(160), nullable=False),
            sa.Column("sector_id", sa.Uuid(), sa.ForeignKey("sectors.id"), nullable=False),
            sa.Column("city", sa.String(80), nullable=False, server_default=""),
            sa.Column("is_synthetic", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.UniqueConstraint("name", "city", name="uq_agency_name_city"),
        )
        op.create_index("ix_agencies_sector_id", "agencies", ["sector_id"])
        op.create_index("ix_agencies_is_active", "agencies", ["is_active"])
    if "caretaker_profiles" not in tables:
        op.create_table(
            "caretaker_profiles",
            sa.Column("id", sa.Uuid(), primary_key=True),
            sa.Column("caregiver_id", sa.Uuid(), sa.ForeignKey("caregivers.id", ondelete="CASCADE"), nullable=False, unique=True),
            sa.Column("agency_id", sa.Uuid(), sa.ForeignKey("agencies.id", ondelete="SET NULL"), nullable=True),
            sa.Column("gender", sa.String(16), nullable=False, server_default="UNDISCLOSED"),
            sa.Column("origin_state", sa.String(60), nullable=False, server_default=""),
            sa.Column("origin_city", sa.String(80), nullable=False, server_default=""),
            sa.Column("current_state", sa.String(60), nullable=False, server_default=""),
            sa.Column("current_city", sa.String(80), nullable=False, server_default=""),
            sa.Column("current_district", sa.String(80), nullable=False, server_default=""),
            sa.Column("sector_id", sa.Uuid(), sa.ForeignKey("sectors.id", ondelete="SET NULL"), nullable=True),
            sa.Column("languages", sa.JSON(), nullable=False),
            sa.Column("years_experience", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("bio", sa.String(500), nullable=False, server_default=""),
            sa.Column("listed", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("is_synthetic", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.CheckConstraint("gender IN ('FEMALE','MALE','NON_BINARY','UNDISCLOSED')", name="ck_caretaker_profile_gender"),
            sa.CheckConstraint("years_experience >= 0 AND years_experience <= 60", name="ck_caretaker_profile_experience"),
            sa.CheckConstraint("length(bio) <= 500", name="ck_caretaker_profile_bio"),
        )
        for column in ("agency_id", "current_city", "sector_id", "listed"):
            op.create_index(f"ix_caretaker_profiles_{column}", "caretaker_profiles", [column])
    _seed_reference(bind)


def _seed_reference(bind):
    """The four sectors and the state map are reference configuration, so every database gets them, demo or not."""
    config = json.loads(CONFIG.read_text(encoding="utf-8"))
    sectors = sa.table("sectors", sa.column("id", sa.Uuid()), sa.column("code", sa.String), sa.column("name", sa.String))
    states = sa.table("sector_states", sa.column("state", sa.String), sa.column("sector_id", sa.Uuid()))
    existing = {code: sid for sid, code in bind.execute(sa.select(sectors.c.id, sectors.c.code))}
    for row in config["sectors"]:
        if row["code"] not in existing:
            existing[row["code"]] = uuid.uuid4()
            bind.execute(sectors.insert().values(id=existing[row["code"]], code=row["code"], name=row["name"]))
    mapped = {s for (s,) in bind.execute(sa.select(states.c.state))}
    for state, code in config["states"].items():
        if state not in mapped:
            bind.execute(states.insert().values(state=state, sector_id=existing[code]))


def downgrade():
    tables = set(inspect(op.get_bind()).get_table_names())
    for table in ("caretaker_profiles", "agencies", "sector_states", "sectors"):
        if table in tables: op.drop_table(table)
