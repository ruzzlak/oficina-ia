#!/usr/bin/env bash
# office.sh — atajos para administrar la Oficina IA en el VPS.
set -euo pipefail
cd "$(dirname "$0")"

C="docker compose"
EXEC="$C exec -u hermes -e HOME=/opt/data -e HERMES_HOME=/opt/data office"
AGENTS="manager investigador desarrollador bibliotecario"

die() { echo "✗ $*" >&2; exit 1; }
need_env() { [ -f .env ] || die "Falta .env — ejecuta primero: ./office.sh setup"; }

cmd_setup() {
  command -v docker >/dev/null || die "Instala Docker primero: https://docs.docker.com/engine/install/"
  if [ ! -f .env ]; then
    cp .env.example .env
    rand() { openssl rand -hex "$1" 2>/dev/null || head -c "$1" /dev/urandom | od -An -tx1 | tr -d ' \n'; }
    sed -i "s/^HERMES_UID=.*/HERMES_UID=$(id -u)/; s/^HERMES_GID=.*/HERMES_GID=$(id -g)/" .env
    sed -i "s/^HERMES_DASHBOARD_BASIC_AUTH_PASSWORD=.*/HERMES_DASHBOARD_BASIC_AUTH_PASSWORD=$(rand 12)/" .env
    sed -i "s/^HERMES_DASHBOARD_BASIC_AUTH_SECRET=.*/HERMES_DASHBOARD_BASIC_AUTH_SECRET=$(rand 32)/" .env
    sed -i "s/^OBSIDIAN_WEB_PASSWORD=.*/OBSIDIAN_WEB_PASSWORD=$(rand 12)/" .env
    chmod 600 .env
    echo "✓ Creado .env con contraseñas aleatorias. Edítalo y añade tus claves de modelo:"
    echo "    nano .env"
  else
    echo "• .env ya existe (no lo toco)"
  fi
  mkdir -p data/hermes data/vault data/proyectos data/obsidian-config
  echo "✓ Carpetas de datos listas en ./data"
}

cmd_up() {
  need_env
  mkdir -p data/hermes data/vault data/proyectos data/obsidian-config
  if [ "${1:-}" = "--public" ]; then $C --profile public up -d --build; else $C up -d --build; fi
  echo "Esperando a la oficina…"
  for _ in $(seq 1 60); do
    if $EXEC office-url >/dev/null 2>&1; then break; fi
    sleep 2
  done
  cmd_status
}

cmd_status() {
  $C ps
  echo
  url="$($EXEC office-url 2>/dev/null || true)"
  # shellcheck disable=SC1091
  . ./.env
  echo "🏢 Oficina pixel-art : ${url:-'(aún arrancando: ./office.sh url)'}"
  echo "🧠 Dashboard Hermes  : http://localhost:${DASHBOARD_PORT:-9119}   (usuario: ${HERMES_DASHBOARD_BASIC_AUTH_USERNAME:-admin})"
  echo "📚 Obsidian web      : http://localhost:${OBSIDIAN_PORT:-3000}   (usuario: ${OBSIDIAN_WEB_USER:-oficina})"
  echo
  echo "Desde tu PC, abre un túnel:  ./office.sh tunnel-help"
}

cmd_tunnel_help() {
  # shellcheck disable=SC1091
  . ./.env
  host="$(hostname -I 2>/dev/null | awk '{print $1}')"
  cat <<EOF
En tu ordenador (no en el VPS) ejecuta:

  ssh -N -L ${OFFICE_PORT:-3100}:localhost:${OFFICE_PORT:-3100} \\
         -L ${DASHBOARD_PORT:-9119}:localhost:${DASHBOARD_PORT:-9119} \\
         -L ${OBSIDIAN_PORT:-3000}:localhost:${OBSIDIAN_PORT:-3000} \\
         $(whoami)@${host:-IP_DEL_VPS}

y abre en el navegador la URL de la oficina que da ./office.sh url
EOF
}

