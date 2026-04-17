"""
data/embeddings/vector_store.py

pgvector similarity search queries for contracts and disputes.
All queries use cosine distance (<=> operator) via pgvector.

This module sits between the raw SQL in dispute_lookup.py and
the higher-level enrichment client, providing typed interfaces
and connection management.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

# Cosine similarity threshold — below this we consider results not similar enough
DEFAULT_SIMILARITY_THRESHOLD = 0.75


async def find_similar_contracts(
    db: AsyncSession,
    query_embedding: list[float],
    limit: int = 5,
    exclude_contract_id: str | None = None,
    similarity_threshold: float = DEFAULT_SIMILARITY_THRESHOLD,
) -> list[dict[str, Any]]:
    """
    Find contracts similar to the query embedding using cosine similarity.
    Useful for "have we audited something like this before?" lookups.
    """
    embedding_str = _embedding_to_str(query_embedding)
    exclude_clause = "AND id != :exclude_id" if exclude_contract_id else ""

    params: dict[str, Any] = {
        "embedding": embedding_str,
        "threshold": 1.0 - similarity_threshold,
        "limit": limit,
    }
    if exclude_contract_id:
        params["exclude_id"] = exclude_contract_id

    sql = text(f"""
        SELECT
            id,
            question,
            platform,
            close_date,
            1 - (embedding <=> :embedding::vector) AS similarity_score
        FROM contracts
        WHERE embedding IS NOT NULL
          AND (embedding <=> :embedding::vector) <= :threshold
          {exclude_clause}
        ORDER BY embedding <=> :embedding::vector
        LIMIT :limit
    """)

    try:
        result = await db.execute(sql, params)
        rows = result.fetchall()
        return [
            {
                "id": str(row.id),
                "question": row.question,
                "platform": row.platform,
                "close_date": str(row.close_date),
                "similarity_score": float(row.similarity_score),
            }
            for row in rows
        ]
    except Exception as e:
        logger.warning(f"Contract similarity search failed: {e}")
        return []


async def find_similar_disputes(
    db: AsyncSession,
    query_embedding: list[float],
    failure_category: str | None = None,
    limit: int = 5,
    similarity_threshold: float = DEFAULT_SIMILARITY_THRESHOLD,
) -> list[dict[str, Any]]:
    """
    Find historically disputed contracts similar to the query embedding.
    Optionally filter by failure_category to get category-specific precedents.
    """
    embedding_str = _embedding_to_str(query_embedding)
    category_clause = "AND failure_category = :category" if failure_category else ""

    params: dict[str, Any] = {
        "embedding": embedding_str,
        "threshold": 1.0 - similarity_threshold,
        "limit": limit,
    }
    if failure_category:
        params["category"] = failure_category

    sql = text(f"""
        SELECT
            question,
            dispute_reason,
            failure_category,
            source_platform,
            resolution,
            dispute_date,
            1 - (embedding <=> :embedding::vector) AS similarity_score
        FROM disputes
        WHERE embedding IS NOT NULL
          AND (embedding <=> :embedding::vector) <= :threshold
          {category_clause}
        ORDER BY embedding <=> :embedding::vector
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
                "platform": row.source_platform,
                "resolution": row.resolution,
                "dispute_date": str(row.dispute_date) if row.dispute_date else None,
                "similarity_score": float(row.similarity_score),
            }
            for row in rows
        ]
    except Exception as e:
        logger.warning(f"Dispute similarity search failed: {e}")
        return []


async def upsert_contract_embedding(
    db: AsyncSession,
    contract_id: str,
    embedding: list[float],
) -> None:
    """Update the embedding for a contract row."""
    embedding_str = _embedding_to_str(embedding)
    await db.execute(
        text("UPDATE contracts SET embedding = :emb::vector WHERE id = :id"),
        {"emb": embedding_str, "id": contract_id},
    )


async def upsert_dispute_embedding(
    db: AsyncSession,
    dispute_id: str,
    embedding: list[float],
) -> None:
    """Update the embedding for a dispute row."""
    embedding_str = _embedding_to_str(embedding)
    await db.execute(
        text("UPDATE disputes SET embedding = :emb::vector WHERE id = :id"),
        {"emb": embedding_str, "id": dispute_id},
    )


def _embedding_to_str(embedding: list[float]) -> str:
    """Convert a float list to the pgvector literal format: '[0.1,0.2,...]'"""
    return "[" + ",".join(str(v) for v in embedding) + "]"
