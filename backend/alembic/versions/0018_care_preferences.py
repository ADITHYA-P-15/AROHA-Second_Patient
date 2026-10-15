"""Patient care preferences for building a care team and ranking backups. Additive and guarded."""
import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision = "0018_care_preferences"
down_revision = "0017_reputation"
branch_labels = None
depends_on = None


def upgrade():
    if "patient_care_preferences" in inspect(op.get_bind()).get_table_names(): return
    op.create_table(
        "patient_care_preferences",
        sa.Column("patient_id", sa.Uuid(), sa.ForeignKey("patients.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("gender", sa.String(16), nullable=True),
        sa.Column("gender_mode", sa.String(4), nullable=False, server_default="SOFT"),
        sa.Column("languages", sa.JSON(), nullable=False),
        sa.Column("city", sa.String(80), nullable=False, server_default=""),
        sa.Column("sector_code", sa.String(8), nullable=True),
        sa.Column("min_rating", sa.Float(), nullable=True),
        sa.Column("capabilities", sa.JSON(), nullable=False),
        sa.Column("updated_by", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("gender IS NULL OR gender IN ('FEMALE','MALE','NON_BINARY')", name="ck_care_pref_gender"),
        sa.CheckConstraint("gender_mode IN ('HARD','SOFT')", name="ck_care_pref_gender_mode"),
        sa.CheckConstraint("min_rating IS NULL OR (min_rating >= 0 AND min_rating <= 100)", name="ck_care_pref_min_rating"),
    )


def downgrade():
    if "patient_care_preferences" in inspect(op.get_bind()).get_table_names(): op.drop_table("patient_care_preferences")
