"""Puente Hermes -> Pixel Agents.

Pixel Agents (https://github.com/pixel-agents-hq/pixel-agents) expone una API de
hooks HTTP pensada para Claude Code:

    POST http://127.0.0.1:<port>/api/hooks/claude
    Authorization: Bearer <token>
    {"session_id": ..., "hook_event_name": "PreToolUse", ...}

El puerto y el token de cada servidor vivo se publican en
``~/.pixel-agents/servers/<pid>-<port>.json``. Este módulo traduce los eventos
de los hooks de Hermes a ese mismo formato, de modo que cada perfil de Hermes
(manager, investigador, desarrollador, bibliotecario) aparece como un personaje
"headless" con su propio escritorio.

Diseño:
  * Nunca bloquea al agente: los POST salen por un hilo en segundo plano con
    timeouts cortos y se descartan si la oficina no está arriba.
  * Identidad estable: un session_id fijo por perfil (``hermes-<perfil>``), así
    el mismo personaje se reutiliza en todos los turnos y trabajos Kanban.
  * El nombre que se ve sobre el personaje es el basename del ``cwd`` que
    enviamos, por eso usamos ``/office/agentes/<perfil>``.
"""

from __future__ import annotations

import atexit
import json
import os
import queue
import threading
import time
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

PROVIDER_ID = "claude"  # el único proveedor de hooks que trae Pixel Agents hoy
HOOK_PATH = f"/api/hooks/{PROVIDER_ID}"

# ---------------------------------------------------------------------------
# Identidad del agente
# ---------------------------------------------------------------------------


def profile_name(env: Optional[Dict[str, str]] = None) -> str:
    """Nombre del perfil de Hermes que ejecuta este proceso.

    Orden: HERMES_PROFILE (lo fija el dispatcher del Kanban) -> carpeta
    ``profiles/<nombre>`` de HERMES_HOME -> nombre del perfil raíz.
    """
    env = os.environ if env is None else env
    explicit = (env.get("HERMES_PROFILE") or "").strip()
    if explicit and explicit != "default":
        return explicit
    home = (env.get("HERMES_HOME") or "").strip()
    if home:
        p = Path(home)
        if p.parent.name == "profiles" and p.name:
            return p.name
    return (env.get("PIXEL_OFFICE_ROOT_NAME") or "manager").strip() or "manager"


def session_id_for(profile: str) -> str:
    return f"hermes-{profile}"


def cwd_for(profile: str, env: Optional[Dict[str, str]] = None) -> str:
    env = os.environ if env is None else env
    root = env.get("PIXEL_OFFICE_AGENTS_ROOT") or "/office/agentes"
    return f"{root.rstrip('/')}/{profile}"


# ---------------------------------------------------------------------------
# Traducción de herramientas Hermes -> nombres que Pixel Agents sabe mostrar
# ---------------------------------------------------------------------------

# Pixel Agents formatea la etiqueta de actividad según el nombre de herramienta
# de Claude Code (Read -> "Reading foo.md", Bash -> "Running: cmd", ...).
_TOOL_MAP = {
    "terminal": "Bash",
    "process_manage": "Bash",
    "execute_code": "Bash",
    "read_file": "Read",
    "write_file": "Write",
    "patch": "Edit",
    "search_files": "Grep",
    "web_search": "WebSearch",
    "web_extract": "WebFetch",
    "delegate_task": "Agent",
    "clarify": "AskUserQuestion",
    "todo_list": "EnterPlanMode",
}


def _first_str(d: Dict[str, Any], *keys: str) -> str:
    for k in keys:
        v = d.get(k)
        if isinstance(v, str) and v:
            return v
    return ""


