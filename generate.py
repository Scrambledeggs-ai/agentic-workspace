import os
import json
import sys
import shutil

def build(path, node):

    if not isinstance(node, dict):
        return

    for filename in node.get("files", []):
        filepath = os.path.join(path, filename)
        with open(filepath, "w"):
            pass

    for folder_name, folder_content in node.get("folders", {}).items():
        folder_path = os.path.join(path, folder_name)
        os.makedirs(folder_path, exist_ok=True)
        build(folder_path, folder_content)

    for key, value in node.items():
        if key in ["files", "folders"]:
            continue
        subdir = os.path.join(path, key)
        os.makedirs(subdir, exist_ok=True)
        build(subdir, value)


def load_structure():
    with open("structure.json", "r") as f:
        return json.load(f)


def init():
    structure = load_structure()
    build(".", structure)
    print("Estructura creada")


def new_project(name):
    template = "projects/template_project"
    target = f"projects/{name}"

    if not os.path.exists(template):
        print("No existe template_project")
        return

    if os.path.exists(target):
        print("El proyecto ya existe")
        return

    shutil.copytree(template, target)
    print(f"Proyecto creado: {name}")


if __name__ == "__main__":

    if len(sys.argv) == 1:
        init()

    elif sys.argv[1] == "new":
        if len(sys.argv) < 3:
            print("Uso: python3 generate.py new <nombre>")
        else:
            new_project(sys.argv[2])

    else:
        print("Comandos: init | new <name>")
