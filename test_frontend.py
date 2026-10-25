"""Runs web/app.js against the real server under Node (skipped without Node)."""

import pathlib
import shutil
import subprocess
import threading
import unittest

import server


@unittest.skipUnless(shutil.which("node"), "node is not installed")
class FrontendSmoke(unittest.TestCase):
    def test_app_js_against_real_server(self):
        httpd = server.make_server("127.0.0.1", 0)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        try:
            script = pathlib.Path(__file__).with_name("frontend_smoke.js")
            base = f"http://127.0.0.1:{httpd.server_address[1]}"
            run = subprocess.run(["node", str(script), base], capture_output=True, text=True, timeout=60)
            self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        finally:
            httpd.shutdown()
            httpd.server_close()


if __name__ == "__main__":
    unittest.main()
