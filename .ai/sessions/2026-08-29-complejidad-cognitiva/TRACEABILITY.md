# TRACEABILITY: Resumen de Sesión

## Sesión
- **Fecha**: 2026-08-29
- **Tipo**: `refactor` (SonarLint/SonarQube: complejidad cognitiva) + `fix` (lint `PYI034`,
  continuación de `.ai/sessions/2026-08-29-python-3-11/`)
- **Rama**: `develop`
- **Estado**: ✅ COMPLETADA (código + tests en verde en el working tree, **pendiente de commit** —
  no se ha ejecutado ningún `git commit`/`push` en esta sesión)

## Objetivo
El editor (extensión SonarLint de VS Code) marcó `python:S3776` (Cognitive Complexity) en dos
funciones — `AuthStore.update_role` (17/15) y `scan_websocket` (18/15) — y Ruff (`PYI034`, misma
regla ya corregida en `AuthStore.__aenter__` en la sesión anterior) en otros cuatro
`__aenter__`. También se evaluó `RUF022` (`__all__` sin ordenar) en `core/constants.py` y se
decidió **no** aplicarlo. Ninguno de estos avisos viene de la configuración real de Ruff del
proyecto (`extend-select` en `pyproject.toml` no incluye `PYI` ni `RUF`) ni de un gate de CI —
son solo reglas por defecto de las extensiones del editor, distintas del comando real
`python -m ruff check`. Se corrigieron los dos primeros por ser mejoras reales y de bajo riesgo;
el tercero se dejó explícitamente sin tocar (ver más abajo el porqué).

## Cambios Ejecutados

### ✅ 1. `PYI034` — `Self` en el resto de `__aenter__` (continuación)
La sesión anterior (`2026-08-29-python-3-11`) ya corrigió `AuthStore.__aenter__`; esta la
completa en las cuatro clases restantes con el mismo patrón (`async def __aenter__(self) ->
"ClaseX":` → `-> Self:`), ahora posible sin dependencia nueva porque el suelo mínimo ya es
Python 3.11.

**Archivo(s)**:
- `src/doc_organize/cache/cache_manager.py`: `CacheManager.__aenter__`
- `src/doc_organize/converter/converter.py`: `DocumentConverter.__aenter__` (import `Self` añadido
  a la línea existente `from typing import Any`)
- `src/doc_organize/projects/project_registry.py`: `ProjectRegistry.__aenter__`
- `src/doc_organize/scanner/document_scanner.py`: `DocumentScanner.__aenter__`
**Descripción**: mismo fix mecánico en las cuatro clases; ninguna tenía otro uso de `typing` que
chocara con el import nuevo.
**Status**: ✅ Hecho.

### ✅ 2. `AuthStore.update_role` — Cognitive Complexity 17 → bajo 15
**Archivo(s)**: `src/doc_organize/auth/auth_store.py`.
**Descripción**: sin cambio de comportamiento (mismas reglas de validación, mismos mensajes de
error, misma secuencia de escrituras SQL). Se extrajo:
- `_resolve_role_update` (nuevo `@staticmethod`): calcula `name`/`is_admin`/`project_names`/
  `allowed_scan_roots` nuevos y lanza los `AuthError` de validación — función pura, sin acceso a
  BD.
- `_replace_role_associations` (nuevo helper, junto a `_insert_role_row`): el
  delete+reinsert de `role_projects`/`role_scan_roots`, ahora reutilizado también aquí.
- `_role_name_taken` extendido con `exclude_role_id: str | None = None` — `update_role` reutiliza
  el mismo helper que ya usaba `create_role` en vez de una query manual duplicada.

`update_role` queda como: obtener `current` → resolver campos nuevos → check de unicidad →
escribir → devolver. Efecto lateral positivo: también resolvió un aviso de SonarLint
(`python:S1192`, literal SQL duplicado 3 veces) que apareció como consecuencia intermedia del
refactor, al quedar las dos sentencias `INSERT INTO role_...` en un solo sitio en vez de tres.
**Status**: ✅ Hecho, verificado con `tests/unit/test_auth_store.py` (49 passed).

### ✅ 3. `scan_websocket` — Cognitive Complexity 18 → bajo 15
**Archivo(s)**: `src/doc_organize/web/routes/scan.py`.
**Descripción**: se extrajo todo el bloque de autenticación/autorización (antes anidado 3-4
niveles dentro de `if requires_auth(...): ... else: ...`) a una función nueva:

`_authorize_scan_websocket(websocket, project_name) -> tuple[str, list[str] | None] | None`
- Sin auth requerida → `("default", None)`.
- Sesión inválida → cierra el socket (`1008 Unauthorized`) y devuelve `None`.
- Admin → `(tenant_id, None)` (sin restricción de rutas).
- Rol no-admin sin acceso al proyecto → cierra (`1008 Project not found`) y devuelve `None`.
- Rol no-admin con acceso → `(tenant_id, role.allowed_scan_roots)`.

`scan_websocket` llama al helper y corta con `return` si devuelve `None` — mismos códigos/razones
de cierre, mismo orden de comprobaciones, sin cambio de comportamiento observable.
**Status**: ✅ Hecho, verificado con `tests/unit/test_web_scan.py` (13 passed).

### ⬜ 4. `RUF022` en `core/constants.py::__all__` — evaluado, no aplicado
**Descripción**: el orden actual de `__all__` no es alfabético, pero tampoco arbitrario — agrupa
las constantes por función (`SCRYPT_*` juntas, `ROLE_*` juntas, `DEFAULT_ADMIN_*` juntas),
reflejando el orden de declaración arriba. Ordenar alfabéticamente dispersaría esos grupos sin
ganar nada, para una regla que el proyecto no aplica en CI (`RUF` no está en `extend-select`).
Se explicó el trade-off al usuario y se dejó pendiente de decisión explícita, no se tocó el
archivo.
**Status**: ⬜ Sin aplicar, decisión pendiente del usuario si la quiere de todos modos.

