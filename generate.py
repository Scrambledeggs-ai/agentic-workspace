import argparse
import contextlib
import datetime
import errno
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
12) Actualizar aw desde su repositorio
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
# Entradas del reflog que crean un commit: commit (también amend e initial), merge, cherry-pick y revert. Un cambio de
# rama, un reset, un rebase o un avance directo (Fast-forward) no crean commits propios y no cuentan.
COMMIT_REFLOG_RE = re.compile(r"(?:commit|merge|cherry-pick|revert)\b(?!.*\bFast-forward\b)")


HOOK_EVENTS = ("session-start", "post-tool", "tool-failure", "pre-compact", "stop", "session-end")

TEXT_EXT = (".md", ".json")  # los únicos archivos que aw interpreta; lo demás no lo lee


def is_text_file(name):
    return name.lower().endswith(TEXT_EXT)

ARTIFACT_INDEX_FILES = ("outputs.md", "code_snippets.md", "assets_index.md")
ASSET_EXT = {".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".ico", ".mp4", ".mov", ".mp3", ".wav", ".fig"}


class AwError(Exception):
    pass


class AwEncodingError(AwError, ValueError):
    # Archivo que no está en UTF-8. Como AwError llega al usuario con un mensaje claro; como ValueError,
    # las lecturas de JSON lo tratan igual que un JSON inválido y siguen con lo demás.
    pass


def make_header(name, description):
    return f"---\nname: {name}\ndescription: {description}\n---\n\n"


def read_header(filepath):
    lines = read_text(filepath).splitlines()
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
    except UnicodeDecodeError:
        raise AwEncodingError(f"El archivo no está en UTF-8: {path}. Conviértelo a UTF-8 y repite el comando.") from None


def write_text(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = f"{path}.{os.getpid()}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, path)


def append_text(path, text):
    # Solo mira el último byte: el registro y los errores crecen y no hace falta releerlos en cada escritura.
    os.makedirs(os.path.dirname(path), exist_ok=True)
    needs_newline = False
    try:
        with open(path, "rb") as f:
            if f.seek(0, os.SEEK_END):
                f.seek(-1, os.SEEK_END)
                needs_newline = f.read(1) != b"\n"
    except (FileNotFoundError, IsADirectoryError):
        pass
    with open(path, "a", encoding="utf-8") as f:
        if needs_newline:
            f.write("\n")
        f.write(text)


def as_dict(value):
    # Un JSON editado a mano puede ser válido y traer otro tipo donde se espera un objeto o una lista.
    return value if isinstance(value, dict) else {}


def as_list(value):
    return value if isinstance(value, list) else []


# -- Plantillas --

def sh_quote(path):
    # Comillas dobles, como siempre, pero con \ " $ ` escapados para que el shell no los interprete.
    return '"' + re.sub(r'([\\"$`])', r"\\\1", path) + '"'


def machine_vars():
    script = os.path.abspath(__file__)
    return {"ROOT": ROOT, "SCRIPT": script, "AW_CMD": f"python3 {sh_quote(script)}"}


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
    return render(read_text(path), variables, json_safe=relpath.lower().endswith(".json"))


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


def build(path, node, rel="", collect=None):
    # Con collect (un dict) no escribe nada: anota {ruta relativa: contenido} de lo que crearía o rellenaría.
    if not isinstance(node, dict):
        return

    if collect is None:
        os.makedirs(path, exist_ok=True)
    variables = machine_vars()

    for filename in node.get("files", []):
        filepath = os.path.join(path, filename)
        relpath = os.path.join(rel, filename).replace(os.sep, "/")
        exists = os.path.exists(filepath)
        if exists and os.path.getsize(filepath) > 0:
            continue
        if not exists and os.path.islink(filepath):
            continue  # enlace simbólico roto: no se escribe a través de él
        content = workspace_claude_md() if relpath == "CLAUDE.md" else template_content(relpath, variables)
        if not exists and content is None and relpath in DEFAULT_HEADERS:
            name, desc = DEFAULT_HEADERS[relpath]
            content = make_header(name, desc)
        if collect is not None:
            if content:
                collect[relpath] = content
        elif not exists or content is not None:  # un archivo existente pero vacío se rellena con su plantilla
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(content or "")

    children = dict(node.get("folders", {}))
    children.update({key: value for key, value in node.items() if key not in ("files", "folders")})
    for name, child in children.items():
        child_path = os.path.join(path, name)
        if os.path.islink(child_path) and (collect is not None or not os.path.exists(child_path)):
            continue  # enlace roto, o (al anotar) enlace a otra carpeta: la sincronización no lo recorre
        if collect is None:
            os.makedirs(child_path, exist_ok=True)
        build(child_path, child, os.path.join(rel, name), collect)


def load_structure():
    with open(STRUCTURE_FILE, "r", encoding="utf-8") as f:
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
        print("CLAUDE.md de la raíz: no es el del workspace aw (sin huella y con otra primera línea); no se gestiona. "
              "Si es una versión antigua del workspace, renómbralo y ejecuta 'aw init'.")


# -- Registro dinámico de agentes / skills / tools --

def list_registry(folder):
    dirpath = os.path.join(ROOT, folder)
    if not os.path.isdir(dirpath):
        print("No existe la carpeta todavía. Ejecuta primero 'Iniciar / actualizar estructura del sistema'.")
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
    if not is_plain_name(name):
        print("Nombre inválido.")
        return
    description = input("Descripción breve: ").strip()
    filename = name.lower().replace(" ", "_") + ".md"
    filepath = os.path.join(dirpath, filename)
    if os.path.exists(filepath):
        print("Ya existe un archivo con ese nombre.")
        return
    write_text(filepath, make_header(name, description))
    print(f"Creado: {folder}/{filename}")


def registry_menu(label, folder):
    while True:
        print(f"\n-- {label} --")
        print("a) Ver disponibles")
        print("b) Crear nuevo")
        print("c) Volver")
        choice = input("Elige una opción: ").strip().lower()
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

# Carpetas que dejan las herramientas de desarrollo: no son proyectos ni se recorren dentro de uno.
HEAVY_DIRS = {"node_modules", "__pycache__", "venv"}
# Carpetas de projects/ que nunca son un proyecto. check_project_name rechaza las pesadas; check_project_names,
# además, la plantilla.
NOT_PROJECTS = {"template_project"} | HEAVY_DIRS


def list_projects():
    projects_dir = os.path.join(ROOT, "projects")
    if not os.path.isdir(projects_dir):
        return []
    return sorted(
        p for p in os.listdir(projects_dir)
        if p not in NOT_PROJECTS and not p.startswith(".") and os.path.isdir(os.path.join(projects_dir, p))
    )


def summary_line(filepath):
    if not os.path.exists(filepath):
        return "(sin datos)"
    for line in read_text(filepath).splitlines():
        line = line.strip()
        if line:
            return line
    return "(vacío)"


def render_tree(root_dir, variables):
    for dirpath, _dirs, files in os.walk(root_dir):
        for fname in files:
            if not is_text_file(fname):
                continue
            fpath = os.path.join(dirpath, fname)
            text = read_text(fpath)
            new = render(text, variables, json_safe=fname.lower().endswith(".json"))
            if new != text:
                write_text(fpath, new)


def ignore_template_extras(dirpath, names):
    # Al copiar la plantilla solo se llevan carpetas y archivos .md y .json (la misma regla que en sync), sin
    # respaldos ni enlaces simbólicos rotos.
    def skip(name):
        path = os.path.join(dirpath, name)
        return ".bak-" in name or not os.path.exists(path) or not (os.path.isdir(path) or is_text_file(name))

    return [name for name in names if skip(name)]


def create_project(name, description=""):
    name = (name or "").strip()
    check_project_name(name)
    if name == "template_project":
        raise AwError("Nombre de proyecto inválido.")
    template = os.path.join(ROOT, "projects", "template_project")
    if not os.path.isdir(template):
        raise AwError("No existe template_project. Ejecuta primero 'Iniciar / actualizar estructura del sistema' (aw init).")
    target = os.path.join(ROOT, "projects", name)
    if os.path.exists(target):
        raise AwError("Ya existe un proyecto con ese nombre.")
    variables = project_vars(name, description)
    try:
        os.mkdir(target)  # si otra llamada la creó entretanto, falla aquí y no se toca lo que haya dentro
    except FileExistsError:
        raise AwError("Ya existe un proyecto con ese nombre.") from None
    try:
        shutil.copytree(template, target, ignore=ignore_template_extras, dirs_exist_ok=True)
        render_tree(target, variables)
        # La plantilla del workspace puede venir de un aw anterior: los hooks y permisos se toman del repo.
        settings_text = repo_settings_text()
        if settings_text.strip():
            sync_settings(target, settings_text, variables, dry_run=False, backup=False)
        if not read_text(os.path.join(target, "project.md")).strip():
            write_text(os.path.join(target, "project.md"), f"# {name}\n\n{description}\n")
        log_event(target, "nota", "proyecto creado")
        refresh_state(target)
    except BaseException:  # no se deja un proyecto a medias: el nombre queda libre para reintentar
        shutil.rmtree(target, ignore_errors=True)
        raise
    try:
        refresh_workspace_index()
    except (OSError, AwError):  # el índice es secundario: el proyecto ya está creado
        pass
    return target


def action_new_project():
    template = os.path.join(ROOT, "projects", "template_project")
    if not os.path.isdir(template):
        print("No existe template_project. Ejecuta primero 'Iniciar / actualizar estructura del sistema'.")
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
        print("No hay proyectos todavía. Crea uno desde la opción 1.")
        return
    for name in projects:
        state_file = os.path.join(ROOT, "projects", name, "state.md")
        print(f"- {name}: {summary_line(state_file)}")


def choose_project():
    projects = list_projects()
    if not projects:
        print("No hay proyectos todavía. Crea uno desde la opción 1.")
        return None
    for i, name in enumerate(projects, 1):
        print(f"{i}) {name}")
    choice = input("Elige un proyecto (número): ").strip()
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
    content = read_text(filepath).strip()
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


def is_plain_name(name):
    # Se rechazan ambos separadores en cualquier sistema: en Windows "/" también separa rutas.
    return bool(name) and "/" not in name and "\\" not in name and not name.startswith(".")


def check_project_name(name):
    if not is_plain_name(name) or name in HEAVY_DIRS:
        raise AwError("Nombre de proyecto inválido.")


TEMPLATE_ERROR = "template_project es la plantilla, no un proyecto: no se modifica desde estos comandos."


def check_project_names(names):
    for name in names or []:
        check_project_name(name)
        if name == "template_project":
            raise AwError(TEMPLATE_ERROR)


def resolve_project(name=None, write=False):
    if name:
        check_project_name(name)
        path = os.path.join(ROOT, "projects", name)
        if not os.path.isdir(path):
            raise AwError(f"No existe el proyecto '{name}'.")
        # Los comandos de escritura están preaprobados en cada proyecto: desde uno no se escribe en otro.
        current = find_project()
        if write and current and os.path.realpath(current) != os.path.realpath(path):
            raise AwError(f"Dentro del proyecto '{os.path.basename(current)}' no se escribe en '{name}': "
                          "ejecuta el comando desde ese proyecto o desde fuera de un proyecto.")
    else:
        path = find_project()
        if not path:
            raise AwError("No se está dentro de un proyecto aw (carpeta con state.md y tasks/). Usa --project NOMBRE.")
    if os.path.basename(path) == "template_project":
        raise AwError(TEMPLATE_ERROR)
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


# "pass" solo cuenta unido a otra palabra por _ . o - (DB_PASS, pass_file): suelto aparece en salidas de pruebas.
# Ante la duda se oculta de más: un nombre de archivo con una de estas palabras seguido de ":" también se tapa.
SENSITIVE_WORD = (r"(?:token|secret|passw(?:or)?d|pwd|api[_-]?key|access[_-]?key|private[_-]?key"
                  r"|[_.-]pass(?![A-Za-z])|(?<![A-Za-z])pass[_.-])")
SENSITIVE_KEY = r"[\w.-]{0,64}" + SENSITIVE_WORD + r"[\w.-]{0,64}"
AUTH_SCHEME = r"(?:bearer|basic|token|digest|negotiate|api-?key)"
REDACT_LIMIT = 2000  # caracteres que los hooks pasan a redact como máximo
# Entre comillas dobles se admiten comillas escapadas (\"), y también un valor entero entre
# comillas escapadas (\"con espacios\"), como queda dentro de otro texto entre comillas.
QUOTED_VALUE = r"""(?:"(?:[^"\\]|\\.)*"|\\"(?:[^\\"]|\\[^"])*\\"|'[^']*')"""
SECRET_VALUE = r"(?!\[oculto\])(?:" + QUOTED_VALUE + r"|\S+)"
OPTION_RE = re.compile(r"(?i)(?<![\w-])(--?[\w-]*" + SENSITIVE_WORD + r"[\w-]*)\s+(?!-)" + SECRET_VALUE)
OPTION_NOT_SECRET_RE = re.compile(r"-(?:prompt|limit|count|length|size|type|stdin|ttl)$", re.I)
LONG_STRING_RE = re.compile(r"(?<![A-Za-z0-9+/_-])[A-Za-z0-9+/_-]{32,}={0,2}(?![A-Za-z0-9+/_-])")


def mask_long_string(match):
    value = match.group(0)
    # Con "/" o "+" solo se oculta si parece base64 (mayúscula, minúscula y dígito): así las rutas largas se conservan.
    if re.search(r"[/+]", value) and not all(re.search(p, value) for p in (r"[A-Z]", r"[a-z]", r"\d")):
        return value
    return "[oculto]"


def mask_option(match):
    # --password x, --api-key x, --secret-key x. Las opciones que no llevan un secreto como valor se dejan.
    return match.group(0) if OPTION_NOT_SECRET_RE.search(match.group(1)) else match.group(1) + " [oculto]"


def redact(text):
    text = re.sub(r"(?i)\b(authorization)\\?[\"']?\s*[:=]\s*(?:" + QUOTED_VALUE + r"|(?:" + AUTH_SCHEME + r"\s+)?\S+)",
                  r"\1 [oculto]", text)
    text = re.sub(r"(?i)\b(bearer|basic)\s+\S+", r"\1 [oculto]", text)
    # La contraseña puede llevar / o @: se oculta hasta el último @ de la URL, aunque a veces tape de más.
    text = re.sub(r"(?i)(\b[a-z][a-z0-9+.-]*://)[^/\s:@]+:\S*@", r"\1[oculto]@", text)
    text = re.sub(r"(?i)([?&](?:" + SENSITIVE_KEY + r"|key|sig|signature))=[^&\s#]+", r"\1=[oculto]", text)
    text = re.sub(r"(?i)\b(" + SENSITIVE_KEY + r")\\?[\"']?\s*[=:]\s*" + SECRET_VALUE, r"\1 [oculto]", text)
    # Opciones de línea de comandos con el valor separado por un espacio.
    text = OPTION_RE.sub(mask_option, text)
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

def block_marks_ok(text):
    # Las marcas deben venir en parejas inicio…fin, en ese orden.
    marks = re.findall(re.escape(AUTO_START) + "|" + re.escape(AUTO_END), text)
    return len(marks) % 2 == 0 and all(mark == (AUTO_END if i % 2 else AUTO_START) for i, mark in enumerate(marks))


def replace_block(path, body, header=None):
    # Reemplaza lo que hay entre las marcas aw:auto; el resto del archivo es del usuario.
    block = f"{AUTO_START}\n{body}\n{AUTO_END}"
    text = read_text(path)
    if not block_marks_ok(text):
        return  # falta una marca: no se sabe dónde termina el bloque y se podría borrar texto del usuario
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
    with project_lock(ROOT):  # los índices del workspace los escriben varios proyectos a la vez
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
        dirs[:] = sorted(d for d in dirs if not d.startswith(".") and d not in HEAVY_DIRS)
        for fname in sorted(fnames):
            if fname == "context_index.json" or fname.endswith(".tmp") or fname.startswith(".") or ".bak-" in fname:
                continue
            full = os.path.join(dirpath, fname)
            rel = os.path.relpath(full, project).replace(os.sep, "/")
            try:
                info = os.stat(full)
            except OSError:
                continue  # enlace simbólico roto o archivo que desapareció: no se indexa
            mtime = datetime.datetime.fromtimestamp(info.st_mtime).strftime("%Y-%m-%d %H:%M")
            files[rel] = {"bytes": info.st_size, "modificado": mtime}
    path = pj(project, "context_index.json")
    try:
        current = json.loads(read_text(path) or "{}")
    except ValueError:
        current = {}
    current = as_dict(current)
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


def session_write(path, text):
    # Los temporales de sesión viven en un directorio compartido (/tmp): se crean sin seguir enlaces simbólicos
    # (O_EXCL y O_NOFOLLOW) y solo legibles por su dueño (0600).
    tmp = f"{path}.{os.getpid()}.tmp"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(tmp, flags, 0o600)
    except FileExistsError:  # sobra de un proceso anterior con el mismo PID, o un enlace plantado: se quita el enlace, no su destino
        os.unlink(tmp)
        fd = os.open(tmp, flags, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, path)


def session_append(path, text):
    fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0), 0o600)
    with os.fdopen(fd, "a", encoding="utf-8") as f:
        f.write(text)


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
    # Solo al reanudar o compactar se conserva el estado de la sesión; en cualquier otro caso es una sesión nueva
    # y se descarta lo que haya dejado una anterior que terminó sin SessionEnd.
    if not (payload.get("source") in ("resume", "compact") and load_session(key)):
        session_write(session_path(key, "json"), json.dumps({"hashes": watched_hashes(project), "reminded": False,
                                                             "inicio": now_str(), "inicio_ts": int(time.time())}))
        try:
            os.remove(session_path(key, "events"))
        except OSError:
            pass
    log_event(project, "sesión", f"iniciada ({payload.get('source') or 'startup'})")
    refresh_state(project)
    output = {"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": build_digest(project)}}
    print(json.dumps(output, ensure_ascii=False))


