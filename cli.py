"""Command-line front end.

    python cli.py                      # pick a domain from a menu
    python cli.py --domain car --lang ar
"""

from __future__ import annotations

import argparse
import sys
from typing import Callable

from expert import ALL_KBS, KnowledgeBase, Session, tr
from expert.explain import render_trace, to_markdown
from expert.ui import ANSWER_ALIASES, UI


class Quit(Exception):
    """Raised when the user leaves the consultation."""


def _ask(input_fn: Callable[[str], str], prompt: str) -> str:
    try:
        return input_fn(prompt).strip()
    except EOFError as exc:  # piped input ran out
        raise Quit from exc


def choose_domain(lang: str, input_fn=None, print_fn=None) -> KnowledgeBase:
    input_fn, print_fn = input_fn or input, print_fn or print
    ui = UI[lang]
    keys = list(ALL_KBS)
    print_fn(f"\n{ui['pick_domain']}")
    for i, key in enumerate(keys, 1):
        print_fn(f"  {i}. {tr(ALL_KBS[key].title, lang)}")
    while True:
        raw = _ask(input_fn, ui["choose"])
        if raw.isdigit() and 1 <= int(raw) <= len(keys):
            return ALL_KBS[keys[int(raw) - 1]]
        if raw in ALL_KBS:
            return ALL_KBS[raw]
        print_fn(ui["bad_input"])


def consult(kb: KnowledgeBase, lang: str = "en", input_fn=None, print_fn=None,
            show_why: bool | None = None) -> Session:
    """Run one interactive consultation and print the results."""
    input_fn, print_fn = input_fn or input, print_fn or print
    ui = UI[lang]
    session = Session(kb)
    print_fn(f"\n=== {tr(kb.title, lang)} ===")
    print_fn(tr(kb.intro, lang))
    print_fn(ui["keys"])

    while (question := session.next_question()) is not None:
        print_fn(f"\n{ui['question'].format(n=session.answered + 1)}: {tr(question.text, lang)}")
        raw = _ask(input_fn, "> ").lower()
        if raw in ("q", "quit", "خروج"):
            raise Quit
        if raw in ("b", "back", "رجوع"):
            session.undo()
            continue
        choice = ANSWER_ALIASES.get(raw)
        if choice is None:
            print_fn(ui["bad_input"])
            continue
        session.answer(question.fact, choice)

    print_results(session, lang, print_fn)
    if show_why is None:
        try:
            show_why = _ask(input_fn, "\n" + ui["ask_why"]).lower() in ("y", "yes", "ن", "نعم")
        except Quit:
            show_why = False
    if show_why:
        print_why(session, lang, print_fn)
    print_fn(f"\n{ui['disclaimer']}")
    return session


def print_results(session: Session, lang: str, print_fn=None) -> None:
    print_fn = print_fn or print
    ui = UI[lang]
    results = session.diagnoses()
    print_fn(f"\n=== {ui['results']} ===")
    if not results:
        print_fn(ui["no_result"])
        return
    for i, (diagnosis, cf) in enumerate(results, 1):
        flag = f"  [{ui['important']}]" if diagnosis.urgent else ""
        print_fn(f"\n{i}. {tr(diagnosis.title, lang)} - {ui['confidence']} {round(cf * 100)}%{flag}")
        print_fn(f"   {ui['what_to_do']}:")
        for step in diagnosis.steps:
            print_fn(f"   * {tr(step, lang)}")


def print_why(session: Session, lang: str, print_fn=None) -> None:
    print_fn = print_fn or print
    ui = UI[lang]
    for diagnosis, _ in session.diagnoses():
        print_fn(f"\n--- {ui['why']} {tr(diagnosis.title, lang)}")
        lines = render_trace(session.kb, session.explain(diagnosis.fact), lang)
        print_fn(to_markdown(lines))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Mini expert system (CLI)")
    parser.add_argument("--lang", choices=("en", "ar"), default="en")
    parser.add_argument("--domain", choices=list(ALL_KBS))
    parser.add_argument("--why", action="store_true", help="always print the reasoning")
    args = parser.parse_args(argv)
    try:
        kb = ALL_KBS[args.domain] if args.domain else choose_domain(args.lang)
        consult(kb, args.lang, show_why=True if args.why else None)
    except (Quit, KeyboardInterrupt):
        print(f"\n{UI[args.lang]['goodbye']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
