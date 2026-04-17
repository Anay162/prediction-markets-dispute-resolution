"""
data/scrapers/augur_history.py

Loads Augur v2 historical dispute data.
Augur is deprecated but its dispute history is a valuable training corpus —
it was one of the first large-scale prediction markets and accumulated
hundreds of disputed markets between 2018 and 2023.

Data source: Augur's public subgraph on The Graph.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)

AUGUR_SUBGRAPH = "https://api.thegraph.com/subgraphs/name/augurproject/augur-v2-staging"

DISPUTE_QUERY = """
{
  markets(
    first: %d
    skip: %d
    where: { disputeRound_gt: 0 }
    orderBy: creationTime
    orderDirection: desc
  ) {
    id
    description
    extraInfo
    outcomes
    disputeRound
    finalized
    winningPayoutNumerators
    numTicks
    creationTime
    endTime
  }
}
"""


async def scrape_augur_history(limit: int = 500) -> list[dict[str, Any]]:
    """
    Pull disputed markets from the Augur v2 subgraph.
    Markets with disputeRound > 0 had at least one dispute filed.
    """
    disputes = []
    page_size = 100
    skip = 0

    async with httpx.AsyncClient(timeout=30) as client:
        while skip < limit:
            try:
                response = await client.post(
                    AUGUR_SUBGRAPH,
                    json={"query": DISPUTE_QUERY % (page_size, skip)},
                )
                if response.status_code != 200:
                    logger.warning(f"Augur subgraph returned {response.status_code}")
                    break

                data = response.json()
                markets = data.get("data", {}).get("markets", [])
                if not markets:
                    break

                for market in markets:
                    normalised = _normalise(market)
                    if normalised:
                        disputes.append(normalised)

                skip += page_size
                if len(markets) < page_size:
                    break

            except Exception as e:
                logger.error(f"Augur subgraph error (skip={skip}): {e}")
                break

    logger.info(f"Augur scraper found {len(disputes)} disputed markets")
    return disputes


def _normalise(market: dict) -> dict[str, Any] | None:
    description = market.get("description", "")
    if not description:
        return None

    extra_info = market.get("extraInfo", "") or ""
    # extraInfo is often a JSON string with resolution source
    resolution_source = None
    try:
        import json

        extra = json.loads(extra_info)
        resolution_source = extra.get("resolutionSource") or extra.get("source")
    except Exception:
        pass

    return {
        "source_platform": "augur",
        "external_id": f"augur_{market.get('id', '')}",
        "question": description[:2000],
        "resolution_criteria": extra_info[:2000] if extra_info else None,
        "resolution_source": resolution_source,
        "failure_category": None,
        "dispute_reason": (
            f"Dispute rounds: {market.get('disputeRound', 0)}. "
            f"Finalized: {market.get('finalized', False)}"
        ),
        "resolution": str(market.get("winningPayoutNumerators", "")),
        "raw_data": market,
        "dispute_date": None,
    }
