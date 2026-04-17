"""
Turns a raw ContractInput into a ParsedContract by:
1. Running an LLM extraction call with the entity_extraction.txt prompt
2. Parsing the JSON response into typed dataclasses
3. Running a fast regex pass to catch any URLs the LLM missed

The ParsedContract is then passed to all six analyzers in parallel.
"""

from __future__ import annotations

import json
import logging
import re
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any

from api.schemas.contract import ContractInput

logger = logging.getLogger(__name__)

PROMPTS_DIR = Path(__file__).parent.parent / "prompts"
URL_PATTERN = re.compile(r"https?://[^\s\"'<>]+", re.IGNORECASE)


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class NamedEntity:
    text: str
    entity_type: str  # ORG | PERSON | GPE | LAW | PRODUCT | EVENT | DATE
    context: str
    ambiguity_risk: bool = False


@dataclass
class Threshold:
    raw_text: str
    value: float | None
    unit: str
    data_series: str
    revision_risk: bool
    single_point_risk: bool


@dataclass
class Timeframe:
    raw_text: str
    parsed_date: date | None
    timezone_specified: bool
    ambiguity_note: str


@dataclass
class KeyTerm:
    term: str
    context: str
    ambiguity_type: str  # undefined | jurisdiction_dependent | multiple_meanings
    note: str


@dataclass
class ParsedContract:
    contract_id: uuid.UUID
    question: str
    resolution_criteria: str
    resolution_source: str
    close_date: date
    named_entities: list[NamedEntity] = field(default_factory=list)
    thresholds: list[Threshold] = field(default_factory=list)
    timeframes: list[Timeframe] = field(default_factory=list)
    key_terms: list[KeyTerm] = field(default_factory=list)
    source_url: str | None = None

    @property
    def full_text(self) -> str:
        return (
            f"QUESTION: {self.question}\n\n"
            f"RESOLUTION CRITERIA: {self.resolution_criteria}\n\n"
            f"RESOLUTION SOURCE: {self.resolution_source}\n\n"
            f"CLOSE DATE: {self.close_date}"
        )

    def to_prompt_dict(self) -> dict[str, Any]:
        return {
            "question": self.question,
            "resolution_criteria": self.resolution_criteria,
            "resolution_source": self.resolution_source,
            "close_date": str(self.close_date),
            "named_entities": [
                {"text": e.text, "type": e.entity_type, "ambiguity_risk": e.ambiguity_risk}
                for e in self.named_entities
            ],
            "thresholds": [
                {
                    "raw": t.raw_text,
                    "value": t.value,
                    "unit": t.unit,
                    "data_series": t.data_series,
                    "revision_risk": t.revision_risk,
                    "single_point_risk": t.single_point_risk,
                }
                for t in self.thresholds
            ],
            "timeframes": [
                {
                    "raw": tf.raw_text,
                    "timezone_specified": tf.timezone_specified,
                    "ambiguity": tf.ambiguity_note,
                }
                for tf in self.timeframes
            ],
            "key_terms": [
                {
                    "term": kt.term,
                    "ambiguity_type": kt.ambiguity_type,
                    "note": kt.note,
                }
                for kt in self.key_terms
            ],
        }


# ---------------------------------------------------------------------------
# Parser class
# ---------------------------------------------------------------------------


