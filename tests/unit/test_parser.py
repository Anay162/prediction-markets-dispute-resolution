"""
tests/unit/test_parser.py

Unit tests for core/parser/entity_extractor.py

Tests cover:
  - URL extraction (LLM path and deterministic regex fallback)
  - Timezone flag injection for deadline language
  - High-risk key term detection
  - Malformed LLM output graceful handling
  - ParsedContract.full_text and to_prompt_dict()
"""

from __future__ import annotations

import json
import uuid
from datetime import date, timedelta

import pytest

from api.schemas.contract import ContractInput, Platform
from core.parser.entity_extractor import EntityExtractor, ParsedContract

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_contract(**kwargs) -> ContractInput:
    defaults = dict(
        question="Will X happen before end of year?",
        resolution_criteria="Resolves YES if X is officially announced.",
        resolution_source="https://example.com/data",
        close_date=date.today() + timedelta(days=90),
        platform=Platform.generic,
    )
    defaults.update(kwargs)
    return ContractInput(**defaults)


GOOD_EXTRACTION_RESPONSE = json.dumps(
    {
        "named_entities": [
            {
                "text": "Example Corp",
                "entity_type": "ORG",
                "context": "Will Example Corp go bankrupt?",
                "ambiguity_risk": True,
            }
        ],
        "thresholds": [
            {
                "raw_text": "exceed 2%",
                "value": 2.0,
                "unit": "percent",
                "data_series": "GDP growth",
                "revision_risk": True,
                "single_point_risk": False,
            }
        ],
        "timeframes": [
            {
                "raw_text": "end of year",
                "parsed_date": None,
                "timezone_specified": False,
                "ambiguity_note": "No timezone specified",
            }
        ],
        "key_terms": [
            {
                "term": "officially announced",
                "context": "if X is officially announced",
                "ambiguity_type": "undefined",
                "note": "Official source not defined",
            }
        ],
        "source_url": "https://example.com/data",
    }
)


# ---------------------------------------------------------------------------
# Tests: URL extraction
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_url_extracted_from_llm_response(mock_llm):
    mock_llm._responses = {"extraction": GOOD_EXTRACTION_RESPONSE}
    extractor = EntityExtractor(mock_llm)
    contract = make_contract(resolution_source="https://example.com/data")
    parsed = await extractor.parse(contract, uuid.uuid4())
    assert parsed.source_url == "https://example.com/data"


@pytest.mark.asyncio
async def test_url_extracted_deterministically_when_llm_misses_it(mock_llm):
    """If LLM returns source_url=null, the regex fallback should catch it."""
    response = json.dumps(
        {
            "named_entities": [],
            "thresholds": [],
            "timeframes": [],
            "key_terms": [],
            "source_url": None,  # LLM missed it
        }
    )
    mock_llm._responses = {"extraction": response}
    extractor = EntityExtractor(mock_llm)
    contract = make_contract(resolution_source="See https://bls.gov/cpi for the CPI release.")
    parsed = await extractor.parse(contract, uuid.uuid4())
    assert parsed.source_url == "https://bls.gov/cpi"


@pytest.mark.asyncio
async def test_no_url_in_source_gives_none(mock_llm):
    response = json.dumps(
        {
            "named_entities": [],
            "thresholds": [],
            "timeframes": [],
            "key_terms": [],
            "source_url": None,
        }
    )
    mock_llm._responses = {"extraction": response}
    extractor = EntityExtractor(mock_llm)
    contract = make_contract(resolution_source="Reuters and Bloomberg financial news")
    parsed = await extractor.parse(contract, uuid.uuid4())
    assert parsed.source_url is None


# ---------------------------------------------------------------------------
# Tests: Timezone flag injection
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_timezone_flag_injected_for_end_of_year(mock_llm):
    """Deterministic pass should flag 'end of year' even if LLM misses it."""
    empty_response = json.dumps(
        {
            "named_entities": [],
            "thresholds": [],
            "timeframes": [],  # LLM returned nothing
            "key_terms": [],
            "source_url": None,
        }
    )
    mock_llm._responses = {"extraction": empty_response}
    extractor = EntityExtractor(mock_llm)
    contract = make_contract(resolution_criteria="Resolves YES if announced by end of year.")
    parsed = await extractor.parse(contract, uuid.uuid4())
    tz_unspecified = [tf for tf in parsed.timeframes if not tf.timezone_specified]
    assert len(tz_unspecified) >= 1
    texts = [tf.raw_text.lower() for tf in tz_unspecified]
    assert any("end of year" in t or "end of" in t for t in texts)


