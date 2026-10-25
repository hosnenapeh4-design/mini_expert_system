"""A small rule-based expert system (forward chaining + certainty factors)."""

from .engine import (
    ANSWER_CF,
    CHOICES,
    REPORT_MIN,
    THRESHOLD,
    Diagnosis,
    KnowledgeBase,
    Question,
    Rule,
    Session,
    Trace,
    explain,
    infer,
    tr,
)
from .kb import ALL_KBS

__all__ = [
    "ALL_KBS", "ANSWER_CF", "CHOICES", "REPORT_MIN", "THRESHOLD", "Diagnosis",
    "KnowledgeBase", "Question", "Rule", "Session", "Trace", "explain", "infer", "tr",
]
