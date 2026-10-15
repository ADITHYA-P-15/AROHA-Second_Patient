"""Ratings and reputation: agency ratings, doctor ratings, reviews, review reports and daily reputation snapshots. Additive and guarded."""
import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision = "0017_reputation"
down_revision = "0016_directory"
branch_labels = None
depends_on = None

TABLES = ("review_reports", "reputation_snapshots", "reviews", "doctor_ratings", "agency_ratings")


def upgrade():
    tables = set(inspect(op.get_bind()).get_table_names())
    if "agency_ratings" not in tables:
        op.create_table(
            "agency_ratings",
            sa.Column("id", sa.Uuid(), primary_key=True),
            sa.Column("caregiver_id", sa.Uuid(), sa.ForeignKey("caregivers.id", ondelete="CASCADE"), nullable=False, unique=True),
            sa.Column("agency_id", sa.Uuid(), sa.ForeignKey("agencies.id", ondelete="SET NULL"), nullable=True),
            sa.Column("rating", sa.Float(), nullable=False),
            sa.Column("is_synthetic", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.CheckConstraint("rating >= 1 AND rating <= 5", name="ck_agency_rating_range"),
        )
    if "doctor_ratings" not in tables:
        op.create_table(
            "doctor_ratings",
            sa.Column("id", sa.Uuid(), primary_key=True),
            sa.Column("caregiver_id", sa.Uuid(), sa.ForeignKey("caregivers.id", ondelete="CASCADE"), nullable=False),
            sa.Column("author_user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
            sa.Column("patient_id", sa.Uuid(), sa.ForeignKey("patients.id", ondelete="SET NULL"), nullable=True),
            sa.Column("rating", sa.Integer(), nullable=False),
            sa.Column("note", sa.String(300), nullable=False, server_default=""),
            sa.Column("is_synthetic", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.CheckConstraint("rating >= 1 AND rating <= 5", name="ck_doctor_rating_range"),
            sa.CheckConstraint("length(note) <= 300", name="ck_doctor_rating_note"),
        )
        op.create_index("ix_doctor_ratings_caregiver_id", "doctor_ratings", ["caregiver_id"])
        op.create_index("ix_doctor_ratings_created_at", "doctor_ratings", ["created_at"])
        op.create_index("ix_doctor_rating_author_caregiver", "doctor_ratings", ["author_user_id", "caregiver_id", "created_at"])
    if "reviews" not in tables:
        op.create_table(
            "reviews",
            sa.Column("id", sa.Uuid(), primary_key=True),
            sa.Column("caregiver_id", sa.Uuid(), sa.ForeignKey("caregivers.id", ondelete="CASCADE"), nullable=False),
            sa.Column("author_user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
            sa.Column("author_role", sa.String(16), nullable=False),
            sa.Column("patient_id", sa.Uuid(), sa.ForeignKey("patients.id", ondelete="SET NULL"), nullable=True),
            sa.Column("rating", sa.Integer(), nullable=False),
            sa.Column("text", sa.String(500), nullable=False, server_default=""),
            sa.Column("hidden", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("is_synthetic", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.CheckConstraint("rating >= 1 AND rating <= 5", name="ck_review_rating_range"),
            sa.CheckConstraint("length(text) <= 500", name="ck_review_text"),
            sa.CheckConstraint("author_role IN ('PRIMARY_CONTACT','PATIENT')", name="ck_review_author_role"),
        )
        op.create_index("ix_reviews_caregiver_id", "reviews", ["caregiver_id"])
        op.create_index("ix_reviews_created_at", "reviews", ["created_at"])
        op.create_index("ix_review_author_caregiver", "reviews", ["author_user_id", "caregiver_id", "created_at"])
    if "review_reports" not in tables:
        op.create_table(
            "review_reports",
            sa.Column("id", sa.Uuid(), primary_key=True),
            sa.Column("review_id", sa.Uuid(), sa.ForeignKey("reviews.id", ondelete="CASCADE"), nullable=False),
            sa.Column("reporter_user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
            sa.Column("reason", sa.String(300), nullable=False, server_default=""),
            sa.Column("status", sa.String(8), nullable=False, server_default="OPEN"),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint("review_id", "reporter_user_id", name="uq_review_report_once"),
            sa.CheckConstraint("status IN ('OPEN','CLOSED')", name="ck_review_report_status"),
        )
        op.create_index("ix_review_reports_review_id", "review_reports", ["review_id"])
    if "reputation_snapshots" not in tables:
        op.create_table(
            "reputation_snapshots",
            sa.Column("id", sa.Uuid(), primary_key=True),
            sa.Column("caregiver_id", sa.Uuid(), sa.ForeignKey("caregivers.id", ondelete="CASCADE"), nullable=False),
            sa.Column("day", sa.Date(), nullable=False),
            sa.Column("metric_score", sa.Float(), nullable=True),
            sa.Column("composite", sa.Float(), nullable=True),
            sa.Column("breakdown", sa.JSON(), nullable=False),
            sa.Column("computed_at", sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint("caregiver_id", "day", name="uq_reputation_snapshot_day"),
        )
        op.create_index("ix_reputation_snapshots_caregiver_id", "reputation_snapshots", ["caregiver_id"])
        op.create_index("ix_reputation_snapshots_day", "reputation_snapshots", ["day"])


def downgrade():
    tables = set(inspect(op.get_bind()).get_table_names())
    for table in TABLES:
        if table in tables: op.drop_table(table)
