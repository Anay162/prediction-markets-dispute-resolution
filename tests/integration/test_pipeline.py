"""
tests/integration/test_pipeline.py

Integration tests for core/pipeline.py

These tests run the full pipeline with a mock LLM and mock enrichment,
verifying that all layers wire together correctly and produce a valid
ReportOutput with the expected structure.
"""

from __future__ import annotations

import json
import uuid
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock

import pytest

from api.schemas.report import ReportOutput
from core.pipeline import AuditPipeline

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

ENTITY_EXTRACTION_RESPONSE = json.dumps(
    {
        "named_entities": [
            {
                "text": "BEA",
                "entity_type": "ORG",
                "context": "Bureau of Economic Analysis",
                "ambiguity_risk": False,
            }
        ],
        "thresholds": [
            {
                "raw_text": "exceed 2%",
                "value": 2.0,
                "unit": "percent",
                "data_series": "US GDP",
                "revision_risk": True,
                "single_point_risk": False,
            }
        ],
        "timeframes": [
            {
                "raw_text": "end of year",
                "parsed_date": None,
                "timezone_specified": False,
                "ambiguity_note": "No tz",
            }
        ],
        "key_terms": [
            {
                "term": "exceeds",
                "context": "GDP growth exceeds 2%",
                "ambiguity_type": "multiple_meanings",
                "note": "Ambiguous boundary",
            }
        ],
        "source_url": "https://bea.gov/gdp",
    }
)

DEFINITIONAL_FINDINGS = json.dumps(
    [
        {
            "severity": "high",
            "description": "The term 'exceeds' is ambiguous.",
            "affected_clause": "US GDP growth exceeds 2%",
            "rewrite": "US real GDP growth is strictly greater than 2.0%",
            "evidence": [],
            "confidence": 0.95,
        }
    ]
)

THRESHOLD_FINDINGS = json.dumps(
    [
        {
            "severity": "high",
            "description": "GDP is revised after initial release.",
            "affected_clause": "exceed 2% in 2025",
            "rewrite": "the BEA advance estimate, with no revisions applying",
            "evidence": [],
            "confidence": 0.98,
        }
    ]
)

TIMING_FINDINGS = json.dumps(
    [
        {
            "severity": "medium",
            "description": "No timezone specified.",
            "affected_clause": "end of year",
            "rewrite": "11:59:59 PM UTC on December 31, 2025",
            "evidence": [],
            "confidence": 0.85,
        }
    ]
)

REWRITE_RESPONSE = json.dumps(
    {
        "original_clause": "US GDP growth exceeds 2%",
        "rewritten_clause": "US real GDP growth (advance estimate) is strictly greater than 2.0%",
        "changes_made": ["Replaced exceeds with strictly greater than"],
        "residual_risks": [],
    }
)

VALIDATE_RESPONSE = json.dumps(
    {
        "closes_vulnerability": True,
        "closure_explanation": "Closes the ambiguity",
        "new_issues": [],
        "quality_score": 4,
        "approved": True,
        "suggested_improvement": None,
    }
)


def make_pipeline_llm():
    """LLM client that returns appropriate responses for each pipeline stage."""
    call_count = 0

    async def complete(system: str, user: str, **kwargs) -> str:
        nonlocal call_count
        call_count += 1
        s = system.lower()
        if "extraction engine" in s or "extract" in s:
            return ENTITY_EXTRACTION_RESPONSE
        elif "definitional ambiguity" in s:
            return DEFINITIONAL_FINDINGS
        elif "threshold gaming" in s:
            return THRESHOLD_FINDINGS
        elif "timing ambiguity" in s:
            return TIMING_FINDINGS
        elif "source failure" in s or "adversarial" in s or "scope creep" in s:
            return "[]"
        elif "clause rewriter" in s or "rewrite" in s.replace(" ", ""):
            return REWRITE_RESPONSE
        elif "quality reviewer" in s or "validator" in s:
            return VALIDATE_RESPONSE
        return "[]"

    async def embed(text: str) -> list[float]:
        return [0.0] * 1536

    llm = MagicMock()
    llm.complete = complete
    llm.embed = embed
    return llm


