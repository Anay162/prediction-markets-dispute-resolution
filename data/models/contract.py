"""
SQLAlchemy ORM models for the core contract and report tables.
Uses async-compatible declarative base.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import (
    JSON,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Contract(Base):
    __tablename__ = "contracts"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    resolution_criteria: Mapped[str] = mapped_column(Text, nullable=False)
    resolution_source: Mapped[str] = mapped_column(Text, nullable=False)
    close_date: Mapped[date] = mapped_column(Date, nullable=False)
    platform: Mapped[str] = mapped_column(String(50), nullable=False, default="generic")
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, nullable=False, default=dict)

    # Embedding vector stored as JSON array until pgvector extension confirmed
    # Will be migrated to VECTOR(1536) in production
    embedding: Mapped[list | None] = mapped_column(JSON, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    reports: Mapped[list[Report]] = relationship("Report", back_populates="contract")

    __table_args__ = (
        Index("ix_contracts_platform", "platform"),
        Index("ix_contracts_close_date", "close_date"),
        Index("ix_contracts_created_at", "created_at"),
    )


class Report(Base):
    __tablename__ = "reports"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    contract_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("contracts.id"), nullable=False
    )
    job_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, unique=True)

    resolution_clarity_score: Mapped[int] = mapped_column(Integer, nullable=False)
    score_label: Mapped[str] = mapped_column(String(50), nullable=False)

    critical_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    high_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    medium_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    low_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    rewritten_contract: Mapped[str | None] = mapped_column(Text, nullable=True)

    audit_duration_seconds: Mapped[float] = mapped_column(Float, nullable=False)
    model_version: Mapped[str] = mapped_column(String(100), nullable=False)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    contract: Mapped[Contract] = relationship("Contract", back_populates="reports")
    findings: Mapped[list[FindingRecord]] = relationship(
        "FindingRecord", back_populates="report", order_by="FindingRecord.severity_rank"
    )

    __table_args__ = (
        Index("ix_reports_contract_id", "contract_id"),
        Index("ix_reports_score", "resolution_clarity_score"),
    )


class FindingRecord(Base):
    __tablename__ = "findings"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    report_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("reports.id"), nullable=False
    )

    category: Mapped[str] = mapped_column(String(50), nullable=False)
    severity: Mapped[str] = mapped_column(String(20), nullable=False)

    # Numeric rank for ordering (critical=1, high=2, medium=3, low=4)
    severity_rank: Mapped[int] = mapped_column(Integer, nullable=False)

    description: Mapped[str] = mapped_column(Text, nullable=False)
    affected_clause: Mapped[str] = mapped_column(Text, nullable=False)
    rewrite: Mapped[str] = mapped_column(Text, nullable=False)

    diff: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    evidence: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)

    report: Mapped[Report] = relationship("Report", back_populates="findings")

    __table_args__ = (
        Index("ix_findings_report_id", "report_id"),
        Index("ix_findings_category", "category"),
        Index("ix_findings_severity", "severity"),
    )
