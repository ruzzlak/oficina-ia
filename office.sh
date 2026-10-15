#!/usr/bin/env bash
# office.sh — atajos para administrar la Oficina IA en el VPS.
set -euo pipefail
cd "$(dirname "$0")"

C="docker compose"
EXEC="$C exec -T -u hermes -e HOME=/opt/data -e HERMES_HOME=/opt/data office"
EXEC_IT="$C exec -it -u hermes -e HOME=/opt/data -e HERMES_HOME=/opt/data office"
AGENTS="manager investigador desarrollador bibliotecario"

die() { echo "✗ $*" >&2; exit 1; }
need_env() { [ -f .env ] || die "Falta .env — ejecuta primero: ./office.sh setup"; }
envget() { [ -f .env ] && grep -E "^$1=" .env | tail -1 | cut -d= -f2- || true; }

cmd_setup() {
  command -v docker >/dev/null || die "Instala Docker primero (o usa install.sh)"
  if [ ! -f .env ]; then
    cp .env.example .env
    rand() { openssl rand -hex "$1" 2>/dev/null || head -c "$1" /dev/urandom | od -An -tx1 | tr -d ' \n'; }
    # Los agentes NUNCA deben correr como root (UID 0). En VPS donde entras como
    # root (Hostinger, etc.) usamos el usuario por defecto de Hermes, 10000.
    uid="$(id -u)"; gid="$(id -g)"
    if [ "$uid" = 0 ]; then uid=10000; gid=10000; fi
    sed -i "s/^HERMES_UID=.*/HERMES_UID=${uid}/; s/^HERMES_GID=.*/HERMES_GID=${gid}/" .env
    sed -i "s/^HERMES_DASHBOARD_BASIC_AUTH_PASSWORD=.*/HERMES_DASHBOARD_BASIC_AUTH_PASSWORD=$(rand 12)/" .env
    sed -i "s/^HERMES_DASHBOARD_BASIC_AUTH_SECRET=.*/HERMES_DASHBOARD_BASIC_AUTH_SECRET=$(rand 32)/" .env
    sed -i "s/^OBSIDIAN_WEB_PASSWORD=.*/OBSIDIAN_WEB_PASSWORD=$(rand 12)/" .env
    if [ -f /etc/timezone ]; then sed -i "s|^TZ=.*|TZ=$(cat /etc/timezone)|" .env; fi
    chmod 600 .env
    echo "✓ Creado .env con contraseñas aleatorias"
  else
    echo "• .env ya existe (no lo toco)"
  fi
  mkdir -p data/hermes data/vault data/proyectos data/obsidian-config
  echo "✓ Carpetas de datos listas en ./data"
}

# ./office.sh set CLAVE VALOR   (sin VALOR: lo pide sin mostrarlo en pantalla)
cmd_set() {
  need_env
  local key="${1:-}" val="${2:-}"
  [[ "$key" =~ ^[A-Z][A-Z0-9_]*$ ]] || die "Uso: ./office.sh set CLAVE [VALOR]"
  if [ $# -lt 2 ]; then read -rsp "Valor para $key: " val; echo; fi
  val="${val//$'\r'/}"
  local tmp; tmp="$(mktemp)"
  if grep -qE "^${key}=" .env; then
    awk -v k="$key" -v v="$val" 'BEGIN{FS=OFS="="} $1==k{print k"="v; next} {print}' .env > "$tmp"
  else
    cat .env > "$tmp"; printf '%s=%s\n' "$key" "$val" >> "$tmp"
  fi
  cat "$tmp" > .env; rm -f "$tmp"
  case "$key" in *KEY*|*TOKEN*|*PASSWORD*|*SECRET*) echo "✓ $key guardada (${#val} caracteres)";; *) echo "✓ $key=$val";; esac
}

