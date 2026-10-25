"""Zero-dependency web front end (standard library only).

    python server.py            # http://127.0.0.1:8000
    python server.py --port 9000

The server keeps no state: the browser sends the list of answers given so far
and the server replays them through the expert system on every request.
"""

from __future__ import annotations

import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from expert import ALL_KBS, CHOICES, Session, tr
from expert.explain import render_trace
from expert.ui import UI

WEB_DIR = Path(__file__).parent / "web"
STATIC = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/style.css": ("style.css", "text/css; charset=utf-8"),
    "/app.js": ("app.js", "application/javascript; charset=utf-8"),
}
MAX_BODY = 64 * 1024
MAX_ANSWERS = 200
TOP_LIVE = 4


def meta() -> dict:
    """Everything the page needs to draw itself."""
    return {
        "ui": UI,
        "domains": [
            {"key": kb.key, "title": list(kb.title), "intro": list(kb.intro)}
            for kb in ALL_KBS.values()
        ],
    }


def step(domain: str, answers: list, lang: str) -> dict:
    """Replay ``answers`` and describe the state of the consultation.

    Raises ``ValueError`` for anything that is not a legitimate dialogue.
    """
    kb = ALL_KBS.get(domain)
    if kb is None:
        raise ValueError("unknown domain")
    if lang not in UI:
        raise ValueError("unknown language")
    if not isinstance(answers, list) or len(answers) > MAX_ANSWERS:
        raise ValueError("answers must be a short list")

    session = Session(kb)
    for item in answers:
        if not (isinstance(item, list) and len(item) == 2
                and all(isinstance(x, str) for x in item)):
            raise ValueError("each answer must be [fact, choice]")
        fact, choice = item
        question = session.next_question()
        if question is None or question.fact != fact or choice not in CHOICES:
            raise ValueError("answer does not match the current question")
        session.answer(fact, choice)

    question = session.next_question()
    payload: dict = {
        "answered": session.answered,
        "done": question is None,
        "question": None if question is None else {"fact": question.fact, "text": tr(question.text, lang)},
        "live": [
            {"fact": d.fact, "title": tr(d.title, lang), "cf": round(cf * 100)}
            for d, cf in session.diagnoses()[:TOP_LIVE]
        ],
    }
    if question is None:
        payload["results"] = [
            {
                "fact": d.fact,
                "title": tr(d.title, lang),
                "cf": round(cf * 100),
                "urgent": d.urgent,
                "steps": [tr(s, lang) for s in d.steps],
                "why": [{"depth": depth, "text": text}
                        for depth, text in render_trace(kb, session.explain(d.fact), lang)],
            }
            for d, cf in session.diagnoses()
        ]
    return payload


class Handler(BaseHTTPRequestHandler):
    server_version = "MiniExpert/1.0"

    def _send(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Security-Policy", "default-src 'self'")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, status: int, data: dict) -> None:
        self._send(status, json.dumps(data, ensure_ascii=False).encode("utf-8"),
                   "application/json; charset=utf-8")

    def do_GET(self) -> None:  # noqa: N802 (http.server naming)
        path = self.path.split("?", 1)[0]
        if path == "/api/meta":
            return self._json(200, meta())
        if path in STATIC:
            name, content_type = STATIC[path]
            return self._send(200, (WEB_DIR / name).read_bytes(), content_type)
        self._json(404, {"error": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        if self.path.split("?", 1)[0] != "/api/step":
            return self._json(404, {"error": "not found"})
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= MAX_BODY:
                raise ValueError("bad body size")
            body = json.loads(self.rfile.read(length))
            if not isinstance(body, dict):
                raise ValueError("body must be an object")
            result = step(body.get("domain", ""), body.get("answers", []), body.get("lang", "en"))
        except (ValueError, json.JSONDecodeError) as exc:
            return self._json(400, {"error": str(exc)})
        self._json(200, result)

    def log_message(self, fmt: str, *args) -> None:  # keep the console quiet
        pass


def make_server(host: str = "127.0.0.1", port: int = 8000) -> ThreadingHTTPServer:
    return ThreadingHTTPServer((host, port), Handler)


def main() -> None:
    parser = argparse.ArgumentParser(description="Mini expert system (web)")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    server = make_server(args.host, args.port)
    print(f"Serving on http://{args.host}:{args.port}  (Ctrl+C to stop)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
