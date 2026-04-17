"""
tests/unit/test_rewriter.py

Unit tests for core/rewriter/clause_rewriter.py and diff_generator.py
"""

from __future__ import annotations

import json
import uuid

import pytest

from api.schemas.report import Finding, Severity, VulnerabilityCategory
from core.rewriter.diff_generator import _collapse, attach_diffs, generate_diff

# ---------------------------------------------------------------------------
# Diff generator
# ---------------------------------------------------------------------------


def test_diff_identical_strings():
    diff = generate_diff("hello world", "hello world")
    ops = [op for op, _ in diff]
    assert "delete" not in ops
    assert "insert" not in ops
    assert "equal" in ops


def test_diff_complete_replacement():
    diff = generate_diff("old clause text", "new clause text")
    ops = [op for op, _ in diff]
    # Should have deletes and inserts
    assert "delete" in ops or "insert" in ops


def test_diff_partial_change():
    diff = generate_diff(
        "will the GDP exceed 2% by year end",
        "will the BEA advance GDP estimate exceed 2.0% by 11:59 PM UTC on December 31",
    )
    ops = [op for op, _ in diff]
    assert "equal" in ops
    assert "insert" in ops


def test_diff_returns_list_of_tuples():
    diff = generate_diff("original", "rewritten")
    assert isinstance(diff, list)
    for item in diff:
        assert isinstance(item, tuple)
        assert len(item) == 2
        op, text = item
        assert op in ("equal", "insert", "delete")
        assert isinstance(text, str)


def test_diff_empty_inputs():
    diff = generate_diff("", "")
    assert diff == [] or all(text == "" for _, text in diff)


def test_collapse_merges_adjacent_same_ops():
    ops = [("equal", "a"), ("equal", " b"), ("insert", "c")]
    result = _collapse(ops)
    assert result[0] == ("equal", "a b")
    assert result[1] == ("insert", "c")


def test_attach_diffs_modifies_findings_in_place(multi_finding_list):
    for f in multi_finding_list:
        assert f.diff == []
    result = attach_diffs(multi_finding_list)
    for f in result:
        assert isinstance(f.diff, list)


def test_attach_diffs_skips_finding_with_no_rewrite():
    f = Finding(
        id=uuid.uuid4(),
        category=VulnerabilityCategory.timing_ambiguity,
        severity=Severity.low,
        description="test",
        affected_clause="original",
        rewrite="",  # No rewrite
    )
    attach_diffs([f])
    assert f.diff == []


# ---------------------------------------------------------------------------
# Clause rewriter
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rewriter_calls_both_llm_prompts(mock_llm, sample_finding):
    """Rewriter should make 2 LLM calls per finding: rewrite + validate."""
    rewrite_response = json.dumps(
        {
            "original_clause": sample_finding.affected_clause,
            "rewritten_clause": "Strictly greater than 2.0% (i.e., 2.001% or higher)",
            "changes_made": ["Replaced 'exceeds' with 'strictly greater than'"],
            "residual_risks": [],
        }
    )
    validate_response = json.dumps(
        {
            "closes_vulnerability": True,
            "closure_explanation": "Rewrite closes the ambiguity",
            "new_issues": [],
            "quality_score": 4,
            "approved": True,
            "suggested_improvement": None,
        }
    )

    call_count = 0
    responses = [rewrite_response, validate_response]

    async def mock_complete(**kwargs):
        nonlocal call_count
        resp = responses[min(call_count, len(responses) - 1)]
        call_count += 1
        return resp

    mock_llm.complete = mock_complete

    from core.rewriter.clause_rewriter import ClauseRewriter

    rewriter = ClauseRewriter(mock_llm)
    result = await rewriter.rewrite_finding(sample_finding, "full contract text")

    assert call_count == 2
    assert result.rewrite == "Strictly greater than 2.0% (i.e., 2.001% or higher)"


@pytest.mark.asyncio
async def test_rewriter_keeps_original_on_llm_failure(mock_llm, sample_finding):
    """If rewriter LLM call fails, keep the original finding unchanged."""
    original_rewrite = sample_finding.rewrite

    async def broken_complete(**kwargs):
        raise ConnectionError("LLM down")

    mock_llm.complete = broken_complete

    from core.rewriter.clause_rewriter import ClauseRewriter

    rewriter = ClauseRewriter(mock_llm)
    result = await rewriter.rewrite_finding(sample_finding, "contract text")

    assert result.rewrite == original_rewrite


@pytest.mark.asyncio
async def test_rewrite_all_returns_same_count(mock_llm, multi_finding_list):
    """rewrite_all should return the same number of findings regardless of failures."""

    async def always_fail(**kwargs):
        raise RuntimeError("always fails")

    mock_llm.complete = always_fail

    from core.rewriter.clause_rewriter import ClauseRewriter

    rewriter = ClauseRewriter(mock_llm)
    results = await rewriter.rewrite_all(multi_finding_list, "full contract")
    assert len(results) == len(multi_finding_list)
