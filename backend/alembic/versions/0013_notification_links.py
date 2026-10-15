"""Notifications: de-duplication key (timely reminders are sent once) and a deep link."""
import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision = "0013_notification_links"
down_revision = "0012_voice_note_preview"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    columns = {c["name"] for c in inspect(bind).get_columns("notifications")}
    with op.batch_alter_table("notifications") as batch:
        if "dedupe_key" not in columns: batch.add_column(sa.Column("dedupe_key", sa.String(120)))
        if "link" not in columns: batch.add_column(sa.Column("link", sa.String(200)))
    indexes = {i["name"] for i in inspect(bind).get_indexes("notifications")}
    if "ix_notifications_user_dedupe" not in indexes:
        op.create_index("ix_notifications_user_dedupe", "notifications", ["user_id", "dedupe_key"])


def downgrade():
    op.drop_index("ix_notifications_user_dedupe", table_name="notifications")
    with op.batch_alter_table("notifications") as batch:
        batch.drop_column("link"); batch.drop_column("dedupe_key")
