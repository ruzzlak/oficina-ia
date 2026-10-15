"""pixel-office — muestra los agentes Hermes en la oficina de Pixel Agents.

Activación (ya lo hace el bootstrap del contenedor en cada perfil):

    plugins:
      enabled: [pixel-office]
"""

from __future__ import annotations

import logging
import os
from typing import Any

from . import bridge

logger = logging.getLogger("plugins.pixel-office")

_state: dict = {}


def _factory() -> "bridge.EventFactory":
    # El perfil se resuelve en cada llamada: el mismo proceso de gateway puede
    # servir a varios perfiles (multi-profile gateways).
    prof = bridge.profile_name()
    f = _state.get(prof)
    if f is None:
        f = bridge.EventFactory(prof)
        _state[prof] = f
    return f


def _sender() -> "bridge.Sender":
    s = _state.get("__sender__")
    if s is None:
        s = bridge.Sender()
        _state["__sender__"] = s
    return s


def _emit(*events: dict) -> None:
    s = _sender()
    for ev in events:
        s.send(ev)


# ── Hooks ──────────────────────────────────────────────────────────────────


def _on_session_start(**_kw: Any) -> None:
    f = _factory()
    _emit(f.session_start())


def _on_pre_llm_call(**_kw: Any) -> None:
    # Reanuncia la sesión (idempotente) por si la oficina se reinició, y pone
    # al personaje en "Planning" mientras el modelo piensa.
    f = _factory()
    _emit(f.session_start(), f.thinking())
    return None


def _on_pre_tool_call(tool_name: str = "", args: Any = None, **_kw: Any) -> None:
    f = _factory()
    _emit(f.tool_end(), f.tool_start(tool_name or "", args if isinstance(args, dict) else {}))
    return None  # observador: nunca bloquea ni modifica


def _on_post_tool_call(**_kw: Any) -> None:
    _emit(_factory().tool_end())


def _on_session_end(**_kw: Any) -> None:
    f = _factory()
    _emit(f.tool_end(), f.turn_end())


def _on_human_input_request(kind: str = "", **_kw: Any) -> None:
    f = _factory()
    _emit(f.awaiting_input() if kind == "clarify" else f.permission())


def _on_human_input_resolved(**_kw: Any) -> None:
    _emit(_factory().tool_end())


def _on_subagent_start(child_role: str = "", **_kw: Any) -> None:
    _emit(_factory().subagent_start(child_role or "subagente"))


def _on_subagent_stop(**_kw: Any) -> None:
    _emit(_factory().subagent_stop())


def _on_kanban_claimed(task_id: str = "", assignee: str = "", board: str = "", **_kw: Any) -> None:
    # Se dispara en el proceso del dispatcher (el Manager): lo mostramos
    # "pasando" la tarea al compañero y lo anotamos en el vault.
    f = _factory()
    _emit(f.session_start(), f.tool_start("kanban_create", {"assignee": assignee}), f.tool_end(), f.turn_end())
    bridge.vault_log(f"🟡 **{assignee or '?'}** tomó la tarea `{task_id}` (tablero `{board or 'default'}`)")


def _on_kanban_completed(task_id: str = "", assignee: str = "", summary: str = "", **_kw: Any) -> None:
    who = assignee or bridge.profile_name()
    text = (summary or "").strip().replace("\n", " ")
    if len(text) > 280:
        text = text[:277] + "…"
    bridge.vault_log(f"✅ **{who}** completó `{task_id}` — {text}" if text else f"✅ **{who}** completó `{task_id}`")


def _on_kanban_blocked(task_id: str = "", assignee: str = "", reason: str = "", **_kw: Any) -> None:
    who = assignee or bridge.profile_name()
    _emit(_factory().awaiting_input())
    bridge.vault_log(f"⛔ **{who}** bloqueó `{task_id}` — {(reason or '').strip()[:280]}")


_HOOKS = {
    "on_session_start": _on_session_start,
    "pre_llm_call": _on_pre_llm_call,
    "pre_tool_call": _on_pre_tool_call,
    "post_tool_call": _on_post_tool_call,
    "on_session_end": _on_session_end,
    "on_human_input_request": _on_human_input_request,
    "on_human_input_resolved": _on_human_input_resolved,
    "subagent_start": _on_subagent_start,
    "subagent_stop": _on_subagent_stop,
    "kanban_task_claimed": _on_kanban_claimed,
    "kanban_task_completed": _on_kanban_completed,
    "kanban_task_blocked": _on_kanban_blocked,
}


def register(ctx) -> None:
    if os.environ.get("PIXEL_OFFICE_DISABLED") in ("1", "true", "yes"):
        logger.info("pixel-office desactivado por PIXEL_OFFICE_DISABLED")
        return
    for name, cb in _HOOKS.items():
        try:
            ctx.register_hook(name, cb)
        except Exception as exc:  # versión de Hermes sin ese hook
            logger.debug("pixel-office: hook %s no disponible (%s)", name, exc)