cmd_up() {
  need_env
  mkdir -p data/hermes data/vault data/proyectos data/obsidian-config
  if grep -qE '^HERMES_UID=0\s*$' .env; then
    die "HERMES_UID=0 en .env: los agentes no deben correr como root. Pon HERMES_UID=10000 y HERMES_GID=10000."
  fi
  if [ "${1:-}" = "--public" ]; then $C --profile public up -d --build
  else $C up -d --build; fi
  echo "Esperando a la oficina…"
  for _ in $(seq 1 90); do
    if $EXEC office-url >/dev/null 2>&1; then break; fi
    sleep 2
  done
  cmd_status
}

cmd_status() {
  $C ps
  echo
  url="$($EXEC office-url 2>/dev/null || true)"
  echo "🏢 Oficina pixel-art : ${url:-'(aún arrancando: ./office.sh url)'}"
  echo "🧠 Dashboard Hermes  : http://localhost:$(envget DASHBOARD_PORT)   (usuario: $(envget HERMES_DASHBOARD_BASIC_AUTH_USERNAME))"
  echo "📚 Obsidian web      : http://localhost:$(envget OBSIDIAN_PORT)   (usuario: $(envget OBSIDIAN_WEB_USER))"
  echo "🔑 Contraseñas       : ./office.sh passwords"
  echo
  echo "Desde tu PC, abre un túnel:  ./office.sh tunnel-help"
}

cmd_passwords() {
  echo "Dashboard Hermes : $(envget HERMES_DASHBOARD_BASIC_AUTH_USERNAME) / $(envget HERMES_DASHBOARD_BASIC_AUTH_PASSWORD)"
  echo "Obsidian web     : $(envget OBSIDIAN_WEB_USER) / $(envget OBSIDIAN_WEB_PASSWORD)"
}

cmd_tunnel_help() {
  host="$(hostname -I 2>/dev/null | awk '{print $1}')"
  o="$(envget OFFICE_PORT)"; d="$(envget DASHBOARD_PORT)"; b="$(envget OBSIDIAN_PORT)"
  cat <<EOF
En tu ordenador (no en el VPS) ejecuta y deja la ventana abierta:

  ssh -N -L ${o:-3100}:localhost:${o:-3100} -L ${d:-9119}:localhost:${d:-9119} -L ${b:-3000}:localhost:${b:-3000} $(whoami)@${host:-IP_DEL_VPS}

Luego abre en el navegador:
  $($EXEC office-url 2>/dev/null || echo "http://localhost:${o:-3100}  (./office.sh url para el token)")
  http://localhost:${d:-9119}
  http://localhost:${b:-3000}
EOF
}

