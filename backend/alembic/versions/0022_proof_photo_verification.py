"""The primary contact must be able to review and verify each proof photo (who reviewed it, and when)."""
import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision = "0022_proof_photo_verification"
down_revision = "0021_activity_proof_photos"
branch_labels = None
depends_on = None


def upgrade():
    columns = {c["name"] for c in inspect(op.get_bind()).get_columns("activity_proof_photos")}
    if {"verified_by", "verified_at"} <= columns: return
    with op.batch_alter_table("activity_proof_photos", recreate="auto") as batch:
        if "verified_by" not in columns: batch.add_column(sa.Column("verified_by", sa.Uuid(), sa.ForeignKey("users.id", name="fk_proof_photo_verified_by"), nullable=True))
        if "verified_at" not in columns: batch.add_column(sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True))


def downgrade():
    columns = {c["name"] for c in inspect(op.get_bind()).get_columns("activity_proof_photos")}
    if not ({"verified_by", "verified_at"} & columns): return
    # SQLite's plain DROP COLUMN leaves a dangling FK clause behind; batch mode recreates the table instead.
    with op.batch_alter_table("activity_proof_photos", recreate="auto") as batch:
        if "verified_at" in columns: batch.drop_column("verified_at")
        if "verified_by" in columns: batch.drop_column("verified_by")
