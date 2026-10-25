"""Core of the expert system: knowledge representation and inference engine.

Design in one paragraph
-----------------------
Knowledge lives in a ``KnowledgeBase`` made of *questions* (where facts come
from), *rules* (IF all premises hold [UNLESS some fact holds] THEN conclusion
with a certainty factor) and *diagnoses* (the conclusions we report).  The
engine does **forward chaining**: starting from the user's answers it applies
every rule whose premises hold, adds the new facts, and repeats until nothing
changes.  Uncertainty is handled with MYCIN-style **certainty factors** (CF):

* premises are joined with ``min``          -> a chain is as strong as its weakest link
* rule strength = ``min(premises) * rule.cf``
* independent evidence for one fact merges with ``a + b * (1 - a)``

Every conclusion can be traced back to the answers and rules that produced it,
which is what makes the ``explain`` feature possible.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# A bilingual string: (English, Arabic).
Text = tuple[str, str]

THRESHOLD = 0.2   # a fact "holds" when its certainty is at least this
REPORT_MIN = 0.3  # diagnoses below this certainty are not reported
_EPS = 1e-9

# What the user can answer -> certainty of the fact.  "unknown" records nothing.
ANSWER_CF = {"yes": 1.0, "probably": 0.6, "no": 0.0}
CHOICES = ("yes", "probably", "no", "unknown")


def tr(text: Text, lang: str) -> str:
    """Pick the right language out of a bilingual ``Text``."""
    return text[1] if lang == "ar" else text[0]


def combine(a: float, b: float) -> float:
    """Merge two independent pieces of positive evidence for the same fact."""
    return a + b * (1.0 - a)


# --------------------------------------------------------------------------- #
# Knowledge representation
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class Rule:
    id: str
    if_all: tuple[str, ...]          # every premise must hold
    then: str                        # fact concluded
    cf: float                        # confidence in the rule itself, (0, 1]
    unless: tuple[str, ...] = ()     # rule is blocked if any of these holds


@dataclass(frozen=True)
class Question:
    fact: str
    text: Text
    # Ask only when at least one of these facts holds (empty = always ask).
    ask_if_any: tuple[str, ...] = ()


@dataclass(frozen=True)
class Diagnosis:
    fact: str
    title: Text
    steps: tuple[Text, ...]          # what to do about it
    urgent: bool = False             # safety-critical: shown as a warning


@dataclass
class KnowledgeBase:
    key: str
    title: Text
    intro: Text
    questions: tuple[Question, ...]
    rules: tuple[Rule, ...]
    diagnoses: tuple[Diagnosis, ...]
    # Human-readable names for intermediate (non-question, non-diagnosis) facts.
    labels: dict[str, Text] = field(default_factory=dict)

    # -- lookups ----------------------------------------------------------- #
    def question_for(self, fact: str) -> Question | None:
        return next((q for q in self.questions if q.fact == fact), None)

    def diagnosis_for(self, fact: str) -> Diagnosis | None:
        return next((d for d in self.diagnoses if d.fact == fact), None)

    def label(self, fact: str, lang: str) -> str:
        q = self.question_for(fact)
        if q:
            return tr(q.text, lang)
        d = self.diagnosis_for(fact)
        if d:
            return tr(d.title, lang)
        if fact in self.labels:
            return tr(self.labels[fact], lang)
        return fact

    # -- self-check -------------------------------------------------------- #
    def validate(self) -> list[str]:
        """Return a list of problems in the knowledge base (empty = healthy)."""
        problems: list[str] = []
        q_facts = [q.fact for q in self.questions]
        if len(set(q_facts)) != len(q_facts):
            problems.append("duplicate question facts")
        rule_ids = [r.id for r in self.rules]
        if len(set(rule_ids)) != len(rule_ids):
            problems.append("duplicate rule ids")

        derived = {r.then for r in self.rules}
        known = set(q_facts) | derived
        for clash in sorted(set(q_facts) & derived):
            problems.append(f"fact '{clash}' is both asked and derived")

        for r in self.rules:
            if not r.if_all:
                problems.append(f"{r.id}: rule has no premises")
            if not 0 < r.cf <= 1:
                problems.append(f"{r.id}: cf {r.cf} outside (0, 1]")
            for f in r.if_all + r.unless:
                if f not in known:
                    problems.append(f"{r.id}: unknown fact '{f}'")
        for q in self.questions:
            for f in q.ask_if_any:
                if f not in known:
                    problems.append(f"question '{q.fact}': unknown gate fact '{f}'")

        diag_facts = {d.fact for d in self.diagnoses}
        for d in self.diagnoses:
            if d.fact not in derived:
                problems.append(f"diagnosis '{d.fact}' is never concluded by a rule")
            if not d.steps:
                problems.append(f"diagnosis '{d.fact}' has no steps")
        used = {f for r in self.rules for f in r.if_all + r.unless}
        used |= {f for q in self.questions for f in q.ask_if_any}
        for f in sorted(derived - diag_facts):
            if f not in self.labels:
                problems.append(f"intermediate fact '{f}' has no label")
            if f not in used:
                problems.append(f"intermediate fact '{f}' is a dead end")

        # Every user-visible string must exist in both languages.
        texts: list[tuple[str, Text]] = [("title", self.title), ("intro", self.intro)]
        texts += [(f"question {q.fact}", q.text) for q in self.questions]
        texts += [(f"diagnosis {d.fact}", d.title) for d in self.diagnoses]
        texts += [(f"step of {d.fact}", s) for d in self.diagnoses for s in d.steps]
        texts += [(f"label {k}", v) for k, v in self.labels.items()]
        for name, t in texts:
            if len(t) != 2 or not all(isinstance(s, str) and s.strip() for s in t):
                problems.append(f"{name}: missing English or Arabic text")

        problems += self._cycle_problems(derived)
        if not problems:
            problems += self._reachability_problems(diag_facts)
        return problems

    def _cycle_problems(self, derived: set[str]) -> list[str]:
        graph: dict[str, set[str]] = {}
        for r in self.rules:
            graph.setdefault(r.then, set()).update(
                f for f in r.if_all + r.unless if f in derived
            )
        state: dict[str, int] = {}

        def visit(node: str) -> bool:
            if state.get(node) == 1:
                return True
            if state.get(node) == 2:
                return False
            state[node] = 1
            if any(visit(n) for n in graph.get(node, ())):
                return True
            state[node] = 2
            return False

        return ["cyclic rules" for n in list(graph) if visit(n)][:1]

    def _reachability_problems(self, diag_facts: set[str]) -> list[str]:
        """Optimistic check: answer 'yes' to everything that can be asked."""
        true: set[str] = set()
        opened: set[str] = set()
        changed = True
        while changed:
            changed = False
            for q in self.questions:
                if q.fact not in opened and (not q.ask_if_any or true & set(q.ask_if_any)):
                    opened.add(q.fact)
                    true.add(q.fact)
                    changed = True
            for r in self.rules:  # ``unless`` ignored on purpose (optimistic)
                if r.then not in true and set(r.if_all) <= true:
                    true.add(r.then)
                    changed = True
        out = [f"question '{q.fact}' can never be asked"
               for q in self.questions if q.fact not in opened]
        out += [f"diagnosis '{f}' can never be reached" for f in sorted(diag_facts - true)]
        return out


# --------------------------------------------------------------------------- #
# Inference (forward chaining with certainty factors)
# --------------------------------------------------------------------------- #
def holds(facts: dict[str, float], fact: str) -> bool:
    return facts.get(fact, 0.0) >= THRESHOLD


def rule_strength(rule: Rule, facts: dict[str, float]) -> float | None:
    """How strongly ``rule`` fires on ``facts``; ``None`` if it does not."""
    if any(holds(facts, f) for f in rule.unless):
        return None
    cfs = [facts.get(f, 0.0) for f in rule.if_all]
    if min(cfs) < THRESHOLD:
        return None
    return min(cfs) * rule.cf


def infer(kb: KnowledgeBase, evidence: dict[str, float]) -> dict[str, float]:
    """Forward-chain from ``evidence`` to a fixed point; return all facts."""
    facts = dict(evidence)
    for _ in range(len(kb.rules) + 2):  # enough passes for any acyclic chain
        derived: dict[str, float] = {}
        for rule in kb.rules:
            strength = rule_strength(rule, facts)
            if strength is not None:
                derived[rule.then] = combine(derived.get(rule.then, 0.0), strength)
        merged = {**evidence, **derived}
        if merged.keys() == facts.keys() and all(
            abs(merged[k] - facts[k]) < _EPS for k in merged
        ):
            return merged
        facts = merged
    return facts


# --------------------------------------------------------------------------- #
# Explanation traces
# --------------------------------------------------------------------------- #
@dataclass
class RuleTrace:
    rule: Rule
    strength: float
    premises: list["Trace"]


@dataclass
class Trace:
    fact: str
    cf: float
    asked: bool                       # True = came straight from a user answer
    rules: list[RuleTrace] = field(default_factory=list)


def explain(kb: KnowledgeBase, evidence: dict[str, float], fact: str) -> Trace:
    """Build the proof tree showing why ``fact`` holds."""
    facts = infer(kb, evidence)

    def build(f: str, seen: frozenset[str]) -> Trace:
        if f in evidence:
            return Trace(f, evidence[f], asked=True)
        trace = Trace(f, facts.get(f, 0.0), asked=False)
        if f in seen:
            return trace
        for rule in kb.rules:
            if rule.then != f:
                continue
            strength = rule_strength(rule, facts)
            if strength is None:
                continue
            premises = [build(p, seen | {f}) for p in rule.if_all]
            trace.rules.append(RuleTrace(rule, strength, premises))
        return trace

    return build(fact, frozenset())


# --------------------------------------------------------------------------- #
# A consultation session
# --------------------------------------------------------------------------- #
class Session:
    """One consultation: asks the next sensible question and keeps answers."""

    def __init__(self, kb: KnowledgeBase):
        self.kb = kb
        self.evidence: dict[str, float] = {}
        self.history: list[str] = []  # facts in the order they were answered
        self._cache: dict[str, float] | None = None

    # -- state ------------------------------------------------------------- #
    def facts(self) -> dict[str, float]:
        if self._cache is None:
            self._cache = infer(self.kb, self.evidence)
        return self._cache

    @property
    def answered(self) -> int:
        return len(self.history)

    # -- dialogue ---------------------------------------------------------- #
    def next_question(self) -> Question | None:
        facts = self.facts()
        for q in self.kb.questions:
            if q.fact in self.history:
                continue
            if q.ask_if_any and not any(holds(facts, f) for f in q.ask_if_any):
                continue
            return q
        return None

    def answer(self, fact: str, choice: str) -> None:
        if choice not in CHOICES:
            raise ValueError(f"choice must be one of {CHOICES}, got {choice!r}")
        if self.kb.question_for(fact) is None:
            raise KeyError(fact)
        if fact in self.history:
            raise ValueError(f"'{fact}' was already answered")
        if choice != "unknown":
            self.evidence[fact] = ANSWER_CF[choice]
        self.history.append(fact)
        self._cache = None

    def undo(self) -> bool:
        """Take back the last answer. Returns False if there was nothing to undo."""
        if not self.history:
            return False
        self.evidence.pop(self.history.pop(), None)
        self._cache = None
        return True

    # -- results ----------------------------------------------------------- #
    def diagnoses(self) -> list[tuple[Diagnosis, float]]:
        """Reported diagnoses: safety warnings first, then by certainty."""
        facts = self.facts()
        found = [(d, facts[d.fact]) for d in self.kb.diagnoses
                 if facts.get(d.fact, 0.0) >= REPORT_MIN]
        return sorted(found, key=lambda pair: (not pair[0].urgent, -pair[1]))

    def explain(self, fact: str) -> Trace:
        return explain(self.kb, self.evidence, fact)
