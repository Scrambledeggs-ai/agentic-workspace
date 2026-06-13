# Agentic Workspace

Proyecto de scripts en Python para automatización y pruebas locales.

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
├── generate.py
├── structure.json
├── .gitignore
└── README.md
```

---

## Ejecución

Ejecutar el script principal:

```bash
python3 generate.py
```
## Crear nuevo proyecto

Este comando crea un nuevo proyecto dentro de `projects/` replicando la plantilla `template_project`.

```bash
python3 generate.py new <nombre_del_proyecto>
---

> Nota: El comando debe ejecutarse desde la carpeta raíz del proyecto donde se encuentra `generate.py`.
---

## Descripción

Este proyecto contiene scripts básicos en Python para generación y manejo de estructuras de datos utilizando la configuración definida en `structure.json`.

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

## Autor

Scrambledeggs-ai
