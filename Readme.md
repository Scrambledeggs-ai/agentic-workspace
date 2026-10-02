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

---

## Descripción

Este proyecto contiene un menú en Python para generar y manejar la estructura de un workspace de trabajo con agentes de IA, usando la configuración definida en `structure.json`.

---

## Que el sistema se escriba y se lea solo

Cada proyecto creado con aw lleva su estado en archivos, y Claude Code los usa así:

* **Al abrir una sesión**, un hook (`SessionStart`) carga un resumen: estado, tareas en curso y últimas líneas del registro.
* **Mientras se trabaja**, otros hooks anotan solos los commits, los fallos de herramientas (sin comandos completos ni secretos), las compactaciones y el resumen de cada sesión.
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
| `aw task add "título" --prio P1` | Agrega una tarea (P0 urgente, P1 alta, P2 normal, P3 baja) |
| `aw task start T-001` / `aw task done T-001` | Pasa la tarea a en curso / hecha |
| `aw task list [--all]` | Lista las tareas |
| `aw decide "título" --why "motivo" [--alt "alternativas"]` | Registra una decisión; sin motivo no se registra |
| `aw log "texto"` | Agrega una nota al registro de ejecución |
| `aw state` | Regenera y muestra `state.md` |
| `aw sync [proyecto...] [--dry-run] [--workspace]` | Lleva a los proyectos lo nuevo de la plantilla: solo crea lo que falta, respalda y agrega, nunca reemplaza. Actualiza el `CLAUDE.md` del workspace si nadie lo modificó; con `--workspace` lo actualiza aunque tenga cambios propios (respaldando antes). Si un proyecto es un repo git y `sync` le añadió archivos de aw sin ignorar, lo avisa |
| `aw doctor [proyecto...]` | Diagnóstico: estructura, archivos vacíos, hooks, permisos, referencias a agentes, skills y herramientas, y, si el proyecto está en un repo git, qué archivos de aw no están ignorados (un `git add .` los incluiría) o ya están versionados, con las líneas para ignorarlos solo en local (`.git/info/exclude`) |

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