SESSION_FALLBACK_WINDOW = 600  # segundos hacia atrás que se miran si la sesión no pasó por SessionStart


def new_commits(cwd, since, seen):
    # Los commits que HEAD ganó desde `since` (segundos) según el reflog del repositorio de `cwd`, del más antiguo al
    # más reciente, sin los que ya están en `seen`. No interpreta el comando: así cuenta igual un `git commit`, un
    # alias, un merge o un cherry-pick, y no cuenta un `--dry-run`, un `--help` o un commit que falló.
    top = run_git(cwd, "rev-parse", "--show-toplevel")
    if not top or top.returncode != 0 or not top.stdout.strip():
        return []
    result = run_git(cwd, "log", "-g", "-n", "30", "--date=unix", "--format=%gd%x1f%gs%x1f%h %s")
    found = []
    for line in (result.stdout.splitlines() if result and result.returncode == 0 else []):
        parts = line.split("\x1f", 2)
        stamp = re.search(r"\{(\d+)\}$", parts[0])
        if len(parts) < 3 or not stamp:
            continue
        if int(stamp.group(1)) < since:
            break  # el reflog va del más reciente al más antiguo
        key = f"{top.stdout.strip()}:{stamp.group(1)}:{parts[2].split(' ', 1)[0]}"
        if COMMIT_REFLOG_RE.match(parts[1]) and key not in seen:
            found.append((key, parts[2]))
    return found[::-1]


