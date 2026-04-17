"""
core/enrichment/entity_lookup.py

Looks up named entities (companies) in OpenCorporates and SEC EDGAR
to surface recent corporate actions, M&A activity, or status changes.

Used by ScopeCreepAnalyzer._post_process_findings().
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)

OPENCORPORATES_BASE = "https://api.opencorporates.com/v0.4"
EDGAR_FULL_TEXT_SEARCH = "https://efts.sec.gov/LATEST/search-index"
EDGAR_COMPANY_SEARCH = "https://www.sec.gov/cgi-bin/browse-edgar"
REQUEST_TIMEOUT = 12


async def lookup_entity(
    entity_name: str,
    opencorporates_api_key: str | None = None,
) -> dict[str, Any]:
    """
    Look up a named entity and return any known corporate actions.

    Returns:
        recent_corporate_actions: list of {type, description, source, date}
        m_and_a_rumors: str | None
        jurisdiction: str | None
        status: str | None   ("active" | "dissolved" | "unknown")
        sec_filings: list of recent 8-K / S-4 / DEF14A filings (M&A signals)
    """
    result: dict[str, Any] = {
        "recent_corporate_actions": [],
        "m_and_a_rumors": None,
        "jurisdiction": None,
        "status": "unknown",
        "sec_filings": [],
    }

    # Run OpenCorporates and SEC EDGAR in parallel
    import asyncio

    oc_task = asyncio.create_task(_opencorporates_lookup(entity_name, opencorporates_api_key))
    sec_task = asyncio.create_task(_edgar_lookup(entity_name))

    oc_result, sec_result = await asyncio.gather(oc_task, sec_task, return_exceptions=True)

    if isinstance(oc_result, dict):
        result.update(oc_result)
    else:
        logger.debug(f"OpenCorporates lookup failed for '{entity_name}': {oc_result}")

    if isinstance(sec_result, dict):
        result["sec_filings"] = sec_result.get("filings", [])
        # Surface M&A signals from SEC filings
        ma_filings = [
            f
            for f in result["sec_filings"]
            if f.get("form") in ("S-4", "DEF14A", "SC 13D", "SC TO-T")
        ]
        if ma_filings:
            result["recent_corporate_actions"].extend(
                [
                    {
                        "type": f["form"],
                        "description": f"SEC filing {f['form']}: {f.get('description', 'M&A-related filing')}",
                        "source": "SEC EDGAR",
                        "date": f.get("filed"),
                    }
                    for f in ma_filings[:3]
                ]
            )
    else:
        logger.debug(f"SEC EDGAR lookup failed for '{entity_name}': {sec_result}")

    return result


async def _opencorporates_lookup(
    entity_name: str,
    api_key: str | None,
) -> dict[str, Any]:
    """Search OpenCorporates for the company and return status."""
    params: dict[str, Any] = {
        "q": entity_name,
        "format": "json",
        "per_page": 5,
    }
    if api_key:
        params["api_token"] = api_key

    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
        response = await client.get(
            f"{OPENCORPORATES_BASE}/companies/search",
            params=params,
        )
    if response.status_code != 200:
        return {}

    data = response.json()
    companies = data.get("results", {}).get("companies", [])
    if not companies:
        return {}

    # Take best match (first result)
    company = companies[0].get("company", {})
    actions = []

    # Map OpenCorporates dissolution status to a corporate action
    if company.get("current_status") in ("Dissolved", "Inactive", "Liquidation"):
        actions.append(
            {
                "type": "dissolution",
                "description": f"Company status: {company['current_status']}",
                "source": "OpenCorporates",
                "date": company.get("dissolution_date"),
            }
        )

    return {
        "jurisdiction": company.get("jurisdiction_code"),
        "status": "dissolved" if actions else "active",
        "recent_corporate_actions": actions,
    }


async def _edgar_lookup(entity_name: str) -> dict[str, Any]:
    """
    Search SEC EDGAR full-text search for recent M&A-signal filings.
    Looks for 8-K (material events), S-4 (mergers), DEF14A (proxy/acquisition votes).
    """
    params = {
        "q": f'"{entity_name}"',
        "dateRange": "custom",
        "startdt": _one_year_ago(),
        "forms": "8-K,S-4,DEF14A,SC 13D,SC TO-T",
        "_source": "file_date,form_type,display_names,period_of_report",
    }
    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
        response = await client.get(EDGAR_FULL_TEXT_SEARCH, params=params)
    if response.status_code != 200:
        return {"filings": []}

    data = response.json()
    hits = data.get("hits", {}).get("hits", [])
    filings = []
    for hit in hits[:10]:
        src = hit.get("_source", {})
        filings.append(
            {
                "form": src.get("form_type", ""),
                "description": src.get("display_names", [""])[0]
                if src.get("display_names")
                else "",
                "filed": src.get("file_date", ""),
                "period": src.get("period_of_report", ""),
            }
        )
    return {"filings": filings}


def _one_year_ago() -> str:
    from datetime import date, timedelta

    return (date.today() - timedelta(days=365)).isoformat()
