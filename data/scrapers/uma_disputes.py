"""
data/scrapers/uma_disputes.py

Pulls UMA Optimistic Oracle dispute records from The Graph subgraph.
UMA is used by Polymarket and other platforms for dispute resolution.
All data is public on-chain.
"""
from __future__ import annotations

import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)

UMA_SUBGRAPH = (
    "https://api.thegraph.com/subgraphs/name/umaprotocol/mainnet-optimistic-oracle-v2"
)

DISPUTE_QUERY = """
{
  requestPrices(
    first: %d
    skip: %d
    where: { disputed: true }
    orderBy: requestTime
    orderDirection: desc
  ) {
    id
    identifier
    ancillaryData
    requestTime
    requester
    proposedPrice
    disputedPrice
    settled
    settlementPrice
    currency
    reward
  }
}
"""


async def scrape_uma_disputes(limit: int = 300) -> list[dict[str, Any]]:
    """
    Pull disputed price requests from UMA's Optimistic Oracle subgraph.
    """
    disputes = []
    page_size = 100
    skip = 0

    async with httpx.AsyncClient(timeout=30) as client:
        while skip < limit:
            try:
                response = await client.post(
                    UMA_SUBGRAPH,
                    json={"query": DISPUTE_QUERY % (page_size, skip)},
                )
                if response.status_code != 200:
                    break

                data = response.json()
                records = data.get("data", {}).get("requestPrices", [])
                if not records:
                    break

                for record in records:
                    disputes.append(_normalise(record))

                skip += page_size
                if len(records) < page_size:
                    break

            except Exception as e:
                logger.error(f"UMA subgraph error (skip={skip}): {e}")
                break

    logger.info(f"UMA scraper found {len(disputes)} disputed requests")
    return disputes


def _normalise(record: dict) -> dict[str, Any]:
    ancillary = record.get("ancillaryData", "") or ""
    # ancillaryData often contains the market question as a hex-encoded string
    question = _decode_hex(ancillary) if ancillary.startswith("0x") else ancillary

    return {
        "source_platform": "uma",
        "external_id": f"uma_{record['id']}",
        "question": question[:2000],
        "resolution_criteria": None,
        "resolution_source": None,
        "failure_category": None,
        "dispute_reason": (
            f"Proposed: {record.get('proposedPrice')} | "
            f"Settled: {record.get('settlementPrice')}"
        ),
        "resolution": str(record.get("settlementPrice")),
        "raw_data": record,
        "dispute_date": None,
    }


def _decode_hex(hex_str: str) -> str:
    try:
        return bytes.fromhex(hex_str[2:]).decode("utf-8", errors="replace")
    except Exception:
        return hex_str
