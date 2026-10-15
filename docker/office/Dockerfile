# syntax=docker/dockerfile:1.7
#
# Imagen de la Oficina IA:
#   Hermes Agent (Nous Research)  +  Pixel Agents (servidor standalone)  +  Claude Code
#
# Todo vive en un mismo contenedor a propósito: los hooks de Claude Code y el
# plugin pixel-office de Hermes hablan con Pixel Agents por 127.0.0.1 y leen el
# token de ~/.pixel-agents/servers/, y Pixel Agents lee los transcripts de
# Claude Code en ~/.claude/projects. Con HOME=/opt/data (el volumen de Hermes)
# todo comparte el mismo hogar.

ARG HERMES_IMAGE=nousresearch/hermes-agent:latest

# ── Pixel Agents desde el código fuente (opcional: PIXEL_AGENTS_SOURCE=git) ──
FROM node:22-bookworm-slim AS pixel_agents_git
ARG PIXEL_AGENTS_SOURCE=npm
ARG PIXEL_AGENTS_REF=v1.4.1
ARG PIXEL_AGENTS_REPO=https://github.com/pixel-agents-hq/pixel-agents.git
RUN mkdir -p /out && if [ "$PIXEL_AGENTS_SOURCE" = "git" ]; then \
      apt-get update && apt-get install -y --no-install-recommends git ca-certificates && \
      git clone --depth 1 --branch "$PIXEL_AGENTS_REF" "$PIXEL_AGENTS_REPO" /src && \
      cd /src && HUSKY=0 npm ci && (cd webview-ui && npm ci) && \
      HUSKY=0 npm pack --pack-destination /out ; \
    fi

# ── Imagen final ─────────────────────────────────────────────────────────────
FROM ${HERMES_IMAGE}

ARG PIXEL_AGENTS_SOURCE=npm
ARG PIXEL_AGENTS_VERSION=latest
ARG CLAUDE_CODE_VERSION=latest

USER root

# Herramientas globales de Node en /usr/local (la imagen de Hermes ya trae node/npm).
COPY --from=pixel_agents_git /out/ /tmp/pixel-agents-pkg/
RUN set -eux; \
    node --version; npm --version; \
    if [ "$PIXEL_AGENTS_SOURCE" = "git" ]; then \
        npm install -g --prefix /usr/local /tmp/pixel-agents-pkg/*.tgz; \
    else \
        npm install -g --prefix /usr/local "pixel-agents@${PIXEL_AGENTS_VERSION}"; \
    fi; \
    npm install -g --prefix /usr/local "@anthropic-ai/claude-code@${CLAUDE_CODE_VERSION}"; \
    npm cache clean --force; rm -rf /tmp/pixel-agents-pkg; \
    command -v pixel-agents; command -v claude; claude --version || true

# Material de la oficina (plantillas, plugin, vault inicial, layout)
COPY hermes/        /opt/office/hermes/
COPY vault/         /opt/office/vault-seed/
COPY pixel-agents/  /opt/office/pixel-agents/
COPY claude/        /opt/office/claude/
COPY --chmod=0755 docker/office/bootstrap/office-bootstrap.py /opt/office/bin/office-bootstrap.py
COPY --chmod=0755 docker/office/bin/ /usr/local/bin/

# Servicio s6 supervisado para Pixel Agents (se reinicia solo si se cae)
COPY docker/office/s6/pixel-office/ /etc/s6-overlay/s6-rc.d/pixel-office/
RUN chmod 0755 /etc/s6-overlay/s6-rc.d/pixel-office/run && \
    touch /etc/s6-overlay/s6-rc.d/user/contents.d/pixel-office

# Bootstrap de la oficina: después del setup de Hermes (01, 015, 02)
COPY --chmod=0755 docker/office/cont-init/03-office-bootstrap /etc/cont-init.d/03-office-bootstrap

RUN mkdir -p /office/proyectos /office/agentes /vault && chown -R hermes:hermes /office /vault

ENV OFFICE_VAULT=/vault \
    OFFICE_WORKDIR=/office \
    OBSIDIAN_VAULT_PATH=/vault \
    PIXEL_AGENTS_DIR=/opt/data/.pixel-agents \
    PIXEL_OFFICE_AGENTS_ROOT=/office/agentes

EXPOSE 3100 9119
VOLUME [ "/opt/data", "/vault", "/office" ]
