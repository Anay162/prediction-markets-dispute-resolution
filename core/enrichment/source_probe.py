"""
core/enrichment/source_probe.py

Probes a resolution source URL for liveness and checks the
Wayback Machine CDX API for archival history.

Used by SourceFailureAnalyzer._post_process_findings().
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from typing import Any

import httpx

logger = logging.getLogger(__name__)

WAYBACK_CDX_URL = "http://web.archive.org/cdx/search/cdx"
PROBE_TIMEOUT_SECONDS = 10
WAYBACK_TIMEOUT_SECONDS = 15


async def probe_source(url: str) -> dict[str, Any]:
    """
    Probe a URL for liveness and Wayback availability.
    Returns a dict with keys:
        status: int | None          HTTP status code, or None on timeout/error
        redirect_chain: list[str]   URLs followed during redirects
        final_url: str              Final URL after redirects
        content_type: str | None    Content-Type header
        wayback_available: bool     Whether Wayback has snapshots
        wayback_snapshot_count: int
        wayback_last_snapshot: str | None  ISO datetime of most recent snapshot
        probed_at: str              ISO datetime of this probe
    """
    result: dict[str, Any] = {
        "status": None,
        "redirect_chain": [],
        "final_url": url,
        "content_type": None,
        "wayback_available": False,
        "wayback_snapshot_count": 0,
        "wayback_last_snapshot": None,
        "probed_at": datetime.now(UTC).isoformat(),
    }

    # Run HTTP probe and Wayback check concurrently
    http_task = asyncio.create_task(_http_probe(url))
    wayback_task = asyncio.create_task(_wayback_check(url))

    http_result, wayback_result = await asyncio.gather(
        http_task, wayback_task, return_exceptions=True
    )

    if isinstance(http_result, dict):
        result.update(http_result)
    else:
        logger.warning(f"HTTP probe failed for {url}: {http_result}")

    if isinstance(wayback_result, dict):
        result.update(wayback_result)
    else:
        logger.warning(f"Wayback check failed for {url}: {wayback_result}")

    return result


async def _http_probe(url: str) -> dict[str, Any]:
    """HEAD request with redirect tracking."""
    redirect_chain: list[str] = []

    async with httpx.AsyncClient(
        follow_redirects=True,
        timeout=PROBE_TIMEOUT_SECONDS,
        headers={"User-Agent": "ContractAuditor/1.0 (resolution-source-check)"},
    ) as client:
        response = await client.head(url)
        # Capture redirect history
        for r in response.history:
            redirect_chain.append(str(r.url))

        return {
            "status": response.status_code,
            "redirect_chain": redirect_chain,
            "final_url": str(response.url),
            "content_type": response.headers.get("content-type"),
        }


async def _wayback_check(url: str) -> dict[str, Any]:
    """
    Query the Wayback Machine CDX API for snapshot history.
    CDX API docs: https://github.com/internetarchive/wayback/tree/master/wayback-cdx-server
    """
    params = {
        "url": url,
        "output": "json",
        "fl": "timestamp,statuscode",
        "limit": "100",
        "filter": "statuscode:200",
        "collapse": "timestamp:6",  # Collapse by month to avoid huge responses
    }
    async with httpx.AsyncClient(timeout=WAYBACK_TIMEOUT_SECONDS) as client:
        response = await client.get(WAYBACK_CDX_URL, params=params)

    if response.status_code != 200:
        return {
            "wayback_available": False,
            "wayback_snapshot_count": 0,
            "wayback_last_snapshot": None,
        }

    rows = response.json()
    # First row is the header ["timestamp", "statuscode"]
    data_rows = rows[1:] if rows and rows[0] == ["timestamp", "statuscode"] else rows
    count = len(data_rows)

    last_snapshot = None
    if data_rows:
        # Timestamps are in format YYYYMMDDHHmmss
        last_ts = data_rows[-1][0]
        try:
            dt = datetime.strptime(str(last_ts), "%Y%m%d%H%M%S")
            last_snapshot = dt.isoformat()
        except ValueError:
            last_snapshot = str(last_ts)

    return {
        "wayback_available": count > 0,
        "wayback_snapshot_count": count,
        "wayback_last_snapshot": last_snapshot,
    }
