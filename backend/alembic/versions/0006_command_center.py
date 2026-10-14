"""Command Center action items and daily briefs."""
from alembic import op
from sqlalchemy import inspect
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0006_command_center"
down_revision = "0005_escalation_timers"
branch_labels = None
depends_on = None

JSON = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")
UUID = sa.Uuid()


def upgrade():
    # The original 0001 migration uses current Base.metadata.create_all rather
    # than a frozen Phase 1 table list. A fresh install therefore already has
    # every current model table; a database that ran through 0005 before this
    # release does not. Keep both supported without editing committed history.
    if "action_items" in inspect(op.get_bind()).get_table_names():
        return
    op.create_table("action_items",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("patient_id", UUID, sa.ForeignKey("patients.id", ondelete="CASCADE"), nullable=False),
        sa.Column("dedupe_key", sa.String(180), nullable=False), sa.Column("kind", sa.String(48), nullable=False),
        sa.Column("source", sa.String(16), nullable=False), sa.Column("title", sa.String(200), nullable=False),
        sa.Column("reason", sa.String(500), nullable=False, server_default=""), sa.Column("reasons", JSON, nullable=False),
        sa.Column("severity", sa.String(12), nullable=False, server_default="MEDIUM"), sa.Column("related_activity_ids", JSON, nullable=False),
        sa.Column("related_incident_id", UUID, sa.ForeignKey("incidents.id", ondelete="SET NULL")),
        sa.Column("owner_user_id", UUID, sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("assigned_to_user_id", UUID, sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("due_at", sa.DateTime(timezone=True)), sa.Column("status", sa.String(20), nullable=False, server_default="OPEN"),
        sa.Column("snoozed_until", sa.DateTime(timezone=True)), sa.Column("suppressed_until", sa.DateTime(timezone=True)),
        sa.Column("resolution_note", sa.String(500)), sa.Column("resolution_reason", sa.String(32)),
        sa.Column("suggested_actions", JSON, nullable=False), sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False), sa.Column("resolved_at", sa.DateTime(timezone=True)),
        sa.Column("resolved_by", UUID, sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("reopened_count", sa.Integer(), nullable=False, server_default="0"), sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.CheckConstraint("source IN ('DERIVED','MANUAL','INCIDENT','HANDOVER')", name="ck_action_item_source"),
        sa.CheckConstraint("severity IN ('LOW','MEDIUM','HIGH','CRITICAL')", name="ck_action_item_severity"),
        sa.CheckConstraint("status IN ('OPEN','SNOOZED','DONE','AUTO_RESOLVED','DISMISSED')", name="ck_action_item_status"),
        sa.CheckConstraint("reopened_count >= 0 AND version >= 1", name="ck_action_item_counters"))
    op.create_index("ix_action_items_patient_id", "action_items", ["patient_id"])
    op.create_index("ix_action_items_due_at", "action_items", ["due_at"])
    op.create_index("ix_action_items_status", "action_items", ["status"])
    op.create_index("ix_action_item_patient_status", "action_items", ["patient_id", "status"])
    op.create_index("ix_action_item_assignee_status", "action_items", ["assigned_to_user_id", "status"])
    op.create_index("uq_action_item_active_dedupe", "action_items", ["patient_id", "dedupe_key"], unique=True, postgresql_where=sa.text("status IN ('OPEN','SNOOZED')"), sqlite_where=sa.text("status IN ('OPEN','SNOOZED')"))

    op.create_table("daily_briefs",
        sa.Column("id", UUID, primary_key=True), sa.Column("patient_id", UUID, sa.ForeignKey("patients.id", ondelete="CASCADE"), nullable=False),
        sa.Column("kind", sa.String(12), nullable=False), sa.Column("for_date", sa.DateTime(timezone=False), nullable=False),
        sa.Column("status", sa.String(12), nullable=False, server_default="DRAFT"), sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("generated_by", UUID, sa.ForeignKey("users.id", ondelete="SET NULL")), sa.Column("auto_generated", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("content", JSON, nullable=False), sa.Column("rendered_text", sa.Text(), nullable=False, server_default=""), sa.Column("rendered_html", sa.Text(), nullable=False, server_default=""),
        sa.Column("author_user_id", UUID, sa.ForeignKey("users.id", ondelete="SET NULL")), sa.Column("from_user_id", UUID, sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("to_user_id", UUID, sa.ForeignKey("users.id", ondelete="SET NULL")), sa.Column("ai_enhanced", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.CheckConstraint("kind IN ('MORNING','HANDOVER')", name="ck_daily_brief_kind"), sa.CheckConstraint("status IN ('DRAFT','PUBLISHED')", name="ck_daily_brief_status"))
    op.create_index("ix_daily_briefs_patient_id", "daily_briefs", ["patient_id"])
    op.create_index("ix_daily_brief_patient_date", "daily_briefs", ["patient_id", "for_date"])
    op.create_index("uq_daily_brief_published", "daily_briefs", ["patient_id", "kind", "for_date"], unique=True, postgresql_where=sa.text("status = 'PUBLISHED'"), sqlite_where=sa.text("status = 'PUBLISHED'"))

    op.create_table("brief_acknowledgements", sa.Column("id", UUID, primary_key=True), sa.Column("brief_id", UUID, sa.ForeignKey("daily_briefs.id", ondelete="CASCADE"), nullable=False), sa.Column("user_id", UUID, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False), sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=False), sa.Column("note", sa.String(500)), sa.UniqueConstraint("brief_id", "user_id", name="uq_brief_ack_user"))
    op.create_index("ix_brief_acknowledgements_brief_id", "brief_acknowledgements", ["brief_id"])
    op.create_index("ix_brief_acknowledgements_user_id", "brief_acknowledgements", ["user_id"])

    op.create_table("handover_items", sa.Column("id", UUID, primary_key=True), sa.Column("brief_id", UUID, sa.ForeignKey("daily_briefs.id", ondelete="CASCADE"), nullable=False), sa.Column("activity_id", UUID, sa.ForeignKey("care_activities.id", ondelete="SET NULL")), sa.Column("action_item_id", UUID, sa.ForeignKey("action_items.id", ondelete="SET NULL")), sa.Column("disposition", sa.String(16), nullable=False, server_default="CARRY_OVER"), sa.Column("note", sa.String(500)), sa.CheckConstraint("disposition IN ('DONE','CARRY_OVER','DROPPED','FYI')", name="ck_handover_item_disposition"))
    op.create_index("ix_handover_items_brief_id", "handover_items", ["brief_id"])

    op.create_table("command_center_settings", sa.Column("patient_id", UUID, sa.ForeignKey("patients.id", ondelete="CASCADE"), primary_key=True), sa.Column("morning_brief_time", sa.String(5), nullable=False, server_default="07:00"), sa.Column("handover_time", sa.String(5), nullable=False, server_default="19:30"), sa.Column("handover_autopublish_after_min", sa.Integer(), nullable=False, server_default="60"), sa.Column("daypart_boundaries", JSON, nullable=False), sa.Column("routine_rules", JSON, nullable=False), sa.Column("snooze_max_minutes_by_severity", JSON, nullable=False), sa.Column("suppress_hours", sa.Integer(), nullable=False, server_default="12"), sa.Column("updated_by", UUID, sa.ForeignKey("users.id", ondelete="SET NULL")), sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False), sa.CheckConstraint("handover_autopublish_after_min BETWEEN 5 AND 1440", name="ck_cc_autopublish_minutes"), sa.CheckConstraint("suppress_hours BETWEEN 1 AND 168", name="ck_cc_suppress_hours"))


def downgrade():
    op.drop_table("command_center_settings")
    op.drop_index("ix_handover_items_brief_id", table_name="handover_items")
    op.drop_table("handover_items")
    op.drop_index("ix_brief_acknowledgements_user_id", table_name="brief_acknowledgements")
    op.drop_index("ix_brief_acknowledgements_brief_id", table_name="brief_acknowledgements")
    op.drop_table("brief_acknowledgements")
    op.drop_index("uq_daily_brief_published", table_name="daily_briefs")
    op.drop_index("ix_daily_brief_patient_date", table_name="daily_briefs")
    op.drop_index("ix_daily_briefs_patient_id", table_name="daily_briefs")
    op.drop_table("daily_briefs")
    op.drop_index("uq_action_item_active_dedupe", table_name="action_items")
    op.drop_index("ix_action_item_assignee_status", table_name="action_items")
    op.drop_index("ix_action_item_patient_status", table_name="action_items")
    op.drop_index("ix_action_items_status", table_name="action_items")
    op.drop_index("ix_action_items_due_at", table_name="action_items")
    op.drop_index("ix_action_items_patient_id", table_name="action_items")
    op.drop_table("action_items")
