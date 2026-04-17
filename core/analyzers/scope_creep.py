"""
Category 4: Scope Creep Analyzer

Checks whether the subject entity could change its nature
(M&A, delisting, rebrand, political withdrawal) before close date.

Post-processing: queries OpenCorporates and SEC EDGAR for any
known corporate actions on the named entities.
"""
from __future__ import annotations

import logging

from api.schemas.report import VulnerabilityCategory
from core.analyzers.base import BaseAnalyzer
from core.parser.entity_extractor import ParsedContract
from api.schemas.report import Finding

logger = logging.getLogger(__name__)


class ScopeCreepAnalyzer(BaseAnalyzer):
    category = VulnerabilityCategory.scope_creep
    prompt_file = "scope_creep.txt"

    async def _post_process_findings(
        self, findings: list[Finding], contract: ParsedContract
    ) -> list[Finding]:
        """
        For each named entity flagged as having ambiguity_risk=True,
        query the enrichment layer for known corporate actions or
        recent M&A activity and attach as evidence.
        """
        if not self.enrichment:
            return findings

        at_risk_entities = [e for e in contract.named_entities if e.ambiguity_risk]
        if not at_risk_entities:
            return findings

        entity_evidence = []
        for entity in at_risk_entities:
            if entity.entity_type != "ORG":
                continue
            try:
                corp_data = await self.enrichment.lookup_entity(entity.text)
                if corp_data.get("recent_corporate_actions"):
                    for action in corp_data["recent_corporate_actions"]:
                        entity_evidence.append(
                            f"Entity '{entity.text}': {action['type']} — {action['description']} "
                            f"(Source: {action['source']}, Date: {action.get('date', 'unknown')})"
                        )
                if corp_data.get("m_and_a_rumors"):
                    entity_evidence.append(
                        f"Entity '{entity.text}': Active M&A speculation reported: "
                        + corp_data["m_and_a_rumors"]
                    )
            except Exception as e:
                logger.warning(f"Entity lookup failed for '{entity.text}': {e}")

        if entity_evidence:
            for finding in findings:
                finding.evidence.extend(entity_evidence)

        return findings