cmd_hash_password() {
  read -rsp "Contraseña para la oficina web: " pw; echo
  docker run --rm caddy:2-alpine caddy hash-password --plaintext "$pw"
}

case "${1:-help}" in
  setup)        cmd_setup ;;
  up)           shift; cmd_up "$@" ;;
  down)         $C --profile public --profile sync down ;;
  restart)      $C restart office ;;
  status|ps)    cmd_status ;;
  logs)         shift; $C logs -f --tail=200 "${@:-office}" ;;
  url)          $EXEC office-url ;;
  tunnel-help)  cmd_tunnel_help ;;
  hash-password) cmd_hash_password ;;
  chat)         # ./office.sh chat [agente]
                agent="${2:-manager}"
                if [ "$agent" = manager ]; then $C exec -it -u hermes -e HOME=/opt/data office hermes
                else $C exec -it -u hermes -e HOME=/opt/data office hermes -p "$agent"; fi ;;
  task)         # ./office.sh task "Objetivo" [asignado]
                [ $# -ge 2 ] || die 'Uso: ./office.sh task "Objetivo de la tarea" [manager|investigador|desarrollador|bibliotecario]'
                title="$2"; who="${3:-manager}"
                if [ "$who" = manager ]; then $EXEC hermes kanban create "$title" --triage
                else $EXEC hermes kanban create "$title" --assignee "$who"; fi ;;
  board)        $EXEC hermes kanban list ;;
  hermes)       shift; $C exec -it -u hermes -e HOME=/opt/data office hermes "$@" ;;
  claude)       shift; $C exec -it -u hermes -e HOME=/opt/data -w /office/proyectos office claude "$@" ;;
  claude-login) $C exec -it -u hermes -e HOME=/opt/data office claude auth login ;;
  shell)        $C exec -it -u hermes -e HOME=/opt/data office bash ;;
  bootstrap)    $EXEC /opt/hermes/.venv/bin/python /opt/office/bin/office-bootstrap.py ;;
  reset-souls)  for a in $AGENTS; do
                  if [ "$a" = manager ]; then f=data/hermes/SOUL.md; else f="data/hermes/profiles/$a/SOUL.md"; fi
                  cp "hermes/profiles/$a/SOUL.md" "$f" && echo "✓ $f"
                done ;;
  backup)       ts="$(date +%Y%m%d-%H%M)"; mkdir -p backups
                tar --exclude='data/hermes/.cache' -czf "backups/oficina-$ts.tgz" data/vault data/proyectos data/hermes
                echo "✓ backups/oficina-$ts.tgz" ;;
  help|*)       cat <<'EOF'
Oficina IA — comandos

  ./office.sh setup                 crea .env con contraseñas y las carpetas de datos
  ./office.sh up [--public]         construye y arranca (con --public: Caddy + HTTPS)
  ./office.sh status                estado y URLs
  ./office.sh url                   URL de la oficina pixel-art con token
  ./office.sh tunnel-help           cómo abrir el túnel SSH desde tu PC
  ./office.sh logs [servicio]       logs (office | obsidian | caddy)
  ./office.sh down                  para todo

  ./office.sh chat [agente]         chatea con un agente (por defecto el manager)
  ./office.sh task "objetivo" [ag]  crea una tarjeta Kanban (sin agente: el manager la descompone)
  ./office.sh board                 muestra el tablero Kanban
  ./office.sh claude [args]         abre Claude Code en /office/proyectos
  ./office.sh claude-login          inicia sesión de Claude Code con tu cuenta
  ./office.sh hermes <args>         cualquier comando de Hermes (model, kanban, profile…)

  ./office.sh bootstrap             re-aplica perfiles, plugin y configuración
  ./office.sh reset-souls           restaura las personalidades (SOUL.md) de serie
  ./office.sh backup                copia de seguridad de vault, proyectos y Hermes
  ./office.sh hash-password         hash bcrypt para la oficina pública
EOF
  ;;
esac
