"""CLI front end driven by scripted input."""

import io
import re
import unittest
from contextlib import redirect_stdout
from unittest import mock

import cli
from expert import ALL_KBS


def scripted(lines):
    it = iter(lines)

    def input_fn(prompt=""):
        try:
            return next(it)
        except StopIteration:
            raise EOFError from None

    return input_fn


def run(kb_key, lines, lang="en", show_why=None):
    out = []
    session = cli.consult(ALL_KBS[kb_key], lang, scripted(lines), out.append, show_why)
    return session, "\n".join(out)


BATTERY = ["y", "y", "?", "y"] + ["n"] * 7  # exactly the 11 questions this scenario asks


class Consultation(unittest.TestCase):
    def test_full_run_prints_diagnosis_and_steps(self):
        session, text = run("car", BATTERY, show_why=False)
        self.assertIn("Weak or dead battery", text)
        self.assertIn("What to do", text)
        self.assertIn("Jump-start", text)
        self.assertEqual(session.diagnoses()[0][0].fact, "dead_battery")

    def test_reasoning_lists_rules_and_answers(self):
        _, text = run("car", BATTERY, show_why=True)
        self.assertIn("Rule C01", text)
        self.assertRegex(text, r"slowly or not at all\? - you said: Yes")

    def test_asks_about_reasoning_when_not_decided(self):
        _, text = run("car", BATTERY + ["y"])
        self.assertIn("Rule C01", text)
        _, text = run("car", BATTERY + ["n"])
        self.assertNotIn("Rule C01", text)

    def test_back_undoes_last_answer(self):
        session, _ = run("car", ["y", "n", "b", "y", "?", "n"] + ["n"] * 20, show_why=False)  # extra n's feed the 'why?' prompt
        self.assertEqual(session.evidence.get("slow_or_no_crank"), 1.0)

    def test_bad_input_reprompts_without_consuming_a_question(self):
        _, text = run("car", ["banana"] + BATTERY, show_why=False)
        self.assertIn("Please answer with", text)
        self.assertIn("Weak or dead battery", text)

    def test_quit_and_eof_raise_quit(self):
        with self.assertRaises(cli.Quit):
            run("car", ["q"])
        with self.assertRaises(cli.Quit):
            run("car", ["y"])  # input runs out mid-way

    def test_healthy_system_has_no_diagnosis(self):
        _, text = run("computer", ["n"] * 30, show_why=False)
        self.assertIn("No confident diagnosis", text)

    def test_urgent_diagnosis_is_flagged_and_first(self):
        _, text = run("car", ["n"] * 5 + ["y"] + ["n"] * 10, show_why=False)  # 6th root question: brake_soft
        self.assertRegex(text, r"1\. Do not drive the car.*\[IMPORTANT\]")

    def test_arabic_output(self):
        _, text = run("car", BATTERY, lang="ar", show_why=True)
        self.assertIn("بطارية ضعيفة أو فاضية", text)
        self.assertIn("نسبة الثقة", text)
        self.assertIn("القاعدة C01", text)
        self.assertIsNotNone(re.search(r"[؀-ۿ]", text))


class Menu(unittest.TestCase):
    def test_choose_domain_by_number_and_key(self):
        out = []
        self.assertEqual(cli.choose_domain("en", scripted(["2"]), out.append).key, "computer")
        self.assertEqual(cli.choose_domain("en", scripted(["x", "9", "network"]), out.append).key, "network")

    def test_main_with_domain_flag(self):
        buf = io.StringIO()
        with mock.patch("builtins.input", side_effect=scripted(BATTERY)), redirect_stdout(buf):
            self.assertEqual(cli.main(["--domain", "car", "--why"]), 0)
        self.assertIn("Weak or dead battery", buf.getvalue())
        self.assertIn("Rule C01", buf.getvalue())

    def test_main_says_goodbye_on_quit(self):
        buf = io.StringIO()
        with mock.patch("builtins.input", side_effect=scripted(["q"])), redirect_stdout(buf):
            self.assertEqual(cli.main(["--domain", "car"]), 0)
        self.assertIn("Goodbye", buf.getvalue())


if __name__ == "__main__":
    unittest.main()