cmd_doctor() {
  local ok=0 bad=0
  pass() { echo "  ✓ $*"; ok=$((ok+1)); }
  fail() { echo "  ✗ $*"; bad=$((bad+1)); }
  echo "Oficina IA — diagnóstico"
  echo "• Sistema"
  command -v docker >/dev/null && pass "Docker $(docker --version | awk '{print $3}' | tr -d ,)" || fail "Docker no instalado"
  docker compose version >/dev/null 2>&1 && pass "Docker Compose" || fail "Falta el plugin docker compose"
  mem=$(awk '/MemTotal/{print int($2/1024/1024+0.5)}' /proc/meminfo 2>/dev/null || echo 0)
  [ "${mem:-0}" -ge 7 ] && pass "RAM ${mem} GB" || fail "RAM ${mem} GB (recomendado ≥ 8 GB)"
  df_gb=$(df -BG --output=avail . | tail -1 | tr -dc 0-9)
  [ "${df_gb:-0}" -ge 15 ] && pass "Disco libre ${df_gb} GB" || fail "Disco libre ${df_gb} GB (≥ 15 GB)"
  echo "• Configuración"
  [ -f .env ] && pass ".env presente" || { fail ".env no existe (./office.sh setup)"; echo; return 1; }
  [ "$(envget HERMES_UID)" != 0 ] && pass "Agentes sin root (UID $(envget HERMES_UID))" || fail "HERMES_UID=0"
  pass "Modelos: $(envget HERMES_PROVIDER) — manager $(envget HERMES_MODEL_MANAGER), equipo $(envget HERMES_MODEL_WORKERS)"
  echo "• Servicios"
  for s in office obsidian; do
    st=$($C ps --format '{{.State}}' "$s" 2>/dev/null | head -1)
    [ "$st" = running ] && pass "$s en marcha" || fail "$s: ${st:-parado}"
  done
  if [ "$($C ps --format '{{.State}}' office 2>/dev/null | head -1)" = running ]; then
    echo "• Oficina"
    $EXEC curl -fsS http://127.0.0.1:3100/api/health >/dev/null 2>&1 && pass "Pixel Agents responde" || fail "Pixel Agents no responde (./office.sh logs)"
    $EXEC office-url >/dev/null 2>&1 && pass "Token de la oficina disponible" || fail "Sin registro en ~/.pixel-agents/servers"
    $EXEC grep -q pixel-agents /opt/data/.claude/settings.json 2>/dev/null && pass "Hooks de Pixel Agents en Claude Code" || fail "Hooks de Claude Code sin instalar (se instalan al arrancar Pixel Agents)"
    for a in $AGENTS; do
      if [ "$a" = manager ]; then h=/opt/data; else h=/opt/data/profiles/$a; fi
      $EXEC test -f "$h/plugins/pixel-office/__init__.py" && $EXEC grep -q pixel-office "$h/config.yaml" \
        && pass "Perfil $a con plugin pixel-office" || fail "Perfil $a sin plugin (./office.sh bootstrap)"
    done
    $EXEC test -f /vault/Inicio.md && pass "Vault de Obsidian inicializado" || fail "Vault vacío"
    if $EXEC test -s /opt/data/.claude/.credentials.json || [ -n "$(envget ANTHROPIC_API_KEY)" ]; then
      pass "Claude Code con sesión (el Desarrollador lo usará)"
    else
      echo "  • Claude Code sin sesión (opcional): ./office.sh claude-login"
    fi
    if [ "$(envget HERMES_PROVIDER)" = nous ]; then
      if $EXEC hermes portal info 2>&1 | sed "s/\x1b\[[0-9;]*m//g" | grep -qi "logged in"; then
        pass "Nous Portal: sesión iniciada"
      else
        fail "Nous Portal sin sesión → ./office.sh portal-login"
      fi
    fi
  fi
  echo
  echo "Resultado: $ok correctos, $bad con problemas"
  [ "$bad" = 0 ]
}

cmd_hash_password() {
  read -rsp "Contraseña para la oficina web: " pw; echo
  docker run --rm caddy:2-alpine caddy hash-password --plaintext "$pw"
}

