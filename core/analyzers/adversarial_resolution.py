"""
Category 6: Adversarial Resolution Analyzer

The most sophisticated analyzer. Instead of finding genuine ambiguity,
this looks for language that a motivated bad-faith party with financial
incentive could weaponize to construct a credible dispute — even when
the "obvious" resolution is clear to everyone.
"""

from __future__ import annotations

import logging

from api.schemas.report import Finding, VulnerabilityCategory
from core.analyzers.base import BaseAnalyzer
from core.parser.entity_extractor import ParsedContract

logger = logging.getLogger(__name__)


class AdversarialResolutionAnalyzer(BaseAnalyzer):
    category = VulnerabilityCategory.adversarial_resolution
    prompt_file = "adversarial_resolution.txt"

    def _build_prompt(self, contract: ParsedContract) -> str:
        """
        Override to add extra adversarial framing to the user turn.
        The system prompt has the persona; this user turn reminds the model
        to play the adversarial role aggressively.
        """
        base = super()._build_prompt(contract)
        adversarial_instruction = (
            "\n\n---\n"
            "Now play the role of the bad-faith lawyer described in your instructions. "
            "You have a large financial position. Find every textual exploit surface. "
            "For each one, write the actual argument you would make to the platform's "
            "dispute resolution team. Be specific, be aggressive, and be realistic about "
            "whether your argument would survive a first-level review."
        )
        return base + adversarial_instruction

    async def _post_process_findings(
        self, findings: list[Finding], contract: ParsedContract
    ) -> list[Finding]:
        """
        Check the dispute history database for similar contracts that
        were exploited using the same language patterns.
        """
        if not self.enrichment or not findings:
            return findings

        try:
            similar_disputes = await self.enrichment.find_similar_disputes(
                contract.full_text,
                category="adversarial_resolution",
                limit=3,
            )
            if similar_disputes:
                dispute_evidence = [
                    f"Similar disputed contract on {d['platform']}: '{d['question'][:100]}...' "
                    f"— dispute reason: {d['dispute_reason']}"
                    for d in similar_disputes
                ]
                for finding in findings:
                    finding.evidence.extend(dispute_evidence)
        except Exception as e:
            logger.warning(f"Dispute similarity lookup failed: {e}")

        return findings
