# Mini Expert System

A complete rule-based expert system in pure Python: a knowledge base, an inference engine, an explanation facility and two front ends (command line and web). It diagnoses problems in three domains, in English and Arabic, with no third-party dependencies.

| Domain | Typical problems it can diagnose |
|---|---|
| Car diagnosis | won't start, overheating, brakes, vibration, warning lights |
| Computer troubleshooting | no power, no display, slow PC, overheating, blue screens, failing disk |
| Network troubleshooting | no internet, slow Wi-Fi, drops, DNS/DHCP problems, one site failing |

ملخص بالعربي: نظام خبير كامل بيسألك أسئلة (أيوه / غالباً / لأ / مش عارف)، وبيستنتج الأعطال المحتملة بنسبة ثقة، ويقولك تعمل إيه، ويشرح ليه وصل للنتيجة دي. شغّال بالعربي والإنجليزي، ومش محتاج تثبّت أي مكتبة.

## Run it

Python 3.10+ is all you need.

```bash
python cli.py                        # interactive menu
python cli.py --domain car --lang ar --why
python server.py                     # web UI at http://127.0.0.1:8000
python -m unittest discover -s tests -t .
```

Arabic in the terminal depends on your terminal's right-to-left support; the web UI handles it properly.

## How it works

```
expert/engine.py   Rule, Question, Diagnosis, KnowledgeBase, infer(), explain(), Session
expert/kb/         one file per domain: just data (questions, rules, diagnoses)
expert/explain.py  proof tree -> readable "why?" lines
cli.py, server.py  the two front ends; web/ holds the page
tests/             82+ tests, including fuzzing and a Node run of the page's JavaScript
```

**Knowledge.** A rule reads `IF all premises hold [UNLESS some fact holds] THEN conclusion (certainty)`, for example:

```python
Rule("C01", ("slow_or_no_crank", "dim_lights"), "dead_battery", 0.9)
Rule("C04", ("slow_or_no_crank",), "starter_fault", 0.6, unless=("dim_lights",))
```

**Inference.** Forward chaining: apply every rule whose premises hold, add the new facts, repeat until nothing changes. Rules can feed other rules, so a symptom can lead to an intermediate fact (`cooling_system_problem`) and from there to a safety warning (`unsafe_to_drive`).

**Uncertainty.** MYCIN-style certainty factors. The user answers *yes* (1.0), *probably* (0.6) or *no* (0). A rule fires with `min(premises) x rule certainty`, and independent evidence for the same conclusion merges as `a + b(1 - a)`. Facts count as true from 0.2; diagnoses are reported from 0.3.

**Questions.** A question can be gated (`ask_if_any`) so the system only asks about battery symptoms once the car fails to start. Answers can be undone.

**Explanation.** Every diagnosis keeps its proof tree: which rules fired, how much each added, and which answers they rest on. Safety warnings (`urgent=True`) are always listed first.

**Web.** The server is stateless: the browser sends the answers so far and the server replays them. The live gauge shows the engine's current best guesses as you answer. The page uses a strict Content-Security-Policy and never inserts server text as HTML.

## Add your own domain

Create `expert/kb/your_domain.py` with a `KB = KnowledgeBase(...)`, register it in `expert/kb/__init__.py`, and run:

```python
from expert import ALL_KBS
print(ALL_KBS["your_domain"].validate())   # [] means healthy
```

`validate()` catches unknown facts, cycles, missing translations, intermediate facts without labels, questions that can never be asked and diagnoses that can never be reached.

## Limits

- It gives guidance, not certainty: certainty factors are hand-tuned by the author, not learned from data.
- Negation is "not established" (a rule's `unless` fires on facts that do not hold, including unanswered ones).
- Safety-critical advice (brakes, overheating) always tells the user to see a professional.
