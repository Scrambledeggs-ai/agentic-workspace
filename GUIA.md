# Guía de uso de un proyecto aw

*Apéndice del manual. Explica qué completar al crear un proyecto y qué hacer mientras se trabaja en él, con
ejemplos para cada campo.*

Los ejemplos usan un proyecto inventado: la web de una panadería, **Panadería La Espiga**. En cada campo hay uno
o dos ejemplos, como en un formulario, para que quede claro qué tipo de dato va. Reemplázalos por los de tu
proyecto.

---

## Cómo funciona, en pocas palabras

En un proyecto aw hay tres tipos de información, y cada uno lo escribe alguien distinto:

1. **Lo que aw anota solo.** Cada sesión de Claude Code, cada commit y cada error de una herramienta quedan
   registrados sin que hagas nada. Con eso aw mantiene al día un resumen del estado del proyecto.
2. **Lo que Claude registra con comandos.** Las tareas, las decisiones y las notas se guardan con `aw task`,
   `aw decide` y `aw log`. Normalmente lo hace Claude mientras trabaja; tú también puedes usarlos.
3. **Lo que escribes tú.** Quién es el cliente, qué se busca, cómo hay que trabajar. Esto aw no lo puede adivinar,
   y es lo que más ayuda a que Claude entienda el proyecto.

Esta guía trata sobre todo del tercer tipo. Los campos que esperan un dato tuyo dicen `(completar)`. Si un campo
no aplica a tu proyecto, escribe **no aplica**: así `aw doctor` deja de contarlo como pendiente.

---

## Etapa 1: proyecto nuevo

Se crea con un comando:

```bash
aw project new panaderia-web --desc "Web de Panadería La Espiga con catálogo y pedidos"
```

Después, completa en este orden. Los dos primeros son imprescindibles; el resto, solo si tu proyecto lo usa.

- [ ] `project.md`: la ficha del proyecto
- [ ] `CLAUDE.md` del proyecto: el contexto para Claude
- [ ] `agents/`: solo si usas agentes propios
- [ ] `skills/`: solo si usas skills propias
- [ ] `tools/assigned_tools.md`: solo si dependes de conectores o servicios externos
- [ ] `sop/`: solo si el trabajo sigue un procedimiento fijo
- [ ] `aw doctor panaderia-web` para comprobar qué quedó sin completar

### 1. `project.md`: la ficha del proyecto

Es la identidad del proyecto. Claude la lee al empezar cada sesión, así que conviene que sea breve y exacta.

| Campo | Qué poner | Ejemplos |
|---|---|---|
| Cliente / responsable | Para quién es y quién decide | «Panadería La Espiga (Laura Gómez, dueña)» · «Proyecto propio» |
| Objetivo en una línea | El resultado que se busca, no las tareas | «Web con catálogo y pedidos por WhatsApp» · «Automatizar la facturación mensual» |
| Alcance | Qué incluye y qué no | «Incluye diseño, desarrollo y publicación; no incluye fotos ni mantenimiento» |
| Fecha de inicio | La pone aw al crear el proyecto | — |
| Estado general | arrancando, en curso o mantenimiento | «en curso» |

La línea que está bajo el título es la descripción que diste con `--desc`. Puedes cambiarla cuando quieras.

Así queda completo:

```markdown
# panaderia-web

Web de Panadería La Espiga con catálogo y pedidos

## Identidad
- Cliente / responsable: Panadería La Espiga (Laura Gómez, dueña)
- Objetivo en una línea: Web con catálogo y pedidos por WhatsApp
- Alcance: Incluye diseño, desarrollo y publicación; no incluye fotos ni mantenimiento
- Fecha de inicio: 2026-10-17
- Estado general (arrancando / en curso / mantenimiento): arrancando
```

### 2. `CLAUDE.md` del proyecto: el contexto para Claude

Claude Code lo carga en cada sesión. Aquí va lo que Claude necesita saber de **este** proyecto y no puede deducir
de los archivos. No repitas tus reglas generales: esas van en tu `CLAUDE.md` global.