def map_tool(tool_name: str, args: Optional[Dict[str, Any]]) -> Tuple[str, Dict[str, Any]]:
    """Devuelve (tool_name, tool_input) al estilo Claude Code."""
    args = args if isinstance(args, dict) else {}
    name = _TOOL_MAP.get(tool_name)

    if name == "Bash":
        cmd = _first_str(args, "command", "code", "cmd") or tool_name
        return "Bash", {"command": cmd}
    if name in ("Read", "Write", "Edit"):
        path = _first_str(args, "path", "file_path", "filename", "target")
        return name, {"file_path": path}
    if name == "Agent":
        goal = _first_str(args, "goal", "task", "description", "prompt")
        return "Agent", {"description": goal[:120]}
    if name:
        return name, {}

    if tool_name == "kanban_create":
        assignee = _first_str(args, "assignee") or "equipo"
        return "SendMessage", {"recipient": assignee}
    if tool_name == "kanban_comment":
        return "SendMessage", {"recipient": _first_str(args, "task_id") or "tablero"}
    if tool_name.startswith("browser_"):
        return "WebFetch", {}
    # Cualquier otra -> "Using <tool>" (lo formatea Pixel Agents)
    return tool_name, {}


# ---------------------------------------------------------------------------
# Construcción de eventos
# ---------------------------------------------------------------------------


