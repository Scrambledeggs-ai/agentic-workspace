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
├── generate.py
├── structure.json
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
