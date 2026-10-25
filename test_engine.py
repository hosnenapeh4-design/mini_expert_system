"""Engine behaviour on a tiny, hand-checkable knowledge base."""

import dataclasses
import random
import unittest

from expert.engine import (
    Diagnosis, KnowledgeBase, Question, Rule, Session, combine, explain, infer, tr,
)


def T(s):  # bilingual text helper: same string in both languages
    return (s, s + " (ar)")


def toy_kb(**overrides):
    parts = dict(
        key="toy",
        title=T("Toy"),
        intro=T("A toy"),
        questions=(
            Question("a", T("A?")),
            Question("b", T("B?")),
            Question("c", T("C?"), ("a",)),          # only asked when a holds
        ),
        rules=(
            Rule("T1", ("a", "b"), "x", 0.8),
            Rule("T2", ("a",), "x", 0.5),
            Rule("T3", ("x",), "y", 0.5),
            Rule("T4", ("c",), "z", 1.0, unless=("b",)),
        ),
        diagnoses=(
            Diagnosis("x", T("X"), (T("do x"),)),
            Diagnosis("y", T("Y"), (T("do y"),)),
            Diagnosis("z", T("Z"), (T("do z"),)),
        ),
    )
    parts.update(overrides)
    return KnowledgeBase(**parts)


class CertaintyMath(unittest.TestCase):
    def test_combine_is_probabilistic_or(self):
        self.assertAlmostEqual(combine(0.8, 0.5), 0.9)
        self.assertAlmostEqual(combine(0.0, 0.7), 0.7)
        self.assertAlmostEqual(combine(1.0, 0.7), 1.0)

    def test_two_rules_merge_evidence(self):
        facts = infer(toy_kb(), {"a": 1.0, "b": 1.0})
        self.assertAlmostEqual(facts["x"], combine(0.8, 0.5))

    def test_weakest_premise_limits_the_rule(self):
        facts = infer(toy_kb(), {"a": 1.0, "b": 0.6})
        self.assertAlmostEqual(facts["x"], combine(0.6 * 0.8, 0.5))

    def test_chain_through_an_intermediate_fact(self):
        facts = infer(toy_kb(), {"a": 1.0, "b": 1.0})
        self.assertAlmostEqual(facts["y"], facts["x"] * 0.5)

    def test_false_premise_does_not_fire(self):
        facts = infer(toy_kb(), {"a": 0.0, "b": 1.0})
        self.assertNotIn("x", facts)

    def test_unless_blocks_a_rule(self):
        self.assertAlmostEqual(infer(toy_kb(), {"a": 1.0, "b": 0.0, "c": 1.0})["z"], 1.0)
        self.assertNotIn("z", infer(toy_kb(), {"a": 1.0, "b": 1.0, "c": 1.0}))

    def test_result_does_not_depend_on_rule_order(self):
        kb = toy_kb()
        expected = infer(kb, {"a": 1.0, "b": 0.6, "c": 1.0})
        rules = list(kb.rules)
        for seed in range(10):
            random.Random(seed).shuffle(rules)
            shuffled = toy_kb(rules=tuple(rules))
            got = infer(shuffled, {"a": 1.0, "b": 0.6, "c": 1.0})
            self.assertEqual(got.keys(), expected.keys())
            for k in got:
                self.assertAlmostEqual(got[k], expected[k])

    def test_evidence_is_never_mutated(self):
        evidence = {"a": 1.0}
        infer(toy_kb(), evidence)
        self.assertEqual(evidence, {"a": 1.0})


class SessionFlow(unittest.TestCase):
    def test_gated_question_only_after_its_gate_holds(self):
        s = Session(toy_kb())
        self.assertEqual(s.next_question().fact, "a")
        s.answer("a", "no")
        self.assertEqual(s.next_question().fact, "b")
        s.answer("b", "yes")
        self.assertIsNone(s.next_question())  # c never asked: a is false

        s = Session(toy_kb())
        s.answer("a", "probably")
        s.answer("b", "no")
        self.assertEqual(s.next_question().fact, "c")

    def test_unknown_answer_is_recorded_but_adds_no_evidence(self):
        s = Session(toy_kb())
        s.answer("a", "unknown")
        self.assertEqual(s.evidence, {})
        self.assertEqual(s.answered, 1)
        self.assertEqual(s.next_question().fact, "b")  # not asked twice

    def test_undo(self):
        s = Session(toy_kb())
        s.answer("a", "yes")
        s.answer("b", "yes")
        self.assertTrue(s.undo())
        self.assertEqual(s.next_question().fact, "b")
        self.assertNotIn("b", s.evidence)
        self.assertTrue(s.undo())
        self.assertFalse(s.undo())
        self.assertEqual(s.facts(), {})

    def test_bad_answers_are_rejected(self):
        s = Session(toy_kb())
        with self.assertRaises(ValueError):
            s.answer("a", "maybe")
        with self.assertRaises(KeyError):
            s.answer("nope", "yes")
        s.answer("a", "yes")
        with self.assertRaises(ValueError):
            s.answer("a", "no")

    def test_diagnoses_sorted_and_thresholded(self):
        s = Session(toy_kb())
        s.answer("a", "yes")
        s.answer("b", "yes")
        s.answer("c", "no")
        found = [(d.fact, cf) for d, cf in s.diagnoses()]
        self.assertEqual([f for f, _ in found], ["x", "y"])
        self.assertGreater(found[0][1], found[1][1])
        # y = 0.5 * x ~ 0.45 is above REPORT_MIN; a weaker answer drops it out
        weak = Session(toy_kb())
        weak.answer("a", "probably")
        weak.answer("b", "no")
        self.assertEqual([d.fact for d, _ in weak.diagnoses()], ["x"])


