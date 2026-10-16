"""Endpoint propio (Hive AI) — bootstrap y office-test-model."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).parent))
from test_bootstrap import BootstrapTest  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
TESTER = ROOT / "docker" / "office" / "bin" / "office-test-model"


class CustomBootstrapTest(BootstrapTest):
    def test_full_bootstrap_is_idempotent(self):  # ya cubierto en test_bootstrap
        pass

    def test_soul_upgrade_only_when_unedited(self):
        pass

    def test_hive_then_back_to_nous(self):
        self.env.update(
            HERMES_PROVIDER="custom",
            HERMES_BASE_URL="https://api-cdn.thehive.ai/api/v3",
            HERMES_KEY_ENV="HIVE_API_KEY",
            HIVE_API_KEY="secret-123",
            HERMES_CONTEXT_LENGTH="131072",
            HERMES_MODEL_MANAGER="deepseek-ai/deepseek-v4.1-flash",
            HERMES_MODEL_WORKERS="deepseek-ai/deepseek-v4.1-flash",
        )
        self.run_bootstrap()
        for home in (self.hhome, self.hhome / "profiles" / "investigador"):
            m = yaml.safe_load((home / "config.yaml").read_text())["model"]
            self.assertEqual(m["provider"], "custom")
            self.assertEqual(m["base_url"], "https://api-cdn.thehive.ai/api/v3")
            self.assertEqual(m["key_env"], "HIVE_API_KEY")
            self.assertEqual(m["context_length"], 131072)
            self.assertEqual(m["default"], "deepseek-ai/deepseek-v4.1-flash")
            env = (home / ".env").read_text()
            self.assertIn("HIVE_API_KEY=secret-123", env)
            self.assertEqual(oct((home / ".env").stat().st_mode & 0o777), "0o600")

        # rotar la clave actualiza la línea sin duplicarla
        self.env["HIVE_API_KEY"] = "secret-456"
        self.run_bootstrap()
        env = (self.hhome / ".env").read_text()
        self.assertEqual(env.count("HIVE_API_KEY="), 1)
        self.assertIn("HIVE_API_KEY=secret-456", env)

        # volver a Nous limpia la URL y la variable de clave
        self.env.update(HERMES_PROVIDER="nous", HERMES_BASE_URL="", HERMES_KEY_ENV="",
                        HERMES_MODEL_MANAGER="stepfun/step-5-preview:free",
                        HERMES_MODEL_WORKERS="stepfun/step-5-preview:free")
        self.run_bootstrap()
        m = yaml.safe_load((self.hhome / "config.yaml").read_text())["model"]
        self.assertEqual(m["provider"], "nous")
        self.assertNotIn("base_url", m)
        self.assertNotIn("key_env", m)


class FakeOpenAI:
    def __init__(self, tools_ok: bool, key: str = "secret-123"):
        srv = self
        self.paths = []

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_POST(self):
                srv.paths.append(self.path)
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                if self.headers.get("Authorization") != f"Bearer {key}":
                    return self._send(401, {"error": "bad key"})
                if body.get("tools"):
                    if not tools_ok:
                        return self._send(400, {"error": "tools not supported"})
                    msg = {"role": "assistant", "content": None, "tool_calls": [
                        {"id": "c1", "type": "function",
                         "function": {"name": "get_weather", "arguments": '{"city":"Madrid"}'}}]}
                else:
                    msg = {"role": "assistant", "content": "OK"}
                self._send(200, {"choices": [{"message": msg}]})

            def _send(self, code, obj):
                data = json.dumps(obj).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.url = f"http://127.0.0.1:{self.httpd.server_address[1]}/api/v3"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


class TesterTest(unittest.TestCase):
    def run_tester(self, tmp: Path, url: str, key: str):
        env_file = tmp / ".env"
        env_file.write_text(
            f"HERMES_BASE_URL={url}\nHERMES_KEY_ENV=HIVE_API_KEY\nHIVE_API_KEY={key}\n"
            "HERMES_MODEL_WORKERS=deepseek-ai/deepseek-v4.1-flash\n"
        )
        env = {k: v for k, v in os.environ.items() if not k.lower().endswith("_proxy")}
        return subprocess.run([sys.executable, str(TESTER), str(env_file)], capture_output=True, text=True, env=env)

    def test_verdicts(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            ok = FakeOpenAI(tools_ok=True)
            no_tools = FakeOpenAI(tools_ok=False)
            try:
                r = self.run_tester(tmp, ok.url, "secret-123")
                self.assertEqual(r.returncode, 0, r.stdout)
                self.assertIn("Todo correcto", r.stdout)
                self.assertNotIn("secret-123", r.stdout)
                self.assertEqual(ok.paths[0], "/api/v3/chat/completions")

                r = self.run_tester(tmp, no_tools.url, "secret-123")
                self.assertEqual(r.returncode, 2, r.stdout)
                self.assertIn("NO funcionarán", r.stdout)

                r = self.run_tester(tmp, ok.url, "wrong")
                self.assertEqual(r.returncode, 1, r.stdout)
                self.assertIn("SECRET KEY", r.stdout)

                r = self.run_tester(tmp, ok.url + "/chat/completions", "secret-123")
                self.assertEqual(r.returncode, 1)
                self.assertIn("no debe terminar", r.stdout)
            finally:
                ok.close()
                no_tools.close()


if __name__ == "__main__":
    unittest.main()
