"""Prueba del bootstrap simulando el contenedor en un directorio temporal.

Usa un `hermes` falso que imita `hermes profile create/describe`.
"""

from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "docker" / "office" / "bootstrap" / "office-bootstrap.py"

FAKE_HERMES = textwrap.dedent(
    """\
    #!/usr/bin/env python3
    import sys, os, pathlib
    home = pathlib.Path(os.environ["HERMES_HOME"])
    a = sys.argv[1:]
    with open(home / "calls.log", "a") as f: f.write(" ".join(a) + "\\n")
    if a[:2] == ["profile", "create"]:
        p = home / "profiles" / a[2]; p.mkdir(parents=True, exist_ok=True)
        (p / "config.yaml").write_text("model:\\n  default: stock-model\\n")
        (p / "SOUL.md").write_text(open("/dev/null").read() or "STOCK SOUL\\n")
        desc = a[a.index("--description") + 1] if "--description" in a else ""
        (p / "profile.yaml").write_text(f"description: {desc!r}\\n")
    """
)


class BootstrapTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.share = self.tmp / "opt-office"
        self.share.mkdir()
        for d in ("hermes", "pixel-agents", "claude"):
            shutil.copytree(ROOT / d, self.share / d)
        shutil.copytree(ROOT / "vault", self.share / "vault-seed")
        self.hhome = self.tmp / "data"
        self.hhome.mkdir()
        # config raíz "de serie" como la que siembra Hermes
        (self.hhome / "config.yaml").write_text("model:\n  default: anthropic/claude-opus-4.6\nplugins:\n  enabled: [disk-cleanup]\n")
        bindir = self.tmp / "bin"
        bindir.mkdir()
        fake = bindir / "hermes"
        fake.write_text(FAKE_HERMES)
        fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
        self.env = dict(
            os.environ,
            PATH=f"{bindir}:{os.environ['PATH']}",
            OFFICE_SHARE=str(self.share),
            HERMES_HOME=str(self.hhome),
            OFFICE_USER_HOME=str(self.hhome),
            OFFICE_VAULT=str(self.tmp / "vault"),
            OFFICE_WORKDIR=str(self.tmp / "office"),
            HERMES_PROVIDER="openrouter",
            HERMES_MODEL_MANAGER="anthropic/claude-opus-4.6",
            HERMES_MODEL_WORKERS="",
            HERMES_DASHBOARD_PUBLIC_URL="",
        )

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def run_bootstrap(self):
        r = subprocess.run([sys.executable, str(SCRIPT)], env=self.env, capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertNotIn("ERROR", r.stdout, r.stdout)
        return r.stdout

    def test_full_bootstrap_is_idempotent(self):
        out = self.run_bootstrap()
        self.assertIn("listo", out)

        # perfiles creados + plugin instalado en todos
        for p in ("investigador", "desarrollador", "bibliotecario"):
            ph = self.hhome / "profiles" / p
            self.assertTrue((ph / "plugins" / "pixel-office" / "__init__.py").exists(), p)
            cfg = yaml.safe_load((ph / "config.yaml").read_text())
            self.assertEqual(cfg["plugins"]["enabled"], ["pixel-office"])
            self.assertEqual(cfg["model"]["provider"], "openrouter")
            # HERMES_MODEL_WORKERS vacío -> se respeta el modelo existente
            self.assertEqual(cfg["model"]["default"], "stock-model")
            self.assertIn(p.capitalize(), (ph / "SOUL.md").read_text())
        self.assertIn(
            "timeout", yaml.safe_load((self.hhome / "profiles/desarrollador/config.yaml").read_text())["terminal"]
        )

        # raíz = manager
        root = yaml.safe_load((self.hhome / "config.yaml").read_text())
        self.assertEqual(root["plugins"]["enabled"], ["disk-cleanup", "pixel-office"])
        self.assertEqual(root["toolsets"], ["hermes-cli", "kanban"])
        self.assertIn("terminal", root["agent"]["disabled_toolsets"])
        self.assertTrue(root["kanban"]["dispatch_in_gateway"])
        self.assertNotIn("public_url", root["dashboard"])  # variable vacía -> no se toca
        self.assertIn("Manager", (self.hhome / "SOUL.md").read_text())

        # Pixel Agents
        pa = json.loads((self.hhome / ".pixel-agents/config.json").read_text())
        self.assertTrue(pa["standalone"]["watchAllSessions"])
        self.assertEqual(pa["standalone"]["areaMappings"]["desarrollador"], ["Desarrollo"])
        self.assertEqual(pa["hooksConsent"]["claude"], "granted")
        layout = json.loads((self.hhome / ".pixel-agents/layout.json").read_text())
        self.assertEqual(len(layout["areaTiles"]), layout["cols"] * layout["rows"])
        self.assertEqual({a["label"] for a in layout["areas"]}, {"Dirección", "Investigación", "Biblioteca", "Desarrollo"})

        # vault + Claude
        self.assertTrue((self.tmp / "vault" / "Inicio.md").exists())
        self.assertTrue((self.tmp / "vault" / ".obsidian" / "app.json").exists())
        self.assertTrue((self.hhome / ".claude" / "CLAUDE.md").exists())
        self.assertTrue((self.tmp / "office" / "agentes" / "bibliotecario").is_dir())

        # cambios del usuario se conservan en el segundo arranque
        soul = self.hhome / "profiles/investigador/SOUL.md"
        soul.write_text("mi personalidad editada")
        note = self.tmp / "vault" / "Inicio.md"
        note.write_text("mi inicio")
        self.run_bootstrap()
        self.assertEqual(soul.read_text(), "mi personalidad editada")
        self.assertEqual(note.read_text(), "mi inicio")
        calls = (self.hhome / "calls.log").read_text().count("profile create")
        self.assertEqual(calls, 3, "los perfiles se crean una sola vez")
        root = yaml.safe_load((self.hhome / "config.yaml").read_text())
        self.assertEqual(root["plugins"]["enabled"].count("pixel-office"), 1)

    def test_soul_upgrade_only_when_unedited(self):
        self.run_bootstrap()
        old = subprocess.run(
            ["git", "-C", str(ROOT), "show", "d4253ab:hermes/profiles/desarrollador/SOUL.md"],
            capture_output=True, text=True,
        ).stdout
        self.assertIn("bloquea la tarjeta explicando", old)
        dev = self.hhome / "profiles/desarrollador"
        # instalación antigua: SOUL de serie sin tocar + marcador sin hash
        (dev / "SOUL.md").write_text(old, encoding="utf-8")
        (dev / ".office-soul").write_text("instalada por office-bootstrap; borra este archivo para reinstalarla\n")
        # y otra personalidad editada por el usuario con el mismo marcador antiguo
        bib = self.hhome / "profiles/bibliotecario"
        (bib / "SOUL.md").write_text("mi bibliotecario", encoding="utf-8")
        (bib / ".office-soul").write_text("instalada por office-bootstrap; borra este archivo para reinstalarla\n")
        out = self.run_bootstrap()
        self.assertIn("SOUL.md de desarrollador actualizada", out)
        self.assertIn("no bloquees la tarjeta", (dev / "SOUL.md").read_text(encoding="utf-8"))
        self.assertEqual((bib / "SOUL.md").read_text(encoding="utf-8"), "mi bibliotecario")


if __name__ == "__main__":
    unittest.main()