def hook_post_tool(payload, project):
    tool = str(payload.get("tool_name") or "?")
    key = session_key(payload, project)
    events = session_path(key, "events")
    session_append(events, f"T {tool}\n")
    command = str((payload.get("tool_input") or {}).get("command") or "") if tool == "Bash" else ""
    if not re.search(r"\bgit\b", command):
        return  # sin git en el comando no se consulta el repositorio: el hook corre tras cada herramienta
    session = load_session(key)
    since = session.get("inicio_ts")
    started = isinstance(since, int)
    if not started:
        since = session["inicio_ts"] = int(time.time()) - SESSION_FALLBACK_WINDOW
    seen = as_list(session.get("commits_vistos"))
    cwd = payload.get("cwd") or project
    found = new_commits(cwd, since, seen)
    if os.path.realpath(cwd) != os.path.realpath(project):
        found += new_commits(project, since, seen + [k for k, _ in found])
    if not found and started:
        return
    for commit_key, summary in found:
        log_event(project, "commit", redact(summary[:REDACT_LIMIT]))
        session_append(events, "C\n")
        seen.append(commit_key)
    session["commits_vistos"] = seen[-200:]
    session_write(session_path(key, "json"), json.dumps(session))


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
    # Se acota antes de redact: sus patrones son costosos con líneas muy largas y el hook tiene un tiempo límite.
    append_text(pj(project, "execution", "errors.md"), f"- {now_str()} [{tool}] {redact(first[:REDACT_LIMIT])[:160]}\n")
    session_append(session_path(session_key(payload, project), "events"), "E\n")


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
        session_write(session_path(session_id, "json"), json.dumps(session))
        message = (f"aw: hubo {commits} commit(s) en esta sesión y no se registró ninguna decisión ni movimiento de tareas. "
                   "Si corresponde, usa `aw decide` o `aw task`.")
        print(json.dumps({"systemMessage": message}, ensure_ascii=False))


def append_month_log(project, text):
    logs = os.path.join(ROOT, "logs")
    path = os.path.join(logs, "current_month.md")
    month = today()[:7]
    with project_lock(ROOT):  # el registro mensual es compartido por todos los proyectos
        existing = read_text(path)
        header = re.match(r"# Registro de (\d{4}-\d{2})", existing)
        if header and header.group(1) != month:
            dest = os.path.join(logs, f"{header.group(1)}.md")
            if os.path.exists(dest):
                append_text(dest, re.sub(r"\A# Registro de \d{4}-\d{2}[^\n]*\n\n?", "", existing))  # sin repetir la cabecera
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
        # Primero el proyecto donde se abrió la sesión: el cwd del evento cambia si se hace cd a otra carpeta.
        session_dir = os.environ.get("CLAUDE_PROJECT_DIR")
        project = (find_project(session_dir) if session_dir else None) or find_project(payload.get("cwd") or os.getcwd())
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

HOOK_TAIL = r"""\s+hook\s+([a-z-]+)(?=$|[\s"';&|)])"""
HOOK_SCRIPT_RE = re.compile(r"""(?:^|[\s"'/\\])generate\.py["']?""" + HOOK_TAIL)
# El comando aw: suelto, con una ruta delante o con la ruta entre comillas (puede llevar espacios).
HOOK_WRAPPER_RES = (re.compile(r"""(?:^|[\s"';&|(])((?:[^\s"';&|()]*[/\\])?)aw["']?""" + HOOK_TAIL),
                    re.compile(r"""["']([^"']*[/\\])aw["']""" + HOOK_TAIL))


def is_wrapper_path(path):
    # Otro ejecutable llamado aw en otra ruta es del usuario: solo cuenta el comando que instala aw.
    installed = (os.path.expanduser(os.path.join("~", ".local", "bin", WRAPPER_NAME)), shutil.which(WRAPPER_NAME))
    real = os.path.realpath(os.path.expandvars(os.path.expanduser(path)))
    return any(candidate and os.path.realpath(candidate) == real for candidate in installed)


def hook_signature(command):
    # Solo reconoce los hooks de aw: generate.py o el comando aw, seguido de "hook <evento conocido>", con o sin
    # comillas alrededor (también dentro de bash -c "..."). Los demás devuelven None.
    command = str(command or "")
    events = [match.group(1) for match in HOOK_SCRIPT_RE.finditer(command)]
    for pattern in HOOK_WRAPPER_RES:
        events += [match.group(2) for match in pattern.finditer(command)
                   if not match.group(1) or is_wrapper_path(match.group(1) + WRAPPER_NAME)]
    return next((event for event in events if event in HOOK_EVENTS), None)


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
                             for h in as_list(g.get("hooks")) if isinstance(h, dict)]
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


def sync_settings(project, source_text, variables, dry_run, backup=True):
    dest = pj(project, ".claude", "settings.json")
    template = json.loads(render(source_text, variables, json_safe=True))
    if not os.path.exists(dest):
        if not dry_run:
            write_text(dest, json.dumps(template, indent=2, ensure_ascii=False) + "\n")
        return [("crear", ".claude/settings.json")]
    try:
        existing = json.loads(read_text(dest) or "{}")
    except AwEncodingError:
        return [("omitir", ".claude/settings.json (no está en UTF-8; no se toca)")]
    except ValueError:
        return [("omitir", ".claude/settings.json (JSON inválido; no se toca)")]
    if not isinstance(existing, dict):
        return [("omitir", ".claude/settings.json (no es un objeto JSON; no se toca)")]
    merged, notes = merge_settings(existing, template)
    if not notes:
        return []
    if not dry_run:
        if backup:
            backup_file(dest)
        write_text(dest, json.dumps(merged, indent=2, ensure_ascii=False) + "\n")
    return [("actualizar", ".claude/settings.json: " + "; ".join(notes))]


def template_overlay(template):
    # Lo que build() crearía o rellenaría en la plantilla del workspace, como {ruta relativa: texto}, sin
    # escribirlo: así el modo prueba compara contra la misma plantilla que usará la sincronización real.
    prefix = "projects/template_project"
    collected = {}
    build(template, as_dict(as_dict(load_structure().get("projects")).get("folders")).get("template_project"), prefix, collected)
    return {rel[len(prefix) + 1:]: text for rel, text in collected.items()}


def walk_order(rel):
    # El orden de os.walk: los archivos de una carpeta antes que sus subcarpetas.
    parts = rel.split("/")
    return [(1, part) for part in parts[:-1]] + [(0, parts[-1])]