class EntityExtractor:
    """
    Parses a raw ContractInput into a ParsedContract using an LLM call
    followed by deterministic post-processing.
    """

    def __init__(self, llm_client):
        self._llm = llm_client
        self._system_prompt: str | None = None

    async def parse(self, contract: ContractInput, contract_id: uuid.UUID) -> ParsedContract:
        system = self._load_system_prompt()
        user = self._build_user_prompt(contract)

        try:
            raw = await self._llm.complete(
                system=system,
                user=user,
                temperature=0.1,
                max_tokens=2048,
            )
            extracted = self._parse_llm_response(raw)
        except Exception as e:
            logger.warning(f"LLM entity extraction failed ({e}), using empty extraction")
            extracted = {}

        parsed = self._build_parsed_contract(contract, contract_id, extracted)
        parsed = self._deterministic_postprocess(parsed, contract)
        return parsed

    def _load_system_prompt(self) -> str:
        if self._system_prompt is None:
            path = PROMPTS_DIR / "entity_extraction.txt"
            self._system_prompt = path.read_text(encoding="utf-8")
        return self._system_prompt

    def _build_user_prompt(self, contract: ContractInput) -> str:
        return (
            f"QUESTION:\n{contract.question}\n\n"
            f"RESOLUTION CRITERIA:\n{contract.resolution_criteria}\n\n"
            f"RESOLUTION SOURCE:\n{contract.resolution_source}\n\n"
            f"CLOSE DATE: {contract.close_date}"
        )

    def _parse_llm_response(self, raw: str) -> dict:
        clean = raw.strip()
        for fence in ("```json", "```"):
            if clean.startswith(fence):
                clean = clean[len(fence) :]
                break
        if clean.endswith("```"):
            clean = clean[:-3]
        clean = clean.strip()
        match = re.search(r"\{[\s\S]*\}", clean)
        if match:
            clean = match.group(0)
        return json.loads(clean)

    def _build_parsed_contract(
        self, contract: ContractInput, contract_id: uuid.UUID, extracted: dict
    ) -> ParsedContract:
        parsed = ParsedContract(
            contract_id=contract_id,
            question=contract.question,
            resolution_criteria=contract.resolution_criteria,
            resolution_source=contract.resolution_source,
            close_date=contract.close_date,
            source_url=extracted.get("source_url"),
        )

        for item in extracted.get("named_entities", []):
            try:
                parsed.named_entities.append(
                    NamedEntity(
                        text=str(item.get("text", "")),
                        entity_type=str(item.get("entity_type", "ORG")),
                        context=str(item.get("context", "")),
                        ambiguity_risk=bool(item.get("ambiguity_risk", False)),
                    )
                )
            except Exception as e:
                logger.debug(f"Skipping malformed entity: {item} — {e}")

        for item in extracted.get("thresholds", []):
            try:
                raw_val = item.get("value")
                value = float(raw_val) if raw_val is not None else None
                parsed.thresholds.append(
                    Threshold(
                        raw_text=str(item.get("raw_text", "")),
                        value=value,
                        unit=str(item.get("unit", "")),
                        data_series=str(item.get("data_series", "")),
                        revision_risk=bool(item.get("revision_risk", False)),
                        single_point_risk=bool(item.get("single_point_risk", False)),
                    )
                )
            except Exception as e:
                logger.debug(f"Skipping malformed threshold: {item} — {e}")

        for item in extracted.get("timeframes", []):
            try:
                parsed_date = None
                raw_date = item.get("parsed_date")
                if raw_date and raw_date != "null":
                    try:
                        parsed_date = datetime.strptime(str(raw_date), "%Y-%m-%d").date()
                    except ValueError:
                        pass
                parsed.timeframes.append(
                    Timeframe(
                        raw_text=str(item.get("raw_text", "")),
                        parsed_date=parsed_date,
                        timezone_specified=bool(item.get("timezone_specified", False)),
                        ambiguity_note=str(item.get("ambiguity_note", "")),
                    )
                )
            except Exception as e:
                logger.debug(f"Skipping malformed timeframe: {item} — {e}")

        for item in extracted.get("key_terms", []):
            try:
                parsed.key_terms.append(
                    KeyTerm(
                        term=str(item.get("term", "")),
                        context=str(item.get("context", "")),
                        ambiguity_type=str(item.get("ambiguity_type", "undefined")),
                        note=str(item.get("note", "")),
                    )
                )
            except Exception as e:
                logger.debug(f"Skipping malformed key term: {item} — {e}")

        return parsed

    def _deterministic_postprocess(
        self, parsed: ParsedContract, contract: ContractInput
    ) -> ParsedContract:
        full_text = (
            f"{contract.question} {contract.resolution_criteria} {contract.resolution_source}"
        )

        # Extract URL if LLM missed it
        if not parsed.source_url:
            urls = URL_PATTERN.findall(contract.resolution_source)
            if urls:
                parsed.source_url = urls[0]

        # Flag timezone-absent deadline language
        tz_trigger_patterns = [
            r"\bend\s+of\s+(the\s+)?(year|quarter|month|day)\b",
            r"\bby\s+(december|january|february|march|april|may|june|july|august|september|october|november|q[1-4])\b",
            r"\bbefore\s+\d{4}\b",
            r"\bclose\s+of\s+(business|trading)\b",
            r"\bmidnight\b",
        ]
        for pattern in tz_trigger_patterns:
            for match in re.finditer(pattern, full_text, re.IGNORECASE):
                matched_text = match.group(0)
                already_covered = any(
                    matched_text.lower() in tf.raw_text.lower() for tf in parsed.timeframes
                )
                if not already_covered:
                    parsed.timeframes.append(
                        Timeframe(
                            raw_text=matched_text,
                            parsed_date=None,
                            timezone_specified=False,
                            ambiguity_note=f"Deadline language '{matched_text}' has no timezone specified",
                        )
                    )

        # Flag high-risk key terms not already extracted
        HIGH_RISK_TERMS = {
            "bankrupt": "Could mean Chapter 7 liquidation or Chapter 11 reorganization",
            "bankruptcy": "Could mean Chapter 7 liquidation or Chapter 11 reorganization",
            "passes": "Could mean committee vote, floor vote, bicameral passage, or presidential signature",
            "launched": "Could mean announced, soft launch, beta, or general availability",
            "completes": "Completion criteria undefined — who confirms, by what standard",
            "officially": "Official source undefined — press release vs regulatory filing",
            "significant": "Vague quantifier with no defined threshold",
            "substantially": "Vague quantifier with no defined threshold",
            "major": "Vague quantifier with no defined threshold",
            "exceeds": "Ambiguous — strictly greater than, or greater than or equal to?",
            "reaches": "Ambiguous — strictly greater than, or greater than or equal to?",
        }
        existing_terms = {kt.term.lower() for kt in parsed.key_terms}
        for term, note in HIGH_RISK_TERMS.items():
            if term.lower() in full_text.lower() and term.lower() not in existing_terms:
                context = _extract_sentence_containing(full_text, term)
                parsed.key_terms.append(
                    KeyTerm(
                        term=term,
                        context=context,
                        ambiguity_type="multiple_meanings",
                        note=note,
                    )
                )

        return parsed


def _extract_sentence_containing(text: str, term: str) -> str:
    sentences = re.split(r"(?<=[.!?])\s+", text)
    for sentence in sentences:
        if term.lower() in sentence.lower():
            return sentence.strip()
    return text[:200]