---

## Impacto

### Código
- **Archivos modificados**: `src/doc_organize/{auth/auth_store.py, cache/cache_manager.py,
  converter/converter.py, projects/project_registry.py, scanner/document_scanner.py,
  web/routes/scan.py}`
- **Archivos nuevos**: `.ai/sessions/2026-08-29-complejidad-cognitiva/TRACEABILITY.md` (este
  fichero)
- **Cambios funcionales**: no — refactor puro (extracción de funciones/reutilización de helpers),
  sin cambios de API pública ni de comportamiento observable.

### Compatibilidad
- **BREAKING**: ninguno.
- **NO BREAKING**: todo — firmas públicas (`update_role`, la ruta WebSocket `/api/projects/
  {name}/scan`) sin cambios; los métodos/funciones nuevos son privados (`_resolve_role_update`,
  `_replace_role_associations`, `_authorize_scan_websocket`).

---

## Verificación
```
python -m ruff check src tests               → All checks passed
python -m mypy src                           → Success: no issues found in 42 source files
python -m pytest tests/unit/test_auth_store.py -q   → 49 passed
python -m pytest tests/unit/test_web_scan.py -q     → 13 passed
python -m pytest -k "not slow" -q                   → 233 passed, 12 deselected (x2, tras cada refactor)
```
No se ejecutó `mkdocs build --strict` (sin cambios en `docs/`) ni `python -m build` en esta
sesión.

---

## Riesgos Residuales

| Riesgo | Mitigación | Status |
|--------|-----------|--------|
| Ninguno identificado — refactor sin cambio de comportamiento, cubierto por los tests existentes | — | — |

---

## Siguientes Pasos (Recomendado)
1. `git add`/commit de los cambios de esta sesión — mensaje de commit preparado en la respuesta
   al usuario, ningún commit ejecutado todavía.
2. Si el usuario decide aplicar `RUF022` en `core/constants.py` de todos modos, hacerlo en un
   commit separado (es un cambio puramente cosmético, no relacionado con este refactor).

---

## Directrices para Futuras IAs

- **[`Self` en context managers async]**: las cinco clases con `__aenter__`/`__aexit__` del
  proyecto (`AuthStore`, `CacheManager`, `DocumentConverter`, `ProjectRegistry`,
  `DocumentScanner`) devuelven `typing.Self` desde esta sesión (más `AuthStore` en la sesión
  anterior). Cualquier clase nueva con el mismo patrón debe seguir el mismo estilo — no volver a
  `-> "NombreClase":`.
- **[patrón para bajar Cognitive Complexity en este proyecto]**: cuando SonarLint marca `S3776`
  en un método de `AuthStore` o una ruta de `web/routes/`, el patrón aplicado dos veces en esta
  sesión es: (1) extraer el bloque de *validación/resolución de valores* (sin I/O si es posible)
  a un método/función separado que devuelva los valores calculados o lance el error, y (2)
  extraer bloques de *efectos secundarios repetidos* (aquí: reemplazar filas de asociación
  `role_projects`/`role_scan_roots`) a un helper reutilizable. Ver `AuthStore._resolve_role_update`
  + `AuthStore._replace_role_associations`, y `web/routes/scan.py::_authorize_scan_websocket`,
  como referencia del patrón.
- **[reglas de SonarLint/Ruff del editor ≠ reglas de CI]**: confirmado de nuevo (ver también
  `2026-08-29-python-3-11`) — antes de "arreglar" un aviso visible solo en el editor
  (SonarLint/extensión Ruff con su propio ruleset), verificar si aplica al proyecto de verdad:
  `python -m ruff check <archivo>` para Ruff; para SonarLint no hay equivalente de CLI en este
  repo, así que se evalúa caso a caso si la corrección mejora el código real (aquí sí, para
  `S3776`) o es solo ruido/preferencia estética sin beneficio claro (aquí no, para `RUF022` en
  `__all__` — el orden por grupos es más legible que el alfabético).
- **[`__all__` de `core/constants.py`]**: el orden no es alfabético a propósito — agrupa por
  función (SCRYPT, roles, admin por defecto, etc.), reflejando el orden de declaración de las
  constantes arriba en el mismo archivo. No "arreglarlo" con un sort automático sin que el
  usuario lo pida explícitamente.

---

## Veredicto

### 🟢 COMPLETADA

**Criterios**:
- ✅ Los dos hallazgos reales de complejidad cognitiva (`S3776`) corregidos sin cambio de
  comportamiento
- ✅ `PYI034` resuelto en las cuatro clases restantes con el mismo patrón que `AuthStore`
- ✅ `ruff check`, `mypy src`, tests específicos y suite completa (`-k "not slow"`, 233 passed) —
  todos en verde tras cada cambio
- ✅ `RUF022` evaluado explícitamente y su trade-off comunicado al usuario, no aplicado sin
  confirmación
- ⬜ Commit/push — explícitamente no ejecutado en esta sesión (el usuario pidió solo el mensaje)

**Evidencia**:
- Branch: `develop` (sin commits nuevos en esta sesión — working tree con los cambios; el commit
  anterior, `83504cc`, ya cerró la sesión `2026-08-29-python-3-11`)
- Commits: ninguno todavía; mensaje de commit preparado en la respuesta de esta sesión
- Tests: 233 passed (`-k "not slow"`), sin regresiones; 49 passed en `test_auth_store.py`, 13
  passed en `test_web_scan.py`

**Sesión cerrada**: 2026-08-29
