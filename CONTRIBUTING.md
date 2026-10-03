# Cómo contribuir

Gracias por el interés en mejorar Agentic Workspace (aw). Esta guía explica cómo proponer un cambio y qué se revisa antes de aceptarlo.

## Antes de empezar

* Para un error, abre un *issue* con los pasos para reproducirlo, lo que esperabas y lo que pasó. Incluye la versión de Python (`python3 --version`) y el sistema operativo.
* Para una mejora, abre primero un *issue* que explique el problema que resuelve. Así se acuerda el enfoque antes de escribir código.
* Para una vulnerabilidad, no abras un *issue* público: sigue [SECURITY.md](SECURITY.md).

## Principios del proyecto

* **Un solo archivo y solo la biblioteca estándar.** `generate.py` no usa dependencias externas. Un cambio que necesite una librería se discute antes en un *issue*.
* **El estado vive en archivos.** aw solo interpreta archivos `.md` y `.json`, y solo escribe dentro de la raíz del workspace, en el comando `~/.local/bin/aw` y en los temporales de sesión.
* **Nunca se pierde contenido del usuario.** Un archivo que ya tiene texto no se reemplaza; lo que se modifica se respalda antes.
* **Los hooks nunca bloquean ni fallan en voz alta.** Un error en un hook se anota en `logs/debug.md` y la sesión sigue.
* **Para cambiar lo que se crea**, se editan `structure.json` y `templates/`, no la lógica que los recorre.

## Cómo preparar un cambio

1. Haz un *fork* del repositorio y crea una rama con un nombre descriptivo, por ejemplo `feat/nombre-del-cambio`
   o `fix/nombre-del-error`.
2. Escribe el cambio y **una prueba que falle con el código anterior** y pase con el nuevo. Las pruebas viven en
   `tests/test_aw.py` y trabajan en un workspace temporal (`AW_HOME` y `TMPDIR`), nunca en el real.
3. Ejecuta la suite completa:

   ```bash
   python3 -m unittest discover -s tests -v
   ```

4. Si el cambio afecta al uso, actualiza `Readme.md`.
5. Abre un *pull request* que explique qué cambia y por qué, y cómo se probó.

## Estilo

* Los textos que ve el usuario están en español neutro, sin voseo ni modismos regionales.
* Los comentarios del código explican el porqué, no el qué, y siguen la densidad del código que los rodea.
* Los mensajes de commit describen el comportamiento nuevo en una frase.
* No incluyas datos personales, correos, rutas de tu máquina ni secretos en el código, las pruebas o los
  mensajes de commit.

## Conducta

La participación en el proyecto se rige por el [código de conducta](CODE_OF_CONDUCT.md).