def template_files(template):
    # Los archivos de la plantilla que aw gestiona, como (ruta relativa, ruta): solo .md y .json, sin respaldos.
    # Lo demás (un .DS_Store, una imagen) no se lee ni se lleva a los proyectos, tampoco a los nuevos.
    for dirpath, _dirs, files in os.walk(template):
        for fname in files:
            if is_text_file(fname) and ".bak-" not in fname:
                path = os.path.join(dirpath, fname)
                yield os.path.relpath(path, template).replace(os.sep, "/"), path


def template_sources(template, overlay=None):
    sources = {}
    for rel, source in template_files(template):
        if rel == ".claude/settings.json" and repo_settings_text().strip():
            sources[rel] = ""  # se usa el del repo: el de la plantilla no hace falta leerlo
            continue
        try:
            sources[rel] = read_text(source)
        except OSError:
            continue  # enlace en bucle o archivo sin permiso de lectura: no se usa
    sources.update(overlay or {})
    return sources


MIGRATION_FILE = "MIGRACION.md"


def migration_facts(project):
    # Lo que hay en una carpeta antes de que aw escriba nada en ella: sus archivos, si es un repositorio git y
    # desde cuándo existe. Las carpetas ocultas y las de dependencias no cuentan como archivos propios.
    count, oldest = 0, None
    for dirpath, dirs, fnames in os.walk(project):
        dirs[:] = [d for d in dirs if not d.startswith(".") and d not in HEAVY_DIRS]
        for fname in fnames:
            if fname.startswith("."):
                continue
            try:
                mtime = os.stat(os.path.join(dirpath, fname)).st_mtime
            except OSError:
                continue
            count += 1
            oldest = mtime if oldest is None else min(oldest, mtime)
    oldest_date = datetime.date.fromtimestamp(oldest).isoformat() if oldest is not None else None
    deps = [d for d in ("node_modules", "venv", ".venv") if os.path.isdir(pj(project, d))]
    git, first_commit = "no", None
    top = run_git(project, "rev-parse", "--show-toplevel")
    if top and top.returncode == 0 and top.stdout.strip():
        if os.path.realpath(top.stdout.strip()) == os.path.realpath(project):
            branch = run_git(project, "symbolic-ref", "--short", "-q", "HEAD")
            remote = run_git(project, "remote")
            name = branch.stdout.strip() if branch and branch.stdout.strip() else "(sin rama)"
            git = f"sí, rama {name}, " + ("con remoto" if remote and remote.stdout.strip() else "sin remoto")
            roots = run_git(project, "log", "--max-parents=0", "--format=%ad", "--date=short")
            dates = roots.stdout.split() if roots and roots.returncode == 0 else []
            first_commit = min(dates) if dates else None
        else:
            git = "sí, dentro de un repositorio superior"
    return {"propios": count, "antiguo": oldest_date, "dependencias": deps, "git": git,
            "inicio": min(first_commit or oldest_date or today(), today())}


def migration_text(name, project, facts, created, kept, merged_settings, origin=None):
    own = (f"{facts['propios']} (el más antiguo, del {facts['antiguo']})" if facts["propios"]
           else "ninguno (la carpeta estaba vacía)")
    deps = "sí (" + ", ".join(facts["dependencias"]) + ")" if facts["dependencias"] else "no"
    respected = ", ".join(f"`{rel}`" for rel in kept) if kept else "ninguno"
    lines = [
        f"# Migración de `{name}` — {today()}",
        "<!-- La escribió `aw sync` al convertir esta carpeta en un proyecto aw. La lista entre las marcas aw:auto dice "
        "qué archivos creó aw: no la edites, `aw doctor` la usa. El resto del archivo es tuyo. -->",
        "",
        "## Estado inicial",
        f"- Carpeta: `{os.path.relpath(project, ROOT).replace(os.sep, '/')}`",
        *([f"- Origen: `{origin}` (importada con `aw project import`)"] if origin else []),
        f"- Archivos propios: {own}",
        f"- Repositorio git: {facts['git']}",
        f"- Dependencias instaladas (node_modules, venv): {deps}",
        f"- Archivos propios con nombres que usa aw, respetados: {respected}",
        *(["- `.claude/settings.json` ya existía: aw le agrega sus hooks y permisos y guarda un respaldo al lado"]
          if merged_settings else []),
        "",
        "## Archivos creados por aw",
        AUTO_START,
        *[f"- `{rel}`" for rel in created],
        AUTO_END,
        "",
        "## Después de migrar",
        f"1. Ejecuta `aw doctor {name}`: revisa el resultado y, si el proyecto tiene git, da las líneas para que git "
        "ignore lo que agregó aw.",
        "2. Completa `project.md` (cliente, objetivo, alcance) y revisa la fecha de inicio: es una estimación, tomada "
        "del primer commit o del archivo más antiguo.",
        "3. Abre una sesión de Claude Code dentro del proyecto: el resumen del estado se carga solo.",
        "",
        "## Notas",
        "(incidencias de la migración y lo aprendido; lo completa quien migra)",
    ]
    return "\n".join(lines) + "\n"


def migration_created(project):
    # Los archivos que aw creó al migrar, según la lista de MIGRACION.md; [] si no hay ficha o no trae la lista.
    try:
        text = read_text(pj(project, MIGRATION_FILE))
    except AwError:
        return []
    match = re.search(re.escape(AUTO_START) + r"(.*?)" + re.escape(AUTO_END), text, re.S)
    found = re.findall(r"^- `(.+)`$", match.group(1), re.M) if match else []
    return [rel for rel in found if not os.path.isabs(rel) and ".." not in rel.split("/")]


def is_untouched_by_aw(project):
    # Una carpeta que aw todavía no convirtió en proyecto. No basta con que falte state.md: es un archivo
    # generado, que puede estar ignorado en git o haberse borrado en un proyecto que ya es de aw. Se miran archivos
    # con nombre propio de aw, no carpetas: un proyecto puede tener su tasks/ o su execution/ con otro uso.
    return not any(os.path.exists(pj(project, *rel.split("/")))
                   for rel in ("state.md", "tasks/backlog.md", "execution/run_log.md"))


def sync_project(project, sources, dry_run=False, origin=None):
    name = os.path.basename(project)
    variables = project_vars(name, "")
    migrating = is_untouched_by_aw(project)
    # Qué se va a hacer con cada archivo de la plantilla, antes de escribir nada.
    plan, kept, merged_settings = [], [], False
    for rel in sorted(sources, key=walk_order):
        dest = pj(project, *rel.split("/"))
        if rel == ".claude/settings.json":
            merged_settings = os.path.exists(dest)
            plan.append(("settings" if merged_settings else "crear", rel))
        elif not sources[rel].strip():
            continue  # la plantilla aún no tiene contenido para este archivo
        elif not os.path.exists(dest):
            plan.append(("crear", rel))
        elif os.path.getsize(dest) == 0:
            plan.append(("rellenar", rel))
        else:
            kept.append(rel)
    created = [rel for action, rel in plan if action == "crear"]
    ficha = pj(project, MIGRATION_FILE)
    write_ficha = migrating and bool(created) and not os.path.exists(ficha)  # una ficha que ya estaba es del usuario
    if migrating and not dry_run:
        # La ficha se escribe antes que los archivos: si la sincronización se corta, la lista de lo que crea aw
        # ya quedó guardada y repetir el comando completa lo que falte.
        facts = migration_facts(project)
        variables["DATE"] = facts["inicio"]
        if write_ficha:
            write_text(ficha, migration_text(name, project, facts, created, kept, merged_settings, origin))
    changes = []
    for action, rel in plan:
        if rel == ".claude/settings.json":
            changes += sync_settings(project, repo_settings_text() or sources[rel], variables, dry_run)
            continue
        changes.append((action, rel))
        if not dry_run:
            write_text(pj(project, *rel.split("/")), render(sources[rel], variables, json_safe=rel.lower().endswith(".json")))
    if write_ficha:
        changes.append(("crear", MIGRATION_FILE))
    if not dry_run:
        if migrating and changes:
            log_event(project, "nota", f"proyecto migrado a aw: {len(created)} archivo(s) creados, "
                                       f"{len(kept)} propio(s) respetado(s)")
        elif "proyecto migrado a aw" not in read_text(pj(project, "execution", "run_log.md")):
            listed = migration_created(project)  # una migración que se cortó antes de dejar su entrada en el registro
            if listed:
                log_event(project, "nota", f"proyecto migrado a aw: {len(listed)} archivo(s) creados")
    if not dry_run:
        refresh_state(project)
        refresh_artifact_indexes(project)
        refresh_context_index(project)
    return changes


