# NEXT_STEPS.md

Estado del proyecto al cierre de la sesión del 2026-08-20.

## Hecho esta sesión

- `generate.py` reescrito con el menú interactivo completo (9 opciones: proyectos 1-4,
  sistema 5-9), probado opción por opción y con la creación de un proyecto de prueba
  (en copia aislada, no quedó nada de prueba en el repo real).
- `structure.json` limpiado: se sacaron las 3 entradas `registry.md` sueltas (diseño
  viejo, reemplazado por auto-descubrimiento vía encabezado).
- Los 11 archivos ya definidos en `agents/`, `skills/`, `tools/` recibieron su
  encabezado `name`/`description` por defecto (antes estaban vacíos porque el
  generador viejo no los rellenaba).
- Comando `aw` instalado en `~/.local/bin/aw` (wrapper que abre el menú desde
  cualquier carpeta).
- `CLAUDE.md` del repo reescrito con la arquitectura real: el menú, el mecanismo de
  auto-descubrimiento por encabezado en `agents/skills/tools`, y qué acción del menú
  actualiza cada archivo (y cuáles nunca se reescriben).
- Se encontró que el clon git original (historial completo + remoto a
  `github.com/Scrambledeggs-ai/agentic-workspace` + 1 commit sin subir) había quedado
  en la papelera del sistema, movido ahí el mismo día. Se restauró como raíz del repo
  en `/home/zenau/Developer` — no se perdió contenido, todo coincidía byte a byte con
  lo reconstruido en esta sesión.
- `main` sincronizado con `origin/main` (push hecho, 2 commits subidos).
- Manual de uso (artifact en claude.ai, linkeado desde `Readme.md`) actualizado con la
  sección "Qué actualiza cada acción" — mismo link, sin necesidad de tocar el repo.

## Qué falta (contenido, no código)

- `core/*.md` (`init.md`, `agent.md`, `config.md`, `router.md`, `memory_policy.md`)
  siguen vacíos — falta escribir cómo arranca y rutea el sistema.
- `memory/*.md` (`global.md`, `user_profile.md`, `preferences.md`) siguen vacíos.
- Los 11 archivos de `agents/`, `skills/`, `tools/` solo tienen el encabezado por
  defecto — falta el cuerpo real de cada definición (qué sabe hacer cada uno).
- No hay ningún proyecto real creado todavía en `projects/` (solo `template_project`).

## Decisiones pendientes

- Conectar el `CLAUDE.md` global (`~/.claude/CLAUDE.md`) con
  `~/agency-stack/tools/estructura-emprendedor/06-plantillas/` para dejar definido
  dónde vive la documentación y qué plantillas usar — pedido explícitamente para otra
  sesión, no tocar sin que el usuario lo retome.
- No hay ningún mecanismo que haga que Claude Code lea `core/*.md` automáticamente al
  abrir sesión en este repo — el menú es gestión de proyectos para el humano, no
  bootstrapping de contexto para el agente. Si más adelante se quiere resolver, evaluar
  un `CLAUDE.md` de proyecto que apunte a `core/init.md` (decisión del usuario, no
  asumir).