| Campo | Qué poner | Ejemplos |
|---|---|---|
| Datos propios del negocio | Rubro, clientes, competencia, lo que lo hace distinto | «Panadería artesanal de barrio con dos locales; compite con las cadenas de supermercado» |
| Idioma de salida | En qué idioma se escribe lo que se entrega | «Español neutro» · «Código en inglés, textos en español» |
| Restricciones o reglas del cliente | Tono, temas a evitar, límites | «Tono cercano y sin tecnicismos; no publicar precios en la web» |
| Dónde están los inputs | Dónde están los briefs, datos y archivos del cliente | «Carpeta `inputs/` del proyecto» · «Carpeta compartida "Espiga" en Google Drive» |
| Glosario | Términos, siglas o nombres internos | «MM: masa madre» · «Pedido mayorista: más de 20 unidades» |

Las líneas que dicen «Ver @project.md» o «ver `execution/decisions.md`» ya están bien: no hay que tocarlas.

### 3. `memory.md`: lo que Claude debe recordar

Empieza vacío y se completa con el uso, una línea por dato y con fecha. Sirve para hechos que no cambian y que
Claude necesita tener presentes.

```markdown
- 2026-10-17 La web se publica en Vercel con el dominio laespiga.example
- 2026-10-20 El cliente aprueba los cambios solo por correo
```

No confundirlo con otros archivos: una **decisión** («elegimos Vercel en vez de Netlify porque…») va con
`aw decide`, y algo **por hacer** va con `aw task`. En `memory.md` va solo el dato que queda.

### 4. Agentes propios (solo si los usas)

Un agente propio es un archivo de instrucciones guardado en la carpeta `agents/` de la raíz del workspace (por
ejemplo `2_agente_redactor.md`). No vive dentro del proyecto: el proyecto solo indica cuál usa y para qué.

**`agents/assigned_agents.md`**: una fila por tarea.

| Columna | Qué poner | Ejemplo |
|---|---|---|
| Tarea | Para qué se usa el agente | «Redactar los textos de la web» |
| Agente (archivo) | El nombre del archivo en `agents/` de la raíz | «2_agente_redactor.md» |
| Notas | Cualquier aclaración | «Revisar el tono con la clienta antes de publicar» |

**`agents/agent_context.md`**: los datos del proyecto que los agentes usan. Si el archivo de un agente dice
`{{business_name}}`, Claude pone ahí el valor que escribas en este archivo.

| Campo | Ejemplos |
|---|---|
| agent_name | «Asistente de La Espiga» |
| business_name | «Panadería La Espiga» |
| tono | «Cercano y cálido» · «Formal» |
| idioma | «Español neutro» |

Si el proyecto no usa agentes propios, escribe **no aplica** en estos campos.

### 5. Skills propias (solo si las usas)

Funciona igual que los agentes, con la carpeta `skills/` de la raíz del workspace.

Una aclaración: las skills que ya trae Claude Code o que instalaste en Claude Code aparecen solas y **no hace falta
registrarlas aquí**. Este archivo es solo para las skills que guardas en la carpeta `skills/` del workspace.

**`skills/assigned_skills.md`**

| Columna | Ejemplo |
|---|---|
| Tarea | «Revisar todo antes de publicar» |
| Skill (archivo o carpeta) | «prelanzamiento/» |
| Notas | «Correrla antes de cada entrega al cliente» |

**`skills/skill_context.md`**

| Campo | Ejemplos |
|---|---|
| cliente | «Panadería La Espiga» |
| idioma | «Español neutro» |
| formato_de_salida | «Markdown» · «PDF con el logo del cliente» |

### 6. Conectores y servicios externos (solo si los usas)

**`tools/assigned_tools.md`** lista los servicios de los que depende el proyecto. Es una nota: la configuración
real está en `.mcp.json` o en los conectores de Claude.

| Columna | Qué poner | Ejemplos |
|---|---|---|
| Herramienta o conector | Su nombre | «vercel» · «Google Drive» |
| Para qué se usa | Qué hace en este proyecto | «Publicar la web» · «Recibir las fotos del cliente» |
| Dónde se configura | Dónde está la configuración | «.mcp.json» · «Conectores de claude.ai» |

