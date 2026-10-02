# Agentic Workspace

Proyecto de scripts en Python para creacion de entorno de carpetas para trabajar con agentes IA

---

## Requisitos

* Python 3 instalado
* Git instalado

Verificar instalación:

```bash
python3 --version
git --version
```

---

## Dependencias

Este proyecto no requiere librerías externas ni paquetes adicionales.

Una instalación estándar de Python 3 es suficiente para ejecutarlo.

---

## Instalación

Clonar el repositorio:

```bash
git clone https://github.com/Scrambledeggs-ai/agentic-workspace.git
```

Entrar al directorio del proyecto:

```bash
cd agentic-workspace
```

---

## Estructura del proyecto

```text
agentic-workspace/
├── generate.py       menú, comandos, hooks, sync y diagnóstico (un solo archivo)
├── structure.json    esquema de carpetas y archivos del workspace
├── templates/        contenido inicial de los archivos del esquema
├── tests/            pruebas (solo biblioteca estándar)
├── .gitignore
└── README.md
```

---

## Ejecución

Todo el sistema se maneja desde un menú, no hace falta recordar comandos ni tocar carpetas a mano:

```bash
python3 generate.py
```

Esto muestra un menú con dos secciones:

* **Proyectos**: crear un proyecto nuevo, ver el estado de los existentes, ver tareas pendientes y bitácora de decisiones.
* **Sistema**: crear/actualizar la estructura de carpetas, y ver o crear agentes, skills y herramientas.

La lista de agentes, skills y herramientas se arma escaneando esas carpetas en el momento — no hay un archivo de registro que mantener a mano. Alcanza con crear un elemento nuevo desde el menú (o agregar un `.md` con el mismo formato de encabezado) para que aparezca automáticamente.

### Instalar el comando `aw`

Desde el menú, la opción **9) Instalar comando 'aw' en el sistema** copia un wrapper a `~/.local/bin/aw`, para poder abrir el menú desde cualquier carpeta escribiendo:

```bash
aw
```

Disponible por ahora solo en Linux/Mac. Si `~/.local/bin` no está en tu `PATH`, el instalador te indica la línea a agregar en `~/.bashrc` o `~/.zshrc`.

### Actualizar aw

La opción **12) Actualizar aw desde su repositorio** del menú, o el comando:

```bash
aw update --dry-run
```

```bash
aw update
```

`aw update` consulta el repositorio del que se clonó aw, muestra los commits nuevos, los aplica y ejecuta `aw sync` con la versión nueva. Con `--dry-run` solo muestra si hay novedades. Nunca mezcla ni descarta nada: se niega si la carpeta de aw tiene cambios locales sin guardar, si tiene commits propios que el repositorio no tiene, si la rama actual no sigue a una rama remota o si aw no se instaló con `git clone` (en ese caso hay que reemplazar los archivos a mano). Los archivos sin seguimiento de git no lo impiden.

---

## Descripción

Este proyecto contiene un menú en Python para generar y manejar la estructura de un workspace de trabajo con agentes de IA, usando la configuración definida en `structure.json`.

---

## Que el sistema se escriba y se lea solo

Cada proyecto creado con aw lleva su estado en archivos, y Claude Code los usa así:

* **Al abrir una sesión**, un hook (`SessionStart`) carga un resumen: estado, tareas en curso y últimas líneas del registro.
* **Mientras se trabaja**, otros hooks anotan solos los commits, los fallos de herramientas (sin comandos completos ni secretos), las compactaciones y el resumen de cada sesión.
  Los commits se leen del historial de git (reflog), no del texto del comando: cuentan los commits, merges, cherry-picks y reverts hechos durante la sesión, y no un cambio de rama, un `reset` ni un `--dry-run`. Se consulta después de cada comando que menciona `git`.
