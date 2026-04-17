"""
core/enrichment/dispute_lookup.py

Finds historically disputed contracts similar to the one being audited,
using vector similarity search against the disputes table.

Used by AdversarialResolutionAnalyzer and as general enrichment context.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


async def find_similar_disputes(
    db: AsyncSession,
    query_embedding: list[float],
    category: str | None = None,
    limit: int = 5,
    similarity_threshold: float = 0.75,
) -> list[dict[str, Any]]:
    """
    Find disputes similar to the current contract using cosine similarity
    on the embedding column.

    Args:
        db: Async SQLAlchemy session
        query_embedding: 1536-dim embedding of the contract being audited
        category: Optional VulnerabilityCategory to filter by failure_category
        limit: Max number of results
        similarity_threshold: Minimum cosine similarity (0-1)

    Returns:
        List of dicts with keys: question, dispute_reason, failure_category,
        platform, resolution, similarity_score
    """
    # pgvector cosine distance operator: <=>
    # cosine_similarity = 1 - cosine_distance
    embedding_str = "[" + ",".join(str(v) for v in query_embedding) + "]"

    category_filter = ""
    params: dict[str, Any] = {
        "embedding": embedding_str,
        "threshold": 1.0 - similarity_threshold,
        "limit": limit,
    }

    if category:
        category_filter = "AND failure_category = :category"
        params["category"] = category

    sql = text(f"""
        SELECT
            question,
            dispute_reason,
            failure_category,
            source_platform AS platform,
            resolution,
            1 - (embedding::vector <=> :embedding::vector) AS similarity_score
        FROM disputes
        WHERE embedding IS NOT NULL
          AND (embedding::vector <=> :embedding::vector) <= :threshold
          {category_filter}
        ORDER BY embedding::vector <=> :embedding::vector
        LIMIT :limit
    """)

    try:
        result = await db.execute(sql, params)
        rows = result.fetchall()
        return [
            {
                "question": row.question,
                "dispute_reason": row.dispute_reason,
                "failure_category": row.failure_category,
                "platform": row.platform,
                "resolution": row.resolution,
                "similarity_score": float(row.similarity_score),
            }
            for row in rows
        ]
    except Exception as e:
        logger.warning(f"Dispute similarity search failed: {e}")
        return []


async def get_dispute_stats(db: AsyncSession) -> dict[str, Any]:
    """
    Returns aggregate statistics about the dispute corpus.
    Used for report context: "Based on N historical disputes..."
    """
    sql = text("""
        SELECT
            COUNT(*) AS total,
            COUNT(DISTINCT source_platform) AS platforms,
            COUNT(CASE WHEN failure_category IS NOT NULL THEN 1 END) AS labeled,
            MAX(scraped_at) AS last_scraped
        FROM disputes
    """)
    result = await db.execute(sql)
    row = result.fetchone()
    if not row:
        return {"total": 0, "platforms": 0, "labeled": 0, "last_scraped": None}
    return {
        "total": row.total,
        "platforms": row.platforms,
        "labeled": row.labeled,
        "last_scraped": row.last_scraped,
    }
