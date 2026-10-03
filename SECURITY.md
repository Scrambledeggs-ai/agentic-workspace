# Seguridad

## Cómo informar de una vulnerabilidad

No abras un *issue* público. Usa el aviso privado de GitHub: pestaña **Security** del repositorio →
**Report a vulnerability**. El informe solo lo ven quienes mantienen el proyecto.

Incluye, si puedes:

* qué parte de aw está afectada (un comando, un hook, `redact`, la sincronización);
* los pasos para reproducirlo;
* qué podría conseguir alguien que lo aproveche.

Se responde en cuanto sea posible y, una vez corregido, se publica el arreglo con una nota en
[CHANGELOG.md](CHANGELOG.md).

## Qué protege aw y qué no

* aw no lee archivos `.env` ni guarda comandos completos. Antes de guardar lo que deriva de la salida de una
  herramienta o de `git log`, `redact()` oculta lo que parece un secreto. Es un filtro de mejor esfuerzo, no una
  garantía: no publiques tus archivos `execution/` ni `logs/` sin revisarlos.
* Los temporales de sesión se crean sin seguir enlaces simbólicos y solo legibles por su dueño.
* `aw update` solo trae código del repositorio remoto que ya tiene configurado tu clon, y solo como avance
  directo.
