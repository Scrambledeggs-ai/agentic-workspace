import os
import sys
import json
import shutil
import stat

ROOT = os.path.dirname(os.path.abspath(__file__))
STRUCTURE_FILE = os.path.join(ROOT, "structure.json")
WRAPPER_NAME = "aw"

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
0) Salir
"""


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


def build(path, node, rel=""):
    if not isinstance(node, dict):
        return

    for filename in node.get("files", []):
        filepath = os.path.join(path, filename)
        relpath = os.path.join(rel, filename).replace(os.sep, "/")
        if not os.path.exists(filepath):
            with open(filepath, "w") as f:
                if relpath in DEFAULT_HEADERS:
                    name, desc = DEFAULT_HEADERS[relpath]
                    f.write(make_header(name, desc))

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


def action_new_project():
    template = os.path.join(ROOT, "projects", "template_project")
    if not os.path.isdir(template):
        print("No existe template_project. Corré primero 'Iniciar / actualizar estructura del sistema'.")
        return
    name = input("Nombre del proyecto: ").strip()
    if not name:
        print("Nombre vacío, se cancela.")
        return
    target = os.path.join(ROOT, "projects", name)
    if os.path.exists(target):
        print("Ya existe un proyecto con ese nombre.")
        return
    description = input("Descripción breve (opcional): ").strip()
    shutil.copytree(template, target)
    with open(os.path.join(target, "project.md"), "w") as f:
        f.write(f"# {name}\n\n{description}\n")
    with open(os.path.join(target, "state.md"), "w") as f:
        f.write("Estado: iniciado\n")
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
        elif choice == "0":
            print("Hasta luego.")
            break
        else:
            print("Opción inválida.")


if __name__ == "__main__":
    main_menu()