@pytest.mark.asyncio
async def test_timezone_flag_injected_for_midnight(mock_llm):
    empty_response = json.dumps(
        {
            "named_entities": [],
            "thresholds": [],
            "timeframes": [],
            "key_terms": [],
            "source_url": None,
        }
    )
    mock_llm._responses = {"extraction": empty_response}
    extractor = EntityExtractor(mock_llm)
    contract = make_contract(resolution_criteria="Market resolves at midnight on December 31.")
    parsed = await extractor.parse(contract, uuid.uuid4())
    assert any(not tf.timezone_specified for tf in parsed.timeframes)


# ---------------------------------------------------------------------------
# Tests: High-risk key term detection
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_bankrupt_term_flagged(mock_llm):
    empty_response = json.dumps(
        {
            "named_entities": [],
            "thresholds": [],
            "timeframes": [],
            "key_terms": [],
            "source_url": None,
        }
    )
    mock_llm._responses = {"extraction": empty_response}
    extractor = EntityExtractor(mock_llm)
    contract = make_contract(question="Will Company X go bankrupt before Q4 2025?")
    parsed = await extractor.parse(contract, uuid.uuid4())
    term_names = [kt.term.lower() for kt in parsed.key_terms]
    assert "bankrupt" in term_names or "bankruptcy" in term_names


@pytest.mark.asyncio
async def test_exceeds_term_flagged(mock_llm):
    empty_response = json.dumps(
        {
            "named_entities": [],
            "thresholds": [],
            "timeframes": [],
            "key_terms": [],
            "source_url": None,
        }
    )
    mock_llm._responses = {"extraction": empty_response}
    extractor = EntityExtractor(mock_llm)
    contract = make_contract(resolution_criteria="Resolves YES if revenue exceeds $1 billion.")
    parsed = await extractor.parse(contract, uuid.uuid4())
    term_names = [kt.term.lower() for kt in parsed.key_terms]
    assert "exceeds" in term_names


@pytest.mark.asyncio
async def test_no_duplicate_terms_when_llm_and_regex_both_find_term(mock_llm):
    """If LLM already found 'bankrupt', deterministic pass should not add duplicate."""
    response_with_term = json.dumps(
        {
            "named_entities": [],
            "thresholds": [],
            "timeframes": [],
            "key_terms": [
                {
                    "term": "bankrupt",
                    "context": "Will X go bankrupt",
                    "ambiguity_type": "multiple_meanings",
                    "note": "Chapter 7 vs 11",
                }
            ],
            "source_url": None,
        }
    )
    mock_llm._responses = {"extraction": response_with_term}
    extractor = EntityExtractor(mock_llm)
    contract = make_contract(question="Will X go bankrupt?")
    parsed = await extractor.parse(contract, uuid.uuid4())
    bankrupt_terms = [kt for kt in parsed.key_terms if "bankrupt" in kt.term.lower()]
    assert len(bankrupt_terms) == 1  # Not duplicated


# ---------------------------------------------------------------------------
# Tests: Malformed LLM output handling
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_malformed_json_falls_back_to_empty(mock_llm):
    """If LLM returns garbage, parser should return an empty-but-valid ParsedContract."""
    mock_llm._responses = {"extraction": "Sorry, I cannot help with that."}
    extractor = EntityExtractor(mock_llm)
    contract = make_contract()
    parsed = await extractor.parse(contract, uuid.uuid4())
    assert isinstance(parsed, ParsedContract)
    assert parsed.question == contract.question


@pytest.mark.asyncio
async def test_llm_failure_returns_valid_parsed_contract(mock_llm):
    """Network failure during LLM call should not raise — returns empty extraction."""

    async def broken_complete(**kwargs):
        raise ConnectionError("Simulated network failure")

    mock_llm.complete = broken_complete
    extractor = EntityExtractor(mock_llm)
    contract = make_contract()
    parsed = await extractor.parse(contract, uuid.uuid4())
    assert parsed.question == contract.question


# ---------------------------------------------------------------------------
# Tests: ParsedContract properties
# ---------------------------------------------------------------------------


def test_parsed_contract_full_text(parsed_sample_contract):
    text = parsed_sample_contract.full_text
    assert "QUESTION:" in text
    assert "RESOLUTION CRITERIA:" in text
    assert "RESOLUTION SOURCE:" in text
    assert "CLOSE DATE:" in text


def test_parsed_contract_to_prompt_dict(parsed_sample_contract):
    d = parsed_sample_contract.to_prompt_dict()
    assert "question" in d
    assert "named_entities" in d
    assert "thresholds" in d
    assert isinstance(d["thresholds"], list)
    assert d["thresholds"][0]["revision_risk"] is True
