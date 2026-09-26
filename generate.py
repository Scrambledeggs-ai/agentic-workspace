import argparse
import contextlib
import datetime
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import time

try:
    import fcntl
except ImportError:  # Windows: sin bloqueo entre procesos (el instalador tampoco lo soporta todavía)
    fcntl = None

HERE = os.path.dirname(os.path.abspath(__file__))
STRUCTURE_FILE = os.path.join(HERE, "structure.json")
TEMPLATES_DIR = os.environ.get("AW_TEMPLATES") or os.path.join(HERE, "templates")
WRAPPER_NAME = "aw"


def find_root():
    # Raíz del workspace, separada del código: AW_HOME si está definida; si no,
    # dos niveles arriba cuando el script vive en <raíz>/projects/<nombre>/ y
    # <raíz>/projects/template_project existe; si no, la carpeta del script.
    env = os.environ.get("AW_HOME")
    if env:
        return os.path.abspath(os.path.expanduser(env))
    projects_dir = os.path.dirname(HERE)
    if os.path.isdir(os.path.join(projects_dir, "template_project")):
        return os.path.dirname(projects_dir)
    return HERE


ROOT = find_root()

# Encabezados por defecto para los archivos de agents/, skills/ y tools/
# que ya vienen definidos en structure.json, para que aparezcan con
# nombre y descripción apenas se crea la estructura.
DEFAULT_HEADERS = {
    "agents/base_agent.md": ("Base Agent", "Definición base compartida por todos los agentes del sistema."),
    "agents/research_agent.md": ("Research Agent", "Agente especializado en investigación y búsqueda de información."),
    "agents/coding_agent.md": ("Coding Agent", "Agente especializado en generación y edición de código."),
    "agents/planning_agent.md": ("Planning Agent", "Agente especializado en planificación y desglose de tareas."),
    "skills/git_skill.md": ("Git Skill", "Skill para manejo de control de versiones con git."),
    "skills/coding_skill.md": ("Coding Skill", "Skill para tareas de programación y edición de código."),
    "skills/web_research_skill.md": ("Web Research Skill", "Skill para búsqueda e investigación en la web."),
    "skills/memory_skill.md": ("Memory Skill", "Skill para lectura y escritura de memoria del sistema."),
    "tools/filesystem_tool.md": ("Filesystem Tool", "Herramienta para operaciones sobre archivos y carpetas."),
    "tools/web_tool.md": ("Web Tool", "Herramienta para consultas y peticiones web."),
    "tools/executor_tool.md": ("Executor Tool", "Herramienta para ejecución de comandos y scripts."),
}

BANNER = """
==================================
        AGENTIC WORKSPACE
==================================
"""

MENU = """
-- Proyectos --
1) Crear nuevo proyecto
2) Ver mis proyectos y su estado
3) Ver tareas pendientes de un proyecto
4) Ver bitácora de decisiones de un proyecto

-- Sistema --
5) Iniciar / actualizar estructura del sistema
6) Agentes disponibles
7) Skills disponibles
8) Herramientas disponibles

9) Instalar comando 'aw' en el sistema
10) Diagnóstico de proyectos
11) Sincronizar proyectos con la plantilla
0) Salir
"""

# Marca que identifica un state.md generado automáticamente. Si no está, el
# archivo tiene texto manual y no se sobrescribe.
MARK_AUTO = "<!-- aw:auto — este archivo se regenera solo; no editar a mano -->"
AUTO_START = "<!-- aw:auto:inicio -->"
AUTO_END = "<!-- aw:auto:fin -->"

PRIO_ORDER = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}
TASK_RE = re.compile(r"^- \[( |x)\] (T-\d+) \[(P[0-3])\] (.*)$")
DATE_SUFFIX_RE = re.compile(r"(\s*\((?:creada|iniciada|hecha) \d{4}-\d{2}-\d{2}\))+\s*$")
GIT_COMMIT_RE = re.compile(r"(^|[;&|]\s*)git\s+(?:(?:-[cC]\s+\S+|--\S+)\s+)*commit(\s|$)")

HOOK_EVENTS = ("session-start", "post-tool", "tool-failure", "pre-compact", "stop", "session-end")

