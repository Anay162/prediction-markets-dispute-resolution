"""
Category 5: Timing Ambiguity Analyzer

Checks for unspecified timezones, fiscal vs calendar year confusion,
publication lag issues, and ambiguous event completion definitions.
"""
from __future__ import annotations

import logging
from datetime import date, timedelta

from api.schemas.report import VulnerabilityCategory, Finding, Severity
from core.analyzers.base import BaseAnalyzer
from core.parser.entity_extractor import ParsedContract

logger = logging.getLogger(__name__)


class TimingAmbiguityAnalyzer(BaseAnalyzer):
    category = VulnerabilityCategory.timing_ambiguity
    prompt_file = "timing_ambiguity.txt"

    async def _post_process_findings(
        self, findings: list[Finding], contract: ParsedContract
    ) -> list[Finding]:
        """
        Run a deterministic check: if any timeframe in the contract
        has timezone_specified=False, and we don't already have a
        finding about it, add a low/medium finding automatically.

        This catches cases where the LLM might have missed a simple
        timezone omission on a short contract.
        """
        tz_unspecified = [tf for tf in contract.timeframes if not tf.timezone_specified]

        if not tz_unspecified:
            return findings

        # Check if the LLM already flagged timezone issues
        has_tz_finding = any(
            "timezone" in f.description.lower() or "time zone" in f.description.lower()
            for f in findings
        )

        if not has_tz_finding:
            from uuid import uuid4
            tz_finding = Finding(
                category=self.category,
                severity=Severity.medium,
                description=(
                    f"The contract contains {len(tz_unspecified)} time reference(s) without "
                    f"a timezone specification: "
                    + ", ".join(f"'{tf.raw_text}'" for tf in tz_unspecified[:3])
                    + (f" and {len(tz_unspecified) - 3} more" if len(tz_unspecified) > 3 else "")
                    + ". Without a timezone, resolvers in different locations may reach different "
                    "conclusions, particularly for events near midnight boundaries."
                ),
                affected_clause=", ".join(tf.raw_text for tf in tz_unspecified[:3]),
                rewrite=(
                    "Append ' (11:59:59 PM UTC)' or the appropriate UTC offset to all "
                    "deadline references. For example, 'by end of Q3 2025' should read "
                    "'by 11:59:59 PM UTC on September 30, 2025'."
                ),
                evidence=[
                    f"Timeframe '{tf.raw_text}': {tf.ambiguity_note}"
                    for tf in tz_unspecified[:5]
                ],
                confidence=0.9,
            )
            findings.append(tz_finding)

        return findings