* **Lo que exige criterio** se registra con comandos de formato fijo (`aw task`, `aw decide`, `aw log`).
* **Al terminar un turno**, si en la sesión hubo commits y no se registró ninguna decisión ni se movió ninguna tarea, un hook (`Stop`) lo avisa una sola vez. El aviso se muestra a quien usa Claude Code, no al modelo: los hooks de aw nunca bloquean el cierre del turno, así que registrar o no queda a criterio de la persona.
* **El estado** (`state.md`) se genera solo a partir de las tareas y el registro. El archivo generado lleva una línea de marca (`<!-- aw:auto — ... -->`): mientras esa línea esté, cualquier texto agregado a mano se pierde en la siguiente regeneración. Para llevar el estado a mano hay que quitar esa línea; desde entonces aw no lo sobrescribe.
* **`core/` y `memory/`** se crean con un formato base para completar a mano (configuración, arranque, enrutamiento, política de memoria, memoria global). Los que solo remiten a otra fuente lo dicen en vez de duplicar contenido. `aw doctor` cuenta los campos `(completar)` que faltan.
* **El índice de proyectos** del workspace (`memory/projects/project_index.md` y `memory/context_index.json`) lo regenera aw al sincronizar y al cerrar cada sesión: proyecto, estado y última actividad.

Los hooks se declaran en `.claude/settings.json` de cada proyecto, que se crea desde `templates/`. Nunca bloquean ni interrumpen la sesión: si algo falla, lo anotan en `logs/debug.md`.

### Comandos

| Comando | Qué hace |
|---|---|
| `aw` | Abre el menú |
| `aw init` | Crea o actualiza la estructura del workspace (nunca sobrescribe; solo rellena archivos vacíos) |
| `aw project new NOMBRE --desc "texto"` | Crea un proyecto desde la plantilla |
| `aw project import RUTA [--name NOMBRE] [--dry-run] [--yes]` | Mueve una carpeta que ya existe a `projects/`, la sincroniza y la diagnostica. Pide escribir el nombre del proyecto para confirmar |
| `aw task add "título" --prio P1` | Agrega una tarea (P0 urgente, P1 alta, P2 normal, P3 baja) |
| `aw task start T-001` / `aw task done T-001` | Pasa la tarea a en curso / hecha |
| `aw task list [--all]` | Lista las tareas |
| `aw decide "título" --why "motivo" [--alt "alternativas"]` | Registra una decisión; sin motivo no se registra |
| `aw log "texto"` | Agrega una nota al registro de ejecución |
| `aw state` | Regenera y muestra `state.md` |
| `aw sync [proyecto...] [--dry-run] [--workspace]` | Lleva a los proyectos lo nuevo de la plantilla: solo crea lo que falta, respalda y agrega, nunca reemplaza. Actualiza el `CLAUDE.md` del workspace si nadie lo modificó; con `--workspace` lo actualiza aunque tenga cambios propios (respaldando antes). Si un proyecto es un repo git y `sync` le añadió archivos de aw sin ignorar, lo avisa |
| `aw unsync NOMBRE [--dry-run] [--yes]` | Deshace la sincronización de un proyecto migrado: borra los archivos que creó aw, solo si siguen sin cambios. Si alguno tiene cambios, avisa y no borra nada. Nunca toca lo que existía antes |
| `aw update [--dry-run]` | Actualiza aw desde el repositorio del que se clonó (solo como avance directo, sin mezclar) y sincroniza los proyectos con la versión nueva |
| `aw doctor [proyecto...]` | Diagnóstico: estructura, archivos vacíos, hooks, permisos, referencias a agentes, skills y herramientas, y, si el proyecto está en un repo git, qué archivos de aw no están ignorados (un `git add .` los incluiría) o ya están versionados, con las líneas para ignorarlos solo en local (`.git/info/exclude`) |

### Migrar un proyecto que ya existe

Con un solo comando, que mueve la carpeta a `projects/`, la sincroniza y muestra el diagnóstico:

```bash
aw project import RUTA --dry-run
```

```bash
aw project import RUTA
```

Antes de mover avisa de lo que cambia con la ruta: un `venv` deja de funcionar y hay que crearlo de nuevo, una carpeta que estaba dentro de otro repositorio git queda allí como borrada, y la memoria y las sesiones de Claude Code de la ruta anterior no acompañan a la carpeta. Se niega si ya existe un proyecto con ese nombre (`--name` permite elegir otro) o si la carpeta está en otro disco: en ese caso hay que moverla a mano. La ruta de origen queda anotada en `MIGRACION.md`.

También se puede hacer por pasos. Mueve la carpeta a `projects/` y sincronízala por su nombre:

```bash
aw sync NOMBRE --dry-run
```

```bash
aw sync NOMBRE
```

```bash
aw doctor NOMBRE
```

