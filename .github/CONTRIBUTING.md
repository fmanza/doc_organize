# Contribuir

## Alcance

Este repositorio mantiene una libreria Python orientada a introspeccion multibase y generacion de documentacion reproducible.

## Flujo minimo

1. Trabaja sobre ramas cortas y con un objetivo unico: `new_feature`, `hotfix`, `refactor` o `security_review`.
2. Revisa `copilot-instructions.md` y la instruccion especifica del area afectada.
3. Mantiene cambios pequenos, con tests y documentacion cuando aplique.
4. Evita mezclar feature, fix y refactor en una misma PR.

## Validacion local recomendada

Ejecuta, segun el alcance del cambio:

```bash
python -m ruff check src tests
python -m mypy src
python -m pytest
python -m build
```

La CI replica esas comprobaciones en dos bloques: matriz de calidad (`ruff`, `mypy`, `pytest`) y verificacion de empaquetado (`python -m build`).

## Criterios de aceptacion

- API publica estable salvo justificacion documentada.
- Tipado y mensajes de error coherentes.
- Sin dependencias nuevas no justificadas.
- Tests deterministas y sin servicios externos obligatorios.
- Changelog y README actualizados si cambia comportamiento visible.

## Pull requests

- Usa la plantilla de PR.
- Explica objetivo, rutas afectadas, riesgos y validacion.
- Si hay datos faltantes o supuestos, dejalos explicitos.