class EventFactory:
    def __init__(self, profile: str, env: Optional[Dict[str, str]] = None):
        self.profile = profile
        self.session_id = session_id_for(profile)
        self.cwd = cwd_for(profile, env)

    def _base(self, name: str, **extra: Any) -> Dict[str, Any]:
        ev = {"session_id": self.session_id, "hook_event_name": name}
        ev.update(extra)
        return ev

    def session_start(self) -> Dict[str, Any]:
        # Sin transcript_path -> sesión "solo hooks"; el cwd da el nombre visible.
        return self._base("SessionStart", source="startup", cwd=self.cwd)

    def tool_start(self, tool_name: str, args: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        name, tool_input = map_tool(tool_name, args)
        return self._base("PreToolUse", tool_name=name, tool_input=tool_input, cwd=self.cwd)

    def tool_end(self) -> Dict[str, Any]:
        return self._base("PostToolUse")

    def thinking(self) -> Dict[str, Any]:
        return self._base("PreToolUse", tool_name="EnterPlanMode", tool_input={}, cwd=self.cwd)

    def turn_end(self) -> Dict[str, Any]:
        return self._base("Stop")

    def permission(self) -> Dict[str, Any]:
        return self._base("PermissionRequest")

    def awaiting_input(self) -> Dict[str, Any]:
        return self._base("Notification", notification_type="idle_prompt")

    def subagent_start(self, role: str) -> Dict[str, Any]:
        return self._base("SubagentStart", agent_type=(role or "subagente")[:40])

    def subagent_stop(self) -> Dict[str, Any]:
        return self._base("SubagentStop")


# ---------------------------------------------------------------------------
# Descubrimiento de servidores Pixel Agents
# ---------------------------------------------------------------------------


def pixel_agents_dir(env: Optional[Dict[str, str]] = None) -> Path:
    env = os.environ if env is None else env
    explicit = env.get("PIXEL_AGENTS_DIR")
    if explicit:
        return Path(explicit)
    return Path(env.get("HOME") or str(Path.home())) / ".pixel-agents"


def _pid_alive(pid: Any) -> bool:
    try:
        os.kill(int(pid), 0)
        return True
    except PermissionError:
        return True
    except Exception:
        return False


def discover_targets(env: Optional[Dict[str, str]] = None) -> List[Tuple[str, str]]:
    """Lista de (base_url, token) de los servidores Pixel Agents vivos."""
    env = os.environ if env is None else env
    url = (env.get("PIXEL_OFFICE_URL") or "").strip()
    token = (env.get("PIXEL_OFFICE_TOKEN") or "").strip()
    if url and token:
        return [(url.rstrip("/"), token)]

    base = pixel_agents_dir(env)
    host = env.get("PIXEL_OFFICE_HOST") or "127.0.0.1"
    targets: List[Tuple[str, str]] = []
    reg = base / "servers"
    files: Iterable[Path] = sorted(reg.glob("*.json")) if reg.is_dir() else []
    for f in files:
        try:
            cfg = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(cfg, dict) or not cfg.get("port") or not cfg.get("token"):
            continue
        if "pid" in cfg and not _pid_alive(cfg["pid"]):
            continue
        targets.append((f"http://{host}:{int(cfg['port'])}", str(cfg["token"])))
    if not targets:
        legacy = base / "server.json"
        try:
            cfg = json.loads(legacy.read_text(encoding="utf-8"))
            if cfg.get("port") and cfg.get("token"):
                targets.append((f"http://{host}:{int(cfg['port'])}", str(cfg["token"])))
        except Exception:
            pass
    return targets


# ---------------------------------------------------------------------------
# Transporte asíncrono (nunca bloquea al agente)
# ---------------------------------------------------------------------------


class Sender:
    def __init__(self, env: Optional[Dict[str, str]] = None, timeout: float = 1.5):
        self.env = os.environ if env is None else env
        self.timeout = timeout
        self.q: "queue.Queue[Optional[Dict[str, Any]]]" = queue.Queue(maxsize=500)
        self._targets: List[Tuple[str, str]] = []
        self._targets_at = 0.0
        self._thread = threading.Thread(target=self._run, name="pixel-office", daemon=True)
        self._thread.start()
        atexit.register(self.flush, 2.0)

    def send(self, event: Dict[str, Any]) -> None:
        try:
            self.q.put_nowait(event)
        except queue.Full:
            pass

    def flush(self, timeout: float = 2.0) -> None:
        deadline = time.time() + timeout
        while not self.q.empty() and time.time() < deadline:
            time.sleep(0.05)

    def _targets_now(self) -> List[Tuple[str, str]]:
        if time.time() - self._targets_at > 10 or not self._targets:
            self._targets = discover_targets(self.env)
            self._targets_at = time.time()
        return self._targets

    def _post(self, base: str, token: str, event: Dict[str, Any]) -> bool:
        req = urllib.request.Request(
            base + HOOK_PATH,
            data=json.dumps(event).encode("utf-8"),
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"},
            method="POST",
        )
        # La oficina es local: no queremos pasar por proxies corporativos.
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(req, timeout=self.timeout) as resp:
            return 200 <= resp.status < 300

    def _run(self) -> None:
        while True:
            event = self.q.get()
            if event is None:
                return
            for base, token in self._targets_now():
                try:
                    self._post(base, token, event)
                except Exception:
                    self._targets_at = 0  # re-descubrir en el próximo evento


# ---------------------------------------------------------------------------
# Registro en el vault de Obsidian
# ---------------------------------------------------------------------------


def vault_log(text: str, env: Optional[Dict[str, str]] = None, now: Optional[datetime] = None) -> Optional[Path]:
    """Añade una línea a ``<vault>/Agentes/_Registro/AAAA-MM-DD.md``."""
    env = os.environ if env is None else env
    vault = env.get("OFFICE_VAULT") or "/vault"
    root = Path(vault)
    if not root.is_dir():
        return None
    now = now or datetime.now()
    day = now.strftime("%Y-%m-%d")
    path = root / "Agentes" / "_Registro" / f"{day}.md"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            path.write_text(
                f"---\ntipo: registro\nfecha: {day}\ntags: [registro, kanban]\n---\n"
                f"# Registro de la oficina — {day}\n\n"
                f"Eventos del tablero Kanban escritos automáticamente por el plugin `pixel-office`.\n"
                f"Día anterior/siguiente: ver [[Agentes/_Registro]].\n\n",
                encoding="utf-8",
            )
        with path.open("a", encoding="utf-8") as fh:
            fh.write(f"- {now.strftime('%H:%M')} {text}\n")
        return path
    except Exception:
        return None
