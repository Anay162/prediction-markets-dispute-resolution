"""
tests/conftest.py

Shared pytest fixtures for unit and integration tests.

Key fixtures:
    mock_llm          — LLMClient that returns canned JSON responses
    mock_enrichment   — EnrichmentClient that returns empty/safe responses
    sample_contract   — A ContractInput with known vulnerabilities
    clean_contract    — A well-specified ContractInput that should score ~90
    db_session        — In-memory SQLite session (unit tests)
    async_client      — httpx AsyncClient pointed at the FastAPI test app
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta
from typing import Any

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from api.schemas.contract import ContractInput, Platform
from api.schemas.report import Finding, Severity, VulnerabilityCategory
from core.parser.entity_extractor import KeyTerm, NamedEntity, ParsedContract, Threshold, Timeframe

# ---------------------------------------------------------------------------
# Mock LLM client
# ---------------------------------------------------------------------------


class MockLLMClient:
    """
    Deterministic LLM client for tests.
    Returns pre-baked JSON responses based on the system prompt's content.
    """

    def __init__(self, responses: dict[str, str] | None = None):
        # Map from a keyword in the system prompt → canned response
        self._responses = responses or {}
        self.call_count = 0
        self.last_user_prompt = ""

    async def complete(
        self,
        system: str,
        user: str,
        temperature: float = 0.2,
        max_tokens: int = 4096,
        use_fallback: bool = False,
    ) -> str:
        self.call_count += 1
        self.last_user_prompt = user

        # Match by keyword in system prompt
        for keyword, response in self._responses.items():
            if keyword.lower() in system.lower():
                return response

        # Default: return empty findings array
        return "[]"

    async def embed(self, text: str) -> list[float]:
        # Return a stable deterministic embedding (all zeros + hash-based offset)
        h = hash(text[:50]) % 1000
        return [float(h) / 1000.0] + [0.0] * 1535


def make_mock_llm(responses: dict[str, str] | None = None) -> MockLLMClient:
    return MockLLMClient(responses)


# ---------------------------------------------------------------------------
# Mock enrichment client
# ---------------------------------------------------------------------------


class MockEnrichmentClient:
    """Returns safe empty responses for all enrichment calls."""

    async def probe_source(self, url: str) -> dict[str, Any]:
        return {
            "status": 200,
            "redirect_chain": [],
            "final_url": url,
            "content_type": "text/html",
            "wayback_available": True,
            "wayback_snapshot_count": 42,
            "wayback_last_snapshot": "2024-01-15T00:00:00",
            "probed_at": datetime.utcnow().isoformat(),
        }

    async def lookup_entity(self, entity_name: str) -> dict[str, Any]:
        return {
            "recent_corporate_actions": [],
            "m_and_a_rumors": None,
            "jurisdiction": "us_de",
            "status": "active",
            "sec_filings": [],
        }

    async def find_similar_disputes(
        self, contract_text: str, category: str | None = None, limit: int = 5
    ) -> list[dict[str, Any]]:
        return []


# ---------------------------------------------------------------------------
# Contract fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def close_date() -> date:
    return date.today() + timedelta(days=180)


@pytest.fixture
def sample_contract(close_date) -> ContractInput:
    """
    A deliberately ambiguous contract hitting multiple failure categories.
    Expected: score < 60, multiple findings across categories.
    """
    return ContractInput(
        question="Will the US GDP growth exceed 2% in 2025?",
        resolution_criteria=(
            "This market resolves YES if US GDP growth exceeds 2% in 2025. "
            "Resolution will be based on official government data. "
            "The market closes at end of year."
        ),
        resolution_source="https://www.bea.gov/data/gdp/gross-domestic-product",
        close_date=close_date,
        platform=Platform.generic,
    )


@pytest.fixture
def clean_contract(close_date) -> ContractInput:
    """
    A well-specified contract with minimal vulnerabilities.
    Expected: score >= 80, zero or one low-severity findings.
    """
    return ContractInput(
        question=(
            "Will the BEA advance estimate of US real GDP growth (annualised) "
            "for Q4 2025 be strictly greater than 2.0%, as published in the "
            "BEA advance release on or before February 28, 2026 (11:59 PM UTC)?"
        ),
        resolution_criteria=(
            "This market resolves YES if the Bureau of Economic Analysis (BEA) "
            "advance estimate of real US GDP growth (annualised, seasonally adjusted) "
            "for Q4 2025 is strictly greater than 2.0% (i.e., 2.01% or higher). "
            "Resolution uses ONLY the advance estimate published by the BEA within "
            "30 days of quarter end. No subsequent revisions apply. "
            "If the advance estimate is not published by February 28, 2026 at "
            "11:59:59 PM UTC, the market resolves N/A. "
            "In the event the BEA changes its methodology before publication, "
            "the resolver shall use the methodology in effect as of January 1, 2025."
        ),
        resolution_source=(
            "BEA National Income and Product Accounts table 1.1.1, "
            "advance release: https://apps.bea.gov/iTable/?reqid=19&step=2"
        ),
        close_date=close_date,
        platform=Platform.generic,
    )


@pytest.fixture
def source_failure_contract(close_date) -> ContractInput:
    """Contract with a clearly broken/risky source."""
    return ContractInput(
        question="Will Elon Musk tweet about Dogecoin in December 2025?",
        resolution_criteria=(
            "Resolves YES if @elonmusk posts any tweet mentioning Dogecoin "
            "or DOGE in December 2025."
        ),
        resolution_source="https://twitter.com/elonmusk",
        close_date=close_date,
        platform=Platform.generic,
    )


@pytest.fixture
def adversarial_contract(close_date) -> ContractInput:
    """Contract with textual exploit surfaces."""
    return ContractInput(
        question="Will Company X complete its merger with Company Y by Q3 2025?",
        resolution_criteria=(
            "Resolves YES if the merger between Company X and Company Y "
            "is completed, including all necessary regulatory approvals. "
            "Resolution based on major news sources."
        ),
        resolution_source="Major financial news outlets including Bloomberg and Reuters",
        close_date=close_date,
        platform=Platform.generic,
    )


# ---------------------------------------------------------------------------
# Parsed contract fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def parsed_sample_contract(sample_contract) -> ParsedContract:
    """Pre-parsed version of sample_contract for analyzer unit tests."""
    contract_id = uuid.uuid4()
    return ParsedContract(
        contract_id=contract_id,
        question=sample_contract.question,
        resolution_criteria=sample_contract.resolution_criteria,
        resolution_source=sample_contract.resolution_source,
        close_date=sample_contract.close_date,
        named_entities=[
            NamedEntity(
                text="US GDP",
                entity_type="ORG",
                context="Will the US GDP growth exceed 2% in 2025?",
                ambiguity_risk=False,
            )
        ],
        thresholds=[
            Threshold(
                raw_text="exceed 2%",
                value=2.0,
                unit="percent",
                data_series="US GDP growth rate",
                revision_risk=True,
                single_point_risk=False,
            )
        ],
        timeframes=[
            Timeframe(
                raw_text="end of year",
                parsed_date=None,
                timezone_specified=False,
                ambiguity_note="'End of year' has no timezone — could be Dec 31 EST, UTC, or local",
            )
        ],
        key_terms=[
            KeyTerm(
                term="exceeds",
                context="US GDP growth exceeds 2%",
                ambiguity_type="multiple_meanings",
                note="Ambiguous — strictly greater than, or greater than or equal to?",
            ),
            KeyTerm(
                term="official government data",
                context="Resolution will be based on official government data",
                ambiguity_type="undefined",
                note="Which agency, which release, which methodology?",
            ),
        ],
        source_url="https://www.bea.gov/data/gdp/gross-domestic-product",
    )


# ---------------------------------------------------------------------------
# Finding fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def sample_finding() -> Finding:
    return Finding(
        id=uuid.uuid4(),
        category=VulnerabilityCategory.definitional_ambiguity,
        severity=Severity.high,
        description=(
            "The term 'exceeds 2%' is ambiguous. "
            "It is unclear whether this means strictly greater than 2.0% "
            "or greater than or equal to 2.0%. If GDP prints at exactly 2.000%, "
            "the resolution is indeterminate under the current language."
        ),
        affected_clause="US GDP growth exceeds 2%",
        rewrite=(
            "US real GDP growth (annualised, advance estimate) is strictly greater "
            "than 2.0% (i.e., 2.001% or higher, with no rounding to the nearest "
            "tenth of a percentage point)."
        ),
        evidence=["Historical GDP prints at exact round numbers: Q2 2019 = 2.0%, Q4 2020 = 4.0%"],
        confidence=0.95,
    )


@pytest.fixture
def multi_finding_list(sample_finding) -> list[Finding]:
    """A realistic set of findings across severities."""
    return [
        Finding(
            id=uuid.uuid4(),
            category=VulnerabilityCategory.source_failure,
            severity=Severity.critical,
            description="BEA GDP page has changed URL 3 times since 2020.",
            affected_clause="https://www.bea.gov/data/gdp/gross-domestic-product",
            rewrite="Use the BEA's stable API endpoint: https://apps.bea.gov/api/",
            evidence=["URL changed in 2021, 2022, and 2023"],
            confidence=0.9,
        ),
        sample_finding,
        Finding(
            id=uuid.uuid4(),
            category=VulnerabilityCategory.threshold_gaming,
            severity=Severity.high,
            description="GDP advance estimate is revised twice after initial release.",
            affected_clause="exceed 2% in 2025",
            rewrite="The BEA advance estimate published within 30 days of quarter end. No revisions apply.",
            evidence=["Average revision magnitude: 0.5 percentage points"],
            confidence=0.98,
        ),
        Finding(
            id=uuid.uuid4(),
            category=VulnerabilityCategory.timing_ambiguity,
            severity=Severity.medium,
            description="'End of year' has no timezone specification.",
            affected_clause="end of year",
            rewrite="11:59:59 PM UTC on December 31, 2025.",
            evidence=[],
            confidence=0.85,
        ),
        Finding(
            id=uuid.uuid4(),
            category=VulnerabilityCategory.definitional_ambiguity,
            severity=Severity.low,
            description="'GDP growth' could mean real or nominal.",
            affected_clause="US GDP growth",
            rewrite="US real GDP growth (inflation-adjusted, SAAR)",
            evidence=[],
            confidence=0.7,
        ),
    ]


# ---------------------------------------------------------------------------
# App / HTTP fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_llm() -> MockLLMClient:
    return make_mock_llm()


@pytest.fixture
def mock_enrichment() -> MockEnrichmentClient:
    return MockEnrichmentClient()


@pytest_asyncio.fixture
async def async_client():
    """
    AsyncClient pointed at the FastAPI app with mocked dependencies.
    DB and Redis are not initialised — routes that need them must mock separately.
    """
    from api.dependencies import require_api_key_with_rate_limit
    from api.main import app

    # Override auth so tests don't need a real API key
    app.dependency_overrides[require_api_key_with_rate_limit] = lambda: "test-key"

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client

    app.dependency_overrides.clear()
