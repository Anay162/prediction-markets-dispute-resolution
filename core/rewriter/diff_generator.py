"""
core/rewriter/diff_generator.py

Produces a word-level diff between the original clause and its rewrite.
Output is a list of (operation, text) tuples stored on Finding.diff,
which the dashboard renders as highlighted before/after text.

Operations: "equal" | "insert" | "delete"
"""

from __future__ import annotations

import difflib
import re

from api.schemas.report import Finding


def generate_diff(original: str, rewritten: str) -> list[tuple[str, str]]:
    """
    Produce a word-level diff.

    Returns list of (operation, text) tuples, e.g.:
        [
            ("equal",  "Will the"),
            ("delete", "US GDP growth"),
            ("insert", "BEA advance estimate of US real GDP growth"),
            ("equal",  "exceed 2%"),
            ...
        ]
    """
    original_words = _tokenize(original)
    rewritten_words = _tokenize(rewritten)

    matcher = difflib.SequenceMatcher(None, original_words, rewritten_words, autojunk=False)

    result: list[tuple[str, str]] = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            result.append(("equal", " ".join(original_words[i1:i2])))
        elif tag == "replace":
            result.append(("delete", " ".join(original_words[i1:i2])))
            result.append(("insert", " ".join(rewritten_words[j1:j2])))
        elif tag == "delete":
            result.append(("delete", " ".join(original_words[i1:i2])))
        elif tag == "insert":
            result.append(("insert", " ".join(rewritten_words[j1:j2])))

    # Collapse consecutive same-operation segments for cleaner output
    return _collapse(result)


def attach_diffs(findings: list[Finding]) -> list[Finding]:
    """
    Generate and attach diffs to all findings that have a rewrite.
    Modifies findings in place, returns the list.
    """
    for finding in findings:
        if finding.rewrite and finding.affected_clause:
            finding.diff = generate_diff(finding.affected_clause, finding.rewrite)
    return findings


def _tokenize(text: str) -> list[str]:
    """
    Split text into tokens: words, punctuation, and whitespace.
    Preserves enough granularity that diffs are readable.
    """
    return re.findall(r"\S+|\s+", text)


def _collapse(ops: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """Merge adjacent tuples with the same operation."""
    if not ops:
        return ops
    result = [ops[0]]
    for op, text in ops[1:]:
        if op == result[-1][0]:
            result[-1] = (op, result[-1][1] + text)
        else:
            result.append((op, text))
    return result
