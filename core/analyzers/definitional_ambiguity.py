"""
Category 2: Definitional Ambiguity Analyzer

Checks whether key terms in the contract are defined precisely enough
to produce a mechanical yes/no resolution answer.
"""
from __future__ import annotations

import logging

from api.schemas.report import VulnerabilityCategory
from core.analyzers.base import BaseAnalyzer

logger = logging.getLogger(__name__)


class DefinitionalAmbiguityAnalyzer(BaseAnalyzer):
    category = VulnerabilityCategory.definitional_ambiguity
    prompt_file = "definitional_ambiguity.txt"

    # No special post-processing needed — LLM output is sufficient for this category.
    # The entity parser already flags key terms, which are injected into the prompt.
