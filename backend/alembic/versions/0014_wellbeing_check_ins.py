"""Optional wellbeing check-ins (pain, mood, note) that the progress report can quote."""
import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision = "0014_wellbeing_check_ins"
down_revision = "0013_notification_links"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    if "wellbeing_check_ins" in inspect(bind).get_table_names():
        return
    op.create_table(
        "wellbeing_check_ins",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("patient_id", sa.Uuid(), sa.ForeignKey("patients.id", ondelete="CASCADE"), nullable=False),
        sa.Column("recorded_by", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("pain", sa.Integer(), nullable=True),
        sa.Column("mood", sa.Integer(), nullable=True),
        sa.Column("note", sa.String(300), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("pain IS NULL OR (pain >= 0 AND pain <= 10)", name="ck_checkin_pain"),
        sa.CheckConstraint("mood IS NULL OR (mood >= 1 AND mood <= 5)", name="ck_checkin_mood"),
    )
    op.create_index("ix_wellbeing_check_ins_patient_id", "wellbeing_check_ins", ["patient_id"])
    op.create_index("ix_wellbeing_check_ins_created_at", "wellbeing_check_ins", ["created_at"])


def downgrade():
    op.drop_table("wellbeing_check_ins")
