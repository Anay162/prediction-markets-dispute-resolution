"""
data/scrapers/manifold_resolutions.py

Scrapes Manifold Markets for resolved markets with N/A or ambiguous resolutions.
Manifold's API is fully public.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

import httpx

logger = logging.getLogger(__name__)

MANIFOLD_API = "https://api.manifold.markets/v0"


async def scrape_manifold_resolutions(limit: int = 500) -> list[dict[str, Any]]:
    """
    Fetch Manifold markets that resolved N/A or had ambiguous resolution.
    N/A resolutions are the strongest signal of contract quality failure.
    """
    disputes = []
    before: str | None = None

    async with httpx.AsyncClient(timeout=20) as client:
        fetched = 0
        while fetched < limit:
            params: dict = {"limit": 100, "sort": "resolve-time", "order": "desc"}
            if before:
                params["before"] = before

            try:
                response = await client.get(f"{MANIFOLD_API}/markets", params=params)
                if response.status_code != 200:
                    break
                markets = response.json()
                if not markets:
                    break

                for market in markets:
                    if market.get("resolution") in ("NA", "CANCEL", "MKT"):
                        dispute = _normalise(market)
                        if dispute:
                            disputes.append(dispute)

                before = markets[-1].get("id")
                fetched += len(markets)
                if len(markets) < 100:
                    break

            except Exception as e:
                logger.error(f"Manifold scrape error: {e}")
                break

    logger.info(f"Manifold scraper found {len(disputes)} NA/cancelled markets")
    return disputes


def _normalise(market: dict) -> dict[str, Any] | None:
    question = market.get("question", "")
    if not question:
        return None

    resolution = market.get("resolution", "")
    reason_map = {
        "NA": "Market resolved N/A — question became unresolvable or inapplicable",
        "CANCEL": "Market was cancelled before resolution",
        "MKT": "Market resolved at probability rather than YES/NO — ambiguous outcome",
    }

    return {
        "source_platform": "manifold",
        "external_id": f"manifold_{market.get('id', '')}",
        "question": question,
        "resolution_criteria": market.get("description", ""),
        "resolution_source": None,
        "failure_category": None,
        "dispute_reason": reason_map.get(resolution, f"Resolution: {resolution}"),
        "resolution": resolution,
        "raw_data": market,
        "dispute_date": _ts_to_date(market.get("resolutionTime")),
    }


def _ts_to_date(ts_ms: int | None):
    if not ts_ms:
        return None
    try:
        return datetime.fromtimestamp(ts_ms / 1000).date()
    except Exception:
        return None
