"""
integrations/external_apis/wayback.py

Wayback Machine CDX API client.
Used by the source probe enrichment to check archival history of URLs.

CDX API docs: https://github.com/internetarchive/wayback/tree/master/wayback-cdx-server
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

import httpx

logger = logging.getLogger(__name__)

CDX_ENDPOINT = "http://web.archive.org/cdx/search/cdx"
AVAILABILITY_ENDPOINT = "https://archive.org/wayback/available"
TIMEOUT = 15


async def get_snapshot_history(
    url: str,
    collapse_by: str = "timestamp:6",  # Collapse by month — avoids huge responses
    limit: int = 100,
    status_filter: str = "200",
) -> dict[str, Any]:
    """
    Query Wayback CDX for snapshot history of a URL.

    Returns:
        available: bool
        snapshot_count: int
        first_snapshot: str | None  (ISO datetime)
        last_snapshot: str | None   (ISO datetime)
        snapshots: list[dict]       (timestamp, statuscode pairs)
    """
    params = {
        "url": url,
        "output": "json",
        "fl": "timestamp,statuscode,mimetype",
        "limit": str(limit),
        "collapse": collapse_by,
    }
    if status_filter:
        params["filter"] = f"statuscode:{status_filter}"

    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            response = await client.get(CDX_ENDPOINT, params=params)

        if response.status_code != 200:
            return _empty_result()

        rows = response.json()
        # First row is the header ["timestamp", "statuscode", "mimetype"]
        if not rows or rows[0] == ["timestamp", "statuscode", "mimetype"]:
            data_rows = rows[1:] if len(rows) > 1 else []
        else:
            data_rows = rows

        if not data_rows:
            return _empty_result()

        snapshots = []
        for row in data_rows:
            if len(row) >= 2:
                snapshots.append(
                    {
                        "timestamp": row[0],
                        "statuscode": row[1],
                        "mimetype": row[2] if len(row) > 2 else None,
                        "url": f"https://web.archive.org/web/{row[0]}/{url}",
                    }
                )

        first_iso = _ts_to_iso(snapshots[0]["timestamp"]) if snapshots else None
        last_iso = _ts_to_iso(snapshots[-1]["timestamp"]) if snapshots else None

        return {
            "available": True,
            "snapshot_count": len(snapshots),
            "first_snapshot": first_iso,
            "last_snapshot": last_iso,
            "snapshots": snapshots[:10],  # Return at most 10 for the report
        }

    except Exception as e:
        logger.debug(f"Wayback CDX query failed for {url}: {e}")
        return _empty_result()


async def get_nearest_snapshot(url: str, timestamp: str | None = None) -> dict[str, Any]:
    """
    Get the nearest available Wayback snapshot to a given timestamp.
    If timestamp is None, returns the most recent snapshot.

    Returns:
        available: bool
        url: str | None    (the wayback URL)
        timestamp: str | None
    """
    params: dict[str, str] = {"url": url}
    if timestamp:
        params["timestamp"] = timestamp

    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            response = await client.get(AVAILABILITY_ENDPOINT, params=params)

        data = response.json()
        archived = data.get("archived_snapshots", {}).get("closest", {})
        if not archived or not archived.get("available"):
            return {"available": False, "url": None, "timestamp": None}

        return {
            "available": True,
            "url": archived.get("url"),
            "timestamp": archived.get("timestamp"),
        }
    except Exception as e:
        logger.debug(f"Wayback availability check failed for {url}: {e}")
        return {"available": False, "url": None, "timestamp": None}


def _empty_result() -> dict[str, Any]:
    return {
        "available": False,
        "snapshot_count": 0,
        "first_snapshot": None,
        "last_snapshot": None,
        "snapshots": [],
    }


def _ts_to_iso(ts: str) -> str | None:
    """Convert Wayback timestamp (YYYYMMDDHHmmss) to ISO format."""
    try:
        return datetime.strptime(str(ts), "%Y%m%d%H%M%S").isoformat()
    except ValueError:
        return str(ts)
