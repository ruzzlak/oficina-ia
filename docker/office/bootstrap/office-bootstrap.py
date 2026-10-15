#!/usr/bin/env python3
"""Bootstrap idempotente de la Oficina IA (se ejecuta en cada arranque).

Corre como el usuario ``hermes`` dentro del contenedor, después del setup
propio de Hermes (cont-init 01/015/02). Nunca borra datos del usuario:

* vault de Obsidian  -> se siembra solo si está vacío (sin Inicio.md)
* perfiles Hermes    -> se crean si faltan; config.yaml se FUSIONA
* SOUL.md            -> se copia si no existe o si sigue siendo el de serie
* plugin pixel-office-> se reinstala siempre (es código nuestro)
* Pixel Agents       -> config.json se fusiona; layout.json solo si no existe
* Claude Code        -> ~/.claude/CLAUDE.md solo si no existe

Uso manual:  office-bootstrap.py [--dry-run]
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List

import yaml

OFFICE = Path(os.environ.get("OFFICE_SHARE", "/opt/office"))
HERMES_HOME = Path(os.environ.get("HERMES_HOME", "/opt/data"))
HOME = Path(os.environ.get("OFFICE_USER_HOME", str(HERMES_HOME)))
VAULT = Path(os.environ.get("OFFICE_VAULT", "/vault"))
WORKDIR = Path(os.environ.get("OFFICE_WORKDIR", "/office"))
STOCK_SOUL = Path("/opt/hermes/docker/SOUL.md")
DRY = "--dry-run" in sys.argv


def log(msg: str) -> None:
    print(f"[oficina] {msg}", flush=True)


# ── utilidades ──────────────────────────────────────────────────────────────

_VAR = re.compile(r"\$\{([A-Z0-9_]+)\}")


def substitute(node: Any) -> Any:
    """Sustituye ${VAR}; devuelve None si la variable está vacía (=no tocar)."""
    if isinstance(node, dict):
        out = {}
        for k, v in node.items():
            sv = substitute(v)
            if sv is not None:
                out[k] = sv
        return out or None
    if isinstance(node, list):
        return [x for x in (substitute(i) for i in node) if x is not None]
    if isinstance(node, str):
        missing = False

        def rep(m: "re.Match[str]") -> str:
            nonlocal missing
            val = os.environ.get(m.group(1), "")
            if not val:
                missing = True
            return val

        res = _VAR.sub(rep, node)
        return None if missing and not res.strip() else res
    return node


def deep_merge(base: Dict[str, Any], overlay: Dict[str, Any]) -> Dict[str, Any]:
    """Fusiona overlay sobre base. Las listas se unen sin duplicados."""
    for k, v in overlay.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            deep_merge(base[k], v)
        elif isinstance(v, list) and isinstance(base.get(k), list):
            for item in v:
                if item not in base[k]:
                    base[k].append(item)
        else:
            base[k] = v
    return base


def write_text(path: Path, text: str) -> None:
    if DRY:
        log(f"(dry-run) escribiría {path}")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def load_yaml(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except yaml.YAMLError as exc:
        log(f"AVISO: {path} no es YAML válido ({exc}); no lo modifico")
        raise


def hermes(*args: str) -> subprocess.CompletedProcess:
    cmd = [shutil.which("hermes") or "hermes", *args]
    if DRY:
        log(f"(dry-run) {' '.join(cmd)}")
        return subprocess.CompletedProcess(cmd, 0, "", "")
    env = dict(os.environ, HERMES_HOME=str(HERMES_HOME), HOME=str(HOME))
    return subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=180)


# ── pasos ───────────────────────────────────────────────────────────────────


def seed_vault() -> None:
    seed = OFFICE / "vault-seed"
    if not seed.is_dir():
        return
    if (VAULT / "Inicio.md").exists():
        log("vault ya inicializado")
        return
    log(f"sembrando vault en {VAULT}")
    for src in seed.rglob("*"):
        rel = src.relative_to(seed)
        dst = VAULT / rel
        if src.is_dir():
            dst.mkdir(parents=True, exist_ok=True)
        elif not dst.exists() and not DRY:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)


def profile_home(agent: Dict[str, Any]) -> Path:
    return HERMES_HOME if agent.get("root") else HERMES_HOME / "profiles" / agent["name"]


def ensure_profile(agent: Dict[str, Any]) -> None:
    if agent.get("root"):
        return
    home = profile_home(agent)
    if (home / "config.yaml").exists() or (home / "SOUL.md").exists():
        return
    log(f"creando perfil Hermes '{agent['name']}'")
    res = hermes("profile", "create", agent["name"], "--description", agent.get("description", ""))
    if res.returncode != 0:
        log(f"AVISO: no se pudo crear el perfil {agent['name']}: {res.stderr.strip()[:400]}")
        home.mkdir(parents=True, exist_ok=True)  # al menos que exista para la config


def apply_config(agent: Dict[str, Any], common: Dict[str, Any]) -> None:
    home = profile_home(agent)
    cfg_path = home / "config.yaml"
    try:
        cfg = load_yaml(cfg_path)
    except yaml.YAMLError:
        return
    overlay = deep_merge(json.loads(json.dumps(common)), agent.get("config") or {})
    overlay = substitute(overlay) or {}
    merged = deep_merge(cfg, overlay)
    write_text(cfg_path, yaml.safe_dump(merged, sort_keys=False, allow_unicode=True))


def apply_soul(agent: Dict[str, Any]) -> None:
    src = OFFICE / "hermes" / "profiles" / agent["name"] / "SOUL.md"
    if not src.exists():
        return
    home = profile_home(agent)
    dst = home / "SOUL.md"
    marker = home / ".office-soul"
    if marker.exists():
        return  # ya instalada una vez: a partir de aquí la personalidad es del usuario
    current = dst.read_text(encoding="utf-8") if dst.exists() else ""
    stock = STOCK_SOUL.read_text(encoding="utf-8") if STOCK_SOUL.exists() else None
    if current.strip() and current != stock and not DRY:
        shutil.copy2(dst, home / "SOUL.md.antes-de-oficina")  # por si había una propia
    log(f"SOUL.md de {agent['name']}")
    write_text(dst, src.read_text(encoding="utf-8"))
    write_text(marker, "instalada por office-bootstrap; borra este archivo para reinstalarla\n")


def install_plugin(agent: Dict[str, Any]) -> None:
    src = OFFICE / "hermes" / "plugins" / "pixel-office"
    dst = profile_home(agent) / "plugins" / "pixel-office"
    if DRY:
        log(f"(dry-run) plugin -> {dst}")
        return
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))


def ensure_description(agent: Dict[str, Any]) -> None:
    if agent.get("root") or not agent.get("description"):
        return
    meta = profile_home(agent) / "profile.yaml"
    if meta.exists() and "description" in meta.read_text(encoding="utf-8"):
        return
    hermes("profile", "describe", agent["name"], "--text", agent["description"])


def ensure_workdirs(agents: List[Dict[str, Any]]) -> None:
    for d in [WORKDIR / "proyectos", *[WORKDIR / "agentes" / a["name"] for a in agents]]:
        if not DRY:
            d.mkdir(parents=True, exist_ok=True)
    readme = WORKDIR / "agentes" / "README.md"
    if not readme.exists():
        write_text(
            readme,
            "Estas carpetas solo dan nombre a los personajes de la oficina pixel-art.\n"
            "El trabajo real vive en /office/proyectos (código) y /vault (conocimiento).\n",
        )


def seed_pixel_agents(agents: List[Dict[str, Any]]) -> None:
    pa = HOME / ".pixel-agents"
    cfg_path = pa / "config.json"
    try:
        cfg = json.loads(cfg_path.read_text(encoding="utf-8")) if cfg_path.exists() else {}
    except json.JSONDecodeError:
        cfg = {}
    std = cfg.setdefault("standalone", {})
    std["watchAllSessions"] = True  # adopta sesiones de Claude Code y de Hermes
    std.setdefault("alwaysShowLabels", True)
    std.setdefault("showAreas", True)
    std.setdefault("hooksInfoShown", True)
    mappings = std.setdefault("areaMappings", {})
    for a in agents:
        if a.get("area"):
            mappings.setdefault(a["name"], [a["area"]])
    # Consentimiento para que Pixel Agents instale sus hooks en ~/.claude/settings.json
    cfg.setdefault("hooksConsent", {}).setdefault("claude", "granted")
    cfg.setdefault("hooksEnabled", {}).setdefault("claude", True)
    cfg.setdefault("externalAssetDirectories", [])
    write_text(cfg_path, json.dumps(cfg, indent=2, ensure_ascii=False))

    layout_dst = pa / "layout.json"
    layout_src = OFFICE / "pixel-agents" / "layout.json"
    if not layout_dst.exists() and layout_src.exists():
        log("instalando la distribución de la oficina (layout.json)")
        write_text(layout_dst, layout_src.read_text(encoding="utf-8"))


def seed_claude() -> None:
    src = OFFICE / "claude" / "CLAUDE.md"
    dst = HOME / ".claude" / "CLAUDE.md"
    if src.exists() and not dst.exists():
        log("CLAUDE.md global para Claude Code")
        write_text(dst, src.read_text(encoding="utf-8"))


def main() -> int:
    manifest = yaml.safe_load((OFFICE / "hermes" / "office.yaml").read_text(encoding="utf-8"))
    agents: List[Dict[str, Any]] = manifest.get("agents", [])
    common: Dict[str, Any] = manifest.get("common", {})

    seed_vault()
    ensure_workdirs(agents)
    for agent in agents:
        ensure_profile(agent)
        apply_config(agent, common)
        apply_soul(agent)
        install_plugin(agent)
        ensure_description(agent)
    seed_pixel_agents(agents)
    seed_claude()
    log("listo ✔  equipo: " + ", ".join(a["name"] for a in agents))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # nunca impedir que arranque el contenedor
        log(f"ERROR en bootstrap: {exc!r}")
        sys.exit(0)
