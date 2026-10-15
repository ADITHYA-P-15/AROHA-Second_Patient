"""Task check-ins: a caretaker confirms they are at a task; a missing check-in can open a NO_CHECKIN cover request. Additive and guarded."""
import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision = "0015_task_check_ins"
down_revision = "0014_wellbeing_check_ins"
branch_labels = None
depends_on = None

OLD_REASONS = "reason IN ('DECLINED','ABSENCE','MANUAL','UNASSIGNED')"
NEW_REASONS = "reason IN ('DECLINED','ABSENCE','MANUAL','UNASSIGNED','NO_CHECKIN')"


def _reason_check(bind) -> str:
    for ck in inspect(bind).get_check_constraints("cover_requests"):
        if ck.get("name") == "ck_cover_request_reason": return ck.get("sqltext") or ""
    return ""


def _set_reasons(rule: str):
    with op.batch_alter_table("cover_requests", recreate="auto") as batch:
        if _reason_check(op.get_bind()): batch.drop_constraint("ck_cover_request_reason", type_="check")
        batch.create_check_constraint("ck_cover_request_reason", rule)


def upgrade():
    bind = op.get_bind()
    if "task_check_ins" not in inspect(bind).get_table_names():
        op.create_table(
            "task_check_ins",
            sa.Column("id", sa.Uuid(), primary_key=True),
            sa.Column("activity_id", sa.Uuid(), sa.ForeignKey("care_activities.id", ondelete="CASCADE"), nullable=False),
            sa.Column("caregiver_id", sa.Uuid(), sa.ForeignKey("caregivers.id", ondelete="CASCADE"), nullable=False),
            sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
            sa.Column("checked_in_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("status", sa.String(8), nullable=False),
            sa.Column("minutes_late", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("is_synthetic", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint("activity_id", name="uq_task_check_in_activity"),
            sa.CheckConstraint("status IN ('ON_TIME','LATE')", name="ck_task_check_in_status"),
        )
        op.create_index("ix_task_check_in_caregiver_at", "task_check_ins", ["caregiver_id", "checked_in_at"])
    if "NO_CHECKIN" not in _reason_check(bind):
        _set_reasons(NEW_REASONS)


def downgrade():
    bind = op.get_bind()
    if "NO_CHECKIN" in _reason_check(bind):
        op.execute("UPDATE cover_requests SET reason = 'MANUAL' WHERE reason = 'NO_CHECKIN'")
        _set_reasons(OLD_REASONS)
    if "task_check_ins" in inspect(bind).get_table_names():
        op.drop_table("task_check_ins")
