"""
Category 1: Source Failure Analyzer

Checks whether the resolution source could become unavailable,
change methodology, or contradict itself before close date.

Post-processing: probes the source URL live and attaches HTTP status
and Wayback Machine archival history as evidence.
"""
from __future__ import annotations

import logging

from api.schemas.report import VulnerabilityCategory
from core.analyzers.base import BaseAnalyzer
from core.parser.entity_extractor import ParsedContract
from api.schemas.report import Finding

logger = logging.getLogger(__name__)


class SourceFailureAnalyzer(BaseAnalyzer):
    category = VulnerabilityCategory.source_failure
    prompt_file = "source_failure.txt"

    async def _post_process_findings(
        self, findings: list[Finding], contract: ParsedContract
    ) -> list[Finding]:
        """
        Enrich findings with live source probe results.
        If the URL is already dead or has changed, escalate severity to critical.
        """
        if not contract.source_url or not self.enrichment:
            return findings

        try:
            probe_result = await self.enrichment.probe_source(contract.source_url)

            # If the source is already unreachable, add a critical finding
            # regardless of what the LLM found
            if probe_result.get("status") in (404, 410, None):
                from uuid import uuid4
                from api.schemas.report import Severity
                dead_finding = Finding(
                    category=self.category,
                    severity=Severity.critical,
                    description=(
                        f"The resolution source URL returned HTTP {probe_result.get('status', 'timeout')} "
                        f"at time of audit. The source is currently unreachable. "
                        f"This contract cannot be resolved if the source remains unavailable."
                    ),
                    affected_clause=contract.resolution_source,
                    rewrite=(
                        f"Replace the current source with a verified alternative. "
                        f"The original source ({contract.source_url}) was unreachable at time of audit. "
                        f"Add at least two fallback sources and define which takes precedence."
                    ),
                    evidence=[
                        f"HTTP {probe_result.get('status', 'timeout')} at {contract.source_url}",
                        f"Probe timestamp: {probe_result.get('probed_at', 'unknown')}",
                    ],
                    confidence=1.0,
                )
                findings.insert(0, dead_finding)

            # Attach probe result as evidence to all existing source findings
            for finding in findings:
                if probe_result.get("wayback_available"):
                    finding.evidence.append(
                        f"Wayback Machine has {probe_result['wayback_snapshot_count']} snapshots "
                        f"of this URL; most recent: {probe_result.get('wayback_last_snapshot')}"
                    )
                if probe_result.get("redirect_chain"):
                    finding.evidence.append(
                        f"URL redirects through {len(probe_result['redirect_chain'])} hops: "
                        + " → ".join(probe_result["redirect_chain"])
                    )

        except Exception as e:
            logger.warning(f"Source probe failed for {contract.source_url}: {e}")
            # Don't fail the whole analysis if enrichment fails

        return findings