case "${1:-help}" in
  setup)        cmd_setup ;;
  set)          shift; cmd_set "$@" ;;
  up)           shift; cmd_up "$@" ;;
  down)         $C --profile public --profile sync down ;;
  restart)      # recrea "office" para que lea el .env nuevo
                $C up -d --force-recreate office ;;
  update)       git pull --ff-only && cmd_up ;;
  status|ps)    cmd_status ;;
  doctor)       cmd_doctor ;;
  passwords)    cmd_passwords ;;
  logs)         shift; $C logs -f --tail=200 "${@:-office}" ;;
  url)          $EXEC office-url ;;
  tunnel-help)  cmd_tunnel_help ;;
  hash-password) cmd_hash_password ;;
  chat)         agent="${2:-manager}"
                if [ "$agent" = manager ]; then $EXEC_IT hermes
                else $EXEC_IT hermes -p "$agent"; fi ;;
  task)         [ $# -ge 2 ] || die 'Uso: ./office.sh task "Objetivo de la tarea" [manager|investigador|desarrollador|bibliotecario]'
                title="$2"; who="${3:-manager}"
                if [ "$who" = manager ]; then $EXEC hermes kanban create "$title" --triage
                else $EXEC hermes kanban create "$title" --assignee "$who"; fi ;;
  board)        $EXEC hermes kanban list ;;
  hermes)       shift; $EXEC_IT hermes "$@" ;;
  claude)       shift; $C exec -it -u hermes -e HOME=/opt/data -w /office/proyectos office claude "$@" ;;
  claude-login) $EXEC_IT claude auth login ;;
  portal-login) # Nous Portal: código de dispositivo, no necesita pegar claves.
                # Si el .env aún apunta a otro proveedor (instalación anterior), lo pasa a Nous.
                need_env
                if [ "$(envget HERMES_PROVIDER)" != nous ]; then
                  cmd_set HERMES_PROVIDER nous
                  case "$(envget HERMES_MODEL_MANAGER)" in ""|claude-*) cmd_set HERMES_MODEL_MANAGER deepseek/deepseek-v4-pro ;; esac
                  case "$(envget HERMES_MODEL_WORKERS)" in ""|claude-*) cmd_set HERMES_MODEL_WORKERS deepseek/deepseek-v4-pro ;; esac
                  [ -n "$(envget HERMES_WEB_BACKEND)" ] || cmd_set HERMES_WEB_BACKEND nous
                  [ -n "$(envget HERMES_BROWSER_PROVIDER)" ] || cmd_set HERMES_BROWSER_PROVIDER nous
                  echo "• Aplicando el cambio de proveedor…"; $C up -d --force-recreate office >/dev/null
                  for _ in $(seq 1 60); do $EXEC true 2>/dev/null && break; sleep 2; done
                fi
                $EXEC_IT hermes portal ;;
  portal)       shift; $EXEC_IT hermes portal "${@:-info}" ;;
  models)       $EXEC_IT hermes model ;;
  shell)        $EXEC_IT bash ;;
  bootstrap)    $EXEC /opt/hermes/.venv/bin/python /opt/office/bin/office-bootstrap.py ;;
  routines)     shift; $EXEC office-routines "${@:-install}" ;;
  reset-souls)  for a in $AGENTS; do
                  if [ "$a" = manager ]; then f=data/hermes/SOUL.md; else f="data/hermes/profiles/$a/SOUL.md"; fi
                  cp "hermes/profiles/$a/SOUL.md" "$f" && echo "✓ $f"
                done ;;
  backup)       ts="$(date +%Y%m%d-%H%M)"; mkdir -p backups
                tar --exclude='data/hermes/.cache' -czf "backups/oficina-$ts.tgz" data/vault data/proyectos data/hermes
                echo "✓ backups/oficina-$ts.tgz" ;;
  help|*)       cat <<'EOF'
Oficina IA — comandos

  Instalación y servicio
  ./office.sh setup                 crea .env con contraseñas y las carpetas de datos
  ./office.sh set CLAVE [VALOR]     cambia un valor de .env (sin VALOR lo pide oculto)
  ./office.sh up [--public]         construye y arranca (con --public: Caddy + HTTPS)
  ./office.sh restart               aplica cambios de .env
  ./office.sh update                git pull + reconstruir
  ./office.sh status | doctor       estado y URLs | diagnóstico completo
  ./office.sh passwords             usuarios y contraseñas de los paneles
  ./office.sh url | tunnel-help     URL de la oficina | cómo verla desde tu PC
  ./office.sh logs [servicio]       logs (office | obsidian | caddy)
  ./office.sh down                  para todo

  Trabajo
  ./office.sh chat [agente]         chatea con un agente (por defecto el manager)
  ./office.sh task "objetivo" [ag]  crea una tarjeta Kanban (sin agente: el manager la descompone)
  ./office.sh board                 tablero Kanban
  ./office.sh claude [args]         Claude Code interactivo en /office/proyectos
  ./office.sh portal-login          inicia sesión en Nous Portal (modelos de los agentes Hermes)
  ./office.sh portal [info|tools]   estado de la suscripción y del Tool Gateway
  ./office.sh models                elige modelo de forma interactiva
  ./office.sh claude-login          (opcional) Claude Code con tu cuenta de Claude
  ./office.sh routines [install|list|remove]   rutinas automáticas (diario, Inbox, revisión)
  ./office.sh hermes <args>         cualquier comando de Hermes

  Mantenimiento
  ./office.sh bootstrap             re-aplica perfiles, plugin y configuración
  ./office.sh reset-souls           restaura las personalidades (SOUL.md) de serie
  ./office.sh backup                copia de vault, proyectos y Hermes
  ./office.sh hash-password         hash bcrypt para la oficina pública
EOF
  ;;
esac
