---
tipo: protocolo
estado: final
tags: [agentes, protocolo]
---
# Protocolo de la oficina

Reglas que siguen **todos** los agentes (Hermes y Claude Code) al trabajar con este vault.

## Estructura

| Carpeta | Qué contiene | Quién escribe |
|---|---|---|
| `00 Inbox/` | Notas sin clasificar, capturas rápidas, adjuntos | cualquiera (tú incluido) |
| `01 Proyectos/` | Una nota por proyecto: objetivo, tareas, decisiones, bitácora técnica | Manager, Desarrollador, Bibliotecario |
| `02 Investigación/` | Una nota por investigación, con fuentes | Investigador |
| `03 Conocimiento/` | Notas permanentes (una idea por nota) y MOCs | Bibliotecario |
| `04 Diario/` | Resumen diario de la oficina (`AAAA-MM-DD.md`) | Bibliotecario |
| `Agentes/` | Fichas de cada agente y este protocolo | humanos |
| `Agentes/_Registro/` | Log automático del Kanban (no editar) | plugin `pixel-office` |
| `Plantillas/` | Plantillas de notas | humanos |

## Nombres

- Proyectos: `01 Proyectos/<Nombre del proyecto>.md` (mismo nombre que la carpeta de código en `/office/proyectos/<nombre-del-proyecto>`, en minúsculas y con guiones).
- Investigaciones: `02 Investigación/AAAA-MM-DD Tema corto.md`.
- Notas permanentes: título que afirma la idea (`SQLite en WAL permite lecturas concurrentes.md`).

## Frontmatter mínimo

```yaml
---
tipo: proyecto | investigacion | permanente | moc | diario
estado: borrador | activo | final | archivado
creado: AAAA-MM-DD
autor: manager | investigador | desarrollador | bibliotecario | claude-code | humano
tags: []
---
```

## Enlaces y etiquetas

- Usa `[[wikilinks]]`, nunca rutas absolutas dentro del texto de las notas.
- Toda nota nueva enlaza al menos a otra (su proyecto, su MOC o su fuente).
- Etiquetas en minúsculas, en español, jerárquicas cuando ayuda: `#proyecto/activo`, `#investigacion`, `#decision`.

## Reglas de convivencia

1. **No borres** notas ajenas: muévelas o pon `estado: archivado`.
2. **No pegues secretos** (claves, tokens, contraseñas).
3. **Parafrasea** las fuentes; enlázalas en `fuentes:`.
4. No toques `.obsidian/` ni `Agentes/_Registro/`.
5. Si dudas dónde va algo, déjalo en `00 Inbox/`: el Bibliotecario lo ordenará.
