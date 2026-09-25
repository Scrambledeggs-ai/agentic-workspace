# Protocolo aw (workspace)

Aplica solo a proyectos aw: una carpeta con `state.md` y `tasks/` dentro de `projects/`.
En cualquier otro contexto, ignorar este archivo. No repite las reglas del CLAUDE.md global.

## Qué es un proyecto aw
Cada proyecto guarda su estado en archivos. Al abrir la sesión, un hook carga un resumen:
estado, tareas activas y últimas líneas del registro.

| Carpeta o archivo | Qué contiene | Quién lo escribe |
|---|---|---|
| `project.md`, `memory.md` | Identidad y hechos estables | Tú, a demanda |
| `state.md` | Resumen del estado | Automático (hook). No editar |
| `tasks/` | Pendientes, en curso y hechas, con prioridad P0 a P3 | `aw task` |
| `execution/decisions.md` | Decisiones con su motivo | `aw decide` |
| `execution/run_log.md`, `errors.md` | Historial y fallos | Automático (hooks) o `aw log` |
| `agents/`, `skills/`, `tools/` | Notas de qué agentes, skills y herramientas usa el proyecto | Tú, a demanda |
| `artifacts/` | Índice de lo producido | Automático (`aw sync`) |
| `sop/` | Procedimientos del proyecto | Tú, a demanda |

## Protocolo
1. Al empezar, usa el resumen que cargó el hook. No releas todos los archivos.
2. Trabajo nuevo: `aw task add "título" --prio P1`. Al empezar: `aw task start T-001`. Al terminar: `aw task done T-001`.
3. Cada decisión que cambie el rumbo: `aw decide "título" --why "motivo"` (`--alt` para alternativas descartadas).
4. Notas sueltas del historial: `aw log "texto"`.
5. No edites a mano `state.md`, `run_log.md`, `errors.md`, `tool_usage.md` ni `tool_state.json`.
6. Los archivos de `sop/` se leen solo cuando la tarea los necesita.

## Agentes, skills y herramientas
Los agentes y skills propios viven en `@@ROOT@@/agents/` y `@@ROOT@@/skills/`, no en el proyecto.
El proyecto solo indica cuáles usa: `agents/assigned_agents.md` y `skills/assigned_skills.md`
(tarea → archivo). Para usar uno, lee el archivo indicado y sigue sus instrucciones. Los datos
del negocio están en `agents/agent_context.md` y `skills/skill_context.md`. No cargues el resto
del arsenal. Las herramientas y conectores del proyecto figuran en `tools/assigned_tools.md`.

## Límites
- `aw task`, `aw decide` y `aw log` solo escriben dentro del proyecto actual.
- Si el CLAUDE.md global no declara la excepción aw, pide confirmación también para esos comandos.