def sync_projects(names=None, dry_run=False, workspace=False, origin=None):
    check_project_names(names)
    if not dry_run:
        build(ROOT, load_structure())
    return sync_from_template(os.path.join(ROOT, "projects", "template_project"), names, dry_run, workspace, origin)


def sync_from_template(template, names, dry_run, workspace, origin=None):
    if not dry_run and not os.path.isdir(template):
        raise AwError("No existe template_project. Ejecuta primero 'aw init'.")
    overlay = template_overlay(template) if dry_run else {}
    sources = template_sources(template, overlay)
    projects = names or list_projects()
    if dry_run:
        print("Modo prueba: no se cambia nada. Se muestra lo que haría 'aw sync'.")
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
              "no se gestiona, tampoco con --workspace. Si es una versión antigua del workspace, renómbralo y ejecuta 'aw init'.")
    settings_text = repo_settings_text()
    # En modo prueba, si build() crearía el settings de la plantilla, no hay nada que fusionar todavía.
    if settings_text.strip() and ".claude/settings.json" not in overlay:
        for change, rel in sync_settings(template, settings_text, project_vars("template_project", ""), dry_run):
            total += 1
            print(f"- plantilla: {change}: {rel}")
    for name in projects:
        path = os.path.join(ROOT, "projects", name)
        if not os.path.isdir(path):
            print(f"- {name}: no existe, se omite.")
            continue
        changes = sync_project(path, sources, dry_run, origin)
        total += len(changes)
        print(f"- {name}: " + (f"{len(changes)} cambio(s)" if changes else "al día"))
        for change, rel in changes:
            print(f"    {change}: {rel}")
        exposure = git_exposure(path) if changes and not dry_run else None
        if exposure and exposure["expuestos"]:
            print(f"    aviso: {len(exposure['expuestos'])} archivo(s) de aw no están ignorados por git; "
                  f"`aw doctor {name}` explica cómo ignorarlos solo en local.")
    if not dry_run:
        refresh_workspace_index()
        print("- workspace: índice de proyectos al día")
    print(f"Total: {total} cambio(s)" + (" (no aplicados)" if dry_run else "") + ".")


# -- Importar una carpeta y deshacer la sincronización --

def short_path(path):
    # Con ~ en lugar de la carpeta personal: la ruta queda escrita en archivos del proyecto.
    home = os.path.expanduser("~")
    return "~" + path[len(home):] if home != "~" and (path + os.sep).startswith(home + os.sep) else path


def confirm_name(name, yes):
    # Lo que mueve o borra pide escribir el nombre del proyecto; sin esa respuesta no se hace nada.
    if yes:
        return True
    try:
        return input(f"Escribe el nombre del proyecto ({name}) para confirmar: ").strip() == name
    except EOFError:
        return False


def import_project(source, name=None, dry_run=False, yes=False):
    given = os.path.abspath(os.path.expanduser(source or ""))
    if os.path.islink(given):
        raise AwError("La ruta es un enlace simbólico: indica la carpeta real.")
    if not os.path.isdir(given):
        raise AwError(f"No existe la carpeta: {given}")
    src, root = os.path.realpath(given), os.path.realpath(ROOT)
    if (src + os.sep).startswith(os.path.join(root, "projects") + os.sep):
        raise AwError("La carpeta ya está en projects/: usa 'aw sync NOMBRE' para sincronizarla.")
    if (root + os.sep).startswith(src + os.sep):
        raise AwError("La carpeta es el workspace o lo contiene: no se puede importar.")
    name = (name or os.path.basename(src)).strip()
    check_project_names([name])
    target = os.path.join(ROOT, "projects", name)
    if os.path.lexists(target):
        raise AwError(f"Ya existe projects/{name}: elige otro nombre con --name.")
    if not os.path.isdir(os.path.join(ROOT, "projects", "template_project")):
        raise AwError("No existe template_project. Ejecuta primero 'aw init'.")
    origin = short_path(src)
    facts = migration_facts(src)
    notes = []
    if facts["git"].endswith("repositorio superior"):
        notes.append("está dentro de un repositorio git superior: allí sus archivos quedarán como borrados")
    venvs = [d for d in facts["dependencias"] if "venv" in d]
    if venvs:
        notes.append(f"{', '.join(venvs)} lleva rutas absolutas y deja de funcionar al mover la carpeta: hay que crearlo de nuevo")
    if not is_untouched_by_aw(src):
        notes.append("ya tiene archivos de aw: se mueve y se sincroniza, sin ficha de migración")
    notes.append("la memoria y las sesiones de Claude Code de la ruta anterior no acompañan a la carpeta")
    print(f"Importar: {origin} -> projects/{name}")
    for note in notes:
        print(f"  aviso: {note}")
    if dry_run:
        print("Modo prueba: no se movió nada.")
        return 0
    if not confirm_name(name, yes):
        print("Cancelado: no se movió nada.")
        return 1
    try:
        os.rename(src, target)  # atómico; entre discos distintos falla en vez de copiar a medias
    except OSError as exc:
        if exc.errno == errno.EXDEV:
            raise AwError("La carpeta está en otro disco: muévela a mano a projects/ y ejecuta "
                          f"'aw sync {name}'.") from None
        raise AwError(f"No se pudo mover la carpeta: {exc.strerror or exc}") from None
    try:
        sync_projects([name], origin=origin)
        log_event(target, "nota", f"proyecto importado desde {origin}")
        refresh_state(target)
    except (AwError, OSError) as exc:
        raise AwError(f"La carpeta ya se movió a projects/{name}, pero la sincronización falló ({exc}). "
                      f"Repite 'aw sync {name}'.") from None
    print()
    doctor([name])
    return 0


MIGRATION_NOTES_PLACEHOLDER = "(incidencias de la migración y lo aprendido; lo completa quien migra)"
LOG_ARCHIVE = "execution/run_log_archivo.md"
# Archivos que solo escriben los hooks o aw sync: no llevan contenido del usuario.
AW_GENERATED = ("context_index.json", "execution/errors.md", "tools/tool_usage.md", "tools/tool_state.json")
# Entradas del registro que aw escribe solo; las de `aw log`, `aw decide` y las tareas son del usuario.
AUTO_LOG_RE = re.compile(r"- \d{4}-\d{2}-\d{2} \d{2}:\d{2} "
                         r"(?:\[(?:sesión|commit|compactación)\] |\[nota\] proyecto (?:migrado a aw|importado desde))")


def neutral(text):
    # Para comparar con la plantilla: sin el contenido de los bloques aw:auto ni las fechas, que aw escribe solo.
    text = re.sub(re.escape(AUTO_START) + r".*?" + re.escape(AUTO_END), AUTO_START + AUTO_END, text, flags=re.S)
    return re.sub(r"\d{4}-\d{2}-\d{2}", "FECHA", text).strip()


def without_auto_entries(text):
    return "\n".join(line for line in text.splitlines() if not AUTO_LOG_RE.match(line))


def unsync_status(project, rel, sources, variables):
    # None si el archivo ya no existe; "" si sigue como lo dejó aw; si no, el motivo por el que no se borra.
    path = pj(project, *rel.split("/"))
    if not os.path.lexists(path):
        return None
    inside = (os.path.realpath(path) + os.sep).startswith(os.path.realpath(project) + os.sep)
    if os.path.islink(path) or not os.path.isfile(path) or not inside:
        return "ya no es un archivo normal del proyecto"
    if rel in AW_GENERATED:
        return ""
    try:
        text = read_text(path)
    except AwError:
        return "no está en UTF-8"
    if rel == "state.md":
        return "" if state_is_auto(text) else "tiene texto manual"
    if rel == LOG_ARCHIVE:
        entries = [line for line in without_auto_entries(text).splitlines() if line.startswith("- ")]
        return "tiene notas o decisiones registradas" if entries else ""
    if rel == ".claude/settings.json":
        try:
            same = json.loads(text) == json.loads(render(repo_settings_text() or sources.get(rel, ""), variables, json_safe=True))
        except ValueError:
            same = False
        return "" if same else "difiere de lo que instala aw"
    if not sources.get(rel, "").strip():
        return "la plantilla actual no lo tiene: no se puede comparar"
    reason = "tiene contenido propio o es de una plantilla anterior"
    if rel == "execution/run_log.md":
        text, reason = without_auto_entries(text), "tiene notas o decisiones registradas"
    expected = render(sources[rel], variables, json_safe=rel.lower().endswith(".json"))
    return "" if neutral(text) == neutral(expected) else reason


