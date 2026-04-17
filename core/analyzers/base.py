"""
Base class for all vulnerability analyzers.

Every one of the six analyzers (source_failure, definitional_ambiguity,
threshold_gaming, scope_creep, timing_ambiguity, adversarial_resolution)
inherits from this class and implements analyze().

Design principles:
- Each analyzer is stateless and independent: it receives the full
  ParsedContract and returns a list of Findings. No shared state.
- Analyzers run in parallel (see core/analyzers/runner.py).
- Each analyzer loads its own prompt file from core/prompts/.
- The LLM call, retry logic, and output parsing are all handled here
  in the base class so individual analyzers stay focused on their domain.
"""
from __future__ import annotations

import dataclasses
import json
import logging
import re
import uuid
from abc import ABC, abstractmethod
from datetime import date, datetime
from pathlib import Path
from typing import Any, Optional

from api.schemas.report import Finding, Severity, VulnerabilityCategory
from core.parser.entity_extractor import ParsedContract

logger = logging.getLogger(__name__)

PROMPTS_DIR = Path(__file__).parent.parent / "prompts"


def _json_default(obj: Any) -> Any:
    """JSON encoder for dataclass fields that may contain date/datetime objects."""
    if isinstance(obj, (date, datetime)):
        return obj.isoformat()
    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")


def _dc_list(items: list) -> list[dict]:
    """Convert a list of dataclasses to a list of dicts for JSON serialisation."""
    return [dataclasses.asdict(item) for item in items]


class AnalyzerError(Exception):
    """Raised when an analyzer fails to produce usable output."""
    pass


