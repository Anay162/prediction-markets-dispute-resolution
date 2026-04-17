"""
integrations/external_apis/polygon.py

Polygon.io client for ticker status and delisting checks.
Used by the scope creep enrichment to detect whether a stock
referenced in a contract is still actively traded.

API docs: https://polygon.io/docs
Free tier supports ticker details and recent status checks.
"""
from __future__ import annotations

import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)

BASE_URL = "https://api.polygon.io/v3"
TIMEOUT = 10


async def get_ticker_details(
    ticker: str,
    api_key: str,
) -> dict[str, Any] | None:
    """
    Fetch ticker details from Polygon.io.
    Returns the ticker details dict or None if not found / API error.

    Key fields in response:
        active: bool          — False if delisted
        name: str             — Company name
        market: str           — "stocks", "crypto", etc.
        primary_exchange: str — e.g. "XNAS" (NASDAQ)
        type: str             — "CS" (common stock), etc.
        cik: str              — SEC CIK if available
        composite_figi: str
        list_date: str
        delisted_utc: str | None  — Set if delisted
    """
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            response = await client.get(
                f"{BASE_URL}/reference/tickers/{ticker.upper()}",
                params={"apiKey": api_key},
            )

        if response.status_code == 404:
            logger.debug(f"Ticker {ticker} not found on Polygon.io")
            return None
        if response.status_code != 200:
            logger.debug(f"Polygon.io returned {response.status_code} for {ticker}")
            return None

        data = response.json()
        return data.get("results")

    except Exception as e:
        logger.debug(f"Polygon.io ticker lookup failed for {ticker}: {e}")
        return None


async def is_ticker_active(ticker: str, api_key: str) -> dict[str, Any]:
    """
    Check whether a ticker is actively traded.

    Returns:
        active: bool
        delisted: bool
        delisted_date: str | None
        name: str | None
        exchange: str | None
        note: str
    """
    details = await get_ticker_details(ticker, api_key)

    if details is None:
        return {
            "active": False,
            "delisted": False,
            "delisted_date": None,
            "name": None,
            "exchange": None,
            "note": f"Ticker '{ticker}' not found — may be delisted, renamed, or invalid",
        }

    active = details.get("active", False)
    delisted_utc = details.get("delisted_utc")

    return {
        "active": active,
        "delisted": not active or bool(delisted_utc),
        "delisted_date": delisted_utc,
        "name": details.get("name"),
        "exchange": details.get("primary_exchange"),
        "note": (
            f"Ticker '{ticker}' is {'active' if active else 'INACTIVE'} "
            f"on {details.get('primary_exchange', 'unknown exchange')}"
            + (f" (delisted: {delisted_utc})" if delisted_utc else "")
        ),
    }


async def search_tickers(
    query: str,
    api_key: str,
    limit: int = 5,
) -> list[dict[str, Any]]:
    """
    Search for tickers by company name or ticker symbol.
    Useful when the contract mentions a company name but not its ticker.
    """
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            response = await client.get(
                f"{BASE_URL}/reference/tickers",
                params={
                    "search": query,
                    "active": "true",
                    "limit": limit,
                    "apiKey": api_key,
                },
            )
        if response.status_code != 200:
            return []
        return response.json().get("results", [])
    except Exception as e:
        logger.debug(f"Polygon.io ticker search failed for '{query}': {e}")
        return []