def unsync_plan(project, created):
    sources = template_sources(os.path.join(ROOT, "projects", "template_project"))
    variables = project_vars(os.path.basename(project), "")
    listed = list(created)
    if "execution/run_log.md" in listed and LOG_ARCHIVE not in listed:
        listed.append(LOG_ARCHIVE)  # lo crea la rotación del registro, después de la migración
    delete, gone, changed = [], [], []
    for rel in listed:
        status = unsync_status(project, rel, sources, variables)
        if status is None:
            if rel != LOG_ARCHIVE:
                gone.append(rel)
        elif status:
            changed.append((rel, status))
        else:
            delete.append(rel)
    return delete, gone, changed


def unsync_project(name, dry_run=False, yes=False):
    check_project_names([name])
    project = resolve_project(name, write=True)
    created = migration_created(project)
    if not created:
        raise AwError(f"'{name}' no tiene {MIGRATION_FILE} con la lista de archivos creados por aw: "
                      "sin esa lista no se sabe qué existía antes y no se borra nada.")
    plan = unsync_plan(project, created)
    delete, gone, changed = plan
    print(f"Deshacer la sincronización de '{name}' (según {MIGRATION_FILE}):")
    for rel in delete:
        print(f"  borrar: {rel}")
    for rel in gone:
        print(f"  ya no existe: {rel}")
    for rel, reason in changed:
        print(f"  con cambios: {rel} ({reason})")
    if changed:
        print(f"{len(changed)} archivo(s) creados por aw tienen cambios: no se borra nada. Revísalos; "
              "si ya no los necesitas, bórralos a mano y repite el comando.")
        return 1
    if dry_run:
        print("Modo prueba: no se borró nada.")
        return 0
    if not confirm_name(name, yes):
        print("Cancelado: no se borró nada.")
        return 1
    ficha = pj(project, MIGRATION_FILE)
    with project_lock(project):
        if unsync_plan(project, created) != plan:
            raise AwError("El proyecto cambió mientras se esperaba la confirmación: no se borró nada. Repite el comando.")
        ficha_text = read_text(ficha)
        exposure = git_exposure(project, delete)
        for rel in delete:
            os.remove(pj(project, *rel.split("/")))
        # Las carpetas que quedaron vacías; rmdir no borra una carpeta con contenido.
        folders = {"/".join(rel.split("/")[:i]) for rel in delete + gone for i in range(1, len(rel.split("/")))}
        for folder in sorted(folders, key=lambda f: -f.count("/")):
            try:
                os.rmdir(pj(project, *folder.split("/")))
            except OSError:
                pass
        keep_ficha = MIGRATION_NOTES_PLACEHOLDER not in ficha_text
        if not keep_ficha:
            os.remove(ficha)
    print(f"{len(delete)} archivo(s) borrados. Lo que existía antes de la migración no se tocó.")
    if keep_ficha:
        print(f"- {MIGRATION_FILE} se conserva: tiene notas propias.")
    settings = pj(project, ".claude", "settings.json")
    if ".claude/settings.json" not in created and " hook " in read_text(settings):
        backups = sorted(n for n in os.listdir(os.path.dirname(settings)) if n.startswith("settings.json.bak-"))
        print("- .claude/settings.json ya existía y no se toca: conserva los hooks y permisos de aw. Para volver al "
              "original, restaura a mano el respaldo: "
              + (", ".join(f".claude/{n}" for n in backups) if backups else "(no hay respaldo al lado)") + ".")
    if exposure:
        if exposure["versionados"]:
            print(f"- aviso: {len(exposure['versionados'])} archivo(s) borrados estaban versionados en git "
                  f"({', '.join(exposure['versionados'])}): `git status` los muestra como borrados y "
                  "`git checkout -- <archivo>` los recupera.")
        print(f"- Si agregaste a {exposure['exclude']} las líneas que da `aw doctor`, ya puedes quitarlas.")
    try:
        refresh_workspace_index()
    except (OSError, AwError):  # el índice es secundario: lo borrado ya está borrado
        pass
    origin = re.search(r"^- Origen: `(.+?)`", ficha_text, re.M)
    hint = "."
    if origin:
        back = os.path.expanduser(origin.group(1))
        hint = (f": mv {sh_quote(project)} {sh_quote(back)}" if not os.path.lexists(back)
                else f" (su ubicación anterior, {origin.group(1)}, está ocupada).")
    print(f"- La carpeta sigue en projects/: el próximo `aw sync` sin nombres la volvería a convertir en proyecto aw. "
          f"Para evitarlo, sácala de projects/{hint}")
    return 0


# -- Diagnóstico --

def check(condition, ok_text, warn_text):
    return ("ok", ok_text) if condition else ("warn", warn_text)


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


# Archivos de aw que conviene no versionar en el repo git de un proyecto: son estado generado o llevan rutas
# absolutas de esta máquina. El contenido del usuario (tasks/, decisions.md, project.md...) no está aquí.
AW_LOCAL_FILES = (".claude/settings.json", "state.md", "context_index.json", "execution/run_log.md",
                  "execution/run_log_archivo.md", "execution/errors.md", "tools/tool_usage.md", "tools/tool_state.json",
                  "agents/assigned_agents.md", "skills/assigned_skills.md")