class BaseAnalyzer(ABC):
    """
    Abstract base for all six vulnerability analyzers.

    Subclasses must set:
        category: VulnerabilityCategory
        prompt_file: str  (filename inside core/prompts/, e.g. "source_failure.txt")

    Subclasses may override:
        _post_process_findings(): apply category-specific filtering or enrichment
    """

    category: VulnerabilityCategory
    prompt_file: str

    def __init__(self, llm_client, enrichment_client=None):
        """
        Args:
            llm_client: The unified LLM client (integrations/llm/client.py).
            enrichment_client: Optional enrichment layer for evidence gathering.
        """
        self.llm = llm_client
        self.enrichment = enrichment_client
        self._prompt_template: str | None = None

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    async def analyze(self, contract: ParsedContract) -> list[Finding]:
        """
        Run this analyzer against the parsed contract.
        Returns a (possibly empty) list of Findings.
        """
        try:
            prompt = self._build_prompt(contract)
            raw_response = await self.llm.complete(
                system=self._load_prompt_template(),
                user=prompt,
                temperature=0.2,       # Low temperature for consistent structured output
                max_tokens=4096,
            )
            findings = self._parse_llm_output(raw_response, contract)
            findings = await self._post_process_findings(findings, contract)
            logger.info(
                f"{self.__class__.__name__} found {len(findings)} findings "
                f"for contract snippet: '{contract.question[:60]}...'"
            )
            return findings
        except AnalyzerError:
            raise
        except Exception as exc:
            logger.error(f"{self.__class__.__name__} failed: {exc}", exc_info=True)
            raise AnalyzerError(f"{self.__class__.__name__} failed: {exc}") from exc

    # ------------------------------------------------------------------
    # Prompt loading and building
    # ------------------------------------------------------------------

    def _load_prompt_template(self) -> str:
        """Load the system prompt from disk, caching after first read."""
        if self._prompt_template is None:
            path = PROMPTS_DIR / self.prompt_file
            if not path.exists():
                raise AnalyzerError(
                    f"Prompt file not found: {path}. "
                    f"Expected at core/prompts/{self.prompt_file}"
                )
            self._prompt_template = path.read_text(encoding="utf-8")
        return self._prompt_template

    def _build_prompt(self, contract: ParsedContract) -> str:
        """
        Build the user-turn prompt from the parsed contract.
        Subclasses can override to add category-specific context.
        """
        sections = [
            f"QUESTION:\n{contract.question}",
            f"RESOLUTION CRITERIA:\n{contract.resolution_criteria}",
            f"RESOLUTION SOURCE:\n{contract.resolution_source}",
            f"CLOSE DATE: {contract.close_date}",
        ]

        # Append the structured entities the parser extracted — this gives
        # the analyzer precise hooks to reason about rather than re-parsing text
        if contract.named_entities:
            sections.append(
                "NAMED ENTITIES (extracted by parser):\n"
                + json.dumps(_dc_list(contract.named_entities), indent=2, default=_json_default)
            )
        if contract.thresholds:
            sections.append(
                "NUMERIC THRESHOLDS:\n"
                + json.dumps(_dc_list(contract.thresholds), indent=2, default=_json_default)
            )
        if contract.timeframes:
            sections.append(
                "TIMEFRAMES & DATE REFERENCES:\n"
                + json.dumps(_dc_list(contract.timeframes), indent=2, default=_json_default)
            )
        if contract.key_terms:
            sections.append(
                "KEY TERMS FLAGGED FOR AMBIGUITY:\n"
                + json.dumps(_dc_list(contract.key_terms), indent=2, default=_json_default)
            )

        return "\n\n".join(sections)

    # ------------------------------------------------------------------
    # LLM output parsing
    # ------------------------------------------------------------------

    def _parse_llm_output(
        self, raw: str, contract: ParsedContract
    ) -> list[Finding]:
        """
        Parse the LLM's JSON output into a list of Finding objects.

        The LLM is instructed (via the system prompt) to return a JSON array
        of finding objects. We extract that array even if the model wraps it
        in markdown fences or adds preamble text.
        """
        json_str = self._extract_json_block(raw)
        try:
            data = json.loads(json_str)
        except json.JSONDecodeError as e:
            raise AnalyzerError(
                f"Could not parse JSON from {self.__class__.__name__} output. "
                f"Raw (first 500 chars): {raw[:500]!r}. Error: {e}"
            )

        if not isinstance(data, list):
            # Some models wrap in {"findings": [...]}
            if isinstance(data, dict) and "findings" in data:
                data = data["findings"]
            else:
                raise AnalyzerError(
                    f"Expected JSON array from {self.__class__.__name__}, got: {type(data)}"
                )

        findings = []
        for i, item in enumerate(data):
            try:
                finding = self._parse_single_finding(item)
                findings.append(finding)
            except Exception as e:
                logger.warning(
                    f"{self.__class__.__name__}: skipping malformed finding #{i}: {e}. "
                    f"Item: {item}"
                )
                continue

        return findings

    def _parse_single_finding(self, item: dict) -> Finding:
        """Parse one finding dict from the LLM into a Finding object."""
        # Normalise severity — LLM may return "CRITICAL", "Critical", etc.
        severity_raw = str(item.get("severity", "medium")).lower().strip()
        try:
            severity = Severity(severity_raw)
        except ValueError:
            severity = Severity.medium
            logger.warning(f"Unknown severity '{severity_raw}', defaulting to medium")

        return Finding(
            id=uuid.uuid4(),
            category=self.category,
            severity=severity,
            description=str(item.get("description", "")).strip(),
            affected_clause=str(item.get("affected_clause", "")).strip(),
            rewrite=str(item.get("rewrite", "")).strip(),
            evidence=item.get("evidence", []),
            confidence=float(item.get("confidence", 1.0)),
            diff=[],    # diff is generated later by rewriter/diff_generator.py
        )

    @staticmethod
    def _extract_json_block(text: str) -> str:
        """
        Extract JSON from LLM output that may be wrapped in markdown fences.
        Tries ```json ... ``` first, then ``` ... ```, then bare text.
        """
        # Try ```json fence
        match = re.search(r"```json\s*([\s\S]*?)```", text)
        if match:
            return match.group(1).strip()

        # Try plain ``` fence
        match = re.search(r"```\s*([\s\S]*?)```", text)
        if match:
            return match.group(1).strip()

        # Try to find a JSON array directly in the text
        match = re.search(r"(\[[\s\S]*\])", text)
        if match:
            return match.group(1).strip()

        # Try JSON object ({"findings": [...]})
        match = re.search(r"(\{[\s\S]*\})", text)
        if match:
            return match.group(1).strip()

        return text.strip()

    # ------------------------------------------------------------------
    # Post-processing hook
    # ------------------------------------------------------------------

    async def _post_process_findings(
        self, findings: list[Finding], contract: ParsedContract
    ) -> list[Finding]:
        """
        Optional hook for category-specific enrichment or filtering.
        Base implementation does nothing; subclasses override as needed.

        Examples of what subclasses do here:
          - source_failure: probe the URL and attach HTTP status as evidence
          - scope_creep: look up the entity in OpenCorporates and attach M&A data
          - threshold_gaming: check if a revision-prone data series is being referenced
        """
        return findings

    # ------------------------------------------------------------------
    # Utility helpers for subclasses
    # ------------------------------------------------------------------

    @staticmethod
    def _severity_rank(severity: Severity) -> int:
        """Numeric rank for sorting (lower = more severe)."""
        return {
            Severity.critical: 1,
            Severity.high: 2,
            Severity.medium: 3,
            Severity.low: 4,
        }[severity]

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} category={self.category}>"
