"""Voice notes: recorded patient messages with transcript and advisory urgency suggestion."""
import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision = "0011_voice_notes"
down_revision = "0010_care_feeds"
branch_labels = None
depends_on = None

UUID = sa.Uuid()


def upgrade():
    bind = op.get_bind()
    if "voice_notes" in set(inspect(bind).get_table_names()): return
    op.create_table("voice_notes",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("patient_id", UUID, sa.ForeignKey("patients.id", ondelete="CASCADE"), nullable=False),
        sa.Column("sender_user_id", UUID, sa.ForeignKey("users.id"), nullable=False),
        sa.Column("incident_id", UUID, sa.ForeignKey("incidents.id", ondelete="SET NULL")),
        sa.Column("mime_type", sa.String(60), nullable=False), sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("audio", sa.LargeBinary(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="UNTRANSCRIBED"),
        sa.Column("transcript", sa.Text(), nullable=False, server_default=""),
        sa.Column("language", sa.String(8)), sa.Column("confidence", sa.Float()),
        sa.Column("stt_provider", sa.String(24)), sa.Column("stt_model", sa.String(80)),
        sa.Column("suggested_level", sa.Integer()), sa.Column("suggested_reason", sa.String(300)),
        sa.Column("advisor_provider", sa.String(24)), sa.Column("applied_level", sa.Integer()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("status IN ('TRANSCRIBED','UNTRANSCRIBED')", name="ck_voice_note_status"))
    op.create_index("ix_voice_notes_patient_id", "voice_notes", ["patient_id"])
    op.create_index("ix_voice_notes_incident_id", "voice_notes", ["incident_id"])
    op.create_index("ix_voice_notes_created_at", "voice_notes", ["created_at"])


def downgrade():
    op.drop_table("voice_notes")
