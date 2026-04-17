"""
data/models/weight.py

Re-exports ScoringWeight from data/models/dispute.py for import convenience.

The spec lists weight.py as a separate file. ScoringWeight is defined in
dispute.py because it shares the same migration file (004_add_weights_and_vectors).

This module re-exports it so imports like:
    from data.models.weight import ScoringWeight
work as expected.
"""
from data.models.dispute import ScoringWeight

__all__ = ["ScoringWeight"]
