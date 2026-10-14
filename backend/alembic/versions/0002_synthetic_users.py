"""Label seeded/demo users as synthetic."""
import sqlalchemy as sa
from alembic import op

revision = "0002_synthetic_users"
down_revision = "0001_phase1"
branch_labels = None
depends_on = None

def upgrade():
    bind = op.get_bind()
    columns = {column["name"] for column in sa.inspect(bind).get_columns("users")}
    if "is_synthetic" not in columns:
        op.add_column("users", sa.Column("is_synthetic", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.execute("UPDATE users SET is_synthetic = true WHERE email LIKE '%@secondpatient.demo'")

def downgrade():
    bind = op.get_bind()
    columns = {column["name"] for column in sa.inspect(bind).get_columns("users")}
    if "is_synthetic" in columns:
        op.drop_column("users", "is_synthetic")