ARTIFACT_INDEX_FILES = ("outputs.md", "code_snippets.md", "assets_index.md")
ASSET_EXT = {".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".ico", ".mp4", ".mov", ".mp3", ".wav", ".fig"}


class AwError(Exception):
    pass


def make_header(name, description):
    return f"---\nname: {name}\ndescription: {description}\n---\n\n"


def read_header(filepath):
    try:
        with open(filepath, "r") as f:
            lines = f.read().splitlines()
    except (FileNotFoundError, IsADirectoryError):
        return None, None
    if not lines or lines[0].strip() != "---":
        return None, None
    name, desc = None, None
    for line in lines[1:]:
        if line.strip() == "---":
            break
        if line.lower().startswith("name:"):
            name = line.split(":", 1)[1].strip()
        elif line.lower().startswith("description:"):
            desc = line.split(":", 1)[1].strip()
    return name, desc


# -- Utilidades de archivos y fechas --

def today():
    return datetime.date.today().isoformat()


def now_str():
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M")


def read_text(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except (FileNotFoundError, IsADirectoryError):
        return ""


def write_text(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = f"{path}.{os.getpid()}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, path)


def append_text(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    existing = read_text(path)
    with open(path, "a", encoding="utf-8") as f:
        if existing and not existing.endswith("\n"):
            f.write("\n")
        f.write(text)


# -- Plantillas --

def machine_vars():
    script = os.path.abspath(__file__)
    return {"ROOT": ROOT, "SCRIPT": script, "AW_CMD": f'python3 "{script}"'}


def project_vars(name, description=""):
    variables = machine_vars()
    variables.update({"PROJECT": name, "DESCRIPTION": description or "(completar)", "DATE": today()})
    return variables


def render(text, variables, json_safe=False):
    # Sustituye @@VARIABLE@@; las variables desconocidas se dejan intactas.
    def sub(match):
        key = match.group(1)
        if key not in variables:
            return match.group(0)
        value = str(variables[key])
        return json.dumps(value)[1:-1] if json_safe else value

    return re.sub(r"@@([A-Z_]+)@@", sub, text)


def template_content(relpath, variables):
    path = os.path.join(TEMPLATES_DIR, *relpath.split("/"))
    if not os.path.isfile(path):
        return None
    return render(read_text(path), variables, json_safe=relpath.endswith(".json"))


WS_MARK_RE = re.compile(r"<!-- aw:plantilla sha256=([0-9a-f]{64}) -->\n?\Z")


def sha256_text(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def workspace_template_body():
    return template_content("CLAUDE.md", machine_vars())


def workspace_claude_md():
    # El CLAUDE.md del workspace lleva al final la huella de la plantilla que lo generó:
    # así se sabe si alguien lo modificó y se puede actualizar sin perder cambios propios.
    body = workspace_template_body()
    return None if body is None else body + f"<!-- aw:plantilla sha256={sha256_text(body)} -->\n"


def split_marker(text):
    match = WS_MARK_RE.search(text)
    return (text[:match.start()], match.group(1)) if match else (text, None)


def backup_file(path):
    dest = f"{path}.bak-{datetime.datetime.now().strftime('%Y%m%d-%H%M%S')}"
    shutil.copy2(path, dest)
    return dest


def first_line(text):
    return next((line.strip() for line in text.splitlines() if line.strip()), "")


def ensure_workspace_claude_md(dry_run=False, force=False):
    # Devuelve (acción, detalle). Acción: None (al día o sin plantilla), "crear", "marcar",
    # "actualizar", "difiere" (tiene cambios propios o es una versión anterior sin huella) o
    # "ajeno" (no es el del workspace aw: sin huella y con otra primera línea; no se toca nunca).
    body = workspace_template_body()
    if body is None:
        return None, ""
    desired = workspace_claude_md()
    path = os.path.join(ROOT, "CLAUDE.md")
    current = read_text(path)
    if not current.strip():
        if not dry_run:
            write_text(path, desired)
        return "crear", "se crearía" if dry_run else "creado"
    current_body, digest = split_marker(current)
    if digest is None and first_line(current) != first_line(body):
        return "ajeno", ""
    if current_body == body:
        if digest is None:
            if not dry_run:
                write_text(path, desired)
            return "marcar", "igual a la plantilla; se le añadiría la huella" if dry_run else "igual a la plantilla; se le añadió la huella"
        return None, ""
    if (digest is not None and sha256_text(current_body) == digest) or force:
        if dry_run:
            return "actualizar", "se aplicaría la plantilla nueva (con respaldo previo)"
        backup = backup_file(path)
        write_text(path, desired)
        return "actualizar", f"plantilla nueva aplicada (respaldo: {os.path.basename(backup)})"
    return "difiere", ""


def build(path, node, rel=""):
    if not isinstance(node, dict):
        return

    os.makedirs(path, exist_ok=True)
    variables = machine_vars()

    for filename in node.get("files", []):
        filepath = os.path.join(path, filename)
        relpath = os.path.join(rel, filename).replace(os.sep, "/")
        exists = os.path.exists(filepath)
        if exists and os.path.getsize(filepath) > 0:
            continue
        content = workspace_claude_md() if relpath == "CLAUDE.md" else template_content(relpath, variables)
        if not exists:
            if content is None and relpath in DEFAULT_HEADERS:
                name, desc = DEFAULT_HEADERS[relpath]
                content = make_header(name, desc)
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(content or "")
        elif content is not None:
            # Archivo existente pero vacío: se rellena con su plantilla.
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(content)

    for folder_name, folder_content in node.get("folders", {}).items():
        folder_path = os.path.join(path, folder_name)
        os.makedirs(folder_path, exist_ok=True)
        build(folder_path, folder_content, os.path.join(rel, folder_name))

    for key, value in node.items():
        if key in ["files", "folders"]:
            continue
        subdir = os.path.join(path, key)
        os.makedirs(subdir, exist_ok=True)
        build(subdir, value, os.path.join(rel, key))


def load_structure():
    with open(STRUCTURE_FILE, "r") as f:
        return json.load(f)


def action_init():
    structure = load_structure()
    build(ROOT, structure)
    print("Estructura creada / actualizada. Los archivos ya existentes no se tocaron.")
    action, detail = ensure_workspace_claude_md()
    if action in ("actualizar", "marcar"):
        print(f"CLAUDE.md del workspace: {detail}.")
    elif action == "difiere":
        print("CLAUDE.md del workspace: difiere de la plantilla. Usa 'aw sync --workspace' para actualizarlo (se respalda antes).")
    elif action == "ajeno":
        print("CLAUDE.md de la raíz: no es el del workspace aw (sin huella y con otra primera línea); no se gestiona.")


# -- Registro dinámico de agentes / skills / tools --

def list_registry(folder):
    dirpath = os.path.join(ROOT, folder)
    if not os.path.isdir(dirpath):
        print("No existe la carpeta todavía. Corré primero 'Iniciar / actualizar estructura del sistema'.")
        return
    entries = sorted(f for f in os.listdir(dirpath) if f.endswith(".md"))
    if not entries:
        print("No hay elementos todavía.")
        return
    for filename in entries:
        name, desc = read_header(os.path.join(dirpath, filename))
        label = name or filename
        print(f"- {label}: {desc or '(sin descripción)'}  [{filename}]")


def create_registry_item(folder):
    dirpath = os.path.join(ROOT, folder)
    os.makedirs(dirpath, exist_ok=True)
    name = input("Nombre: ").strip()
    if not name:
        print("Nombre vacío, se cancela.")
        return
    description = input("Descripción breve: ").strip()
    filename = name.lower().replace(" ", "_") + ".md"
    filepath = os.path.join(dirpath, filename)
    if os.path.exists(filepath):
        print("Ya existe un archivo con ese nombre.")
        return
    with open(filepath, "w") as f:
        f.write(make_header(name, description))
    print(f"Creado: {folder}/{filename}")


def registry_menu(label, folder):
    while True:
        print(f"\n-- {label} --")
        print("a) Ver disponibles")
        print("b) Crear nuevo")
        print("c) Volver")
        choice = input("Elegí una opción: ").strip().lower()
        if choice == "a":
            print()
            list_registry(folder)
        elif choice == "b":
            create_registry_item(folder)
        elif choice == "c":
            return
        else:
            print("Opción inválida.")


# -- Proyectos --

def list_projects():
    projects_dir = os.path.join(ROOT, "projects")
    if not os.path.isdir(projects_dir):
        return []
    return sorted(
        p for p in os.listdir(projects_dir)
        if p != "template_project" and os.path.isdir(os.path.join(projects_dir, p))
    )


def summary_line(filepath):
    if not os.path.exists(filepath):
        return "(sin datos)"
    with open(filepath) as f:
        for line in f:
            line = line.strip()
            if line:
                return line
    return "(vacío)"


def render_tree(root_dir, variables):
    for dirpath, _dirs, files in os.walk(root_dir):
        for fname in files:
            if not fname.endswith((".md", ".json")):
                continue
            fpath = os.path.join(dirpath, fname)
            text = read_text(fpath)
            new = render(text, variables, json_safe=fname.endswith(".json"))
            if new != text:
                write_text(fpath, new)


def create_project(name, description=""):
    name = (name or "").strip()
    if not name or os.sep in name or name.startswith(".") or name == "template_project":
        raise AwError("Nombre de proyecto inválido.")
    template = os.path.join(ROOT, "projects", "template_project")
    if not os.path.isdir(template):
        raise AwError("No existe template_project. Ejecuta primero 'Iniciar / actualizar estructura del sistema' (aw init).")
    target = os.path.join(ROOT, "projects", name)
    if os.path.exists(target):
        raise AwError("Ya existe un proyecto con ese nombre.")
    shutil.copytree(template, target, ignore=shutil.ignore_patterns("*.bak-*"))
    render_tree(target, project_vars(name, description))
    if not read_text(os.path.join(target, "project.md")).strip():
        write_text(os.path.join(target, "project.md"), f"# {name}\n\n{description}\n")
    log_event(target, "nota", "proyecto creado")
    refresh_state(target)
    try:
        refresh_workspace_index()
    except OSError:
        pass
    return target


def action_new_project():
    template = os.path.join(ROOT, "projects", "template_project")
    if not os.path.isdir(template):
        print("No existe template_project. Corré primero 'Iniciar / actualizar estructura del sistema'.")
        return
    name = input("Nombre del proyecto: ").strip()
    if not name:
        print("Nombre vacío, se cancela.")
        return
    description = input("Descripción breve (opcional): ").strip()
    try:
        create_project(name, description)
    except AwError as exc:
        print(exc)
        return
    print(f"Proyecto creado: projects/{name}")


def action_list_projects():
    projects = list_projects()
    if not projects:
        print("No hay proyectos todavía. Creá uno desde la opción 1.")
        return
    for name in projects:
        state_file = os.path.join(ROOT, "projects", name, "state.md")
        print(f"- {name}: {summary_line(state_file)}")


def choose_project():
    projects = list_projects()
    if not projects:
        print("No hay proyectos todavía. Creá uno desde la opción 1.")
        return None
    for i, name in enumerate(projects, 1):
        print(f"{i}) {name}")
    choice = input("Elegí un proyecto (número): ").strip()
    if not choice.isdigit() or not (1 <= int(choice) <= len(projects)):
        print("Opción inválida.")
        return None
    return projects[int(choice) - 1]


def show_project_file(relparts, empty_msg):
    name = choose_project()
    if not name:
        return
    filepath = os.path.join(ROOT, "projects", name, *relparts)
    print(f"\n-- {'/'.join(relparts)} de {name} --\n")
    content = ""
    if os.path.exists(filepath):
        with open(filepath) as f:
            content = f.read().strip()
    print(content if content else empty_msg)


def action_view_tasks():
    show_project_file(("tasks", "active.md"), "Sin tareas activas registradas.")


def action_view_decisions():
    show_project_file(("execution", "decisions.md"), "Sin decisiones registradas todavía.")


# -- Proyecto actual y registro (base de los comandos y de los hooks) --

def is_project_dir(path):
    return os.path.isfile(os.path.join(path, "state.md")) and os.path.isdir(os.path.join(path, "tasks"))


def find_project(start=None):
    path = os.path.abspath(start or os.getcwd())
    while True:
        if is_project_dir(path):
            return path
        parent = os.path.dirname(path)
        if parent == path:
            return None
        path = parent


def check_project_name(name):
    if not name or os.sep in name or name.startswith("."):
        raise AwError("Nombre de proyecto inválido.")


def resolve_project(name=None):
    if name:
        check_project_name(name)
        path = os.path.join(ROOT, "projects", name)
        if not os.path.isdir(path):
            raise AwError(f"No existe el proyecto '{name}'.")
    else:
        path = find_project()
        if not path:
            raise AwError("No se está dentro de un proyecto aw (carpeta con state.md y tasks/). Usa --project NOMBRE.")
    if os.path.basename(path) == "template_project":
        raise AwError("template_project es la plantilla, no un proyecto: no se modifica desde estos comandos.")
    return path


def pj(project, *parts):
    return os.path.join(project, *parts)


LOCK_TIMEOUT = 5
HELD_LOCKS = set()


@contextlib.contextmanager
def project_lock(project):
    # Bloqueo por proyecto entre procesos (flock sobre la carpeta, sin archivos) y reentrante dentro del proceso.
    key = os.path.abspath(project)
    if fcntl is None or key in HELD_LOCKS:
        yield
        return
    try:
        fd = os.open(key, os.O_RDONLY)
    except OSError:
        yield
        return
    try:
        deadline = time.monotonic() + LOCK_TIMEOUT
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise AwError("El proyecto está ocupado por otro proceso de aw. Inténtalo de nuevo.")
                time.sleep(0.02)
            except OSError:  # el sistema de archivos no admite flock: se sigue sin bloqueo
                break
        HELD_LOCKS.add(key)
        try:
            yield
        finally:
            HELD_LOCKS.discard(key)
    finally:
        os.close(fd)


def clean_title(title):
    return DATE_SUFFIX_RE.sub("", title).strip()


SENSITIVE_KEY = r"[\w.-]{0,64}(?:token|secret|passw(?:or)?d|pwd|api[_-]?key|access[_-]?key|private[_-]?key)[\w.-]{0,64}"
LONG_STRING_RE = re.compile(r"(?<![A-Za-z0-9+/_-])[A-Za-z0-9+/_-]{32,}={0,2}(?![A-Za-z0-9+/_-])")


def mask_long_string(match):
    value = match.group(0)
    # Con "/" o "+" solo se oculta si parece base64 (mayúscula, minúscula y dígito): así las rutas largas se conservan.
    if re.search(r"[/+]", value) and not all(re.search(p, value) for p in (r"[A-Z]", r"[a-z]", r"\d")):
        return value
    return "[oculto]"


def redact(text):
    text = re.sub(r"(?i)\b(authorization)[\"']?\s*[:=]\s*(?:\"[^\"]*\"|'[^']*'|(?:(?:bearer|basic)\s+)?\S+)", r"\1 [oculto]", text)
    text = re.sub(r"(?i)\b(bearer|basic)\s+\S+", r"\1 [oculto]", text)
    text = re.sub(r"(?i)(\b[a-z][a-z0-9+.-]*://)[^/\s:@]+:[^/\s@]+@", r"\1[oculto]@", text)
    text = re.sub(r"(?i)([?&](?:" + SENSITIVE_KEY + r"|key|sig|signature))=[^&\s#]+", r"\1=[oculto]", text)
    text = re.sub(r"(?i)\b(" + SENSITIVE_KEY + r")[\"']?\s*[=:]\s*(?!\[oculto\])(?:\"[^\"]*\"|'[^']*'|\S+)", r"\1 [oculto]", text)
    text = re.sub(r"\b(?:sk|pk|ghp|gho|xox[bpas])[-_][A-Za-z0-9_-]{16,}\b", "[oculto]", text)
    return LONG_STRING_RE.sub(mask_long_string, text)


def rotate_log(path, limit=400, keep=300):
    lines = read_text(path).splitlines()
    first_entry = next((i for i, line in enumerate(lines) if line.startswith("- ")), None)
    if first_entry is None:
        return
    head, entries = lines[:first_entry], lines[first_entry:]
    if len(entries) <= limit:
        return
    old, recent = entries[:-keep], entries[-keep:]
    archive = os.path.join(os.path.dirname(path), "run_log_archivo.md")
    if not os.path.exists(archive):
        write_text(archive, "# Archivo del registro de ejecución\n\n")
    append_text(archive, "\n".join(old) + "\n")
    write_text(path, "\n".join(head + recent) + "\n")


def log_event(project, kind, text):
    line = f"- {now_str()} [{kind}] {' '.join(str(text).split())}"
    path = pj(project, "execution", "run_log.md")
    with project_lock(project):
        append_text(path, line + "\n")
        rotate_log(path)


# -- Tareas --

def parse_tasks(text):
    tasks = []
    for line in text.splitlines():
        match = TASK_RE.match(line)
        if match:
            tasks.append({"done": match.group(1) == "x", "id": match.group(2), "prio": match.group(3), "title": match.group(4)})
    return tasks


def load_tasks(project, name):
    return parse_tasks(read_text(pj(project, "tasks", name)))


def next_task_id(project):
    highest = 0
    for name in ("backlog.md", "active.md", "done.md"):
        for task in load_tasks(project, name):
            highest = max(highest, int(task["id"].split("-")[1]))
    return f"T-{highest + 1:03d}"


def insert_task_line(text, line, prio):
    lines = text.splitlines()
    last_task = None
    for i, current in enumerate(lines):
        match = TASK_RE.match(current)
        if not match:
            continue
        last_task = i
        if PRIO_ORDER[match.group(3)] > PRIO_ORDER[prio]:
            lines.insert(i, line)
            return "\n".join(lines) + "\n"
    position = last_task + 1 if last_task is not None else len(lines)
    lines.insert(position, line)
    return "\n".join(lines) + "\n"


def take_task(text, task_id):
    lines = text.splitlines()
    for i, current in enumerate(lines):
        match = TASK_RE.match(current)
        if match and match.group(2) == task_id:
            del lines[i]
            return ("\n".join(lines) + "\n" if lines else ""), {"prio": match.group(3), "title": match.group(4)}
    return text, None


def normalize_task_id(task_id):
    match = re.fullmatch(r"(?i)t-?(\d+)", (task_id or "").strip())
    if not match:
        raise AwError("Identificador de tarea inválido. Usa el formato T-001.")
    return f"T-{int(match.group(1)):03d}"


def task_add(project, title, prio="P2"):
    title = " ".join((title or "").split())
    if not title:
        raise AwError("El título de la tarea está vacío.")
    prio = (prio or "P2").upper()
    if prio not in PRIO_ORDER:
        raise AwError("La prioridad debe ser P0, P1, P2 o P3.")
    path = pj(project, "tasks", "backlog.md")
    with project_lock(project):
        task_id = next_task_id(project)
        line = f"- [ ] {task_id} [{prio}] {title} (creada {today()})"
        write_text(path, insert_task_line(read_text(path), line, prio))
        refresh_state(project)
    return task_id, prio


# task_start y task_done escriben primero el destino y después quitan el origen: un corte a mitad
# deja la tarea duplicada, nunca perdida, y repetir el comando termina el movimiento sin duplicar.

def task_start(project, task_id):
    task_id = normalize_task_id(task_id)
    backlog_path = pj(project, "tasks", "backlog.md")
    active_path = pj(project, "tasks", "active.md")
    with project_lock(project):
        new_backlog, task = take_task(read_text(backlog_path), task_id)
        if any(t["id"] == task_id for t in load_tasks(project, "active.md")):
            if task is None:
                raise AwError(f"{task_id} ya está en curso.")
            write_text(backlog_path, new_backlog)  # copia que dejó un corte anterior
            refresh_state(project)
            return task
        if task is None:
            if any(t["id"] == task_id for t in load_tasks(project, "done.md")):
                raise AwError(f"{task_id} ya está hecha.")
            raise AwError(f"No existe {task_id} en los pendientes.")
        line = f"- [ ] {task_id} [{task['prio']}] {task['title']} (iniciada {today()})"
        write_text(active_path, insert_task_line(read_text(active_path), line, task["prio"]))
        write_text(backlog_path, new_backlog)
        refresh_state(project)
        return task


def task_done(project, task_id):
    task_id = normalize_task_id(task_id)
    with project_lock(project):
        task = None
        remaining = {}
        for name in ("active.md", "backlog.md"):
            path = pj(project, "tasks", name)
            new_text, found = take_task(read_text(path), task_id)
            if found is not None:
                task = task or found
                remaining[path] = new_text
        already_done = any(t["id"] == task_id for t in load_tasks(project, "done.md"))
        if task is None:
            raise AwError(f"{task_id} ya está hecha." if already_done else f"No existe {task_id}.")
        if not already_done:
            append_text(pj(project, "tasks", "done.md"), f"- [x] {task_id} [{task['prio']}] {task['title']} (hecha {today()})\n")
        for path, text in remaining.items():
            write_text(path, text)
        refresh_state(project)
        return task


# -- Decisiones --

def decide(project, title, why, alt=None):
    title = " ".join((title or "").split())
    why = " ".join((why or "").split())
    if not title:
        raise AwError("El título de la decisión está vacío.")
    if not why:
        raise AwError("Falta el motivo (--why): una decisión sin motivo no se registra.")
    block = f"\n## {today()} — {title}\n- Motivo: {why}\n"
    if alt and alt.strip():
        block += f"- Alternativas: {' '.join(alt.split())}\n"
    with project_lock(project):
        append_text(pj(project, "execution", "decisions.md"), block)
        log_event(project, "decisión", title)
        refresh_state(project)


def decision_titles(project):
    return re.findall(r"^## (.+)$", read_text(pj(project, "execution", "decisions.md")), re.M)


# -- Estado derivado --

def state_is_auto(text):
    stripped = text.strip()
    return (not stripped) or stripped == "Estado: iniciado" or any(line.strip() == MARK_AUTO for line in text.splitlines())


def log_entries(project):
    return [line for line in read_text(pj(project, "execution", "run_log.md")).splitlines() if line.startswith("- ")]


def build_state(project):
    active = load_tasks(project, "active.md")
    backlog = load_tasks(project, "backlog.md")
    done = load_tasks(project, "done.md")
    entries = log_entries(project)
    decisions = decision_titles(project)
    lines = [
        f"Estado: {len(active)} en curso · {len(backlog)} pendientes · {len(done)} hechas · actualizado {today()}",
        MARK_AUTO,
        "",
        "## En curso",
    ]
    lines += [f"- {t['id']} [{t['prio']}] {clean_title(t['title'])}" for t in active] or ["- (ninguna)"]
    lines += ["", "## Próximas (máx. 5)"]
    lines += [f"- {t['id']} [{t['prio']}] {clean_title(t['title'])}" for t in backlog[:5]] or ["- (ninguna)"]
    lines += ["", "## Última actividad"]
    lines += entries[-3:] or ["- (sin registro)"]
    lines += ["", "## Última decisión", f"- {decisions[-1]}" if decisions else "- (ninguna)"]
    return "\n".join(lines) + "\n"


def refresh_state(project):
    # Devuelve True si state.md es automático (y queda al día), False si tiene texto manual.
    path = pj(project, "state.md")
    with project_lock(project):
        current = read_text(path)
        if not state_is_auto(current):
            return False
        new = build_state(project)
        if new != current:
            write_text(path, new)
        return True


# -- Índices derivados --

def replace_block(path, body, header=None):
    # Reemplaza lo que hay entre las marcas aw:auto; el resto del archivo es del usuario.
    block = f"{AUTO_START}\n{body}\n{AUTO_END}"
    text = read_text(path)
    pattern = re.compile(re.escape(AUTO_START) + r".*?" + re.escape(AUTO_END), re.S)
    if pattern.search(text):
        new = pattern.sub(lambda _m: block, text)
    elif not text.strip() and header:
        new = header + block + "\n"
    else:
        new = text.rstrip("\n") + "\n\n" + block + "\n"
    if new != text:
        write_text(path, new)


def replace_auto_block(path, items, prefix):
    if not os.path.exists(path):
        return
    body = "\n".join(f"- `{prefix}/{item}`" for item in items) if items else "(sin archivos todavía)"
    replace_block(path, body)


# -- Índice de proyectos del workspace (memory/) --

INDEX_HEADER = ("# Índice de proyectos\n"
                "<!-- Lo que queda entre las marcas lo regenera aw (aw sync y el cierre de cada sesión); el resto es tuyo. -->\n\n")


def project_summary(name):
    path = os.path.join(ROOT, "projects", name)
    entries = log_entries(path)
    last = re.match(r"- (\d{4}-\d{2}-\d{2} \d{2}:\d{2})", entries[-1]) if entries else None
    return {
        "estado": summary_line(os.path.join(path, "state.md")),
        "en_curso": len(load_tasks(path, "active.md")),
        "pendientes": len(load_tasks(path, "backlog.md")),
        "ultima_actividad": last.group(1) if last else None,
    }


def refresh_workspace_index():
    data = {name: project_summary(name) for name in list_projects()}
    json_path = os.path.join(ROOT, "memory", "context_index.json")
    try:
        current = json.loads(read_text(json_path) or "{}")
    except ValueError:
        current = None  # JSON roto: no se toca
    if isinstance(current, dict) and current.get("proyectos") != data:
        payload = {"actualizado": now_str(), "proyectos": data}
        write_text(json_path, json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
    rows = ["| Proyecto | Estado | Última actividad |", "|---|---|---|"]
    for name, info in data.items():
        rows.append(f"| {name} | {info['estado'].replace('|', '/')} | {info['ultima_actividad'] or '-'} |")
    if not data:
        rows.append("| (ninguno todavía) | | |")
    replace_block(os.path.join(ROOT, "memory", "projects", "project_index.md"), "\n".join(rows), header=INDEX_HEADER)


def refresh_artifact_indexes(project):
    base = pj(project, "artifacts")
    if not os.path.isdir(base):
        return
    found = []
    for dirpath, dirs, files in os.walk(base):
        dirs[:] = sorted(d for d in dirs if not d.startswith("."))
        for fname in files:
            rel = os.path.relpath(os.path.join(dirpath, fname), base).replace(os.sep, "/")
            if fname.startswith(".") or rel in ARTIFACT_INDEX_FILES:
                continue
            found.append(rel)
    assets = sorted(f for f in found if os.path.splitext(f)[1].lower() in ASSET_EXT)
    outputs = sorted(f for f in found if os.path.splitext(f)[1].lower() not in ASSET_EXT)
    replace_auto_block(pj(base, "outputs.md"), outputs, "artifacts")
    replace_auto_block(pj(base, "assets_index.md"), assets, "artifacts")


def refresh_context_index(project):
    files = {}
    for dirpath, dirs, fnames in os.walk(project):
        dirs[:] = sorted(d for d in dirs if not d.startswith("."))
        for fname in sorted(fnames):
            if fname == "context_index.json" or fname.endswith(".tmp") or fname.startswith(".") or ".bak-" in fname:
                continue
            full = os.path.join(dirpath, fname)
            rel = os.path.relpath(full, project).replace(os.sep, "/")
            mtime = datetime.datetime.fromtimestamp(os.path.getmtime(full)).strftime("%Y-%m-%d %H:%M")
            files[rel] = {"bytes": os.path.getsize(full), "modificado": mtime}
    path = pj(project, "context_index.json")
    try:
        current = json.loads(read_text(path) or "{}")
    except ValueError:
        current = {}
    if current.get("archivos") == files and current.get("proyecto") == os.path.basename(project):
        return
    data = {"proyecto": os.path.basename(project), "actualizado": now_str(), "archivos": files}
    write_text(path, json.dumps(data, indent=2, ensure_ascii=False) + "\n")


# -- Hooks (paredes): nunca bloquean ni fallan en voz alta --

def read_payload():
    try:
        data = json.load(sys.stdin)
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def session_path(session_id, suffix):
    safe = re.sub(r"[^A-Za-z0-9_-]", "_", session_id or "sin-sesion")[:64]
    return os.path.join(tempfile.gettempdir(), f"aw-{safe}.{suffix}")


def session_key(payload, project):
    # Sin session_id cada proyecto usa su propio nombre de temporal, no uno compartido.
    return payload.get("session_id") or "sin-sesion-" + hashlib.sha1(project.encode("utf-8")).hexdigest()[:8]


def watched_hashes(project):
    hashes = {}
    for rel in ("tasks/backlog.md", "tasks/active.md", "tasks/done.md", "execution/decisions.md"):
        hashes[rel] = hashlib.sha1(read_text(pj(project, *rel.split("/"))).encode("utf-8")).hexdigest()
    return hashes


def load_session(session_id):
    try:
        data = json.loads(read_text(session_path(session_id, "json")) or "{}")
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def session_events(session_id):
    return read_text(session_path(session_id, "events")).splitlines()


def build_digest(project, max_lines=45, max_chars=4000):
    state_lines = [line for line in read_text(pj(project, "state.md")).splitlines() if line.strip() != MARK_AUTO]
    lines = [f"[aw] Proyecto {os.path.basename(project)}: contexto cargado al iniciar la sesión (protocolo en el CLAUDE.md del workspace)."]
    lines += state_lines
    recent = log_entries(project)[-10:]
    if recent:
        lines += ["", "## Registro reciente"] + recent
    text = "\n".join(lines[:max_lines])
    return text[:max_chars]


def hook_session_start(payload, project):
    key = session_key(payload, project)
    if not load_session(key):  # al reanudar o compactar la sesión ya existe: se conserva su estado
        write_text(session_path(key, "json"), json.dumps({"hashes": watched_hashes(project), "reminded": False, "inicio": now_str()}))
    log_event(project, "sesión", f"iniciada ({payload.get('source') or 'startup'})")
    refresh_state(project)
    output = {"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": build_digest(project)}}
    print(json.dumps(output, ensure_ascii=False))


def git_last_commit(cwd):
    try:
        result = subprocess.run(["git", "log", "-1", "--format=%h %s"], cwd=cwd, capture_output=True, text=True, timeout=5)
    except Exception:
        return None
    return redact(result.stdout.strip()) if result.returncode == 0 and result.stdout.strip() else None


def hook_post_tool(payload, project):
    tool = str(payload.get("tool_name") or "?")
    events = session_path(session_key(payload, project), "events")
    append_text(events, f"T {tool}\n")
    if tool == "Bash":
        command = str((payload.get("tool_input") or {}).get("command") or "")
        if GIT_COMMIT_RE.search(command):
            log_event(project, "commit", git_last_commit(payload.get("cwd") or project) or "(sin detalle)")
            append_text(events, "C\n")


def hook_tool_failure(payload, project):
    tool = str(payload.get("tool_name") or "?")
    raw = payload.get("error") or payload.get("tool_response") or payload.get("message") or ""
    if not isinstance(raw, str):
        raw = json.dumps(raw, ensure_ascii=False)
    lines = [line.strip() for line in raw.splitlines() if line.strip()]
    first = lines[0] if lines else "(sin detalle)"
    if re.fullmatch(r"Exit code \d+", first) and len(lines) > 1:
        first = f"{first} — {lines[1]}"  # Claude Code pone el código de salida en la primera línea
    # Solo herramienta y primera línea del error: nunca el comando completo.
    append_text(pj(project, "execution", "errors.md"), f"- {now_str()} [{tool}] {redact(first)[:160]}\n")
    append_text(session_path(session_key(payload, project), "events"), "E\n")


def hook_pre_compact(payload, project):
    log_event(project, "compactación", payload.get("trigger") or payload.get("matcher") or "compactación")
    refresh_state(project)


def hook_stop(payload, project):
    refresh_state(project)
    session_id = session_key(payload, project)
    session = load_session(session_id)
    if not session or session.get("reminded"):
        return
    commits = sum(1 for line in session_events(session_id) if line == "C")
    if commits and watched_hashes(project) == session.get("hashes"):
        session["reminded"] = True
        write_text(session_path(session_id, "json"), json.dumps(session))
        message = (f"aw: hubo {commits} commit(s) en esta sesión y no se registró ninguna decisión ni movimiento de tareas. "
                   "Si corresponde, usa `aw decide` o `aw task`.")
        print(json.dumps({"systemMessage": message}, ensure_ascii=False))


def append_month_log(project, text):
    logs = os.path.join(ROOT, "logs")
    path = os.path.join(logs, "current_month.md")
    month = today()[:7]
    existing = read_text(path)
    header = re.match(r"# Registro de (\d{4}-\d{2})", existing)
    if header and header.group(1) != month:
        dest = os.path.join(logs, f"{header.group(1)}.md")
        if os.path.exists(dest):
            append_text(dest, existing)
            write_text(path, "")
        else:
            os.replace(path, dest)
        existing = ""
    if not existing.strip():
        write_text(path, f"# Registro de {month}\n\n")
    append_text(path, f"- {now_str()} {os.path.basename(project)} — {text}\n")


def update_tool_usage(project, session_id, tools, commits):
    if not tools:
        return
    top = sorted(tools.items(), key=lambda item: (-item[1], item[0]))[:8]
    summary = ", ".join(f"{name}×{count}" for name, count in top)
    append_text(pj(project, "tools", "tool_usage.md"), f"- {today()} | {(session_id or 'sin-sesion')[:8]} | {summary}\n")
    state_path = pj(project, "tools", "tool_state.json")
    try:
        data = json.loads(read_text(state_path) or "{}")
    except ValueError:
        return
    if not isinstance(data, dict):
        return
    data["ultima_sesion"] = {"id": session_id, "fin": now_str(), "commits": commits, "herramientas": dict(tools)}
    data["actualizado"] = now_str()
    write_text(state_path, json.dumps(data, indent=2, ensure_ascii=False) + "\n")


def run_end_step(name, step, *args):
    try:
        step(*args)
    except Exception as exc:  # cada paso del cierre es independiente: un fallo se anota y no impide los demás
        try:
            log_hook_error(f"session-end ({name})", exc)
        except Exception:
            pass


def hook_session_end(payload, project):
    key = session_key(payload, project)
    try:
        events = session_events(key)
        commits = sum(1 for line in events if line == "C")
        tools = {}
        for line in events:
            if line.startswith("T "):
                tools[line[2:]] = tools.get(line[2:], 0) + 1
        reason = payload.get("reason")
        summary = f"terminada: {commits} commit(s), {sum(tools.values())} usos de herramientas" + (f" ({reason})" if reason else "")
        run_end_step("registro", log_event, project, "sesión", summary)
        run_end_step("herramientas", update_tool_usage, project, payload.get("session_id"), tools, commits)
        run_end_step("registro mensual", append_month_log, project, summary)
        run_end_step("estado", refresh_state, project)
        run_end_step("índice", refresh_workspace_index)
    finally:
        for suffix in ("json", "events"):
            try:
                os.remove(session_path(key, suffix))
            except OSError:
                pass


HOOK_HANDLERS = {
    "session-start": hook_session_start,
    "post-tool": hook_post_tool,
    "tool-failure": hook_tool_failure,
    "pre-compact": hook_pre_compact,
    "stop": hook_stop,
    "session-end": hook_session_end,
}


def log_hook_error(event, exc):
    path = os.path.join(ROOT, "logs", "debug.md")
    append_text(path, f"- {now_str()} hook {event}: {type(exc).__name__}: {str(exc)[:200]}\n")


def run_hook(event):
    try:
        payload = read_payload()
        cwd = payload.get("cwd") or os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()
        project = find_project(cwd)
        handler = HOOK_HANDLERS.get(event)
        if project and handler and os.path.basename(project) != "template_project":
            handler(payload, project)
    except Exception as exc:  # un hook nunca debe romper la sesión
        try:
            log_hook_error(event, exc)
        except Exception:
            pass
    return 0


# -- Sincronización con la plantilla --

def hook_signature(command):
    # Solo reconoce los hooks de aw (generate.py o aw seguido de "hook <nombre>"); los demás devuelven None.
    match = re.search(r'(?:generate\.py"?|\baw)\s+hook\s+([a-z-]+)(?:\s|$)', str(command or ""))
    return match.group(1) if match else None


def hook_key(hook):
    command = str(hook.get("command") or "")
    return hook_signature(command) or command


def update_hook(installed, wanted):
    changed = False
    for field in ("command", "timeout", "async"):
        if field in wanted:
            if installed.get(field) != wanted[field]:
                installed[field] = wanted[field]
                changed = True
        elif field == "async" and installed.get("async"):
            del installed["async"]
            changed = True
    return changed


def repo_settings_text():
    # El settings.json de los proyectos lo gestiona aw: se fusiona siempre desde la plantilla del repo,
    # así lo nuevo (hooks, permisos) llega también a proyectos y plantillas ya existentes.
    return read_text(os.path.join(TEMPLATES_DIR, "projects", "template_project", ".claude", "settings.json"))


def merge_settings(existing, template):
    # Solo agrega lo que falta: nunca reemplaza listas ni toca otras claves.
    merged = json.loads(json.dumps(existing))
    notes = []
    template_perms = template.get("permissions") or {}
    if template_perms:
        perms = merged.setdefault("permissions", {})
        if isinstance(perms, dict):
            for key in ("allow", "additionalDirectories"):
                for item in template_perms.get(key, []):
                    current = perms.setdefault(key, [])
                    if isinstance(current, list) and item not in current:
                        current.append(item)
                        notes.append(f"permissions.{key} += {item}")
    template_hooks = template.get("hooks") or {}
    if template_hooks:
        hooks = merged.setdefault("hooks", {})
        if isinstance(hooks, dict):
            for event, groups in template_hooks.items():
                current = hooks.setdefault(event, [])
                if not isinstance(current, list):
                    continue
                installed = [h for g in current if isinstance(g, dict)
                             for h in (g.get("hooks") or []) if isinstance(h, dict)]
                for group in groups:
                    wanted = [h for h in group.get("hooks", []) if hook_key(h)]
                    keys = {hook_key(h) for h in wanted}
                    found = [h for h in installed if hook_key(h) in keys]
                    if not found:
                        current.append(group)
                        notes.append(f"hook {event}")
                        continue
                    for want in wanted:
                        if not hook_signature(want.get("command")):
                            continue  # solo se reparan los hooks de aw; los del usuario se dejan como están
                        changed = [update_hook(h, want) for h in found if hook_key(h) == hook_key(want)]
                        if any(changed):
                            notes.append(f"hook {event} actualizado")
    return merged, notes


def sync_settings(project, source_text, variables, dry_run):
    dest = pj(project, ".claude", "settings.json")
    template = json.loads(render(source_text, variables, json_safe=True))
    if not os.path.exists(dest):
        if not dry_run:
            write_text(dest, json.dumps(template, indent=2, ensure_ascii=False) + "\n")
        return [("crear", ".claude/settings.json")]
    try:
        existing = json.loads(read_text(dest) or "{}")
    except ValueError:
        return [("omitir", ".claude/settings.json (JSON inválido; no se toca)")]
    merged, notes = merge_settings(existing, template)
    if not notes:
        return []
    if not dry_run:
        backup = f"{dest}.bak-{datetime.datetime.now().strftime('%Y%m%d-%H%M%S')}"
        shutil.copy2(dest, backup)
        write_text(dest, json.dumps(merged, indent=2, ensure_ascii=False) + "\n")
    return [("actualizar", ".claude/settings.json: " + "; ".join(notes))]


def sync_project(project, template, dry_run=False):
    variables = project_vars(os.path.basename(project), "")
    changes = []
    for dirpath, dirs, files in os.walk(template):
        dirs.sort()
        for fname in sorted(files):
            if ".bak-" in fname:
                continue
            source = os.path.join(dirpath, fname)
            rel = os.path.relpath(source, template).replace(os.sep, "/")
            if rel == ".claude/settings.json":
                changes += sync_settings(project, repo_settings_text() or read_text(source), variables, dry_run)
                continue
            source_text = read_text(source)
            if not source_text.strip():
                continue  # la plantilla aún no tiene contenido para este archivo
            dest = pj(project, *rel.split("/"))
            if not os.path.exists(dest):
                action = "crear"
            elif os.path.getsize(dest) == 0:
                action = "rellenar"
            else:
                continue
            changes.append((action, rel))
            if not dry_run:
                write_text(dest, render(source_text, variables, json_safe=rel.endswith(".json")))
    if not dry_run:
        refresh_state(project)
        refresh_artifact_indexes(project)
        refresh_context_index(project)
    return changes


def sync_projects(names=None, dry_run=False, workspace=False):
    for name in names or []:
        check_project_name(name)
    template = os.path.join(ROOT, "projects", "template_project")
    if not dry_run:
        build(ROOT, load_structure())
    if not os.path.isdir(template):
        raise AwError("No existe template_project. Ejecuta primero 'aw init'.")
    projects = names or list_projects()
    if dry_run:
        print("Modo prueba: no se cambia nada. La plantilla del workspace tampoco se actualiza (usa 'aw init' para eso).")
    total = 0
    action, detail = ensure_workspace_claude_md(dry_run=dry_run, force=workspace)
    if action in ("crear", "marcar", "actualizar"):
        total += 1
        print(f"- workspace: CLAUDE.md: {detail}")
    elif action == "difiere":
        print("- workspace: el CLAUDE.md difiere de la plantilla (cambios tuyos o versión anterior). "
              "Usa 'aw sync --workspace' para actualizarlo; se respalda antes.")
    elif action == "ajeno":
        print("- workspace: el CLAUDE.md de la raíz no es el del workspace aw (sin huella y con otra primera línea): "
              "no se gestiona, tampoco con --workspace.")
    settings_text = repo_settings_text()
    if settings_text.strip():
        for change, rel in sync_settings(template, settings_text, project_vars("template_project", ""), dry_run):
            total += 1
            print(f"- plantilla: {change}: {rel}")
    for name in projects:
        path = os.path.join(ROOT, "projects", name)
        if not os.path.isdir(path):
            print(f"- {name}: no existe, se omite.")
            continue
        changes = sync_project(path, template, dry_run)
        total += len(changes)
        print(f"- {name}: " + (f"{len(changes)} cambio(s)" if changes else "al día"))
        for change, rel in changes:
            print(f"    {change}: {rel}")
    if not dry_run:
        refresh_workspace_index()
        print("- workspace: índice de proyectos al día")
    print(f"Total: {total} cambio(s)" + (" (no aplicados)" if dry_run else "") + ".")


# -- Diagnóstico --

def markdown_rows(text):
    rows = []
    for line in text.splitlines():
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if all(re.fullmatch(r":?-{3,}:?", c) for c in cells if c):
            continue
        rows.append(cells)
    return rows[1:]  # sin la fila de encabezado


def doctor_project(project):
    results = []

    def add(level, text):
        results.append((level, text))

    template = os.path.join(ROOT, "projects", "template_project")
    if os.path.isdir(template):
        missing = []
        for dirpath, _dirs, files in os.walk(template):
            for fname in files:
                if ".bak-" in fname:
                    continue
                rel = os.path.relpath(os.path.join(dirpath, fname), template).replace(os.sep, "/")
                if not os.path.exists(pj(project, *rel.split("/"))):
                    missing.append(rel)
        if missing:
            add("warn", f"faltan {len(missing)} archivo(s) de la plantilla (aw sync los crea): " + ", ".join(sorted(missing)[:4]) + ("…" if len(missing) > 4 else ""))
        else:
            add("ok", "estructura completa")
    else:
        add("warn", "no existe template_project en el workspace")

    empty, fields = [], 0
    for dirpath, dirs, files in os.walk(project):
        dirs[:] = [d for d in dirs if not d.startswith(".")]
        for fname in files:
            full = os.path.join(dirpath, fname)
            rel = os.path.relpath(full, project).replace(os.sep, "/")
            if os.path.getsize(full) == 0:
                empty.append(rel)
            elif rel.endswith(".md") and rel.split("/")[0] in ("project.md", "CLAUDE.md", "agents", "skills", "tools", "sop"):
                fields += read_text(full).count("(completar)")
    if empty:
        add("warn", f"{len(empty)} archivo(s) vacío(s) (aw sync los rellena): " + ", ".join(sorted(empty)[:4]) + ("…" if len(empty) > 4 else ""))
    else:
        add("ok", "ningún archivo vacío")
    add("warn" if fields else "ok", f"{fields} campo(s) '(completar)' por rellenar" if fields else "sin campos pendientes de completar")

    state_text = read_text(pj(project, "state.md"))
    if not state_is_auto(state_text):
        add("warn", "state.md tiene texto manual: no se actualiza solo")
    else:
        match = re.search(r"actualizado (\d{4}-\d{2}-\d{2})", state_text)
        entries = log_entries(project)
        last_log = re.match(r"- (\d{4}-\d{2}-\d{2})", entries[-1]) if entries else None
        if match and last_log and last_log.group(1) > match.group(1):
            add("warn", "state.md está desactualizado respecto al registro")
        else:
            add("ok", "state.md al día")

    entries = log_entries(project)
    if not entries:
        add("warn", "el registro de ejecución no tiene entradas")
    else:
        last = re.match(r"- (\d{4}-\d{2}-\d{2})", entries[-1])
        age = (datetime.date.today() - datetime.date.fromisoformat(last.group(1))).days if last else 0
        add("warn" if age > 14 else "ok", f"última actividad registrada hace {age} día(s)")
    commits = sum(1 for e in entries if "[commit]" in e)
    if commits >= 3 and not decision_titles(project):
        add("warn", f"{commits} commit(s) registrados y ninguna decisión")

    settings_path = pj(project, ".claude", "settings.json")
    if not os.path.exists(settings_path):
        add("bad", ".claude/settings.json no existe (aw sync lo crea)")
    else:
        try:
            settings = json.loads(read_text(settings_path))
        except ValueError:
            settings = None
            add("bad", ".claude/settings.json tiene JSON inválido")
        if settings is not None:
            hooks = settings.get("hooks") if isinstance(settings.get("hooks"), dict) else {}
            commands = [h.get("command", "") for groups in hooks.values() if isinstance(groups, list)
                        for g in groups if isinstance(g, dict) for h in g.get("hooks", []) if isinstance(h, dict)]
            present = {hook_signature(c) for c in commands}
            absent = [e for e in HOOK_EVENTS if e not in present]
            add("bad" if absent else "ok", ("faltan hooks: " + ", ".join(absent)) if absent else "hooks de aw instalados")
            for command in commands:
                match = re.search(r'"([^"]*generate\.py)"', command)
                if match and not os.path.exists(match.group(1)):
                    add("bad", f"un hook apunta a un script que no existe: {match.group(1)}")
                    break
            allow = (settings.get("permissions") or {}).get("allow") or []
            need = [p for p in ("Bash(aw task *)", "Bash(aw decide *)", "Bash(aw log *)") if p not in allow]
            add("warn" if need else "ok", ("faltan permisos: " + ", ".join(need)) if need else "permisos de aw presentes")

    add("ok" if os.path.exists(pj(project, "CLAUDE.md")) else "warn", "CLAUDE.md del proyecto presente" if os.path.exists(pj(project, "CLAUDE.md")) else "falta el CLAUDE.md del proyecto (aw sync lo crea)")

    for folder, label in (("agents", "agentes"), ("skills", "skills")):
        notes = pj(project, folder, f"assigned_{folder}.md")
        for cells in markdown_rows(read_text(notes)):
            if len(cells) < 2 or not cells[1] or cells[1] == "(completar)":
                continue
            target = os.path.expanduser(cells[1])
            if not os.path.isabs(target):
                target = os.path.join(ROOT, folder, target)
            if not os.path.exists(target):
                add("bad", f"{label} asignados: no existe {cells[1]} (fila '{cells[0]}')")

    mcp_names = set()
    try:
        mcp = json.loads(read_text(pj(project, ".mcp.json")) or "{}")
        mcp_names = {k.lower() for k in (mcp.get("mcpServers") or {})}
    except ValueError:
        pass
    for cells in markdown_rows(read_text(pj(project, "tools", "assigned_tools.md"))):
        if len(cells) >= 3 and cells[0] and cells[0] != "(completar)" and ".mcp.json" in cells[2].lower():
            if cells[0].lower() not in mcp_names:
                add("warn", f"herramienta '{cells[0]}' declarada en .mcp.json pero no figura ahí")
    return results


def doctor(names=None):
    for name in names or []:
        check_project_name(name)
    symbols = {"ok": "✓", "warn": "▲", "bad": "✕"}
    counts = {"ok": 0, "warn": 0, "bad": 0}
    print("aw doctor")
    global_checks = [
        ("ok" if shutil.which(WRAPPER_NAME) else "warn", "comando 'aw' en el PATH" if shutil.which(WRAPPER_NAME) else "el comando 'aw' no está en el PATH (opción 9 del menú)"),
        ("ok" if os.path.exists(os.path.join(ROOT, "CLAUDE.md")) else "warn", "CLAUDE.md del workspace presente" if os.path.exists(os.path.join(ROOT, "CLAUDE.md")) else "falta el CLAUDE.md del workspace (aw init lo crea)"),
    ]
    action, _detail = ensure_workspace_claude_md(dry_run=True)
    if action in ("actualizar", "difiere"):
        global_checks.append(("warn", "el CLAUDE.md del workspace difiere de la plantilla (aw sync --workspace)"))
    elif action == "ajeno":
        global_checks.append(("warn", "el CLAUDE.md de la raíz no es el del workspace aw: aw no lo gestiona"))
    try:
        indexed = set(json.loads(read_text(os.path.join(ROOT, "memory", "context_index.json")) or "{}").get("proyectos") or {})
    except (ValueError, AttributeError):
        indexed = None
    if indexed is None:
        global_checks.append(("warn", "memory/context_index.json es inválido (aw sync no lo toca mientras esté roto)"))
    else:
        absent = set(list_projects()) - indexed
        global_checks.append(("warn", f"el índice de proyectos no incluye {len(absent)} proyecto(s) (aw sync)") if absent
                             else ("ok", "índice de proyectos al día"))
    pending = 0
    for folder in ("core", "memory"):
        base = os.path.join(ROOT, folder)
        if os.path.isdir(base):
            pending += sum(read_text(os.path.join(base, f)).count("(completar)") for f in sorted(os.listdir(base)) if f.endswith(".md"))
    global_checks.append(("warn", f"{pending} campo(s) '(completar)' por rellenar en core/ y memory/") if pending
                         else ("ok", "core/ y memory/ sin campos pendientes"))
    print("\nWorkspace")
    for level, text in global_checks:
        counts[level] += 1
        print(f"  {symbols[level]} {text}")
    projects = names or list_projects()
    if not projects:
        print("\nNo hay proyectos todavía.")
    for name in projects:
        path = os.path.join(ROOT, "projects", name)
        print(f"\nProyecto {name}")
        if not os.path.isdir(path):
            counts["bad"] += 1
            print(f"  {symbols['bad']} no existe")
            continue
        for level, text in doctor_project(path):
            counts[level] += 1
            print(f"  {symbols[level]} {text}")
    print(f"\nResumen: {counts['ok']} bien, {counts['warn']} por revisar, {counts['bad']} pendientes")
    return 1 if counts["bad"] else 0


# -- Instalación del comando en el sistema --

def action_install_command():
    if sys.platform.startswith("win"):
        print("El instalador todavía no soporta Windows. Por ahora usá 'python3 generate.py' directamente.")
        return
    bin_dir = os.path.expanduser("~/.local/bin")
    os.makedirs(bin_dir, exist_ok=True)
    wrapper_path = os.path.join(bin_dir, WRAPPER_NAME)
    script_path = os.path.abspath(__file__)
    with open(wrapper_path, "w") as f:
        f.write(f'#!/bin/sh\nexec python3 "{script_path}" "$@"\n')
    st = os.stat(wrapper_path)
    os.chmod(wrapper_path, st.st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    print(f"Comando '{WRAPPER_NAME}' instalado en {wrapper_path}")

    path_dirs = os.environ.get("PATH", "").split(os.pathsep)
    if bin_dir not in path_dirs:
        print(f"\n{bin_dir} todavía no está en tu PATH.")
        print("Agregá esta línea a tu ~/.bashrc o ~/.zshrc y abrí una terminal nueva:\n")
        print('  export PATH="$HOME/.local/bin:$PATH"\n')
    else:
        print(f"Ya podés usar el comando '{WRAPPER_NAME}' desde cualquier carpeta.")


# -- Menú principal --

def action_doctor():
    doctor()


def action_sync():
    answer = input("¿Solo mostrar lo que se haría, sin cambiar nada? (s/n): ").strip().lower()
    try:
        sync_projects(dry_run=(answer != "n"))
    except AwError as exc:
        print(exc)


def main_menu():
    print(BANNER)
    while True:
        print(MENU)
        choice = input("Elegí una opción: ").strip()
        print()
        if choice == "1":
            action_new_project()
        elif choice == "2":
            action_list_projects()
        elif choice == "3":
            action_view_tasks()
        elif choice == "4":
            action_view_decisions()
        elif choice == "5":
            action_init()
        elif choice == "6":
            registry_menu("Agentes", "agents")
        elif choice == "7":
            registry_menu("Skills", "skills")
        elif choice == "8":
            registry_menu("Herramientas", "tools")
        elif choice == "9":
            action_install_command()
        elif choice == "10":
            action_doctor()
        elif choice == "11":
            action_sync()
        elif choice == "0":
            print("Hasta luego.")
            break
        else:
            print("Opción inválida.")


# -- Línea de comandos --

def build_parser():
    parser = argparse.ArgumentParser(prog=WRAPPER_NAME, description="Agentic Workspace. Sin argumentos abre el menú.")
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--project", help="nombre del proyecto (por defecto, el de la carpeta actual)")
    sub = parser.add_subparsers(dest="cmd")

    sub.add_parser("init", help="crea o actualiza la estructura del workspace")

    project = sub.add_parser("project", help="gestión de proyectos")
    project_sub = project.add_subparsers(dest="pcmd")
    new = project_sub.add_parser("new", help="crea un proyecto desde la plantilla")
    new.add_argument("name")
    new.add_argument("--desc", default="")

    task = sub.add_parser("task", help="tareas del proyecto")
    task_sub = task.add_subparsers(dest="tcmd")
    add = task_sub.add_parser("add", parents=[common], help="agrega una tarea a los pendientes")
    add.add_argument("title", nargs="+")
    add.add_argument("--prio", default="P2", help="P0 urgente, P1 alta, P2 normal, P3 baja")
    start = task_sub.add_parser("start", parents=[common], help="pasa una tarea a en curso")
    start.add_argument("id")
    done = task_sub.add_parser("done", parents=[common], help="marca una tarea como hecha")
    done.add_argument("id")
    lst = task_sub.add_parser("list", parents=[common], help="lista las tareas")
    lst.add_argument("--all", action="store_true", help="incluye las hechas")

    dec = sub.add_parser("decide", parents=[common], help="registra una decisión con su motivo")
    dec.add_argument("title", nargs="+")
    dec.add_argument("--why", required=True, help="motivo de la decisión")
    dec.add_argument("--alt", default=None, help="alternativas descartadas")

    log = sub.add_parser("log", parents=[common], help="agrega una nota al registro de ejecución")
    log.add_argument("text", nargs="+")

    state = sub.add_parser("state", parents=[common], help="regenera y muestra state.md")
    state.add_argument("--quiet", action="store_true")

    sync = sub.add_parser("sync", help="lleva a los proyectos lo nuevo de la plantilla")
    sync.add_argument("names", nargs="*")
    sync.add_argument("--dry-run", action="store_true", help="muestra los cambios sin aplicarlos")
    sync.add_argument("--workspace", action="store_true",
                      help="actualiza el CLAUDE.md del workspace con la plantilla aunque tenga cambios propios (se respalda antes)")

    doc = sub.add_parser("doctor", help="diagnóstico de proyectos")
    doc.add_argument("names", nargs="*")
    return parser


def print_tasks(project, include_done=False):
    sections = [("En curso", "active.md"), ("Pendientes", "backlog.md")]
    if include_done:
        sections.append(("Hechas", "done.md"))
    for label, filename in sections:
        tasks = load_tasks(project, filename)
        print(f"{label}:")
        for t in tasks or []:
            print(f"  {t['id']} [{t['prio']}] {clean_title(t['title'])}")
        if not tasks:
            print("  (ninguna)")


def dispatch(args):
    if args.cmd == "init":
        action_init()
    elif args.cmd == "project":
        if args.pcmd != "new":
            raise AwError("Uso: aw project new NOMBRE [--desc TEXTO]")
        target = create_project(args.name, args.desc)
        print(f"Proyecto creado: {target}")
    elif args.cmd == "task":
        project = resolve_project(args.project)
        if args.tcmd == "add":
            task_id, prio = task_add(project, " ".join(args.title), args.prio)
            print(f"{task_id} creada [{prio}]")
        elif args.tcmd == "start":
            task = task_start(project, args.id)
            print(f"{normalize_task_id(args.id)} en curso: {clean_title(task['title'])}")
        elif args.tcmd == "done":
            task = task_done(project, args.id)
            print(f"{normalize_task_id(args.id)} hecha: {clean_title(task['title'])}")
        elif args.tcmd == "list":
            print_tasks(project, args.all)
        else:
            raise AwError("Uso: aw task add|start|done|list")
    elif args.cmd == "decide":
        project = resolve_project(args.project)
        decide(project, " ".join(args.title), args.why, args.alt)
        print("Decisión registrada.")
    elif args.cmd == "log":
        project = resolve_project(args.project)
        log_event(project, "nota", " ".join(args.text))
        refresh_state(project)
        print("Nota registrada.")
    elif args.cmd == "state":
        project = resolve_project(args.project)
        automatic = refresh_state(project)
        if not automatic:
            print("state.md tiene texto manual: no se regenera (renómbralo o vacíalo para activar el estado automático).", file=sys.stderr)
        if not args.quiet:
            print(read_text(pj(project, "state.md")), end="")
    elif args.cmd == "sync":
        sync_projects(args.names or None, args.dry_run, args.workspace)
    elif args.cmd == "doctor":
        return doctor(args.names or None)
    return 0


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if not argv:
        main_menu()
        return 0
    if argv[0] == "hook":
        return run_hook(argv[1] if len(argv) > 1 else "")
    parser = build_parser()
    args = parser.parse_args(argv)
    if not args.cmd:
        parser.print_help()
        return 0
    try:
        return dispatch(args)
    except AwError as exc:
        print(exc, file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
