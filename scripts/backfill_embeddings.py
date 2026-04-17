"""
scripts/backfill_embeddings.py

Re-generates embeddings for all contracts and/or disputes.
Run this after switching embedding models or after a large data import.

Usage:
    python -m scripts.backfill_embeddings
    python -m scripts.backfill_embeddings --table disputes --batch-size 50
    python -m scripts.backfill_embeddings --table contracts --force   # re-embed even if exists
    python -m scripts.backfill_embeddings --dry-run                  # count only, no writes
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import time

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


async def main(table: str, batch_size: int, force: bool, dry_run: bool) -> None:

    from data.database import init_db
    from integrations.llm.client import LLMClient

    init_db(os.environ["DATABASE_URL"])

    llm = LLMClient(
        anthropic_api_key=os.environ["ANTHROPIC_API_KEY"],
        openai_api_key=os.environ["OPENAI_API_KEY"],
    )

    tables = ["contracts", "disputes"] if table == "all" else [table]

    for tbl in tables:
        await _backfill_table(tbl, llm, batch_size, force, dry_run)


async def _backfill_table(
    table: str,
    llm,
    batch_size: int,
    force: bool,
    dry_run: bool,
) -> None:
    from sqlalchemy import select

    from data.database import get_session
    from data.embeddings.encoder import embed_batch

    logger.info(f"Backfilling embeddings for table: {table} (force={force}, dry_run={dry_run})")

    async with get_session() as db:
        if table == "contracts":
            from data.models.contract import Contract

            q = select(Contract)
            if not force:
                q = q.where(Contract.embedding == None)
            result = await db.execute(q)
            records = result.scalars().all()

            def get_text(r):
                return f"{r.question} {r.resolution_criteria} {r.resolution_source}"

        elif table == "disputes":
            from data.models.dispute import DisputeRecord

            q = select(DisputeRecord)
            if not force:
                q = q.where(DisputeRecord.embedding == None)
            result = await db.execute(q)
            records = result.scalars().all()

            def get_text(r):
                return f"{r.question} {r.resolution_criteria or ''} {r.dispute_reason or ''}"
        else:
            logger.error(f"Unknown table: {table}")
            return

        total = len(records)
        logger.info(f"Found {total} records to embed in {table}")

        if dry_run:
            logger.info("Dry run — no embeddings written.")
            return

        if total == 0:
            logger.info("Nothing to do.")
            return

        embedded = 0
        start = time.monotonic()

        for i in range(0, total, batch_size):
            batch = records[i : i + batch_size]
            texts = [get_text(r) for r in batch]

            try:
                embeddings = await embed_batch(llm, texts, batch_size=batch_size)
                for record, embedding in zip(batch, embeddings):
                    record.embedding = embedding
                    embedded += 1
                await db.flush()

                elapsed = time.monotonic() - start
                rate = embedded / elapsed if elapsed > 0 else 0
                remaining = (total - embedded) / rate if rate > 0 else 0
                logger.info(
                    f"  {embedded}/{total} embedded ({rate:.1f}/s, ~{remaining:.0f}s remaining)"
                )
            except Exception as e:
                logger.error(f"Batch {i}–{i + batch_size} failed: {e}")
                continue

        elapsed = time.monotonic() - start
        logger.info(f"Done. Embedded {embedded}/{total} records in {table} in {elapsed:.1f}s")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Backfill embeddings for contracts or disputes")
    parser.add_argument(
        "--table",
        choices=["contracts", "disputes", "all"],
        default="all",
        help="Which table to backfill (default: all)",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=20,
        help="Embeddings per batch (default: 20)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-embed even if embedding already exists",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Count records without writing anything",
    )
    args = parser.parse_args()
    asyncio.run(
        main(
            table=args.table,
            batch_size=args.batch_size,
            force=args.force,
            dry_run=args.dry_run,
        )
    )
