# Registro de cambios

Los cambios de cada versión, del más reciente al más antiguo. Las versiones siguen el formato mayor.menor.parche.

## [Sin publicar]

### Cambiado
- El resumen de inicio de sesión y `state.md` ya no muestran las aperturas, cierres y compactaciones de sesión
  (siguen en el registro), y el resumen no repite las líneas de «Última actividad» en «Registro reciente».
- `aw task add`, `start` y `done` dejan una línea `[tarea]` en el registro de ejecución.
- README: descripción, arranque rápido y ejemplo del resumen de inicio; se quitan «Flujo básico de Git» y
  «Buenas prácticas». Nuevo `README.en.md`, un resumen en inglés.

## [2.0.0] — 2026-10-02

Primera versión con etiqueta. La versión que estaba publicada antes en GitHub no tenía número; se considera la
1.0.0. Es un cambio de versión mayor porque modifica el comportamiento en proyectos que ya existen: cómo se
detectan los commits, qué archivos de la plantilla se leen y qué lleva el `CLAUDE.md` de cada proyecto. Después de
actualizar, ejecuta `aw sync` para llevar los cambios a tus proyectos.

### Añadido
- `aw project import RUTA`: mueve una carpeta a `projects/`, la sincroniza y muestra el diagnóstico.
- `aw unsync NOMBRE`: deshace una migración y borra solo lo que creó aw, si sigue sin cambios.
- `aw update` y la opción 12 del menú: actualizan aw desde el repositorio del que se clonó, solo como avance
  directo, y sincronizan los proyectos con la versión nueva.
- `aw sync` deja constancia de cada migración en `MIGRACION.md`: estado inicial, archivos creados por aw, entrada
  en el registro y fecha de inicio estimada.
- `aw doctor` da, archivo por archivo, las líneas para que git ignore lo que agregó aw.
- Integración continua con Python 3.10 y 3.13 en Linux y macOS.
- `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`, `SECURITY.md` y este registro de cambios.

### Cambiado
- Los commits de la sesión se leen del historial de git (reflog) en vez del texto del comando: cuentan los
  merges, cherry-picks y reverts, y no un `--dry-run`, un `--help` ni un cambio de rama.
- `sync` y `doctor` solo consideran los `.md` y `.json` de la plantilla.
- El `CLAUDE.md` de cada proyecto ya no lleva la ruta del workspace.
- Textos del menú en español neutro.

### Corregido
- `redact` oculta contraseñas de URLs que llevan `/` o `@` y valores con comillas escapadas.
- El instalador pregunta antes de reemplazar otro programa llamado `aw`.
- Al archivar un mes que ya tenía archivo, no se repite la cabecera.
- El menú sale sin traza con Ctrl-C, Ctrl-D o sin terminal.
- `doctor` reconoce agentes y skills asignados con ruta desde la raíz o entre comillas invertidas.

## [1.0.0] — 2026-10-02

Publicada sin etiqueta (commit `ef6a9e5`). El sistema base: menú, proyectos desde una plantilla, tareas,
decisiones y registro con comandos de formato fijo, seis hooks de Claude Code, `aw sync` y `aw doctor`.
