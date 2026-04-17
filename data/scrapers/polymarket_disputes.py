"""
data/scrapers/polymarket_disputes.py

Scrapes Polymarket's public dispute/resolution history via their API.
Polymarket uses UMA's Optimistic Oracle for resolution disputes.
All dispute data is on-chain and publicly accessible.
"""

from __future__ import annotations

import hashlib
import logging
from datetime import datetime
from typing import Any

import httpx

logger = logging.getLogger(__name__)

POLYMARKET_GAMMA_API = "https://gamma-api.polymarket.com"
POLYMARKET_CLOB_API = "https://clob.polymarket.com"
REQUEST_TIMEOUT = 20


async def scrape_polymarket_disputes(limit: int = 200) -> list[dict[str, Any]]:
    """
    Fetch resolved markets from Polymarket that had disputes.
    Returns a list of normalised dispute dicts ready for DB insertion.
    """
    disputes = []
    offset = 0
    page_size = 50

    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
        while offset < limit:
            try:
                response = await client.get(
                    f"{POLYMARKET_GAMMA_API}/markets",
                    params={
                        "closed": "true",
                        "limit": page_size,
                        "offset": offset,
                        "order": "end_date_iso",
                        "ascending": "false",
                    },
                )
                if response.status_code != 200:
                    logger.warning(f"Polymarket API returned {response.status_code}")
                    break

                markets = response.json()
                if not markets:
                    break

                for market in markets:
                    # Polymarket surfaces disputed markets via resolution notes
                    dispute_info = _extract_dispute_info(market)
                    if dispute_info:
                        disputes.append(dispute_info)

                offset += page_size
                if len(markets) < page_size:
                    break

            except Exception as e:
                logger.error(f"Error scraping Polymarket (offset={offset}): {e}")
                break

    logger.info(f"Polymarket scraper found {len(disputes)} disputed markets")
    return disputes


def _extract_dispute_info(market: dict) -> dict | None:
    """
    Extract dispute info from a Polymarket market dict.
    Returns None if the market resolved cleanly with no dispute signals.
    """
    question = market.get("question", "")
    description = market.get("description", "")
    resolution_source = market.get("resolutionSource", "")

    # Signals that a market had resolution difficulty
    dispute_signals = [
        "disputed",
        "N/A",
        "unresolvable",
        "ambiguous",
        "cancelled",
        "void",
    ]
    resolution = market.get("resolution", "") or ""
    outcome = market.get("outcome", "") or ""

    has_dispute_signal = any(
        sig.lower() in (resolution + outcome + description).lower() for sig in dispute_signals
    )

    if not has_dispute_signal:
        return None

    external_id = f"polymarket_{market.get('id', hashlib.md5(question.encode()).hexdigest()[:8])}"

    return {
        "source_platform": "polymarket",
        "external_id": external_id,
        "question": question,
        "resolution_criteria": description,
        "resolution_source": resolution_source,
        "failure_category": None,  # Labeled later by classifier
        "dispute_reason": f"Resolution: {resolution}. Outcome: {outcome}",
        "resolution": resolution,
        "raw_data": market,
        "dispute_date": _parse_date(market.get("end_date_iso")),
    }


def _parse_date(date_str: str | None):
    if not date_str:
        return None
    try:
        return datetime.fromisoformat(date_str.replace("Z", "+00:00")).date()
    except Exception:
        return None