Si en la tercera columna escribes `.mcp.json`, `aw doctor` comprueba que el conector esté de verdad en ese archivo.

### 7. Procedimientos: `sop/` (solo si hay un modo de trabajo fijo)

Claude no carga estos archivos en cada sesión: los lee cuando la tarea lo necesita. Por eso conviene que sean
concretos.

**`sop/workflow.md`**: los pasos, en orden.

```markdown
1. Recibir el pedido de cambio por correo.
2. Hacer el cambio en una rama y publicar una vista previa.
3. Enviar el enlace de la vista previa a la clienta.
4. Publicar solo después de su aprobación por escrito.
```

**`sop/rules.md`**: lo obligatorio y lo prohibido.

| Sección | Ejemplos |
|---|---|
| Obligatorio | «Toda foto lleva texto alternativo» · «Probar en un teléfono antes de publicar» |
| Prohibido | «Publicar precios» · «Usar fotos de bancos de imágenes» |

**`sop/conventions.md`**: nombres, formatos y estilo.

| Campo | Ejemplos |
|---|---|
| Nombres de archivos | «AAAA-MM-DD-tema.md» · «minúsculas y guiones» |
| Formato de entregables | «PDF en A4» · «Enlace a la vista previa» |
| Estilo de redacción | «Frases cortas, sin jerga técnica» |

Si necesitas otro procedimiento, crea un archivo nuevo en `sop/` y nómbralo en `sop/README.md`.

### Lo que no se toca

aw mantiene estos archivos solo. Si los editas a mano, tus cambios se pierden o confunden al sistema:

`state.md` · `tasks/` · `execution/` · `tools/tool_usage.md` · `tools/tool_state.json` · `context_index.json` ·
`.claude/settings.json` · lo que está entre las marcas `aw:auto` de `artifacts/`

Las tareas y las decisiones sí se pueden cambiar, pero siempre con los comandos `aw task` y `aw decide`, no
editando los archivos.

### Comprobar

```bash
aw doctor panaderia-web
```

La línea «campo(s) '(completar)' por rellenar» indica cuántos quedan. `aw report` (ver la etapa 2) también los
lista, archivo por archivo.

---

## Etapa 2: proyecto en desarrollo

Mientras trabajas, la mayor parte se registra sola o la registra Claude. Tú intervienes solo en algunas
situaciones. Cada una tiene su lugar:

### Aparece trabajo nuevo

Pídeselo a Claude o regístralo tú:

```bash
aw task add "Agregar la sección de tortas de cumpleaños" --prio P1
aw task start T-004     # al empezarla
aw task done T-004      # al terminarla
```

Prioridades: **P0** urgente · **P1** alta · **P2** normal (la que se usa si no indicas otra) · **P3** baja.

### Se toma una decisión que cambia el rumbo

```bash
aw decide "Pedidos por WhatsApp y no con carrito de compras" \
  --why "La clienta ya recibe pedidos por WhatsApp y no quiere cobrar en línea" \
  --alt "Carrito con pago en línea"
```

El motivo es obligatorio. Las alternativas descartadas son opcionales, pero ayudan a no volver a discutir lo mismo.

### Quieres dejar constancia de algo

```bash
aw log "La clienta envió las fotos nuevas del local"
```

Sirve para hechos sueltos que conviene que figuren en el historial.

### Aparece un dato que Claude debe recordar siempre

Agrega una línea a `memory.md`:

```markdown
- 2026-11-02 El local de calle Mitre cierra los lunes
```

### Empiezas a usar un agente o una skill propios

1. Comprueba que el archivo exista en la carpeta `agents/` o `skills/` de la raíz del workspace. Si no existe,
   créalo desde el menú (`aw`, opciones 6 y 7), que le agrega la cabecera con nombre y descripción.
2. Agrega una fila a `agents/assigned_agents.md` o `skills/assigned_skills.md` (ver la etapa 1).
3. Si el agente usa marcadores como `{{business_name}}`, completa sus valores en `agents/agent_context.md`.

`aw doctor` avisa si una fila apunta a un archivo que no existe.

### Agregas un conector o un servicio externo

