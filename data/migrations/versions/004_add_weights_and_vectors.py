"""
data/migrations/versions/004_add_weights_and_vectors.py

Adds scoring_weights table and enables pgvector for similarity search.
Also migrates the embedding columns from JSON to VECTOR(1536).
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "004"
down_revision = "003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Enable pgvector extension
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "scoring_weights",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("version", sa.String(20), nullable=False, unique=True),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("critical_penalty", sa.Integer, nullable=False, server_default="25"),
        sa.Column("high_penalty", sa.Integer, nullable=False, server_default="12"),
        sa.Column("medium_penalty", sa.Integer, nullable=False, server_default="5"),
        sa.Column("low_penalty", sa.Integer, nullable=False, server_default="2"),
        sa.Column("category_multipliers", postgresql.JSONB, nullable=False, server_default="{}"),
        sa.Column("calibration_notes", sa.Text, nullable=True),
        sa.Column("calibration_accuracy", sa.Float, nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.text("NOW()")),
    )
    op.create_index("ix_scoring_weights_is_active", "scoring_weights", ["is_active"])

    # Insert the default weight set
    op.execute("""
        INSERT INTO scoring_weights (version, is_active, critical_penalty, high_penalty,
            medium_penalty, low_penalty, category_multipliers, calibration_notes)
        VALUES ('v1.0', true, 25, 12, 5, 2,
            '{"adversarial_resolution": 1.2, "threshold_gaming": 1.1}',
            'Default weights — not yet calibrated against outcome data')
    """)

    # Migrate embedding columns from JSON to VECTOR(1536)
    # Drop JSON columns first, then add proper vector columns
    op.drop_column("contracts", "embedding")
    op.drop_column("disputes", "embedding")

    op.execute("ALTER TABLE contracts ADD COLUMN embedding vector(1536)")
    op.execute("ALTER TABLE disputes ADD COLUMN embedding vector(1536)")

    # Create vector similarity search indexes (IVFFlat for approximate search)
    # Lists = sqrt(row_count) is a good starting point
    op.execute("""
        CREATE INDEX ix_contracts_embedding
        ON contracts USING ivfflat (embedding vector_cosine_ops)
        WITH (lists = 100)
    """)
    op.execute("""
        CREATE INDEX ix_disputes_embedding
        ON disputes USING ivfflat (embedding vector_cosine_ops)
        WITH (lists = 100)
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_disputes_embedding")
    op.execute("DROP INDEX IF EXISTS ix_contracts_embedding")
    op.execute("ALTER TABLE disputes DROP COLUMN IF EXISTS embedding")
    op.execute("ALTER TABLE contracts DROP COLUMN IF EXISTS embedding")
    op.add_column("disputes", sa.Column("embedding", postgresql.JSON, nullable=True))
    op.add_column("contracts", sa.Column("embedding", postgresql.JSON, nullable=True))
    op.drop_table("scoring_weights")
