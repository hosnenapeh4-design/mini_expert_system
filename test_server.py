"""Web server: pure ``step`` function plus real HTTP round-trips."""

import json
import re
import threading
import unittest
import urllib.error
import urllib.request

import server
from expert import ALL_KBS, Session

ARABIC = re.compile(r"[؀-ۿ]")


class StepFunction(unittest.TestCase):
    def test_first_step_asks_the_first_question(self):
        out = server.step("car", [], "en")
        self.assertFalse(out["done"])
        self.assertEqual(out["question"]["fact"], "no_start")
        self.assertEqual(out["live"], [])

    def test_replay_matches_a_direct_session(self):
        answers = [["no_start", "yes"], ["slow_or_no_crank", "yes"], ["clicking", "unknown"],
                   ["dim_lights", "yes"]]
        out = server.step("car", answers, "en")
        s = Session(ALL_KBS["car"])
        for fact, choice in answers:
            s.answer(fact, choice)
        self.assertEqual(out["question"]["fact"], s.next_question().fact)
        self.assertEqual(out["live"][0]["fact"], "dead_battery")
        self.assertEqual(out["live"][0]["cf"], round(s.diagnoses()[0][1] * 100))

    def test_finishes_with_results_steps_and_reasoning(self):
        answers, out = [], server.step("car", [], "en")
        script = {"no_start": "yes", "slow_or_no_crank": "yes", "dim_lights": "yes"}
        while not out["done"]:
            answers.append([out["question"]["fact"], script.get(out["question"]["fact"], "no")])
            out = server.step("car", answers, "en")
        top = out["results"][0]
        self.assertEqual(top["fact"], "dead_battery")
        self.assertGreater(top["cf"], 90)
        self.assertTrue(top["steps"])
        self.assertTrue(any("C01" in line["text"] for line in top["why"]))

    def test_urgent_flag_and_order(self):
        answers, out = [], server.step("car", [], "en")
        while not out["done"]:
            answers.append([out["question"]["fact"], "yes" if out["question"]["fact"] == "brake_soft" else "no"])
            out = server.step("car", answers, "en")
        self.assertTrue(out["results"][0]["urgent"])

    def test_arabic(self):
        out = server.step("network", [["no_internet", "yes"]], "ar")
        self.assertRegex(out["question"]["text"], ARABIC)
        self.assertRegex(out["live"][0]["title"] if out["live"] else "x", ARABIC)

    def test_rejects_bad_input(self):
        bad = [
            ("nope", [], "en"),
            ("car", [], "fr"),
            ("car", "notalist", "en"),
            ("car", [["no_start", "maybe"]], "en"),
            ("car", [["clicking", "yes"]], "en"),              # not the current question
            ("car", [["no_start", "yes"], ["no_start", "yes"]], "en"),
            ("car", [["no_start"]], "en"),
            ("car", [[1, 2]], "en"),
            ("car", [["no_start", "no"]] * 201, "en"),
        ]
        for args in bad:
            with self.subTest(args=args), self.assertRaises(ValueError):
                server.step(*args)

    def test_meta_lists_every_domain_in_both_languages(self):
        m = server.meta()
        self.assertEqual([d["key"] for d in m["domains"]], list(ALL_KBS))
        self.assertEqual(set(m["ui"]), {"en", "ar"})
        self.assertEqual(set(m["ui"]["en"]), set(m["ui"]["ar"]))


class Http(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.httpd = server.make_server("127.0.0.1", 0)
        cls.base = f"http://127.0.0.1:{cls.httpd.server_address[1]}"
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()

    def request(self, path, body=None, raw=None):
        data = raw if raw is not None else (None if body is None else json.dumps(body).encode())
        req = urllib.request.Request(self.base + path, data=data,
                                     headers={"Content-Type": "application/json"} if data is not None else {})
        try:
            with urllib.request.urlopen(req, timeout=5) as res:
                return res.status, res.headers, res.read()
        except urllib.error.HTTPError as err:
            return err.code, err.headers, err.read()

    def test_static_files(self):
        for path, ctype in (("/", "text/html"), ("/style.css", "text/css"), ("/app.js", "application/javascript")):
            status, headers, body = self.request(path)
            self.assertEqual(status, 200, path)
            self.assertIn(ctype, headers["Content-Type"])
            self.assertTrue(body)
        self.assertIn("default-src 'self'", headers["Content-Security-Policy"])
        self.assertEqual(headers["X-Content-Type-Options"], "nosniff")

    def test_meta_endpoint(self):
        status, _, body = self.request("/api/meta")
        self.assertEqual(status, 200)
        self.assertEqual(len(json.loads(body)["domains"]), 3)

    def test_step_roundtrip(self):
        status, _, body = self.request("/api/step", {"domain": "computer", "answers": [], "lang": "ar"})
        out = json.loads(body)
        self.assertEqual(status, 200)
        self.assertEqual(out["question"]["fact"], "no_power")
        self.assertRegex(out["question"]["text"], ARABIC)

    def test_errors(self):
        self.assertEqual(self.request("/api/step", {"domain": "nope"})[0], 400)
        self.assertEqual(self.request("/api/step", raw=b"{not json")[0], 400)
        self.assertEqual(self.request("/api/step", raw=b"[1,2]")[0], 400)
        self.assertEqual(self.request("/api/step", raw=b"")[0], 400)
        self.assertEqual(self.request("/api/step", {"domain": "car", "answers": [["clicking", "yes"]]})[0], 400)
        self.assertEqual(self.request("/nothing")[0], 404)
        self.assertEqual(self.request("/api/nothing", {})[0], 404)

    def test_only_whitelisted_files_are_served(self):
        for path in ("/../server.py", "/..%2fserver.py", "/expert/engine.py", "/web/app.js", "/etc/passwd"):
            with self.subTest(path=path):
                self.assertEqual(self.request(path)[0], 404)

    def test_frontend_never_uses_innerhtml_or_inline_style_attributes(self):
        js = self.request("/app.js")[2].decode()
        self.assertNotRegex(js, r"\.(innerHTML|outerHTML)|insertAdjacentHTML|document\.write")
        self.assertNotIn('setAttribute("style"', js)
        html = self.request("/")[2].decode()
        self.assertNotIn("<script>", html)
        self.assertNotIn(" style=", html)


if __name__ == "__main__":
    unittest.main()
