"""Pruebas del plugin pixel-office contra un Pixel Agents simulado.

    python3 -m unittest discover -s tests -v
"""

from __future__ import annotations

import importlib.util
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "hermes" / "plugins" / "pixel-office"
sys.path.insert(0, str(Path(__file__).parent))
from mock_pixel_agents import MockOffice  # noqa: E402


def load_plugin():
    name = "pixel_office_under_test"
    for k in [k for k in sys.modules if k.startswith(name)]:
        del sys.modules[k]
    spec = importlib.util.spec_from_file_location(name, PLUGIN / "__init__.py", submodule_search_locations=[str(PLUGIN)])
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


class FakeCtx:
    def __init__(self):
        self.hooks = {}

    def register_hook(self, name, cb):
        self.hooks.setdefault(name, []).append(cb)

    def fire(self, name, **kw):
        for cb in self.hooks.get(name, []):
            cb(**kw)


def wait_until(pred, timeout=5.0):
    end = time.time() + timeout
    while time.time() < end:
        if pred():
            return True
        time.sleep(0.05)
    return False


class BridgeTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        t = Path(self.tmp.name)
        self.pixel_dir = t / ".pixel-agents"
        self.vault = t / "vault"
        self.vault.mkdir()
        self.office = MockOffice(self.pixel_dir)
        self._env = dict(os.environ)
        os.environ.update(
            PIXEL_AGENTS_DIR=str(self.pixel_dir),
            OFFICE_VAULT=str(self.vault),
            HERMES_HOME=str(t / "hermes" / "profiles" / "investigador"),
        )
        os.environ.pop("HERMES_PROFILE", None)
        os.environ.pop("PIXEL_OFFICE_URL", None)
        self.mod = load_plugin()
        self.ctx = FakeCtx()
        self.mod.register(self.ctx)

    def tearDown(self):
        self.office.close()
        os.environ.clear()
        os.environ.update(self._env)
        self.tmp.cleanup()

    def agent(self, sid="hermes-investigador"):
        return self.office.agents.get(sid)

    def test_registers_all_hooks(self):
        for h in ("pre_tool_call", "post_tool_call", "on_session_end", "kanban_task_completed"):
            self.assertIn(h, self.ctx.hooks)

    def test_turn_creates_named_character_and_tracks_tools(self):
        self.ctx.fire("on_session_start", session_id="abc", model="m", platform="cli")
        self.ctx.fire("pre_llm_call", session_id="abc", user_message="hola")
        self.assertTrue(wait_until(lambda: self.agent() is not None), self.office.raw)
        self.assertEqual(self.agent()["folderName"], "investigador")
        self.assertEqual(self.agent()["tool"][0], "EnterPlanMode")

        self.ctx.fire("pre_tool_call", tool_name="web_search", args={"query": "pixel agents"}, task_id="t")
        self.assertTrue(wait_until(lambda: (self.agent()["tool"] or ("",))[0] == "WebSearch"))

        self.ctx.fire("pre_tool_call", tool_name="write_file", args={"path": "/vault/02 Investigación/x.md", "content": "…"})
        self.assertTrue(wait_until(lambda: (self.agent()["tool"] or ("",))[0] == "Write"))
        self.assertEqual(self.agent()["tool"][1], {"file_path": "/vault/02 Investigación/x.md"})

        self.ctx.fire("post_tool_call", tool_name="write_file", result="{}")
        self.ctx.fire("on_session_end", session_id="abc", completed=True)
        self.assertTrue(wait_until(lambda: self.agent()["status"] == "done"))
        self.assertEqual(self.office.rejected, 0)

    def test_permission_and_clarify(self):
        self.ctx.fire("pre_llm_call")
        self.assertTrue(wait_until(lambda: self.agent() is not None))
        self.ctx.fire("on_human_input_request", kind="approval", prompt="rm -rf")
        self.assertTrue(wait_until(lambda: self.agent()["status"] == "permission"))
        self.ctx.fire("on_human_input_request", kind="clarify", prompt="¿?")
        self.assertTrue(wait_until(lambda: self.agent()["status"] == "waiting"))

    def test_subagents(self):
        self.ctx.fire("pre_llm_call")
        self.assertTrue(wait_until(lambda: self.agent() is not None))
        self.ctx.fire("subagent_start", child_role="lector", child_goal="leer docs")
        self.assertTrue(wait_until(lambda: self.agent()["subagents"] == 1))
        self.ctx.fire("subagent_stop", child_status="ok")
        self.assertTrue(wait_until(lambda: self.agent()["subagents"] == 0))

    def test_kanban_events_land_in_vault(self):
        self.ctx.fire("kanban_task_completed", task_id="t_1", assignee="investigador", summary="Nota en 02 Investigación/x.md")
        self.ctx.fire("kanban_task_blocked", task_id="t_2", assignee="desarrollador", reason="falta API key")
        logs = list((self.vault / "Agentes" / "_Registro").glob("*.md"))
        self.assertEqual(len(logs), 1)
        text = logs[0].read_text(encoding="utf-8")
        self.assertIn("✅ **investigador** completó `t_1`", text)
        self.assertIn("⛔ **desarrollador** bloqueó `t_2` — falta API key", text)
        self.assertTrue(text.startswith("---\ntipo: registro"))

    def test_claimed_shows_handoff_on_manager(self):
        os.environ["HERMES_HOME"] = str(Path(self.tmp.name) / "hermes")  # perfil raíz
        self.ctx.fire("kanban_task_claimed", task_id="t_9", assignee="desarrollador", board="default")
        self.assertTrue(wait_until(lambda: self.agent("hermes-manager") is not None))
        self.assertEqual(self.agent("hermes-manager")["folderName"], "manager")
        self.assertTrue(wait_until(lambda: "Stop" in self.agent("hermes-manager")["log"]))

    def test_office_down_never_raises(self):
        self.office.close()
        for f in (self.pixel_dir / "servers").glob("*.json"):
            f.unlink()
        t0 = time.time()
        for _ in range(50):
            self.ctx.fire("pre_tool_call", tool_name="terminal", args={"command": "ls"})
        self.assertLess(time.time() - t0, 0.5, "los hooks no deben bloquear al agente")


class MappingTest(unittest.TestCase):
    def setUp(self):
        self.bridge = load_plugin().bridge

    def test_profile_resolution(self):
        pn = self.bridge.profile_name
        self.assertEqual(pn({"HERMES_PROFILE": "bibliotecario"}), "bibliotecario")
        self.assertEqual(pn({"HERMES_HOME": "/opt/data/profiles/desarrollador"}), "desarrollador")
        self.assertEqual(pn({"HERMES_HOME": "/opt/data"}), "manager")
        self.assertEqual(pn({"HERMES_PROFILE": "default", "HERMES_HOME": "/opt/data"}), "manager")

    def test_tool_mapping(self):
        m = self.bridge.map_tool
        self.assertEqual(m("terminal", {"command": "pytest -q"}), ("Bash", {"command": "pytest -q"}))
        self.assertEqual(m("patch", {"path": "/a/b.py"}), ("Edit", {"file_path": "/a/b.py"}))
        self.assertEqual(m("kanban_create", {"assignee": "investigador"}), ("SendMessage", {"recipient": "investigador"}))
        self.assertEqual(m("delegate_task", {"goal": "x" * 300})[1]["description"], "x" * 120)
        self.assertEqual(m("something_new", None), ("something_new", {}))


if __name__ == "__main__":
    unittest.main()
