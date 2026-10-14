"""Persist escalation deadlines, policy, app settings, and task acknowledgements."""
from alembic import op
import sqlalchemy as sa
from app.models import Base

revision = "0005_escalation_timers"
down_revision = "0004_escalation_messages"
branch_labels = None
depends_on = None


def _add_if_missing(table, column):
    columns = {item["name"] for item in sa.inspect(op.get_bind()).get_columns(table)}
    if column.name not in columns:
        with op.batch_alter_table(table) as batch:
            batch.add_column(column)


def upgrade():
    _add_if_missing("care_activities", sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True))
    _add_if_missing("care_activities", sa.Column("acknowledged_by", sa.Uuid(), sa.ForeignKey("users.id"), nullable=True))
    _add_if_missing("incidents", sa.Column("current_deadline_at", sa.DateTime(timezone=True), nullable=True))
    _add_if_missing("incidents", sa.Column("deadline_kind", sa.String(8), nullable=True))
    _add_if_missing("incidents", sa.Column("repeat_count", sa.Integer(), nullable=False, server_default="1"))
    _add_if_missing("incidents", sa.Column("emergency_unacknowledged", sa.Boolean(), nullable=False, server_default=sa.false()))
    _add_if_missing("incidents", sa.Column("importance", sa.String(16), nullable=False, server_default="MEDIUM"))
    _add_if_missing("incidents", sa.Column("related_activity_id", sa.Uuid(), sa.ForeignKey("care_activities.id", ondelete="SET NULL"), nullable=True))
    _add_if_missing("notifications", sa.Column("channel", sa.String(12), nullable=False, server_default="ALERT"))
    inspector = sa.inspect(op.get_bind())
    unique_names = {constraint.get("name") for constraint in inspector.get_unique_constraints("incidents")}
    if "uq_incident_patient_dedupe" not in unique_names:
        with op.batch_alter_table("incidents") as batch:
            batch.create_unique_constraint("uq_incident_patient_dedupe", ["patient_id", "dedupe_key"])
    check_names = {item.get("name") for item in sa.inspect(op.get_bind()).get_check_constraints("incidents")}
    with op.batch_alter_table("incidents") as batch:
        if "ck_incidents_importance" not in check_names:
            batch.create_check_constraint("ck_incidents_importance", "importance IN ('LOW','MEDIUM','HIGH','CRITICAL')")
        if "ck_incidents_deadline_kind" not in check_names:
            batch.create_check_constraint("ck_incidents_deadline_kind", "deadline_kind IS NULL OR deadline_kind IN ('ACK','RESOLVE')")
        if "ck_incidents_repeat_count" not in check_names:
            batch.create_check_constraint("ck_incidents_repeat_count", "repeat_count >= 1")
    notification_checks={item.get("name") for item in sa.inspect(op.get_bind()).get_check_constraints("notifications")}
    if "ck_notifications_channel" not in notification_checks:
        with op.batch_alter_table("notifications") as batch:
            batch.create_check_constraint("ck_notifications_channel", "channel IN ('ALERT','INBOX','DIGEST')")
    index_names = {item.get("name") for item in sa.inspect(op.get_bind()).get_indexes("incidents")}
    with op.batch_alter_table("incidents") as batch:
        if "ix_incidents_current_deadline_at" not in index_names:
            batch.create_index("ix_incidents_current_deadline_at", ["current_deadline_at"])
        if "ix_incidents_related_activity_id" not in index_names:
            batch.create_index("ix_incidents_related_activity_id", ["related_activity_id"])
    existing = set(sa.inspect(op.get_bind()).get_table_names())
    for table in Base.metadata.sorted_tables:
        if table.name in {"escalation_policies", "app_settings"} and table.name not in existing:
            table.create(bind=op.get_bind(), checkfirst=True)


def downgrade():
    bind = op.get_bind()
    for name in ("app_settings", "escalation_policies"):
        if sa.inspect(bind).has_table(name):
            Base.metadata.tables[name].drop(bind, checkfirst=True)
    indexes = {item.get("name") for item in sa.inspect(bind).get_indexes("incidents")}
    with op.batch_alter_table("incidents") as batch:
        for name in ("ix_incidents_related_activity_id", "ix_incidents_current_deadline_at"):
            if name in indexes: batch.drop_index(name)
    notification_checks={item.get("name") for item in sa.inspect(bind).get_check_constraints("notifications")}
    if "ck_notifications_channel" in notification_checks:
        with op.batch_alter_table("notifications") as batch:
            batch.drop_constraint("ck_notifications_channel", type_="check")
    incident_checks={item.get("name") for item in sa.inspect(bind).get_check_constraints("incidents")}
    with op.batch_alter_table("incidents") as batch:
        for name in ("ck_incidents_importance", "ck_incidents_deadline_kind", "ck_incidents_repeat_count"):
            if name in incident_checks: batch.drop_constraint(name, type_="check")
    for table, names in (("notifications", ("channel",)), ("incidents", ("related_activity_id", "importance", "emergency_unacknowledged", "repeat_count", "deadline_kind", "current_deadline_at")),
                         ("care_activities", ("acknowledged_by", "acknowledged_at"))):
        columns = {item["name"] for item in sa.inspect(bind).get_columns(table)}
        with op.batch_alter_table(table) as batch:
            for name in names:
                if name in columns:
                    batch.drop_column(name)
