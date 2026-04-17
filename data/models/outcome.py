"""
data/models/outcome.py

Re-exports MarketOutcome from data/models/dispute.py for import convenience.

The spec lists outcome.py as a separate file. MarketOutcome is defined in
dispute.py alongside DisputeRecord because they share the same migration
and are thematically related (both feed the calibration loop).

This module re-exports it so imports like:
    from data.models.outcome import MarketOutcome
work as expected by the rest of the codebase.
"""
from data.models.dispute import MarketOutcome

__all__ = ["MarketOutcome"]
