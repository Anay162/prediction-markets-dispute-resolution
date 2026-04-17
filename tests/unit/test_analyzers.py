"""
tests/unit/test_analyzers.py

Unit tests for the six analyzer classes and the AnalyzerRunner.

Strategy: mock the LLM to return known findings, then verify that
post-processing, severity parsing, and deduplication work correctly.
"""

from __future__ import annotations

import json

import pytest

from api.schemas.report import Severity, VulnerabilityCategory
from core.analyzers.adversarial_resolution import AdversarialResolutionAnalyzer
from core.analyzers.base import AnalyzerError, BaseAnalyzer
from core.analyzers.runner import AnalyzerRunner, _text_overlap
from core.analyzers.source_failure import SourceFailureAnalyzer
from core.analyzers.threshold_gaming import ThresholdGamingAnalyzer
from core.analyzers.timing_ambiguity import TimingAmbiguityAnalyzer

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def one_finding_response(
    severity: str = "high",
    description: str = "Test vulnerability",
    affected_clause: str = "test clause",
    rewrite: str = "improved clause",
) -> str:
    return json.dumps(
        [
            {
                "severity": severity,
                "description": description,
                "affected_clause": affected_clause,
                "rewrite": rewrite,
                "evidence": ["test evidence"],
                "confidence": 0.9,
            }
        ]
    )


def two_findings_response() -> str:
    return json.dumps(
        [
            {
                "severity": "critical",
                "description": "First finding",
                "affected_clause": "first clause",
                "rewrite": "first rewrite",
                "evidence": [],
                "confidence": 1.0,
            },
            {
                "severity": "low",
                "description": "Second finding",
                "affected_clause": "second clause",
                "rewrite": "second rewrite",
                "evidence": [],
                "confidence": 0.6,
            },
        ]
    )


# ---------------------------------------------------------------------------
# Base analyzer: JSON parsing
# ---------------------------------------------------------------------------


class ConcreteAnalyzer(BaseAnalyzer):
    category = VulnerabilityCategory.definitional_ambiguity
    prompt_file = "definitional_ambiguity.txt"


@pytest.mark.asyncio
async def test_analyzer_parses_valid_json(mock_llm, parsed_sample_contract):
    mock_llm._responses = {"definitional": one_finding_response()}
    analyzer = ConcreteAnalyzer(mock_llm)
    findings = await analyzer.analyze(parsed_sample_contract)
    assert len(findings) == 1
    assert findings[0].severity == Severity.high
    assert findings[0].category == VulnerabilityCategory.definitional_ambiguity


@pytest.mark.asyncio
async def test_analyzer_handles_markdown_fenced_json(mock_llm, parsed_sample_contract):
    mock_llm._responses = {"definitional": "```json\n" + one_finding_response() + "\n```"}
    analyzer = ConcreteAnalyzer(mock_llm)
    findings = await analyzer.analyze(parsed_sample_contract)
    assert len(findings) == 1


@pytest.mark.asyncio
async def test_analyzer_returns_empty_list_for_clean_contract(mock_llm, parsed_sample_contract):
    mock_llm._responses = {"definitional": "[]"}
    analyzer = ConcreteAnalyzer(mock_llm)
    findings = await analyzer.analyze(parsed_sample_contract)
    assert findings == []


@pytest.mark.asyncio
async def test_analyzer_handles_wrapped_findings_object(mock_llm, parsed_sample_contract):
    """Some models wrap with {"findings": [...]}"""
    wrapped = json.dumps({"findings": json.loads(one_finding_response())})
    mock_llm._responses = {"definitional": wrapped}
    analyzer = ConcreteAnalyzer(mock_llm)
    findings = await analyzer.analyze(parsed_sample_contract)
    assert len(findings) == 1


@pytest.mark.asyncio
async def test_analyzer_skips_malformed_findings(mock_llm, parsed_sample_contract):
    """Malformed individual findings are skipped, not crashed on."""
    mixed = json.dumps(
        [
            {"severity": "high", "description": "valid", "affected_clause": "x", "rewrite": "y"},
            {"severity": "not_a_real_severity", "affected_clause": "x"},  # Missing description
            {
                "severity": "low",
                "description": "also valid",
                "affected_clause": "a",
                "rewrite": "b",
            },
        ]
    )
    mock_llm._responses = {"definitional": mixed}
    analyzer = ConcreteAnalyzer(mock_llm)
    findings = await analyzer.analyze(parsed_sample_contract)
    assert len(findings) >= 2  # At least the two valid ones


@pytest.mark.asyncio
async def test_analyzer_raises_on_complete_garbage(mock_llm, parsed_sample_contract):
    mock_llm._responses = {"definitional": "I cannot help with prediction markets."}
    analyzer = ConcreteAnalyzer(mock_llm)
    with pytest.raises(AnalyzerError):
        await analyzer.analyze(parsed_sample_contract)


@pytest.mark.asyncio
async def test_severity_normalised_to_lowercase(mock_llm, parsed_sample_contract):
    response = json.dumps(
        [
            {
                "severity": "CRITICAL",  # All caps
                "description": "test",
                "affected_clause": "clause",
                "rewrite": "rewrite",
            }
        ]
    )
    mock_llm._responses = {"definitional": response}
    analyzer = ConcreteAnalyzer(mock_llm)
    findings = await analyzer.analyze(parsed_sample_contract)
    assert findings[0].severity == Severity.critical


