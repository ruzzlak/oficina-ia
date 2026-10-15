"""Servidor falso que imita la API de hooks de Pixel Agents (v1.4.x).

Reproduce la semántica relevante de server/src/hookEventHandler.ts:
  * POST /api/hooks/<provider> con "Authorization: Bearer <token>"
  * SessionStart de una sesión desconocida con cwd -> queda PENDIENTE
  * el siguiente evento (PreToolUse, Stop, Notification, PermissionRequest…)
    la confirma y crea el agente con folderName = basename(cwd)
  * eventos de sesiones desconocidas sin SessionStart previo -> se ignoran
Escribe ~/.pixel-agents/servers/<pid>-<port>.json como el servidor real.
"""

from __future__ import annotations

import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, List


class MockOffice:
    def __init__(self, pixel_dir: Path, token: str = "tok-123"):
        self.token = token
        self.pending: Dict[str, Dict[str, Any]] = {}
        self.agents: Dict[str, Dict[str, Any]] = {}
        self.raw: List[Dict[str, Any]] = []
        self.rejected = 0
        office = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):  # silencio
                pass

            def do_POST(self):
                if self.headers.get("Authorization") != f"Bearer {office.token}":
                    office.rejected += 1
                    self.send_response(401); self.end_headers(); return
                n = int(self.headers.get("Content-Length") or 0)
                ev = json.loads(self.rfile.read(n) or b"{}")
                office.handle(self.path, ev)
                self.send_response(200); self.end_headers(); self.wfile.write(b"ok")

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.port = self.httpd.server_address[1]
        reg = pixel_dir / "servers"
        reg.mkdir(parents=True, exist_ok=True)
        (reg / f"{os.getpid()}-{self.port}.json").write_text(
            json.dumps({"port": self.port, "pid": os.getpid(), "token": token, "protocol": 1})
        )
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def handle(self, path: str, ev: Dict[str, Any]) -> None:
        assert path.startswith("/api/hooks/"), path
        self.raw.append(ev)
        sid, name = ev.get("session_id"), ev.get("hook_event_name")
        if not sid or not name:
            return
        if name == "SessionStart":
            if sid not in self.agents and ev.get("cwd"):
                self.pending[sid] = {"cwd": ev["cwd"]}
            return
        if sid in self.pending:
            cwd = self.pending.pop(sid)["cwd"]
            self.agents[sid] = {"folderName": os.path.basename(cwd), "status": "idle", "tool": None, "subagents": 0, "log": []}
        a = self.agents.get(sid)
        if a is None:
            return
        a["log"].append(name)
        if name == "PreToolUse":
            a["status"], a["tool"] = "active", (ev.get("tool_name"), ev.get("tool_input"))
        elif name == "PostToolUse":
            a["tool"] = None
        elif name == "Stop":
            a["status"], a["tool"] = "done", None
        elif name == "PermissionRequest":
            a["status"] = "permission"
        elif name == "Notification":
            a["status"] = "waiting" if ev.get("notification_type") == "idle_prompt" else "permission"
        elif name == "SubagentStart":
            a["subagents"] += 1
        elif name == "SubagentStop":
            a["subagents"] = max(0, a["subagents"] - 1)

    def close(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()
