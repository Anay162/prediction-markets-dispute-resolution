"""
Category 3: Threshold Gaming Analyzer

Checks whether numeric thresholds are vulnerable to manipulation,
revision risk, or single-point-of-failure data dependencies.

Post-processing: looks up each referenced data series to confirm
whether it is a known revision-prone series.
"""
from __future__ import annotations

import logging

from api.schemas.report import VulnerabilityCategory
from core.analyzers.base import BaseAnalyzer
from core.parser.entity_extractor import ParsedContract
from api.schemas.report import Finding

logger = logging.getLogger(__name__)

# Data series known to be subject to revision after initial release.
# Maps common names/patterns to revision metadata.
KNOWN_REVISION_RISK_SERIES = {
    "gdp": {
        "agency": "Bureau of Economic Analysis (BEA)",
        "revision_note": "GDP is released in three estimates: advance (~30 days), second (~60 days), and third (~90 days). Annual revisions can significantly alter quarterly figures. The advance vs final estimate has historically differed by 1-2+ percentage points.",
    },
    "non-farm payroll": {
        "agency": "Bureau of Labor Statistics (BLS)",
        "revision_note": "Initial payrolls are revised twice in subsequent months. Annual benchmark revisions can shift totals by hundreds of thousands of jobs.",
    },
    "nonfarm payroll": {
        "agency": "Bureau of Labor Statistics (BLS)",
        "revision_note": "Initial payrolls are revised twice in subsequent months.",
    },
    "cpi": {
        "agency": "Bureau of Labor Statistics (BLS)",
        "revision_note": "CPI is not typically revised after release, but methodology changes can shift readings. Seasonal adjustment factors are revised annually.",
    },
    "inflation": {
        "agency": "Bureau of Labor Statistics (BLS)",
        "revision_note": "CPI-based inflation is not revised but PCE inflation (used by the Fed) can be revised.",
    },
    "unemployment": {
        "agency": "Bureau of Labor Statistics (BLS)",
        "revision_note": "Unemployment rate is subject to revision; annual benchmark revisions adjust household survey data.",
    },
    "trade deficit": {
        "agency": "Bureau of Economic Analysis (BEA)",
        "revision_note": "Trade data is revised monthly with a one-month lag, and subject to annual benchmark revisions.",
    },
    "retail sales": {
        "agency": "U.S. Census Bureau",
        "revision_note": "Advance retail sales are revised in the following month's release.",
    },
}


class ThresholdGamingAnalyzer(BaseAnalyzer):
    category = VulnerabilityCategory.threshold_gaming
    prompt_file = "threshold_gaming.txt"

    async def _post_process_findings(
        self, findings: list[Finding], contract: ParsedContract
    ) -> list[Finding]:
        """
        Check each threshold's data series against the known revision-risk list.
        Attach specific revision metadata as evidence to relevant findings.
        """
        if not contract.thresholds:
            return findings

        revision_evidence = []
        for threshold in contract.thresholds:
            series_lower = threshold.data_series.lower()
            for keyword, metadata in KNOWN_REVISION_RISK_SERIES.items():
                if keyword in series_lower:
                    revision_evidence.append(
                        f"'{threshold.raw_text}' references {threshold.data_series}: "
                        f"{metadata['revision_note']} (Source: {metadata['agency']})"
                    )

        if revision_evidence:
            for finding in findings:
                finding.evidence.extend(revision_evidence)

        return findings