class Explanations(unittest.TestCase):
    def test_trace_shows_rules_and_user_answers(self):
        s = Session(toy_kb())
        s.answer("a", "yes")
        s.answer("b", "probably")
        trace = s.explain("y")
        self.assertFalse(trace.asked)
        self.assertEqual([r.rule.id for r in trace.rules], ["T3"])
        x_trace = trace.rules[0].premises[0]
        self.assertEqual(x_trace.fact, "x")
        self.assertEqual({r.rule.id for r in x_trace.rules}, {"T1", "T2"})
        t1 = next(r for r in x_trace.rules if r.rule.id == "T1")
        self.assertTrue(all(p.asked for p in t1.premises))
        self.assertEqual([p.cf for p in t1.premises], [1.0, 0.6])

    def test_blocked_rules_are_not_in_the_trace(self):
        s = Session(toy_kb())
        for fact, choice in (("a", "yes"), ("b", "yes"), ("c", "yes")):
            s.answer(fact, choice)
        self.assertEqual(explain(s.kb, s.evidence, "z").rules, [])


class Validation(unittest.TestCase):
    def test_toy_kb_is_valid_except_for_missing_label(self):
        self.assertEqual(toy_kb().validate(), [])

    def assertProblem(self, kb, needle):
        problems = kb.validate()
        self.assertTrue(any(needle in p for p in problems), f"{needle!r} not in {problems}")

    def test_detects_unknown_fact(self):
        kb = toy_kb(rules=toy_kb().rules + (Rule("T9", ("ghost",), "x", 0.5),))
        self.assertProblem(kb, "unknown fact 'ghost'")

    def test_detects_bad_certainty(self):
        kb = toy_kb(rules=(Rule("T1", ("a",), "x", 1.5),))
        self.assertProblem(kb, "outside (0, 1]")

    def test_detects_cycles(self):
        rules = (Rule("R1", ("a",), "p", 0.5), Rule("R2", ("p",), "q", 0.5),
                 Rule("R3", ("q",), "p", 0.5))
        kb = toy_kb(rules=rules, diagnoses=(Diagnosis("p", T("P"), (T("s"),)),),
                    labels={"q": T("Q")})
        self.assertProblem(kb, "cyclic")

    def test_detects_missing_label_for_intermediate_fact(self):
        rules = (Rule("R1", ("a",), "mid", 0.5), Rule("R2", ("mid",), "end", 0.5))
        kb = toy_kb(rules=rules, diagnoses=(Diagnosis("end", T("E"), (T("s"),)),))
        self.assertProblem(kb, "has no label")

    def test_detects_diagnosis_without_rule(self):
        kb = toy_kb(diagnoses=toy_kb().diagnoses + (Diagnosis("w", T("W"), (T("s"),)),))
        self.assertProblem(kb, "never concluded")

    def test_detects_unreachable_question(self):
        qs = toy_kb().questions + (Question("d", T("D?"), ("z2",)),)
        rules = toy_kb().rules + (Rule("R9", ("d",), "z2", 0.5),)
        kb = toy_kb(questions=qs, rules=rules,
                    diagnoses=toy_kb().diagnoses + (Diagnosis("z2", T("Z2"), (T("s"),)),))
        self.assertProblem(kb, "can never be asked")

    def test_detects_missing_translation(self):
        kb = toy_kb(title=("Toy", ""))
        self.assertProblem(kb, "missing English or Arabic")

    def test_tr_picks_language(self):
        self.assertEqual(tr(("hi", "اهلا"), "en"), "hi")
        self.assertEqual(tr(("hi", "اهلا"), "ar"), "اهلا")

    def test_rules_are_immutable(self):
        with self.assertRaises(dataclasses.FrozenInstanceError):
            Rule("R", ("a",), "b", 0.5).cf = 1.0  # type: ignore[misc]


if __name__ == "__main__":
    unittest.main()