@asynccontextmanager
async def mock_session_factory():
    session = MagicMock()
    session.execute = AsyncMock(
        return_value=MagicMock(
            scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))
        )
    )
    yield session


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pipeline_returns_report_output(sample_contract, mock_enrichment):
    llm = make_pipeline_llm()
    pipeline = AuditPipeline(
        llm_client=llm,
        db_session_factory=mock_session_factory,
    )
    # Patch enrichment onto analyzers by monkey-patching the runner
    from core.analyzers import runner as runner_mod

    original_runner = runner_mod.AnalyzerRunner

    class PatchedRunner(original_runner):
        def __init__(self, llm, enrich=None):
            super().__init__(llm, mock_enrichment)

    runner_mod.AnalyzerRunner = PatchedRunner
    try:
        report = await pipeline.run(sample_contract, uuid.uuid4())
    finally:
        runner_mod.AnalyzerRunner = original_runner

    assert isinstance(report, ReportOutput)
    assert 0 <= report.resolution_clarity_score <= 100
    assert report.score_label
    assert isinstance(report.findings, list)
    assert report.audit_duration_seconds > 0
    assert report.model_version


@pytest.mark.asyncio
async def test_pipeline_score_lower_for_ambiguous_contract(
    sample_contract, clean_contract, mock_enrichment
):
    """Ambiguous contract should score lower than clean contract."""
    llm = make_pipeline_llm()
    pipeline = AuditPipeline(
        llm_client=llm,
        db_session_factory=mock_session_factory,
    )

    from core.analyzers import runner as runner_mod

    original_runner = runner_mod.AnalyzerRunner

    class PatchedRunner(original_runner):
        def __init__(self, llm, enrich=None):
            super().__init__(llm, mock_enrichment)

    runner_mod.AnalyzerRunner = PatchedRunner
    try:
        ambiguous_report = await pipeline.run(sample_contract, uuid.uuid4())
        clean_report = await pipeline.run(clean_contract, uuid.uuid4())
    finally:
        runner_mod.AnalyzerRunner = original_runner

    assert ambiguous_report.resolution_clarity_score <= clean_report.resolution_clarity_score


@pytest.mark.asyncio
async def test_pipeline_findings_have_rewrites(sample_contract, mock_enrichment):
    llm = make_pipeline_llm()
    pipeline = AuditPipeline(
        llm_client=llm,
        db_session_factory=mock_session_factory,
    )

    from core.analyzers import runner as runner_mod

    original_runner = runner_mod.AnalyzerRunner

    class PatchedRunner(original_runner):
        def __init__(self, llm, enrich=None):
            super().__init__(llm, mock_enrichment)

    runner_mod.AnalyzerRunner = PatchedRunner
    try:
        report = await pipeline.run(sample_contract, uuid.uuid4())
    finally:
        runner_mod.AnalyzerRunner = original_runner

    for finding in report.findings:
        assert finding.rewrite, f"Finding {finding.id} has no rewrite"
        assert finding.diff is not None


@pytest.mark.asyncio
async def test_pipeline_progress_callback_called(sample_contract, mock_enrichment):
    llm = make_pipeline_llm()
    pipeline = AuditPipeline(
        llm_client=llm,
        db_session_factory=mock_session_factory,
    )

    progress_calls = []

    async def track_progress(stage: str, pct: int):
        progress_calls.append((stage, pct))

    from core.analyzers import runner as runner_mod

    original_runner = runner_mod.AnalyzerRunner

    class PatchedRunner(original_runner):
        def __init__(self, llm, enrich=None):
            super().__init__(llm, mock_enrichment)

    runner_mod.AnalyzerRunner = PatchedRunner
    try:
        await pipeline.run(sample_contract, uuid.uuid4(), progress_callback=track_progress)
    finally:
        runner_mod.AnalyzerRunner = original_runner

    assert len(progress_calls) > 0
    stages = [s for s, _ in progress_calls]
    assert any("Parsing" in s or "parsing" in s for s in stages)
    # Final call should be 100%
    assert progress_calls[-1][1] == 100
