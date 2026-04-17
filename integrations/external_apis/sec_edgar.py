"""
integrations/external_apis/sec_edgar.py

SEC EDGAR full-text search and company filing client.
Used to surface recent M&A-signal filings (8-K, S-4, DEF14A, SC TO-T)
for named entities in contracts.

All EDGAR APIs are free and require no authentication.
EDGAR full-text search: https://efts.sec.gov/LATEST/search-index
EDGAR company search:   https://www.sec.gov/cgi-bin/browse-edgar
"""
from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Any

import httpx

logger = logging.getLogger(__name__)

FULL_TEXT_SEARCH = "https://efts.sec.gov/LATEST/search-index"
COMPANY_SEARCH = "https://efts.sec.gov/LATEST/search-index"
COMPANY_FACTS = "https://data.sec.gov/submissions"
TIMEOUT = 15

# Filing types that signal M&A activity
MA_FILING_TYPES = frozenset(["S-4", "DEF14A", "SC TO-T", "SC 13D", "SC 13G/A", "8-K"])


async def search_filings(
    entity_name: str,
    form_types: list[str] | None = None,
    days_back: int = 365,
) -> list[dict[str, Any]]:
    """
    Search EDGAR for recent filings mentioning an entity name.
    Defaults to M&A-signal form types over the past year.

    Returns list of filing dicts: {form, description, filed, period, cik}
    """
    forms = ",".join(form_types or list(MA_FILING_TYPES))
    start_date = (date.today() - timedelta(days=days_back)).isoformat()

    params = {
        "q": f'"{entity_name}"',
        "dateRange": "custom",
        "startdt": start_date,
        "forms": forms,
        "_source": "file_date,form_type,display_names,period_of_report,entity_id",
        "_size": "20",
    }

    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            response = await client.get(FULL_TEXT_SEARCH, params=params)

        if response.status_code != 200:
            logger.debug(f"EDGAR search returned {response.status_code} for '{entity_name}'")
            return []

        data = response.json()
        hits = data.get("hits", {}).get("hits", [])

        filings = []
        for hit in hits:
            src = hit.get("_source", {})
            display_names = src.get("display_names", [])
            filings.append({
                "form": src.get("form_type", ""),
                "description": display_names[0] if display_names else entity_name,
                "filed": src.get("file_date", ""),
                "period": src.get("period_of_report", ""),
                "cik": src.get("entity_id", ""),
            })
        return filings

    except Exception as e:
        logger.debug(f"EDGAR search failed for '{entity_name}': {e}")
        return []


async def get_company_cik(entity_name: str) -> str | None:
    """
    Look up a company's CIK (Central Index Key) by name.
    Returns the CIK string or None if not found.
    """
    params = {
        "q": entity_name,
        "dateRange": "custom",
        "startdt": "2000-01-01",
        "_source": "entity_id,display_names",
        "_size": "5",
    }
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            response = await client.get(FULL_TEXT_SEARCH, params=params)
        if response.status_code != 200:
            return None
        hits = response.json().get("hits", {}).get("hits", [])
        if hits:
            return hits[0].get("_source", {}).get("entity_id")
        return None
    except Exception as e:
        logger.debug(f"CIK lookup failed for '{entity_name}': {e}")
        return None


def classify_filing_risk(filings: list[dict[str, Any]]) -> str:
    """
    Classify the M&A risk level based on recent filings.
    Returns: "high" | "medium" | "low" | "none"
    """
    if not filings:
        return "none"

    forms = {f["form"] for f in filings}

    # Hard M&A signals
    if forms & {"SC TO-T", "S-4"}:
        return "high"

    # Softer signals
    if forms & {"DEF14A", "SC 13D"}:
        return "medium"

    # 8-K alone could be anything
    if "8-K" in forms:
        return "low"

    return "none"
