"""Voice notes: draft state (preview before sending), English translation, edited flag."""
import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision = "0012_voice_note_preview"
down_revision = "0011_voice_notes"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    columns = {c["name"] for c in inspect(bind).get_columns("voice_notes")}
    with op.batch_alter_table("voice_notes") as batch:
        if "english" not in columns: batch.add_column(sa.Column("english", sa.Text(), nullable=False, server_default=""))
        if "transcript_original" not in columns: batch.add_column(sa.Column("transcript_original", sa.Text(), nullable=False, server_default=""))
        if "edited" not in columns: batch.add_column(sa.Column("edited", sa.Boolean(), nullable=False, server_default=sa.false()))
        if "is_draft" not in columns: batch.add_column(sa.Column("is_draft", sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade():
    with op.batch_alter_table("voice_notes") as batch:
        for name in ("is_draft", "edited", "transcript_original", "english"): batch.drop_column(name)
