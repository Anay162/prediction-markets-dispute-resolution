"""
data/migrations/versions/002_add_disputes.py

Adds the disputes table for historical dispute records scraped
from Polymarket, UMA, Manifold, and Augur.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "002"
down_revision = "001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "disputes",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("uuid_generate_v4()"),
        ),
        sa.Column("source_platform", sa.String(50), nullable=False),
        sa.Column("external_id", sa.String(200), nullable=False, unique=True),
        sa.Column("question", sa.Text, nullable=False),
        sa.Column("resolution_criteria", sa.Text, nullable=True),
        sa.Column("resolution_source", sa.Text, nullable=True),
        sa.Column("failure_category", sa.String(50), nullable=True),
        sa.Column("dispute_reason", sa.Text, nullable=True),
        sa.Column("resolution", sa.Text, nullable=True),
        sa.Column("embedding", postgresql.JSON, nullable=True),
        sa.Column("raw_data", postgresql.JSONB, nullable=False, server_default="{}"),
        sa.Column("scraped_at", sa.DateTime, nullable=False, server_default=sa.text("NOW()")),
        sa.Column("dispute_date", sa.Date, nullable=True),
    )
    op.create_index("ix_disputes_source_platform", "disputes", ["source_platform"])
    op.create_index("ix_disputes_failure_category", "disputes", ["failure_category"])
    op.create_index("ix_disputes_external_id", "disputes", ["external_id"])


def downgrade() -> None:
    op.drop_table("disputes")
