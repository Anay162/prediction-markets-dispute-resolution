"""
core/enrichment/client.py

Facade that the analyzers use to access all enrichment data.
Provides a single object with clean methods, hiding the underlying
HTTP clients and DB queries behind a simple interface.

The analyzers call:
    enrichment.probe_source(url)
    enrichment.lookup_entity(name)
    enrichment.find_similar_disputes(text, category, limit)
"""
from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from core.enrichment.source_probe import probe_source
from core.enrichment.entity_lookup import lookup_entity
from core.enrichment.dispute_lookup import find_similar_disputes

logger = logging.getLogger(__name__)


class EnrichmentClient:
    """
    Facade for all enrichment operations.
    Injected into analyzers at runtime by the pipeline.
    """

    def __init__(
        self,
        db: AsyncSession,
        llm_client,                         # For generating query embeddings
        opencorporates_api_key: str | None = None,
    ):
        self._db = db
        self._llm = llm_client
        self._oc_key = opencorporates_api_key
        self._embedding_cache: dict[str, list[float]] = {}

    async def probe_source(self, url: str) -> dict[str, Any]:
        """
        Check if a resolution source URL is alive and has Wayback history.
        """
        return await probe_source(url)

    async def lookup_entity(self, entity_name: str) -> dict[str, Any]:
        """
        Look up a named entity in OpenCorporates and SEC EDGAR.
        """
        return await lookup_entity(entity_name, self._oc_key)

    async def find_similar_disputes(
        self,
        contract_text: str,
        category: str | None = None,
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        """
        Find historically disputed contracts similar to the given text.
        Generates an embedding for the query text, then does pgvector search.
        """
        embedding = await self._get_embedding(contract_text)
        if not embedding:
            return []
        return await find_similar_disputes(
            db=self._db,
            query_embedding=embedding,
            category=category,
            limit=limit,
        )

    async def _get_embedding(self, text: str) -> list[float] | None:
        """Generate an embedding, using a simple in-request cache."""
        # Truncate to avoid embedding token limits
        key = text[:200]
        if key in self._embedding_cache:
            return self._embedding_cache[key]
        try:
            embedding = await self._llm.embed(text[:8000])
            self._embedding_cache[key] = embedding
            return embedding
        except Exception as e:
            logger.warning(f"Embedding generation failed: {e}")
            return None
