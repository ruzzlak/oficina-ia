#!/usr/bin/env bash
# Instalador de la Oficina IA para un VPS recién creado (probado para Hostinger, Ubuntu/Debian).
#
#   curl -fsSL https://raw.githubusercontent.com/<usuario>/oficina-ia/main/install.sh | sudo bash -s -- <usuario>
#
# Qué hace (todo idempotente: puedes volver a ejecutarlo):
#   1. instala Docker + Compose y git si faltan
#   2. añade 4 GB de swap si el VPS tiene menos de 8 GB de RAM y no hay swap
#   3. clona (o actualiza) el repo en /opt/oficina-ia
#   4. crea .env con contraseñas aleatorias (./office.sh setup)
#   5. construye y arranca la oficina, salvo que pases --no-start
#
# Variables opcionales: OFICINA_DIR (por defecto /opt/oficina-ia), OFICINA_BRANCH (main)
set -euo pipefail

say()  { printf '\n\033[1;36m▶ %s\033[0m\n' "$*"; }
ok()   { printf '  \033[32m✓\033[0m %s\n' "$*"; }
die()  { printf '\n\033[31m✗ %s\033[0m\n' "$*" >&2; exit 1; }

GH_USER="${1:-${OFICINA_GH_USER:-ruzzlak}}"
START=1
for a in "$@"; do [ "$a" = "--no-start" ] && START=0; done
DIR="${OFICINA_DIR:-/opt/oficina-ia}"
BRANCH="${OFICINA_BRANCH:-main}"

[ "$(id -u)" = 0 ] || die "Ejecútalo como root (o con sudo)."
[ "$GH_USER" = "--no-start" ] && GH_USER="${OFICINA_GH_USER:-ruzzlak}"
[ -n "$GH_USER" ] || die "Uso: install.sh <usuario-de-github> [--no-start]"
REPO="https://github.com/${GH_USER}/oficina-ia.git"

say "1/5 Paquetes básicos"
export DEBIAN_FRONTEND=noninteractive
if ! command -v git >/dev/null || ! command -v curl >/dev/null || ! command -v openssl >/dev/null; then
  apt-get update -qq && apt-get install -y -qq git curl openssl ca-certificates >/dev/null
fi
ok "git, curl, openssl"

if ! command -v docker >/dev/null; then
  say "Instalando Docker (script oficial get.docker.com)"
  curl -fsSL https://get.docker.com | sh >/dev/null
fi
docker compose version >/dev/null 2>&1 || apt-get install -y -qq docker-compose-plugin >/dev/null
systemctl enable --now docker >/dev/null 2>&1 || true
ok "$(docker --version)"
ok "$(docker compose version | head -1)"

say "2/5 Memoria"
mem_gb=$(awk '/MemTotal/{print int($2/1024/1024+0.5)}' /proc/meminfo)
if [ "$mem_gb" -lt 8 ] && ! swapon --show | grep -q .; then
  fallocate -l 4G /swapfile 2>/dev/null || dd if=/dev/zero of=/swapfile bs=1M count=4096 status=none
  chmod 600 /swapfile && mkswap /swapfile >/dev/null && swapon /swapfile
  grep -q '^/swapfile' /etc/fstab || echo '/swapfile none swap sw 0 0' >> /etc/fstab
  ok "RAM ${mem_gb} GB → añadidos 4 GB de swap"
else
  ok "RAM ${mem_gb} GB$(swapon --show | grep -q . && echo ' (swap ya configurada)')"
fi

say "3/5 Código de la oficina → $DIR"
if [ -d "$DIR/.git" ]; then
  git -C "$DIR" fetch -q origin "$BRANCH" && git -C "$DIR" checkout -q "$BRANCH" && git -C "$DIR" pull -q --ff-only
  ok "actualizado ($(git -C "$DIR" rev-parse --short HEAD))"
else
  git clone -q --branch "$BRANCH" "$REPO" "$DIR" || die "No pude clonar $REPO (¿el repositorio es público?)"
  ok "clonado ($(git -C "$DIR" rev-parse --short HEAD))"
fi
cd "$DIR"
chmod +x office.sh install.sh docker/office/bin/* 2>/dev/null || true

say "4/5 Configuración"
./office.sh setup

if [ "$START" = 0 ]; then
  say "Listo. Falta tu clave y arrancar:"
  echo "  cd $DIR && ./office.sh set ANTHROPIC_API_KEY && ./office.sh up"
  exit 0
fi

say "5/5 Construyendo y arrancando (la primera vez tarda 5-15 minutos)"
./office.sh up
echo
./office.sh doctor || true
cat <<EOF

────────────────────────────────────────────────────────────
 Oficina IA instalada en $DIR
   cd $DIR
   ./office.sh set ANTHROPIC_API_KEY   # si aún no la pusiste
   ./office.sh claude-login            # Claude Code con tu cuenta de Claude
   ./office.sh routines                # rutinas automáticas (Inbox, diario, revisión)
   ./office.sh tunnel-help             # cómo abrir la oficina desde tu PC
────────────────────────────────────────────────────────────
EOF