Configúralo donde corresponda (`.mcp.json` o los conectores de Claude) y agrega su fila a
`tools/assigned_tools.md`.

### Cambia el alcance, el cliente o el estado del proyecto

Edita `project.md`. Por ejemplo, al publicar la web, cambia el estado general a «mantenimiento». Si el cambio
responde a una decisión, regístrala también con `aw decide`.

### Se define una forma de trabajar

Escríbela en `sop/`: pasos en `workflow.md`, reglas en `rules.md`, formatos en `conventions.md`.

### Produces un entregable

Guárdalo en la carpeta `artifacts/` del proyecto. El índice de `artifacts/outputs.md` (o `assets_index.md` para
imágenes, audio y video) se actualiza con `aw sync panaderia-web`.

### Quieres ver cómo va el proyecto

```bash
aw report
```

Ejecutado dentro de la carpeta del proyecto, genera una página en `artifacts/reporte-AAAA-MM-DD.html` con todo
junto: la ficha, las tareas, las últimas decisiones, la actividad, los commits y los errores de los últimos 30
días, las herramientas más usadas, los entregables y lo que falta completar. Fuera de un proyecto, indica cuál:
`aw report panaderia-web`.

Para una mirada rápida sin generar nada, `aw state` muestra el estado resumido, que es la base del resumen que
Claude recibe al abrir cada sesión.

### Claude o la pantalla muestran «hubo N commit(s) … y no se registró ninguna decisión»

Es un recordatorio, no un error. Aparece una vez por sesión cuando hubo commits y no se registró ninguna decisión
ni se movió ninguna tarea. Si el trabajo implicó una decisión o completó una tarea, regístrala. Si no, se puede
ignorar.

### Algo se repite en varios proyectos

No lo copies en cada uno: llévalo a la raíz del workspace. Los datos van en `memory/global.md`, y las rutas o
reglas comunes en `core/config.md`.

---

## Archivos que llena el sistema

| Archivo | Qué guarda | Cuándo se actualiza |
|---|---|---|
| `state.md` | Resumen del estado: tareas en curso, próximas, última actividad y última decisión | Con cada tarea, decisión o nota, y al terminar cada turno de Claude |
| `tasks/backlog.md`, `active.md`, `done.md` | Tareas pendientes, en curso y hechas | Con `aw task` |
| `execution/decisions.md` | Decisiones con su motivo | Con `aw decide` |
| `execution/run_log.md` | Historial: sesiones, commits, tareas, decisiones y notas | Solo, y con `aw log` |
| `execution/errors.md` | Primera línea de cada error de una herramienta, sin secretos | Solo, cuando algo falla |
| `tools/tool_usage.md`, `tool_state.json` | Qué herramientas usó Claude en cada sesión | Al cerrar cada sesión |
| `context_index.json` | Lista de los archivos del proyecto | Con `aw sync` |
| `artifacts/outputs.md`, `assets_index.md` | Índice de los entregables (solo lo que está entre las marcas) | Con `aw sync` |

---

## Archivos de consulta del workspace

En la raíz del workspace hay dos carpetas que se completan a mano y valen para todos los proyectos: `core/` y
`memory/`. No todos sus archivos los usa Claude:

**Claude los consulta cuando la tarea lo requiere:**

- `core/config.md`: rutas y reglas comunes. Ejemplos: «Plantillas de entregables: carpeta `plantillas/` de Drive»
  · «Idioma de trabajo: español neutro».
- `memory/global.md`: datos comunes a todos los proyectos, una línea por dato con fecha. Ejemplo: «- 2026-10-17
  Todos los sitios se publican en Vercel».

**Hoy son solo notas para ti:** `core/router.md`, `core/init.md`, `core/agent.md`, `core/memory_policy.md`,
`memory/user_profile.md`, `memory/preferences.md` y, en cada proyecto, `artifacts/code_snippets.md`. Aparte de que `aw doctor`
cuenta sus campos `(completar)`, ni aw ni las instrucciones de Claude los usan. Lo que escribas ahí no cambia cómo trabaja Claude: si quieres que lo tenga en
cuenta, escríbelo en tu `CLAUDE.md` global o en el `CLAUDE.md` del proyecto.
