"""
Analyzer runner — executes all six analyzers in parallel and merges results.

Handles:
- Parallel asyncio execution with individual timeout per analyzer
- Graceful degradation: a single analyzer failure does not abort the run
- Result merging and deduplication
- Progress reporting via callback for the async job status endpoint
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable

from api.schemas.report import Finding, Severity
from core.analyzers.adversarial_resolution import AdversarialResolutionAnalyzer
from core.analyzers.base import AnalyzerError
from core.analyzers.definitional_ambiguity import DefinitionalAmbiguityAnalyzer
from core.analyzers.scope_creep import ScopeCreepAnalyzer
from core.analyzers.source_failure import SourceFailureAnalyzer
from core.analyzers.threshold_gaming import ThresholdGamingAnalyzer
from core.analyzers.timing_ambiguity import TimingAmbiguityAnalyzer
from core.parser.entity_extractor import ParsedContract

logger = logging.getLogger(__name__)

# Per-analyzer timeout in seconds. Adversarial resolution is given more time
# because its prompt is longer and requires deeper reasoning.
ANALYZER_TIMEOUTS = {
    "SourceFailureAnalyzer": 45,
    "DefinitionalAmbiguityAnalyzer": 30,
    "ThresholdGamingAnalyzer": 30,
    "ScopeCreepAnalyzer": 35,
    "TimingAmbiguityAnalyzer": 30,
    "AdversarialResolutionAnalyzer": 60,
}

ProgressCallback = Callable[[str, int], Awaitable[None]]


class AnalyzerRunner:
    """
    Runs all six analyzers against a ParsedContract and returns
    a merged, deduplicated, sorted list of Findings.
    """

    def __init__(self, llm_client, enrichment_client=None):
        self.analyzers = [
            SourceFailureAnalyzer(llm_client, enrichment_client),
            DefinitionalAmbiguityAnalyzer(llm_client, enrichment_client),
            ThresholdGamingAnalyzer(llm_client, enrichment_client),
            ScopeCreepAnalyzer(llm_client, enrichment_client),
            TimingAmbiguityAnalyzer(llm_client, enrichment_client),
            AdversarialResolutionAnalyzer(llm_client, enrichment_client),
        ]

    async def run_all(
        self,
        contract: ParsedContract,
        progress_callback: ProgressCallback | None = None,
    ) -> tuple[list[Finding], dict[str, str | None]]:
        """
        Run all analyzers in parallel.

        Returns:
            findings: Merged, deduplicated, severity-sorted list of Findings
            errors: Dict of {analyzer_name: error_message} for any that failed
        """
        start = time.monotonic()
        tasks = []
        for analyzer in self.analyzers:
            task = asyncio.create_task(
                self._run_with_timeout(analyzer, contract, progress_callback),
                name=analyzer.__class__.__name__,
            )
            tasks.append(task)

        results = await asyncio.gather(*tasks, return_exceptions=True)

        all_findings: list[Finding] = []
        errors: dict[str, str | None] = {}

        for analyzer, result in zip(self.analyzers, results):
            name = analyzer.__class__.__name__
            if isinstance(result, Exception):
                errors[name] = str(result)
                logger.error(f"{name} failed: {result}")
            else:
                findings, err = result
                if err:
                    errors[name] = err
                all_findings.extend(findings)

        elapsed = time.monotonic() - start
        logger.info(
            f"All analyzers completed in {elapsed:.1f}s. "
            f"Total findings: {len(all_findings)}. "
            f"Analyzer errors: {sum(1 for v in errors.values() if v)}"
        )

        merged = self._merge_and_sort(all_findings)
        return merged, errors

    async def _run_with_timeout(
        self,
        analyzer,
        contract: ParsedContract,
        progress_callback: ProgressCallback | None,
    ) -> tuple[list[Finding], str | None]:
        """Run a single analyzer with its timeout. Returns (findings, error_str)."""
        name = analyzer.__class__.__name__
        timeout = ANALYZER_TIMEOUTS.get(name, 45)

        if progress_callback:
            await progress_callback(f"Running {name}", 0)

        try:
            findings = await asyncio.wait_for(
                analyzer.analyze(contract),
                timeout=timeout,
            )
            if progress_callback:
                await progress_callback(f"Completed {name}", len(findings))
            return findings, None

        except TimeoutError:
            msg = f"{name} timed out after {timeout}s"
            logger.warning(msg)
            return [], msg

        except AnalyzerError as e:
            msg = str(e)
            logger.error(f"{name} raised AnalyzerError: {msg}")
            return [], msg

        except Exception as e:
            msg = f"Unexpected error in {name}: {e}"
            logger.error(msg, exc_info=True)
            return [], msg

    @staticmethod
    def _merge_and_sort(findings: list[Finding]) -> list[Finding]:
        """
        Deduplicate and sort findings by severity (critical first).

        Deduplication: two findings are considered duplicates if they have
        the same category and their affected_clause strings have >80% overlap.
        We keep the one with higher severity / more evidence.
        """
        if not findings:
            return []

        severity_order = {
            Severity.critical: 0,
            Severity.high: 1,
            Severity.medium: 2,
            Severity.low: 3,
        }

        # Sort by severity first so we always keep the more severe duplicate
        findings.sort(key=lambda f: severity_order[f.severity])

        deduplicated: list[Finding] = []
        for finding in findings:
            is_duplicate = False
            for existing in deduplicated:
                if (
                    existing.category == finding.category
                    and _text_overlap(existing.affected_clause, finding.affected_clause) > 0.8
                ):
                    # Keep the one already in the list (higher severity due to sort)
                    # but merge any unique evidence from the duplicate
                    for ev in finding.evidence:
                        if ev not in existing.evidence:
                            existing.evidence.append(ev)
                    is_duplicate = True
                    break
            if not is_duplicate:
                deduplicated.append(finding)

        return deduplicated


def _text_overlap(a: str, b: str) -> float:
    """Rough word-level Jaccard similarity between two strings."""
    if not a or not b:
        return 0.0
    words_a = set(a.lower().split())
    words_b = set(b.lower().split())
    if not words_a and not words_b:
        return 1.0
    intersection = words_a & words_b
    union = words_a | words_b
    return len(intersection) / len(union)
