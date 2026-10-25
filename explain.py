"""Turn an inference trace into readable "why?" lines.

``render_trace`` returns ``(depth, text)`` pairs so each front end can draw
them its own way; ``to_markdown`` is the plain-text/markdown form used by the
CLI.
"""

from __future__ import annotations

from .engine import KnowledgeBase, Trace
from .ui import UI


def _pct(x: float) -> int:
    return round(x * 100)


def render_trace(kb: KnowledgeBase, trace: Trace, lang: str, depth: int = 0) -> list[tuple[int, str]]:
    ui = UI[lang]
    label = kb.label(trace.fact, lang)
    if trace.asked:
        answer = ui["yes"] if trace.cf >= 1.0 else ui["probably"]
        return [(depth, f"{label} - {ui['you_said']}: {answer}")]

    lines = [(depth, f"{label} ({_pct(trace.cf)}%)")]
    for rt in trace.rules:
        lines.append((depth + 1, f"{ui['rule']} {rt.rule.id}: {ui['adds']} {_pct(rt.strength)}%"))
        for premise in rt.premises:
            lines += render_trace(kb, premise, lang, depth + 2)
        if rt.rule.unless:
            blocked = ", ".join(kb.label(f, lang) for f in rt.rule.unless)
            lines.append((depth + 2, f"{ui['and_none_of']}: {blocked}"))
    return lines


def to_markdown(lines: list[tuple[int, str]]) -> str:
    return "\n".join(f"{'  ' * depth}- {text}" for depth, text in lines)
