"""
integrations/external_apis/opencorporates.py

OpenCorporates company search and entity lookup client.
Used by the scope creep enrichment to detect dissolved, inactive,
or recently acquired entities.

API docs: https://api.opencorporates.com/documentation/API-Reference
Free tier: 500 requests/month unauthenticated, more with API key.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)

BASE_URL = "https://api.opencorporates.com/v0.4"
TIMEOUT = 12


async def search_company(
    name: str,
    jurisdiction_code: str | None = None,
    api_key: str | None = None,
    per_page: int = 5,
) -> list[dict[str, Any]]:
    """
    Search for companies by name.
    Returns a list of company dicts from OpenCorporates.
    """
    params: dict[str, Any] = {
        "q": name,
        "format": "json",
        "per_page": per_page,
    }
    if jurisdiction_code:
        params["jurisdiction_code"] = jurisdiction_code
    if api_key:
        params["api_token"] = api_key

    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            response = await client.get(f"{BASE_URL}/companies/search", params=params)

        if response.status_code == 429:
            logger.warning("OpenCorporates rate limit hit")
            return []
        if response.status_code != 200:
            return []

        data = response.json()
        companies = data.get("results", {}).get("companies", [])
        return [c.get("company", {}) for c in companies if "company" in c]

    except Exception as e:
        logger.debug(f"OpenCorporates search failed for '{name}': {e}")
        return []


async def get_company(
    company_number: str,
    jurisdiction_code: str,
    api_key: str | None = None,
) -> dict[str, Any] | None:
    """
    Fetch a specific company by its OpenCorporates identifier.
    """
    params: dict = {"format": "json"}
    if api_key:
        params["api_token"] = api_key

    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            response = await client.get(
                f"{BASE_URL}/companies/{jurisdiction_code}/{company_number}",
                params=params,
            )
        if response.status_code != 200:
            return None
        data = response.json()
        return data.get("results", {}).get("company")
    except Exception as e:
        logger.debug(f"OpenCorporates fetch failed: {e}")
        return None


def extract_corporate_actions(company: dict[str, Any]) -> list[dict[str, Any]]:
    """
    Extract corporate action signals from an OpenCorporates company dict.
    Returns a list of action dicts: {type, description, source, date}
    """
    actions = []
    status = company.get("current_status", "")
    dissolution_date = company.get("dissolution_date")

    if status in ("Dissolved", "Inactive", "Liquidation", "Struck Off"):
        actions.append(
            {
                "type": "dissolution",
                "description": f"Company status: {status}",
                "source": "OpenCorporates",
                "date": dissolution_date,
            }
        )

    # Check for registered agent changes — often signal M&A prep
    for officer in company.get("officers", []):
        o = officer.get("officer", {})
        if o.get("position", "").lower() in ("registered agent", "statutory agent"):
            if o.get("end_date"):
                actions.append(
                    {
                        "type": "agent_change",
                        "description": f"Registered agent change detected (end date: {o['end_date']})",
                        "source": "OpenCorporates",
                        "date": o.get("end_date"),
                    }
                )

    return actions
