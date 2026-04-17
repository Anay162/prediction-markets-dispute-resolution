"""
ORM models for historical dispute records and market resolution outcomes.
These feed the scoring calibration loop.
"""
from __future__ import annotations

import uuid
from datetime import datetime, date
from typing import Optional

from sqlalchemy import String, Text, Integer, Float, Boolean, DateTime, Date, JSON, ForeignKey, Index
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from data.models.contract import Base


class DisputeRecord(Base):
    """
    A historical dispute from an external platform (Polymarket, UMA, Manifold, Augur).
    Used to seed the vector store and calibrate scoring weights.
    """
    __tablename__ = "disputes"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    # Which platform this dispute came from
    source_platform: Mapped[str] = mapped_column(String(50), nullable=False)

    # Original platform's ID for deduplication
    external_id: Mapped[str] = mapped_column(String(200), nullable=False, unique=True)

    # The contract text that was disputed
    question: Mapped[str] = mapped_column(Text, nullable=False)
    resolution_criteria: Mapped[str | None] = mapped_column(Text, nullable=True)
    resolution_source: Mapped[str | None] = mapped_column(Text, nullable=True)

    # What failure category this maps to (may be null until labeled)
    failure_category: Mapped[str | None] = mapped_column(String(50), nullable=True)

    # Human-readable description of what went wrong
    dispute_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    # How it resolved
    resolution: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Embedding for similarity search
    embedding: Mapped[list | None] = mapped_column(JSON, nullable=True)

    # Raw data from scraper for reference
    raw_data: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    scraped_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    dispute_date: Mapped[date | None] = mapped_column(Date, nullable=True)

    __table_args__ = (
        Index("ix_disputes_source_platform", "source_platform"),
        Index("ix_disputes_failure_category", "failure_category"),
        Index("ix_disputes_external_id", "external_id"),
    )


class MarketOutcome(Base):
    """
    A real-world resolution outcome for a contract we audited.
    This is the ground truth that feeds back into scoring weight calibration.
    When a market resolves cleanly → our high score was correct.
    When a market is disputed → we should have flagged it higher.
    """
    __tablename__ = "market_outcomes"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    contract_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("contracts.id"), nullable=False
    )
    report_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("reports.id"), nullable=True
    )

    # Did the market resolve cleanly (no dispute)?
    resolved_cleanly: Mapped[bool | None] = mapped_column(Boolean, nullable=True)

    # Was there a formal dispute filed?
    dispute_filed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # The failure category if disputed (maps to VulnerabilityCategory)
    actual_failure_category: Mapped[str | None] = mapped_column(String(50), nullable=True)

    # Our RCS score at time of audit
    predicted_rcs: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Notes from the platform or resolver
    resolution_notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Source: "webhook", "manual", "scraper"
    source: Mapped[str] = mapped_column(String(50), nullable=False, default="webhook")

    recorded_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (
        Index("ix_outcomes_contract_id", "contract_id"),
        Index("ix_outcomes_resolved_cleanly", "resolved_cleanly"),
        Index("ix_outcomes_dispute_filed", "dispute_filed"),
    )


class ScoringWeight(Base):
    """
    Versioned scoring weight configuration.
    Allows us to tune RCS weights as we accumulate outcome data,
    and roll back if a weight change makes things worse.
    """
    __tablename__ = "scoring_weights"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    version: Mapped[str] = mapped_column(String(20), nullable=False, unique=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Points deducted per finding at each severity level
    critical_penalty: Mapped[int] = mapped_column(Integer, default=25, nullable=False)
    high_penalty: Mapped[int] = mapped_column(Integer, default=12, nullable=False)
    medium_penalty: Mapped[int] = mapped_column(Integer, default=5, nullable=False)
    low_penalty: Mapped[int] = mapped_column(Integer, default=2, nullable=False)

    # Per-category multipliers (stored as JSON: {category: multiplier})
    category_multipliers: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    # What dataset was used to calibrate these weights
    calibration_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    calibration_accuracy: Mapped[float | None] = mapped_column(Float, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (
        Index("ix_scoring_weights_is_active", "is_active"),
    )
