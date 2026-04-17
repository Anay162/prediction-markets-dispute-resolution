"""
core/rewriter/clause_rewriter.py

Takes each Finding from the analyzers and produces a concrete rewrite
of the vulnerable clause, then validates the rewrite quality.

Two LLM calls per finding:
  1. clause_rewriter.txt  → produces the improved clause
  2. rewrite_validator.txt → self-critique to catch new issues introduced
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path

from api.schemas.report import Finding

logger = logging.getLogger(__name__)
PROMPTS_DIR = Path(__file__).parent.parent / "prompts"

MAX_REWRITE_ATTEMPTS = 2  # If validator rejects, try once more


class ClauseRewriter:
    """
    Generates improved contract clauses for each vulnerability finding.
    Updates the Finding.rewrite field in place.
    """

    def __init__(self, llm_client):
        self._llm = llm_client
        self._rewriter_prompt: str | None = None
        self._validator_prompt: str | None = None

    async def rewrite_finding(
        self,
        finding: Finding,
        full_contract_text: str,
    ) -> Finding:
        """
        Produce and validate a rewrite for a single Finding.
        Updates finding.rewrite with the best rewrite produced.
        Returns the updated Finding.
        """
        for attempt in range(MAX_REWRITE_ATTEMPTS):
            rewrite_result = await self._call_rewriter(finding, full_contract_text)
            if not rewrite_result:
                break

            validation = await self._call_validator(finding, rewrite_result)

            if validation.get("approved") and validation.get("quality_score", 0) >= 3:
                finding.rewrite = rewrite_result.get("rewritten_clause", finding.rewrite)
                logger.debug(
                    f"Rewrite approved (attempt {attempt + 1}, "
                    f"score {validation['quality_score']}): {finding.category}"
                )
                break
            else:
                logger.debug(
                    f"Rewrite rejected (attempt {attempt + 1}): "
                    f"{validation.get('closure_explanation', 'no reason given')}"
                )
                # On retry, inject the validator's feedback into the next rewrite call
                if attempt < MAX_REWRITE_ATTEMPTS - 1:
                    finding._validator_feedback = validation.get("suggested_improvement", "")

        return finding

    async def rewrite_all(
        self,
        findings: list[Finding],
        full_contract_text: str,
    ) -> list[Finding]:
        """
        Rewrite all findings. Runs sequentially to avoid rate limit spikes
        on large contracts with many findings.
        """
        rewritten = []
        for finding in findings:
            try:
                updated = await self.rewrite_finding(finding, full_contract_text)
                rewritten.append(updated)
            except Exception as e:
                logger.warning(f"Rewrite failed for finding {finding.id}: {e}")
                rewritten.append(finding)  # Keep original finding unchanged
        return rewritten

    # ------------------------------------------------------------------
    # LLM calls
    # ------------------------------------------------------------------

    async def _call_rewriter(self, finding: Finding, full_contract_text: str) -> dict | None:
        system = self._load_prompt("clause_rewriter.txt")
        feedback_note = ""
        if hasattr(finding, "_validator_feedback") and finding._validator_feedback:
            feedback_note = (
                f"\n\nPREVIOUS REWRITE WAS REJECTED. Validator feedback:\n"
                f"{finding._validator_feedback}\n"
                f"Please address this specific issue in your rewrite."
            )

        user = (
            f"FULL CONTRACT TEXT:\n{full_contract_text}\n\n"
            f"VULNERABILITY CATEGORY: {finding.category.value}\n"
            f"SEVERITY: {finding.severity.value}\n"
            f"VULNERABILITY DESCRIPTION: {finding.description}\n\n"
            f"AFFECTED CLAUSE TO REWRITE:\n{finding.affected_clause}"
            f"{feedback_note}"
        )

        try:
            raw = await self._llm.complete(
                system=system, user=user, temperature=0.2, max_tokens=1500
            )
            return self._parse_json(raw)
        except Exception as e:
            logger.warning(f"Rewriter LLM call failed: {e}")
            return None

    async def _call_validator(self, finding: Finding, rewrite_result: dict) -> dict:
        system = self._load_prompt("rewrite_validator.txt")
        user = (
            f"ORIGINAL CLAUSE:\n{finding.affected_clause}\n\n"
            f"VULNERABILITY DESCRIPTION:\n{finding.description}\n\n"
            f"PROPOSED REWRITE:\n{rewrite_result.get('rewritten_clause', '')}\n\n"
            f"CHANGES MADE:\n" + "\n".join(f"- {c}" for c in rewrite_result.get("changes_made", []))
        )

        try:
            raw = await self._llm.complete(
                system=system, user=user, temperature=0.1, max_tokens=800
            )
            result = self._parse_json(raw)
            return result if isinstance(result, dict) else {}
        except Exception as e:
            logger.warning(f"Validator LLM call failed: {e}")
            # Default: approve with low score so we don't block the pipeline
            return {"approved": True, "quality_score": 2}

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _load_prompt(self, filename: str) -> str:
        attr = f"_{filename.replace('.txt', '_prompt').replace('-', '_')}"
        if not getattr(self, attr, None):
            setattr(self, attr, (PROMPTS_DIR / filename).read_text(encoding="utf-8"))
        return getattr(self, attr)

    @staticmethod
    def _parse_json(raw: str) -> dict:
        clean = raw.strip()
        for fence in ("```json", "```"):
            if clean.startswith(fence):
                clean = clean[len(fence) :]
                break
        if clean.endswith("```"):
            clean = clean[:-3]
        match = re.search(r"\{[\s\S]*\}", clean.strip())
        if match:
            clean = match.group(0)
        return json.loads(clean)