# ---------------------------------------------------------------------------
# Source failure: post-processing
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_source_failure_adds_dead_url_finding(mock_llm, parsed_sample_contract):
    """When source probe returns 404, a critical finding should be injected."""
    mock_llm._responses = {"source failure": "[]"}

    class Mock404Enrichment:
        async def probe_source(self, url):
            return {
                "status": 404,
                "redirect_chain": [],
                "final_url": url,
                "wayback_available": False,
                "wayback_snapshot_count": 0,
                "wayback_last_snapshot": None,
                "probed_at": "2025-01-01T00:00:00",
            }

    analyzer = SourceFailureAnalyzer(mock_llm, Mock404Enrichment())
    findings = await analyzer.analyze(parsed_sample_contract)
    assert any(f.severity == Severity.critical for f in findings)
    assert any("404" in f.description or "unreachable" in f.description.lower() for f in findings)


# ---------------------------------------------------------------------------
# Threshold gaming: revision-risk annotation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_threshold_gaming_annotates_gdp_revision_risk(mock_llm, parsed_sample_contract):
    """GDP threshold should have revision risk evidence injected."""
    mock_llm._responses = {"threshold": one_finding_response(affected_clause="exceed 2%")}
    analyzer = ThresholdGamingAnalyzer(mock_llm)
    findings = await analyzer.analyze(parsed_sample_contract)
    assert len(findings) == 1
    all_evidence = " ".join(findings[0].evidence).lower()
    assert "revision" in all_evidence or "bea" in all_evidence or "gdp" in all_evidence


# ---------------------------------------------------------------------------
# Timing ambiguity: deterministic timezone check
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_timing_ambiguity_injects_tz_finding_when_llm_misses(
    mock_llm, parsed_sample_contract
):
    """If LLM returns [], but contract has tz-unspecified timeframes, inject finding."""
    mock_llm._responses = {"timing": "[]"}
    analyzer = TimingAmbiguityAnalyzer(mock_llm)
    # parsed_sample_contract has a Timeframe with timezone_specified=False
    findings = await analyzer.analyze(parsed_sample_contract)
    assert len(findings) >= 1
    assert any(
        "timezone" in f.description.lower() or "time zone" in f.description.lower()
        for f in findings
    )


@pytest.mark.asyncio
async def test_timing_ambiguity_no_injection_when_llm_already_found_tz(
    mock_llm, parsed_sample_contract
):
    """If LLM already flagged timezone, don't double-add."""
    mock_llm._responses = {
        "timing": one_finding_response(
            description="The timezone is not specified in the close date reference."
        )
    }
    analyzer = TimingAmbiguityAnalyzer(mock_llm)
    findings = await analyzer.analyze(parsed_sample_contract)
    tz_findings = [
        f
        for f in findings
        if "timezone" in f.description.lower() or "time zone" in f.description.lower()
    ]
    assert len(tz_findings) == 1  # Not duplicated


# ---------------------------------------------------------------------------
# Adversarial resolution: prompt override
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_adversarial_prompt_contains_bad_faith_instruction(mock_llm, parsed_sample_contract):
    mock_llm._responses = {"adversarial": "[]"}
    analyzer = AdversarialResolutionAnalyzer(mock_llm)
    await analyzer.analyze(parsed_sample_contract)
    assert (
        "bad-faith" in mock_llm.last_user_prompt.lower()
        or "adversarial" in mock_llm.last_user_prompt.lower()
        or "financial position" in mock_llm.last_user_prompt.lower()
    )


# ---------------------------------------------------------------------------
# Runner: parallel execution and deduplication
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_runner_returns_all_findings(mock_llm, mock_enrichment, parsed_sample_contract):
    mock_llm._responses = {
        "source failure": one_finding_response(severity="critical"),
        "definitional": one_finding_response(severity="high"),
        "threshold": one_finding_response(severity="medium"),
        "scope": "[]",
        "timing": "[]",
        "adversarial": "[]",
    }
    runner = AnalyzerRunner(mock_llm, mock_enrichment)
    findings, errors = await runner.run_all(parsed_sample_contract)
    # Should have at least the 3 non-empty responses
    assert len(findings) >= 3


@pytest.mark.asyncio
async def test_runner_gracefully_handles_analyzer_failure(
    mock_llm, mock_enrichment, parsed_sample_contract
):
    """One analyzer failing should not abort the whole run."""
    call_count = 0

    async def flaky_complete(**kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise RuntimeError("Simulated LLM failure")
        return "[]"

    mock_llm.complete = flaky_complete
    runner = AnalyzerRunner(mock_llm, mock_enrichment)
    findings, errors = await runner.run_all(parsed_sample_contract)
    # Should have errors for the failed analyzer but still return results
    assert isinstance(errors, dict)
    assert isinstance(findings, list)


@pytest.mark.asyncio
async def test_runner_sorts_by_severity(mock_llm, mock_enrichment, parsed_sample_contract):
    mock_llm._responses = {
        "source failure": one_finding_response(severity="low", affected_clause="low clause"),
        "definitional": one_finding_response(severity="critical", affected_clause="crit clause"),
        "threshold": "[]",
        "scope": "[]",
        "timing": "[]",
        "adversarial": "[]",
    }
    runner = AnalyzerRunner(mock_llm, mock_enrichment)
    findings, _ = await runner.run_all(parsed_sample_contract)
    if len(findings) >= 2:
        severity_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
        for i in range(len(findings) - 1):
            assert (
                severity_order[findings[i].severity.value]
                <= severity_order[findings[i + 1].severity.value]
            )


def test_text_overlap_identical():
    assert _text_overlap("hello world", "hello world") == 1.0


def test_text_overlap_disjoint():
    assert _text_overlap("apple banana", "cat dog") == 0.0


def test_text_overlap_partial():
    score = _text_overlap("the cat sat on the mat", "the cat in the hat")
    assert 0.0 < score < 1.0


def test_text_overlap_empty():
    assert _text_overlap("", "anything") == 0.0