`aw sync` crea solo lo que falta y nunca reemplaza un archivo que ya tiene contenido: si el proyecto trae su propio `CLAUDE.md`, `memory.md` o archivos en `.claude/`, quedan como estaban. La única excepción es un `.claude/settings.json` que ya exista: aw le agrega sus hooks y permisos y guarda un respaldo al lado. Al convertir la carpeta en proyecto, además:

* escribe `MIGRACION.md` en la raíz, con el estado inicial de la carpeta y la lista de los archivos que creó;
* deja una entrada en el registro de ejecución;
* pone en `project.md` una fecha de inicio estimada: la del primer commit o, si no hay git, la del archivo más antiguo. Conviene revisarla.

Si el proyecto es un repositorio git, `aw doctor NOMBRE` da las líneas para que git ignore lo que agregó aw, ahora o cuando se cree el repositorio. Las da archivo por archivo, sin carpetas enteras, para que lo que se agregue después en `artifacts/` o `tasks/` siga a la vista de git.

#### Deshacer una migración

```bash
aw unsync NOMBRE --dry-run
```

```bash
aw unsync NOMBRE
```

`aw unsync` usa la lista de `MIGRACION.md` para borrar lo que creó aw y dejar la carpeta como estaba. Solo borra un archivo si sigue como lo dejó aw:

* los archivos de estado que aw escribe solo (`state.md` mientras sea automático, `context_index.json`, `errors.md`, el uso de herramientas) siempre se pueden borrar;
* los que se crean desde la plantilla (`project.md`, `memory.md`, `CLAUDE.md`, `sop/`, `.claude/settings.json`, etc.) deben ser iguales a la plantilla actual, sin contar las fechas ni los bloques que aw regenera;
* las tareas, las decisiones y el registro no deben tener nada escrito con `aw task`, `aw decide` o `aw log`. Las entradas que anotan los hooks (sesiones, commits, compactaciones) no cuentan.

Si algún archivo tiene cambios, el comando los lista y no borra nada: hay que revisarlos y, si ya no hacen falta, borrarlos a mano y repetir. Un archivo sin tocar que viene de una plantilla anterior también figura como cambiado. Lo que existía antes de la migración no se toca nunca; un `.claude/settings.json` propio conserva los hooks de aw, y el comando indica el respaldo para restaurarlo a mano. Tampoco toca git: avisa si algún archivo borrado estaba versionado.

Un proyecto creado con `aw project new` no tiene ficha, así que `aw unsync` no actúa sobre él. Y como todo lo que está en `projects/` es un proyecto aw, después de deshacer conviene sacar la carpeta de ahí: el siguiente `aw sync` sin nombres la volvería a convertir. El comando indica cómo devolverla a su ubicación anterior si la conoce.

La plantilla de proyectos (`projects/template_project`) solo lleva archivos `.md` y `.json`: son los únicos que aw interpreta. Cualquier otro archivo que se ponga ahí se ignora, tanto al crear un proyecto como al sincronizar.

Los comandos de tareas, decisiones y notas actúan sobre el proyecto de la carpeta actual (o el indicado con `--project`) y solo escriben dentro de él. Desde dentro de un proyecto, `--project` no permite escribir en otro: para eso hay que ejecutar el comando desde ese proyecto o desde fuera de un proyecto.

### Pruebas

```bash
python3 -m unittest discover -s tests -v
```

Cada prueba usa un workspace temporal (`AW_HOME`), así que no toca el workspace real.

---

## Documentación

Manual de uso: [Agentic Workspace — manual](https://claude.ai/code/artifact/74ecf23d-4272-42a7-94ae-eeecfc6f13ca)

---

## Flujo básico de Git

Guardar cambios:

```bash
git add .
git commit -m "describe changes"
```

Subir cambios a GitHub:

```bash
git push
```

Actualizar el repositorio local:

```bash
git pull
```

---

## Buenas prácticas

* Mantener actualizado este README cuando cambie la funcionalidad del proyecto.
* Utilizar mensajes de commit descriptivos.
* No subir credenciales, tokens ni información sensible.
* Mantener `.gitignore` actualizado para excluir archivos temporales y locales.
* Realizar commits pequeños y frecuentes.

---

## Licencia

MIT. Ver [LICENSE](LICENSE).

---

## Autor

Scrambledeggs-ai
