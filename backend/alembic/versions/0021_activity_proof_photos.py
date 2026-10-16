"""Caretaker accountability: a required proof photo (timestamp + location) before a medicine dose can be recorded as done.

Also extends 0020's public-API lock-down to this new table, since Supabase's anon key must not read or write it either.
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect, text

revision = "0021_activity_proof_photos"
down_revision = "0020_lock_down_public_api"
branch_labels = None
depends_on = None


def upgrade():
    if "activity_proof_photos" not in inspect(op.get_bind()).get_table_names():
        op.create_table(
            "activity_proof_photos",
            sa.Column("id", sa.Uuid(), primary_key=True),
            sa.Column("activity_id", sa.Uuid(), sa.ForeignKey("care_activities.id", ondelete="CASCADE"), nullable=False),
            sa.Column("uploaded_by", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("mime_type", sa.String(60), nullable=False),
            sa.Column("size_bytes", sa.Integer(), nullable=False),
            sa.Column("image", sa.LargeBinary(), nullable=False),
            sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("latitude", sa.Float(), nullable=True),
            sa.Column("longitude", sa.Float(), nullable=True),
            sa.Column("location_accuracy_m", sa.Float(), nullable=True),
            sa.Column("location_status", sa.String(12), nullable=False, server_default="UNAVAILABLE"),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.CheckConstraint("location_status IN ('AVAILABLE','DENIED','UNAVAILABLE')", name="ck_proof_photo_location_status"),
            sa.UniqueConstraint("activity_id", name="uq_proof_photo_activity"),
        )
        op.create_index("ix_activity_proof_photos_activity_id", "activity_proof_photos", ["activity_id"])

    bind = op.get_bind()
    if bind.dialect.name != "postgresql": return
    public_roles = [role for role in ("anon", "authenticated") if bind.scalar(text("SELECT to_regrole(:role) IS NOT NULL"), {"role": role})]
    op.execute('ALTER TABLE public."activity_proof_photos" ENABLE ROW LEVEL SECURITY')
    op.execute('REVOKE ALL ON TABLE public."activity_proof_photos" FROM PUBLIC')
    for role in public_roles:
        op.execute(f'REVOKE ALL ON TABLE public."activity_proof_photos" FROM {role}')


def downgrade():
    if "activity_proof_photos" in inspect(op.get_bind()).get_table_names(): op.drop_table("activity_proof_photos")
