"""Patient messages, incidents, timeline events, and notifications."""
from alembic import op
import sqlalchemy as sa
from app.models import Base

revision = "0004_escalation_messages"
down_revision = "0003_phase2_core_domain"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    existing = set(sa.inspect(bind).get_table_names())
    for table in Base.metadata.sorted_tables:
        if table.name in {"patient_messages", "incidents", "incident_events", "notifications"} and table.name not in existing:
            table.create(bind, checkfirst=True)


def downgrade():
    bind = op.get_bind()
    for name in ("patient_messages", "notifications", "incident_events", "incidents"):
        if sa.inspect(bind).has_table(name):
            Base.metadata.tables[name].drop(bind, checkfirst=True)