def run_git(project, *args):
    try:
        result = subprocess.run(["git", *args], cwd=project, capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return None
    return result if result.returncode in (0, 1) else None


def is_aw_claude_md(text):
    # El que genera aw empieza con "# CLAUDE.md — <proyecto>"; cualquier otro es propio del proyecto.
    return text.startswith("# CLAUDE.md — ")


def project_claude_md(project):
    try:
        return read_text(pj(project, "CLAUDE.md"))
    except AwError:
        return ""


def aw_local_files(project):
    # A la lista fija se suma el CLAUDE.md del proyecto solo si lo generó aw y contiene la ruta de este workspace
    # (los de una versión anterior la llevan); sin esa ruta, o si es propio, es contenido del proyecto.
    text = project_claude_md(project)
    return list(AW_LOCAL_FILES) + (["CLAUDE.md"] if is_aw_claude_md(text) and ROOT in text else [])


def git_exposure(project, files=None):
    # None si el proyecto no está en un repo git (o no hay git). Si lo está, clasifica los archivos de aw que
    # existen: "expuestos" (un `git add .` los incluiría) y "versionados". No escribe nada.
    info = run_git(project, "rev-parse", "--is-inside-work-tree", "--show-prefix", "--git-path", "info/exclude")
    lines = info.stdout.split("\n") if info else []
    if len(lines) < 3 or lines[0] != "true":
        return None
    candidates = aw_local_files(project) if files is None else files
    present = [f for f in candidates if os.path.isfile(pj(project, *f.split("/")))]
    claude_dir = pj(project, ".claude")
    if os.path.isdir(claude_dir):
        present += sorted(f".claude/{n}" for n in os.listdir(claude_dir) if n.startswith("settings.json.bak-"))
    tracked_run = run_git(project, "ls-files", "--", *present) if present else None
    tracked = set(tracked_run.stdout.split("\n")) if tracked_run else set()
    untracked = [f for f in present if f not in tracked]
    ignored_run = run_git(project, "check-ignore", "--", *untracked) if untracked else None
    ignored = set(ignored_run.stdout.split("\n")) if ignored_run else set()
    return {
        "total": len(present),
        "presentes": present,
        "versionados": [f for f in present if f in tracked],
        "expuestos": [f for f in untracked if f not in ignored],
        "prefijo": lines[1],
        "exclude": os.path.normpath(os.path.join(project, lines[2])),
    }


def exclude_patterns(prefix, files):
    patterns = []
    for f in files:
        pattern = "/" + prefix + (".claude/settings.json.bak-*" if f.startswith(".claude/settings.json.bak-") else f)
        if pattern not in patterns:
            patterns.append(pattern)
    return patterns


def doctor_git(project):
    local = aw_local_files(project)
    created = migration_created(project)
    # Con ficha de migración se mira también todo lo que creó aw, para poder ofrecer ignorarlo completo.
    others = sorted((set(created) | {MIGRATION_FILE}) - set(local)) if created else []
    exposure = git_exposure(project, local + others)

    def is_local(f):
        return f in local or f.startswith(".claude/settings.json.bak-")

    if exposure is None or not any(is_local(f) for f in exposure["presentes"]):
        return []
    exposed = [f for f in exposure["expuestos"] if is_local(f)]
    tracked = [f for f in exposure["versionados"] if is_local(f)]
    results = []
    if exposed:
        text = f"{len(exposed)} archivo(s) de aw no están ignorados por git y un `git add .` los incluiría: {', '.join(exposed)}."
        if any(f.startswith(".claude/settings.json") or "/assigned_" in f or f == "CLAUDE.md" for f in exposed):
            with_paths = ".claude/settings.json y las notas assigned_*"
            if "CLAUDE.md" in exposed:
                with_paths = ".claude/settings.json, las notas assigned_* y el CLAUDE.md"
            text += f"\n{with_paths} llevan rutas absolutas de tu máquina; el resto es estado generado."
        text += f"\nPara ignorarlos solo en local, añade estas líneas a {exposure['exclude']}:"
        text += "".join(f"\n  {pattern}" for pattern in exclude_patterns(exposure["prefijo"], exposed))
        text += "\ntasks/, decisions.md, project.md y el resto de tu contenido no están en la lista: versionarlos es decisión tuya."
        if created:
            # Archivo por archivo, sin carpetas enteras: lo que el usuario agregue después en ellas sigue a la vista.
            text += f"\nPara ignorar todo lo que agregó aw al migrar (según {MIGRATION_FILE}), usa estas líneas en su lugar:"
            text += "".join(f"\n  {pattern}" for pattern in exclude_patterns(exposure["prefijo"], exposure["expuestos"]))
    if tracked:
        results.append(("warn", f"{len(tracked)} archivo(s) de aw ya están versionados en git: {', '.join(tracked)}. "
                                f"Contienen rutas de tu máquina o son estado generado; para dejar de versionarlos usa "
                                f"`git rm --cached <archivo>` y añádelos a {exposure['exclude']}."))
    if exposed:
        results.insert(0, ("warn", text))
    if not exposed and not tracked:
        results.append(("ok", "archivos de aw ignorados por git"))
    return results


def doctor_project(project):
    results = []

    def add(level, text):
        results.append((level, text))

    template = os.path.join(ROOT, "projects", "template_project")
    fillable = set()  # archivos que aw sync rellena si están vacíos: los que la plantilla trae con contenido
    if os.path.isdir(template):
        missing = []
        for rel, source in template_files(template):
            try:
                if os.path.getsize(source):
                    fillable.add(rel)
            except OSError:
                continue  # enlace simbólico roto en la plantilla: sync tampoco lo copia
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
        dirs[:] = [d for d in dirs if not d.startswith(".") and d not in HEAVY_DIRS]
        for fname in files:
            full = os.path.join(dirpath, fname)
            rel = os.path.relpath(full, project).replace(os.sep, "/")
            try:
                size = os.path.getsize(full)
            except OSError:
                continue  # enlace simbólico roto o archivo que desapareció
            if size == 0:
                if rel in fillable:
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
        try:
            age = (datetime.date.today() - datetime.date.fromisoformat(last.group(1))).days if last else 0
        except ValueError:
            age = None
        if age is None:
            add("warn", "la última entrada del registro tiene una fecha inválida")
        else:
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
            if not isinstance(settings, dict):
                settings = None
                add("bad", ".claude/settings.json no es un objeto JSON")
        except AwEncodingError:
            settings = None
            add("bad", ".claude/settings.json no está en UTF-8")
        except ValueError:
            settings = None
            add("bad", ".claude/settings.json tiene JSON inválido")
        if settings is not None:
            hooks = as_dict(settings.get("hooks"))
            commands = [str(h.get("command") or "") for groups in hooks.values() if isinstance(groups, list)
                        for g in groups if isinstance(g, dict) for h in as_list(g.get("hooks")) if isinstance(h, dict)]
            present = {hook_signature(c) for c in commands}
            absent = [e for e in HOOK_EVENTS if e not in present]
            add("bad" if absent else "ok", ("faltan hooks: " + ", ".join(absent)) if absent else "hooks de aw instalados")
            for command in commands:
                match = re.search(r'"((?:[^"\\]|\\.)*generate\.py)"', command)
                if match and not os.path.exists(re.sub(r"\\(.)", r"\1", match.group(1))):
                    add("bad", f"un hook apunta a un script que no existe: {match.group(1)}")
                    break
            allow = as_list(as_dict(settings.get("permissions")).get("allow"))
            need = [p for p in ("Bash(aw task *)", "Bash(aw decide *)", "Bash(aw log *)") if p not in allow]
            add("warn" if need else "ok", ("faltan permisos: " + ", ".join(need)) if need else "permisos de aw presentes")

    for name in ARTIFACT_INDEX_FILES:
        if not block_marks_ok(read_text(pj(project, "artifacts", name))):
            add("warn", f"marcas aw:auto desparejas en artifacts/{name}: aw no lo actualiza hasta que estén las dos")

    for level, text in doctor_git(project):
        add(level, text)

    own_claude_md = os.path.exists(pj(project, "CLAUDE.md")) and not is_aw_claude_md(project_claude_md(project))
    add(*check(os.path.exists(pj(project, "CLAUDE.md")),
               "CLAUDE.md del proyecto presente" + (" (propio, no generado por aw)" if own_claude_md else ""),
               "falta el CLAUDE.md del proyecto (aw sync lo crea)"))

    for folder, label in (("agents", "agentes"), ("skills", "skills")):
        notes = pj(project, folder, f"assigned_{folder}.md")
        for cells in markdown_rows(read_text(notes)):
            # Se acepta el nombre del archivo, la ruta desde la raíz (agents/x.md), una ruta absoluta o con ~,
            # y cualquiera de ellas entre comillas invertidas.
            name = cells[1].strip("`").strip() if len(cells) >= 2 else ""
            if not name or name == "(completar)":
                continue
            target = os.path.expanduser(name)
            inside = True
            if not os.path.isabs(target):
                base = os.path.join(ROOT, folder)
                relative = target[len(folder) + 1:] if target.startswith(folder + "/") else target
                target = os.path.normpath(os.path.join(base, relative))
                inside = target.startswith(base + os.sep)  # un archivo dentro de la carpeta, no la carpeta ni otra
            if not inside or not os.path.exists(target):
                add("bad", f"{label} asignados: no existe {name} (fila '{cells[0]}')")

    mcp_names = set()
    try:
        mcp = json.loads(read_text(pj(project, ".mcp.json")) or "{}")
        mcp_names = {k.lower() for k in as_dict(as_dict(mcp).get("mcpServers"))}
    except ValueError:
        pass
    for cells in markdown_rows(read_text(pj(project, "tools", "assigned_tools.md"))):
        if len(cells) >= 3 and cells[0] and cells[0] != "(completar)" and ".mcp.json" in cells[2].lower():
            if cells[0].lower() not in mcp_names:
                add("warn", f"herramienta '{cells[0]}' declarada en .mcp.json pero no figura ahí")
    return results


def doctor(names=None):
    check_project_names(names)
    symbols = {"ok": "✓", "warn": "▲", "bad": "✕"}
    counts = {"ok": 0, "warn": 0, "bad": 0}
    print("aw doctor")
    global_checks = [
        check(shutil.which(WRAPPER_NAME), "comando 'aw' en el PATH", "el comando 'aw' no está en el PATH (opción 9 del menú)"),
        check(os.path.exists(os.path.join(ROOT, "CLAUDE.md")), "CLAUDE.md del workspace presente", "falta el CLAUDE.md del workspace (aw init lo crea)"),
    ]
    action, _detail = ensure_workspace_claude_md(dry_run=True)
    if action in ("actualizar", "difiere"):
        global_checks.append(("warn", "el CLAUDE.md del workspace difiere de la plantilla (aw sync --workspace)"))
    elif action == "ajeno":
        global_checks.append(("warn", "el CLAUDE.md de la raíz no es el del workspace aw: aw no lo gestiona "
                                      "(si es una versión antigua, renómbralo y ejecuta aw init)"))
    try:
        indexed = set(as_dict(json.loads(read_text(os.path.join(ROOT, "memory", "context_index.json")) or "{}").get("proyectos")))
    except (ValueError, AttributeError):
        indexed = None
    if indexed is None:
        global_checks.append(("warn", "memory/context_index.json es inválido (aw sync no lo toca mientras esté roto)"))
    else:
        absent = set(list_projects()) - indexed
        global_checks.append(("warn", f"el índice de proyectos no incluye {len(absent)} proyecto(s) (aw sync)") if absent
                             else ("ok", "índice de proyectos al día"))
    if not block_marks_ok(read_text(os.path.join(ROOT, "memory", "projects", "project_index.md"))):
        global_checks.append(("warn", "marcas aw:auto desparejas en memory/projects/project_index.md: aw no lo actualiza hasta que estén las dos"))
    month_log = read_text(os.path.join(ROOT, "logs", "current_month.md"))
    if month_log.strip() and not re.match(r"# Registro de \d{4}-\d{2}", month_log):
        global_checks.append(("warn", "logs/current_month.md no empieza con '# Registro de AAAA-MM': no rota al cambiar de mes"))
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
            print(f"  {symbols[level]} " + text.replace("\n", "\n    "))
    print(f"\nResumen: {counts['ok']} bien, {counts['warn']} por revisar, {counts['bad']} pendientes")
    return 1 if counts["bad"] else 0


# -- Instalación del comando en el sistema --

def is_aw_wrapper(path):
    try:
        with open(path, "rb") as f:
            head = f.read(4096)
    except OSError:
        return False
    return head.startswith(b"#!/bin/sh\nexec python3 ") and b'generate.py" "$@"' in head


def action_install_command():
    if sys.platform.startswith("win"):
        print("El instalador todavía no soporta Windows. Por ahora usa 'python3 generate.py' directamente.")
        return
    bin_dir = os.path.expanduser("~/.local/bin")
    os.makedirs(bin_dir, exist_ok=True)
    wrapper_path = os.path.join(bin_dir, WRAPPER_NAME)
    script_path = os.path.abspath(__file__)
    if os.path.lexists(wrapper_path) and not is_aw_wrapper(wrapper_path):
        answer = input(f"Ya existe {wrapper_path} y no es el comando de aw. ¿Reemplazarlo? (s/n): ").strip().lower()
        if answer != "s":
            print("No se instaló: el archivo que ya estaba queda como estaba.")
            return
    # write_text reemplaza el archivo: si en ese lugar hay un enlace simbólico, no escribe a través de él.
    write_text(wrapper_path, f'#!/bin/sh\nexec python3 {sh_quote(script_path)} "$@"\n')
    st = os.stat(wrapper_path)
    os.chmod(wrapper_path, st.st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    print(f"Comando '{WRAPPER_NAME}' instalado en {wrapper_path}")

    path_dirs = os.environ.get("PATH", "").split(os.pathsep)
    if bin_dir not in path_dirs:
        print(f"\n{bin_dir} todavía no está en tu PATH.")
        print("Agrega esta línea a tu ~/.bashrc o ~/.zshrc y abre una terminal nueva:\n")
        print('  export PATH="$HOME/.local/bin:$PATH"\n')
    else:
        print(f"Ya puedes usar el comando '{WRAPPER_NAME}' desde cualquier carpeta.")


# -- Actualización de aw desde su repositorio --

def repo_git(*args, timeout=60):
    try:
        return subprocess.run(["git", *args], cwd=HERE, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError):
        return None


def repo_git_out(*args):
    result = repo_git(*args)
    return result.stdout.strip() if result and result.returncode == 0 else None


def update_aw(dry_run=False):
    # Trae lo nuevo del remoto que ya tiene configurado el clon, solo si es un avance directo, y sincroniza con
    # el código nuevo. Nunca mezcla ni descarta nada: ante cambios locales o historias distintas, se niega.
    manual = "Actualiza a mano: descarga la versión nueva del repositorio y reemplaza los archivos de aw."
    top = repo_git_out("rev-parse", "--show-toplevel")
    if top is None or os.path.realpath(top) != os.path.realpath(HERE):
        raise AwError(f"La carpeta de aw ({HERE}) no es un clon de git: no se puede actualizar sola. {manual}")
    branch = repo_git_out("symbolic-ref", "--short", "-q", "HEAD")
    upstream = repo_git_out("rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}") if branch else None
    if not upstream:
        raise AwError(f"La rama actual de aw ({branch or 'sin rama'}) no sigue a ninguna rama remota: "
                      "no hay de dónde actualizar. Cambia a la rama principal y repite.")
    if repo_git_out("status", "--porcelain", "--untracked-files=no"):
        raise AwError(f"Hay cambios locales sin guardar en {HERE}: no se actualiza para no mezclarlos. "
                      "Guárdalos en un commit o descártalos y repite.")
    remote = upstream.split("/", 1)[0]
    fetched = repo_git("fetch", "--quiet", remote, timeout=120)
    if fetched is None or fetched.returncode != 0:
        detail = first_line(fetched.stderr) if fetched else "git no respondió"
        raise AwError(f"No se pudo consultar el repositorio remoto ({remote}): {detail}")
    behind = int(repo_git_out("rev-list", "--count", "HEAD..@{u}") or 0)
    ahead = int(repo_git_out("rev-list", "--count", "@{u}..HEAD") or 0)
    current = repo_git_out("rev-parse", "--short", "HEAD")
    if not behind:
        print(f"aw ya está al día ({current}, rama {branch})."
              + (f" Hay {ahead} commit(s) locales sin publicar." if ahead else ""))
        return 0
    if ahead:
        raise AwError(f"La instalación tiene {ahead} commit(s) propios y el remoto {behind} nuevos: las historias "
                      "se separaron y aw no las mezcla. Resuélvelo con git y repite.")
    print(f"Hay {behind} commit(s) nuevos en {upstream}:")
    lines = (repo_git_out("log", "--oneline", "--no-decorate", "HEAD..@{u}") or "").splitlines()
    for line in lines[:20]:
        print(f"  {line}")
    if len(lines) > 20:
        print(f"  ... y {len(lines) - 20} más")
    if dry_run:
        print("Modo prueba: no se actualizó nada.")
        return 0
    merged = repo_git("merge", "--ff-only", "--quiet", "@{u}")
    if merged is None or merged.returncode != 0:
        detail = first_line(merged.stderr) if merged else "git no respondió"
        raise AwError(f"No se pudo aplicar la actualización: {detail}")
    print(f"aw actualizado: {current} -> {repo_git_out('rev-parse', '--short', 'HEAD')}. Sincronizando con la versión nueva:")
    sys.stdout.flush()
    # Este proceso sigue siendo el código anterior: la sincronización se lanza aparte para usar el nuevo.
    return subprocess.run([sys.executable, os.path.abspath(__file__), "sync"]).returncode


def action_update():
    answer = input("¿Solo mostrar si hay novedades, sin actualizar? (s/n): ").strip().lower()
    try:
        update_aw(dry_run=(answer != "n"))
    except AwError as exc:
        print(exc)


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
        choice = input("Elige una opción: ").strip()
        print()
        try:
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
            elif choice == "12":
                action_update()
            elif choice == "0":
                print("Hasta luego.")
                break
            else:
                print("Opción inválida.")
        except AwError as exc:
            print(exc)


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
    imp = project_sub.add_parser("import", help="mueve una carpeta a projects/, la sincroniza y la diagnostica")
    imp.add_argument("path")
    imp.add_argument("--name", default=None, help="nombre del proyecto (por defecto, el de la carpeta)")
    imp.add_argument("--dry-run", action="store_true", help="muestra lo que haría sin mover nada")
    imp.add_argument("--yes", action="store_true", help="no pide confirmación")

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

    unsync = sub.add_parser("unsync", help="deshace la sincronización: borra lo que creó aw si sigue sin cambios")
    unsync.add_argument("name")
    unsync.add_argument("--dry-run", action="store_true", help="muestra lo que haría sin borrar nada")
    unsync.add_argument("--yes", action="store_true", help="no pide confirmación")

    update = sub.add_parser("update", help="actualiza aw desde su repositorio y sincroniza los proyectos")
    update.add_argument("--dry-run", action="store_true", help="muestra si hay novedades sin actualizar")

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
        if args.pcmd == "import":
            return import_project(args.path, args.name, args.dry_run, args.yes)
        if args.pcmd != "new":
            raise AwError("Uso: aw project new NOMBRE [--desc TEXTO] | aw project import RUTA [--name NOMBRE]")
        target = create_project(args.name, args.desc)
        print(f"Proyecto creado: {target}")
    elif args.cmd == "task":
        if not args.tcmd:  # sin subcomando, args no trae --project
            raise AwError("Uso: aw task add|start|done|list")
        project = resolve_project(args.project, write=args.tcmd != "list")
        if args.tcmd == "add":
            task_id, prio = task_add(project, " ".join(args.title), args.prio)
            print(f"{task_id} creada [{prio}]")
        elif args.tcmd == "start":
            task = task_start(project, args.id)
            print(f"{normalize_task_id(args.id)} en curso: {clean_title(task['title'])}")
        elif args.tcmd == "done":
            task = task_done(project, args.id)
            print(f"{normalize_task_id(args.id)} hecha: {clean_title(task['title'])}")
        else:
            print_tasks(project, args.all)
    elif args.cmd == "decide":
        project = resolve_project(args.project, write=True)
        decide(project, " ".join(args.title), args.why, args.alt)
        print("Decisión registrada.")
    elif args.cmd == "log":
        project = resolve_project(args.project, write=True)
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
    elif args.cmd == "unsync":
        return unsync_project(args.name, args.dry_run, args.yes)
    elif args.cmd == "update":
        return update_aw(args.dry_run)
    elif args.cmd == "doctor":
        return doctor(args.names or None)
    return 0


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if not argv:
        try:
            main_menu()
        except EOFError:
            print("\nHasta luego.")  # Ctrl-D o entrada sin terminal: se sale como con la opción 0
        except KeyboardInterrupt:
            print("\nInterrumpido.")
            return 130
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
