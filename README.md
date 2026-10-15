# 🏢 Oficina IA

Una oficina completa para agentes de IA, lista para un VPS con Docker:

- **Visual:** [Pixel Agents](https://github.com/pixel-agents-hq/pixel-agents) — cada agente es un personaje pixel-art con su escritorio, que se anima cuando lee, escribe, ejecuta comandos o espera tu aprobación.
- **Agentes:** [Hermes Agent](https://github.com/NousResearch/hermes-agent) (Nous Research) gestiona al equipo con su tablero **Kanban** multi-agente, y **Claude Code** hace la implementación de código.
- **Conocimiento:** un vault de **Obsidian** compartido por todos los agentes, accesible desde el navegador (o sincronizado con tu Obsidian de escritorio).

```
                    tú ──► Dashboard de Hermes · Telegram · ./office.sh chat
                                        │
                       ┌────────────────▼─────────────────┐
                       │  🟡 Manager  (orquestador Hermes) │──► tablero Kanban (kanban.db)
                       └────┬──────────────┬──────────┬───┘
                            │ tarjetas     │          │
             ┌──────────────▼──┐  ┌────────▼──────┐  ┌▼─────────────────┐
             │ 🔵 Investigador │  │ 🟢 Desarrollador│  │ 🟣 Bibliotecario │
             │   web + fuentes │  │  planifica y   │  │  enlaza y resume │
             └────────┬────────┘  │  verifica      │  └────────┬─────────┘
                      │           └───────┬────────┘           │
                      │          office-claude │ claude -p     │
                      │           ┌───────▼────────┐           │
                      │           │ 🤖 Claude Code  │           │
                      │           └───────┬────────┘           │
                      ▼                   ▼                    ▼
             ┌──────────────────────────────────────────────────────────┐
             │  📚 /vault  (Obsidian)        💻 /office/proyectos (git)  │
             └──────────────────────────────────────────────────────────┘

  Todos emiten eventos ──► 🏢 Pixel Agents (oficina pixel-art en el navegador)
     Hermes: plugin pixel-office        Claude Code: hooks de Pixel Agents
```

## Qué incluye

| Pieza | Qué hace |
|---|---|
| `docker/office/Dockerfile` | Imagen única basada en `nousresearch/hermes-agent` + Pixel Agents (servidor standalone, supervisado con s6) + Claude Code. Comparten `localhost` y el mismo `HOME`, que es lo que permite que todos los hooks lleguen a la misma oficina. |
| `hermes/plugins/pixel-office/` | **El puente.** Plugin de Hermes que traduce sus hooks (`pre_tool_call`, `on_session_end`, aprobaciones, subagentes, Kanban…) al protocolo de hooks HTTP de Pixel Agents. Cada perfil aparece como un personaje fijo con su nombre. También escribe los eventos del Kanban en `vault/Agentes/_Registro/`. |
| `hermes/office.yaml` + `hermes/profiles/*/SOUL.md` | El equipo: Manager (raíz, sin terminal, solo Kanban), Investigador, Desarrollador y Bibliotecario, con personalidad y reglas en español. |
| `docker/office/bin/office-claude` | Cómo el Desarrollador usa a Claude Code: `office-claude <proyecto> "<instrucción>"` en `/office/proyectos/<proyecto>`, con git, permisos acotados y acceso al vault. |
| `pixel-agents/layout.json` | La oficina por defecto de Pixel Agents con 4 zonas (Dirección, Investigación, Desarrollo, Biblioteca): cada agente se sienta en la suya. Las sesiones de Claude Code ocupan los sofás. |
| `vault/` | Vault inicial: estructura de carpetas, protocolo de agentes, fichas, plantillas (Proyecto, Investigación, Nota permanente, Diario) y ajustes de Obsidian. |
| `claude/CLAUDE.md` | Contexto global para Claude Code (dónde está el vault, reglas). |
| `docker-compose.yml` | `office` + `obsidian` (Obsidian en el navegador) + opcionales `caddy` (HTTPS) y `syncthing` (sincronizar el vault con tu PC). |
| `office.sh` | Atajos: `setup`, `up`, `url`, `chat`, `task`, `board`, `claude`, `backup`… |

## Instalación en el VPS (Hostinger u otro)

Requisitos: VPS con Ubuntu/Debian, **8 GB de RAM** recomendados (Hostinger KVM 2 o superior) y una cuenta de Claude.

**Un solo comando** (como root, por SSH o desde el terminal del navegador de hPanel):

```bash
curl -fsSL https://raw.githubusercontent.com/<usuario>/oficina-ia/main/install.sh | bash -s -- <usuario>
```

Instala Docker si falta, añade swap si hace falta, descarga el proyecto en `/opt/oficina-ia`, genera `.env` con contraseñas aleatorias, construye y arranca. Después:

```bash
cd /opt/oficina-ia
./office.sh set ANTHROPIC_API_KEY   # te la pide sin mostrarla
./office.sh claude-login            # Claude Code con tu cuenta de Claude (Pro o Max)
./office.sh restart && ./office.sh doctor
./office.sh routines                # rutinas automáticas (opcional)
```

### Modelos: todo con Claude

| Quién | Cómo se autentica | Modelo por defecto |
|---|---|---|
| **Claude Code** | Tu suscripción de Claude (`./office.sh claude-login`) o `ANTHROPIC_API_KEY` | el de tu cuenta |
| **Hermes – Manager** | `ANTHROPIC_API_KEY` (pago por uso). Alternativa: tu cuenta de Claude, **solo si es Max con créditos de uso extra** | `claude-opus-5-5` |
| **Hermes – Investigador, Desarrollador, Bibliotecario** | igual que el Manager | `claude-sonnet-5-5` |

Cambia los modelos en `.env` (`HERMES_MODEL_MANAGER`, `HERMES_MODEL_WORKERS`) y aplica con `./office.sh restart`.

## Acceder

Por seguridad todo escucha solo en `127.0.0.1` del VPS (los agentes tienen terminal: no expongas nada sin contraseña). Desde tu ordenador:

```bash
./office.sh tunnel-help    # en el VPS: te imprime el comando ssh -L … exacto
```

| Servicio | URL (con el túnel abierto) |
|---|---|
| 🏢 Oficina pixel-art | la que da `./office.sh url` (`http://localhost:3100/?token=…`) |
| 🧠 Dashboard de Hermes (Kanban, chat, config) | http://localhost:9119 |
| 📚 Obsidian web | http://localhost:3000 → la primera vez: *Open folder as vault* → `/vault` |

**Acceso público con HTTPS:** apunta tres subdominios al VPS, rellena el bloque *opcional* de `.env` (genera el hash con `./office.sh hash-password`) y ejecuta `./office.sh up --public`. Caddy obtiene los certificados y pide contraseña para la oficina; el dashboard y Obsidian usan su propio login.

**Obsidian de escritorio:** `docker compose --profile sync up -d` arranca Syncthing (interfaz en `localhost:8384` por el túnel); comparte la carpeta `/vault` con tu PC.

## Rutinas automáticas

`./office.sh routines` programa en el cron de Hermes tres rutinas, que crean tarjetas para el Bibliotecario (así también se ven en la oficina):

| Rutina | Cuándo | Qué hace |
|---|---|---|
| `oficina-inbox` | cada día 08:00 | clasifica lo que dejes en `00 Inbox/` |
| `oficina-diario` | cada día 21:00 | escribe `04 Diario/AAAA-MM-DD.md` a partir del registro |
| `oficina-semanal` | lunes 09:00 | revisión semanal y actualización de `Inicio.md` |

`./office.sh routines list` las muestra y `./office.sh routines remove` las borra. Las horas siguen `TZ` de `.env`.

## Uso diario

```bash
./office.sh chat                       # habla con el Manager: "Quiero una API de tareas con FastAPI; investiga primero opciones de auth"
./office.sh task "Compara 3 bases de datos vectoriales para RAG"          # el Manager la descompone
./office.sh task "Procesa el Inbox del vault" bibliotecario              # directo a un agente
./office.sh board                      # estado del tablero
./office.sh chat desarrollador         # hablar con un agente concreto
./office.sh claude                     # Claude Code interactivo en /office/proyectos
```

Lo que verás:
1. El **Manager** se activa en *Dirección* y reparte tarjetas (se le ve "enviando" a cada compañero).
2. El dispatcher del Kanban lanza a cada trabajador: su personaje se activa en su zona con la herramienta que usa (*Searching the web*, *Writing nota.md*, *Running: pytest*).
3. El **Desarrollador** llama a Claude Code y aparece un **personaje nuevo en los sofás** (la sesión de Claude Code) mientras programa.
4. Las burbujas `…` indican que alguien espera tu aprobación; ✓ que terminó su turno.
5. Todo queda en Obsidian: investigaciones, notas de proyecto, el registro del Kanban y, si se lo pides al Bibliotecario, el diario.

Para hablar con el Manager por **Telegram**, pon `TELEGRAM_BOT_TOKEN` y `TELEGRAM_ALLOWED_USERS` en `.env` y ejecuta `./office.sh restart`.

## Personalizar

- **Personalidades:** edita `data/hermes/SOUL.md` (Manager) y `data/hermes/profiles/<agente>/SOUL.md`. El bootstrap no las vuelve a pisar; `./office.sh reset-souls` restaura las de serie.
- **Añadir un agente:** añádelo a `hermes/office.yaml` (con `area`) y crea `hermes/profiles/<nombre>/SOUL.md`; luego `./office.sh up`. Para darle escritorio propio, crea un área con el mismo nombre en el editor de layout de Pixel Agents.
- **La oficina:** usa el editor integrado de Pixel Agents (con la URL con token). El layout se guarda en `data/hermes/.pixel-agents/layout.json`.
- **Permisos de Claude Code:** `OFFICE_CLAUDE_ALLOWED_TOOLS` y `OFFICE_CLAUDE_MAX_TURNS` en `.env`.
- **Pixel Agents desde código fuente:** `PIXEL_AGENTS_SOURCE=git` y `PIXEL_AGENTS_REF=v1.4.1` en `.env`.

## Cómo funciona el puente (detalles técnicos)

Pixel Agents publica en `~/.pixel-agents/servers/<pid>-<port>.json` el puerto y un token, y acepta `POST /api/hooks/claude` con eventos al estilo de Claude Code. El plugin `pixel-office`:

| Hook de Hermes | Evento enviado a Pixel Agents |
|---|---|
| `on_session_start`, `pre_llm_call` | `SessionStart` (idempotente) con `cwd=/office/agentes/<perfil>`, que da nombre al personaje, y `PreToolUse EnterPlanMode` ("Planning") |
| `pre_tool_call` / `post_tool_call` | `PreToolUse` / `PostToolUse`, traduciendo `terminal→Bash`, `read_file→Read`, `write_file→Write`, `patch→Edit`, `web_search→WebSearch`, `kanban_create→SendMessage(→asignado)`… |
| `on_session_end` | `Stop` (✓ turno terminado) |
| `on_human_input_request` | `PermissionRequest` (aprobación) o `Notification idle_prompt` (pregunta) |
| `subagent_start/stop` (`delegate_task`) | `SubagentStart/SubagentStop`: aparece un subagente junto a su agente |
| `kanban_task_claimed/completed/blocked` | animación de entrega en el Manager y una línea en `vault/Agentes/_Registro/AAAA-MM-DD.md` |

Usa un `session_id` estable por perfil (`hermes-<perfil>`), así cada rol es siempre el mismo personaje aunque cada tarjeta Kanban sea un proceso nuevo. Los envíos van por un hilo en segundo plano con timeouts cortos: si la oficina está caída, Hermes ni se entera.

Pruebas (no necesitan Docker):

```bash
python3 -m unittest discover -s tests -v
```

`tests/mock_pixel_agents.py` reproduce la semántica de `hookEventHandler.ts` (sesión pendiente → confirmada → personaje con nombre), y `tests/test_bootstrap.py` simula el primer arranque y el segundo del contenedor.

## Mantenimiento

```bash
./office.sh logs            # logs de la oficina (Hermes + Pixel Agents)
./office.sh backup          # tar.gz de vault, proyectos y datos de Hermes
docker compose build --pull --no-cache office && ./office.sh up   # actualizar Hermes, Pixel Agents y Claude Code
```

## Solución de problemas

| Síntoma | Causa probable |
|---|---|
| La oficina carga pero no aparece nadie | Ningún agente ha trabajado aún. Lanza `./office.sh task "di hola" investigador`. Comprueba que `./office.sh url` responde. |
| Los agentes Hermes no aparecen | `./office.sh hermes plugins list` debe mostrar `pixel-office` habilitado; `./office.sh bootstrap` lo reinstala. |
| Claude Code no aparece | Los hooks se instalan al arrancar Pixel Agents en `data/hermes/.claude/settings.json`; reinicia con `./office.sh restart`. |
| El Desarrollador bloquea tarjetas por "no autenticado" | Falta `./office.sh claude-login` (o `ANTHROPIC_API_KEY`). |
| Hermes responde con errores 401/403 | Falta `ANTHROPIC_API_KEY`, o tu cuenta de Claude no es Max con uso extra: `./office.sh set ANTHROPIC_API_KEY` y `./office.sh restart`. |
| Algo no funciona y no sabes qué | `./office.sh doctor` revisa Docker, RAM, servicios, plugin, hooks, vault y credenciales. |
| Las tarjetas se quedan en `ready` | El asignado no existe o no hay modelo configurado: `./office.sh hermes profile list` y `./office.sh hermes doctor`. |
| Permisos en `./data` | `HERMES_UID`/`HERMES_GID` en `.env` deben coincidir con tu usuario (`id -u`, `id -g`). |
