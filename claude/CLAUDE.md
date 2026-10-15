# Oficina IA — contexto para Claude Code

Trabajas dentro de la **Oficina IA**: un equipo de agentes Hermes (Manager, Investigador, Desarrollador, Bibliotecario) que se coordina con un tablero Kanban, con una oficina pixel-art (Pixel Agents) donde aparece cada sesión, y con un vault de Obsidian como memoria compartida.

## Dónde está cada cosa

- `/office/proyectos/<proyecto>/` — repositorios de código. Normalmente te invoca el agente **desarrollador** con una instrucción concreta; cúmplela y verifica (tests) antes de terminar.
- `/vault/` — vault de Obsidian (Markdown). Léelo para contexto:
  - `/vault/01 Proyectos/<Proyecto>.md` — objetivo, decisiones y bitácora técnica del proyecto.
  - `/vault/02 Investigación/` — investigaciones previas con fuentes.
  - `/vault/03 Conocimiento/` — notas permanentes y MOCs.
  - `/vault/Agentes/Protocolo.md` — convenciones del vault.
- El tablero Kanban se consulta con `hermes kanban list` y `hermes kanban show <id>`.

## Reglas

- Responde y comenta en español salvo que el proyecto use otro idioma.
- No escribas secretos en el código ni en el vault; usa variables de entorno.
- Si cambias la arquitectura de un proyecto, añade una entrada breve en la sección *Bitácora técnica* de su nota en `/vault/01 Proyectos/` (fecha, qué y por qué).
- No edites `/vault/.obsidian/` ni `/vault/Agentes/_Registro/`.
- No hagas `git push` salvo que se te pida explícitamente.
