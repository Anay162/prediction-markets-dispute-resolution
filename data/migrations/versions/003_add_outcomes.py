"""
data/migrations/versions/003_add_outcomes.py

Adds market_outcomes table for resolution feedback loop.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "003"
down_revision = "002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "market_outcomes",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("uuid_generate_v4()")),
        sa.Column("contract_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("contracts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("report_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("reports.id", ondelete="SET NULL"), nullable=True),
        sa.Column("resolved_cleanly", sa.Boolean, nullable=True),
        sa.Column("dispute_filed", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("actual_failure_category", sa.String(50), nullable=True),
        sa.Column("predicted_rcs", sa.Integer, nullable=True),
        sa.Column("resolution_notes", sa.Text, nullable=True),
        sa.Column("source", sa.String(50), nullable=False, server_default="webhook"),
        sa.Column("recorded_at", sa.DateTime, nullable=False,
                  server_default=sa.text("NOW()")),
    )
    op.create_index("ix_outcomes_contract_id", "market_outcomes", ["contract_id"])
    op.create_index("ix_outcomes_resolved_cleanly", "market_outcomes", ["resolved_cleanly"])
    op.create_index("ix_outcomes_dispute_filed", "market_outcomes", ["dispute_filed"])


def downgrade() -> None:
    op.drop_table("market_outcomes")
