# Arranque
<!-- Qué ocurre al abrir una sesión en un proyecto aw. Describe lo que el sistema ya hace; no lo repitas en otro archivo. Completa solo los pasos propios que añadas. -->

## Lo que aw hace solo
- El hook `SessionStart` carga el estado, las tareas en curso y las últimas líneas del registro. Está declarado en el `.claude/settings.json` de cada proyecto.
- Claude Code carga los `CLAUDE.md`: el global, el del workspace y el del proyecto.

## Pasos propios al arrancar
- (completar) por ejemplo: revisar el índice de proyectos antes de elegir en cuál trabajar.
