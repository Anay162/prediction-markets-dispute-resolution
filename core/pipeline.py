"""
core/pipeline.py

The audit pipeline orchestrator. This is the single function the
Celery task calls. It runs every layer in the correct order and
returns a complete ReportOutput.

Execution order:
  1. Parse contract → ParsedContract  (entity_extractor)
  2. Run 6 analyzers in parallel       (runner)
  3. Rewrite each finding's clause     (clause_rewriter)
  4. Generate word-level diffs         (diff_generator)
  5. Calculate RCS score               (rcs_calculator)
  6. Assemble final report             (report/builder)

The pipeline is intentionally not async at the top level — it is
called from a Celery task which manages its own event loop.
"""

from __future__ import annotations

import logging
import time
import uuid

from api.schemas.contract import ContractInput
from api.schemas.report import ReportOutput
from core.analyzers.runner import AnalyzerRunner, ProgressCallback
from core.enrichment.client import EnrichmentClient
from core.parser.entity_extractor import EntityExtractor
from core.report.builder import build_report
from core.rewriter.clause_rewriter import ClauseRewriter
from core.rewriter.diff_generator import attach_diffs
from core.scoring.rcs_calculator import RCSCalculator

logger = logging.getLogger(__name__)

MODEL_VERSION = "claude-sonnet-4-20250514"


class AuditPipeline:
    """
    Stateless pipeline. One instance is shared by all workers in a process.
    Each call to run() is fully independent.
    """

    def __init__(
        self,
        llm_client,
        db_session_factory,  # Callable that returns an AsyncSession context manager
        opencorporates_api_key: str | None = None,
        scoring_weights=None,  # Optional custom ScoringWeight from DB
    ):
        self._llm = llm_client
        self._db_factory = db_session_factory
        self._oc_key = opencorporates_api_key
        self._scoring_weights = scoring_weights

    async def run(
        self,
        contract: ContractInput,
        job_id: uuid.UUID,
        progress_callback: ProgressCallback | None = None,
    ) -> ReportOutput:
        """
        Run the full audit pipeline for a single contract.

        Args:
            contract: The raw ContractInput from the API request
            job_id: UUID of the async job (for cost tracking and logging)
            progress_callback: Optional async callable(stage_name, pct) for status updates

        Returns:
            A complete ReportOutput ready to be stored and returned to the caller
        """
        start = time.monotonic()
        contract_id = uuid.uuid4()

        async with self._db_factory() as db:
            enrichment = EnrichmentClient(
                db=db,
                llm_client=self._llm,
                opencorporates_api_key=self._oc_key,
            )

            # ----------------------------------------------------------
            # Stage 1: Parse
            # ----------------------------------------------------------
            await _progress(progress_callback, "Parsing contract", 5)
            extractor = EntityExtractor(self._llm)
            parsed_contract = await extractor.parse(contract, contract_id)
            logger.info(
                f"[{job_id}] Parsed: {len(parsed_contract.named_entities)} entities, "
                f"{len(parsed_contract.thresholds)} thresholds, "
                f"{len(parsed_contract.timeframes)} timeframes, "
                f"{len(parsed_contract.key_terms)} key terms"
            )

            # ----------------------------------------------------------
            # Stage 2: Analyze (parallel)
            # ----------------------------------------------------------
            await _progress(progress_callback, "Running vulnerability analyzers", 15)
            runner = AnalyzerRunner(self._llm, enrichment)
            findings, analyzer_errors = await runner.run_all(
                parsed_contract,
                progress_callback=progress_callback,
            )
            if analyzer_errors:
                failed = [k for k, v in analyzer_errors.items() if v]
                logger.warning(f"[{job_id}] {len(failed)} analyzer(s) failed: {failed}")

            logger.info(f"[{job_id}] Found {len(findings)} findings")

            # ----------------------------------------------------------
            # Stage 3: Rewrite findings
            # ----------------------------------------------------------
            await _progress(progress_callback, "Rewriting vulnerable clauses", 75)
            rewriter = ClauseRewriter(self._llm)
            findings = await rewriter.rewrite_all(findings, parsed_contract.full_text)

            # ----------------------------------------------------------
            # Stage 4: Generate diffs
            # ----------------------------------------------------------
            await _progress(progress_callback, "Generating diffs", 88)
            findings = attach_diffs(findings)

            # ----------------------------------------------------------
            # Stage 5: Score
            # ----------------------------------------------------------
            await _progress(progress_callback, "Calculating Resolution Clarity Score", 92)
            calculator = RCSCalculator()
            score = calculator.calculate(findings)
            logger.info(
                f"[{job_id}] RCS: {score.final_score} ({score.score_label}) "
                f"| critical={score.critical_count} high={score.high_count} "
                f"medium={score.medium_count} low={score.low_count}"
            )

            # ----------------------------------------------------------
            # Stage 6: Build report
            # ----------------------------------------------------------
            await _progress(progress_callback, "Assembling report", 96)
            elapsed = time.monotonic() - start
            report = build_report(
                contract_id=contract_id,
                findings=findings,
                score=score,
                audit_duration_seconds=elapsed,
                model_version=MODEL_VERSION,
                original_resolution_criteria=contract.resolution_criteria,
            )

            await _progress(progress_callback, "Complete", 100)
            logger.info(f"[{job_id}] Pipeline complete in {elapsed:.1f}s. Report ID: {report.id}")
            return report


async def _progress(
    callback: ProgressCallback | None,
    stage: str,
    pct: int,
) -> None:
    if callback:
        try:
            await callback(stage, pct)
        except Exception as e:
            logger.debug(f"Progress callback failed: {e}")
