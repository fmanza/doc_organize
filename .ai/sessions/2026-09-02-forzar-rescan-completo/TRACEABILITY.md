# TRACEABILITY: Resumen de Sesión

## Sesión
- **Fecha**: 2026-09-02
- **Tipo**: `feature` (ciclo `/new-feature`: PLAN → AUDIT_PLAN → IMPLEMENT → AUDIT_CODE)
- **Rama**: `develop`
- **Estado**: ✅ COMPLETADA (implementación y tests en verde; commit pendiente de confirmación del usuario, ver "Siguientes Pasos")

## Objetivo
El usuario pidió incluir en el escaneo la posibilidad de forzar un rescan completo,
"eliminando la caché y lo que sea necesario". Tras un PLAN con tres propuestas de
alcance (A: ignorar caché sin borrar nada; B: vaciar `cache.db`; C: vaciar caché +
limpiar salidas huérfanas), el usuario eligió explícitamente la **Propuesta C**
("reset completo") vía `AskUserQuestion`.

## Cambios Ejecutados

### ✅ 1. PLAN — tres propuestas de alcance para "forzar rescan"
**Descripción**: se investigó primero la arquitectura existente (`DocumentScanner`
agnóstico de caché, `CacheManager` sobre SQLite/WAL sin ningún método de borrado,
`ScanCommand` como único punto que combina escaneo+caché+conversión). Se plantearon
tres niveles: (A) `force` ignora la caché en memoria sin tocar `cache.db`; (B) añade
`CacheManager.clear()` y vacía la tabla de verdad; (C) B + limpieza de los `.md`/
`.json` ya convertidos que quedarían huérfanos. El usuario eligió **C**.
**Status**: ✅ decisión de diseño con tradeoffs reales resuelta por el usuario, no
asumida.

### ✅ 2. AUDIT_PLAN — cierre del punto abierto de la Propuesta C
**Descripción**: quedaba pendiente investigar la convención de nombres del
conversor antes de diseñar el borrado de salidas huérfanas. Se confirmó
empíricamente que `DocumentConverter._write_outputs()` deriva la ruta de salida
**solo del `full_path` del fichero fuente** (nunca del hash SHA-256): mismo árbol
de carpetas bajo `output_dir`, `<stem>.md`/`<stem>.json`. Consecuencia clave: si un
documento cambia de contenido pero mantiene la misma ruta, la reconversión ya
sobrescribe su salida sin fricción — **no hace falta borrado explícito para el caso
común**. Solo quedan huérfanos los ficheros renombrados/movidos/eliminados desde el
último escaneo (su output vive bajo la ruta vieja, que nadie vuelve a tocar). Esto
simplificó el diseño: el borrado dirigido solo aplica a esa diferencia
(`cached_entries antiguos - scan_result.documents actual`), no a todo `output_dir`.
**Status**: ✅ veredicto GO tras cerrar el punto.

### ✅ 3. IMPLEMENT — `force` de extremo a extremo (ScanCommand → Web/CLI)
**Archivo(s)**:
- `src/doc_organize/converter/converter.py` — `resolve_output_paths()` extraído
  como `@staticmethod` reutilizable desde `_write_outputs()` (mismo comportamiento,
  sin cambio funcional); permite calcular la ruta de salida de un documento sin
  reconvertirlo.
- `src/doc_organize/cache/cache_manager.py` — método nuevo `clear()`
  (`DELETE FROM cache_entries` + commit), aditivo, no upsert.
- `src/doc_organize/scan/scan_command.py` — `force: bool = False` añadido a
  `run()`/`run_streaming()` (default compatible hacia atrás). Con `force=True`:
  calcula huérfanos (`set(cached_entries) - current_paths`), los borra vía el
  método nuevo `_delete_orphaned_outputs()` (usa `DocumentConverter.resolve_output_paths`),
  vacía la caché con `cache.clear()` y trata `cached_entries = {}` para que
  `get_changes()` marque todo como nuevo.
- `src/doc_organize/web/routes/scan.py` — el WS de escaneo lee `force` del payload
  igual que `use_ocr`/`use_gpu` (`bool(request_payload.get("force", False))`) y lo
  reenvía a `run_streaming()`.
- `src/doc_organize/web/templates/folder_selector.html.j2` — checkbox "Forzar
  rescan completo" + `window.confirm()` antes de enviar (acción destructiva sin
  deshacer).
- `src/doc_organize/main.py` — flag `--force` en el subcomando `scan`, paridad con
  `--use-ocr`/`--use-gpu`.
**Status**: ✅ implementado en las tres capas (`ScanCommand`, WebSocket, CLI) sin
romper ninguna firma existente.

### ✅ 4. AUDIT_CODE + tests
**Descripción**: 8 tests nuevos — unitarios rápidos (`CacheManager.clear()`,
`DocumentConverter.resolve_output_paths()`, `ScanCommand._delete_orphaned_outputs()`
con artefactos falsos, sin Docling) y end-to-end con Docling real marcados `slow`
(`ScanCommand.run(force=True)` reconvierte lo "unchanged"; borra el output de un
fichero fuente eliminado antes del rescan; CLI `--force`; WebSocket `force: true`).
**Status**: ✅ `ruff`/`mypy` limpios; suite completa en verde.

---

## Impacto

### Código
- **Archivos modificados**: `src/doc_organize/converter/converter.py`,
  `src/doc_organize/cache/cache_manager.py`, `src/doc_organize/scan/scan_command.py`,
  `src/doc_organize/web/routes/scan.py`,
  `src/doc_organize/web/templates/folder_selector.html.j2`, `src/doc_organize/main.py`,
  `tests/unit/test_cache_manager.py`, `tests/unit/test_converter.py`,
  `tests/unit/test_main.py`, `tests/unit/test_web_scan.py`.
- **Cambios funcionales**: sí — nuevo parámetro `force` en `ScanCommand.run()`/
  `run_streaming()`, nuevo método `CacheManager.clear()`, nuevo método estático
  `DocumentConverter.resolve_output_paths()`, nuevo flag `--force` en CLI, nuevo
  campo `force` en el payload del WebSocket de escaneo, nuevo checkbox en la UI.

### Compatibilidad
- **BREAKING**: ninguno.
- **NO BREAKING**: `force` tiene default `False` en todas las capas (`ScanCommand`,
  CLI, WebSocket) — cualquier caller/cliente existente sigue funcionando sin
  cambios. `resolve_output_paths()` es una extracción mecánica sin cambiar el
  comportamiento de `_write_outputs()`.

---

## Verificación
```
python -m ruff check src tests   → All checks passed!
python -m mypy src                → Success: no issues found in 47 source files
python -m pytest -q               → 348 passed, 96% cobertura total
```
Incluye 4 tests `slow` con Docling real verificando el comportamiento de `force`
en `ScanCommand`, CLI y WebSocket (ejecutados explícitamente con `-m slow -k force`
antes de la suite completa).

---

## Riesgos Residuales

| Riesgo | Mitigación | Status |
|--------|-----------|--------|
| Si el proceso se interrumpe entre `cache.clear()` y `save_entries()` (WS cerrado, excepción), `cache.db` queda vacío en disco hasta el siguiente escaneo | Aceptado: la caché es 100% recomputable, el próximo escaneo (con o sin `force`) la repuebla sin pérdida de datos reales | Aceptado, no mitigado |
| El gate cliente de "Buscar duplicados antes de Escanear" (`folder_selector.html.j2`) no distingue si el siguiente escaneo será `force` — un rescan forzado no interactúa con duplicados/histórico (confirmado: `cache.db` está desacoplado de `/duplicates`) | Documentado explícitamente en el PLAN; no requiere cambio de código | No aplica (confirmado desacoplado) |

---

## Siguientes Pasos (Recomendado)
1. Confirmar con el usuario el mensaje de commit preparado en la respuesta del
   turno y ejecutar `git add`/`git commit` — el usuario pidió expresamente "solo
   mensaje", `git commit` no se ha ejecutado.
2. Si en el futuro se necesita "vaciar caché" como acción independiente (sin
   rescan), `CacheManager.clear()` ya queda expuesto y reutilizable para un
   endpoint separado.

---

## Directrices para Futuras IAs

- **[La ruta de salida del conversor depende solo del path fuente, nunca del hash]**:
  `DocumentConverter.resolve_output_paths()` (`converter.py`, extraído de
  `_write_outputs()` en esta sesión) deriva `<stem>.md`/`<stem>.json` únicamente de
  `Path(full_path).resolve().parts`. Esto significa que reconvertir un documento con
  el mismo path siempre sobrescribe su salida anterior sin necesidad de borrado
  previo — el borrado explícito solo hace falta para huérfanos (path que ya no
  aparece en el escaneo actual). No reintroducir el hash en el naming sin una razón
  nueva y documentada.
- **[`CacheManager` no tenía ningún método de borrado antes de esta sesión]**:
  `clear()` es el primero (`DELETE FROM cache_entries`, no upsert). Si aparece una
  necesidad de borrado parcial (por ejemplo, una sola entrada), añadir un método
  específico en vez de sobrecargar `clear()`.
- **["Forzar rescan" (`force=True`) y deduplicación siguen completamente
  desacoplados]**: confirmado en el PLAN de esta sesión — `cache.db` no interactúa
  con `/duplicates` ni con `DEDUP_HISTORY.jsonl` (ver también la sesión
  `2026-08-31-flujo-deduplicacion-escaneo`, que ya había separado ambos flujos). Un
  rescan forzado no resetea el histórico de duplicados; si en el futuro se pide esa
  interacción, es una feature nueva, no una extensión de `force`.
- **[Los huérfanos de `output_dir` solo se limpian cuando `force=True`]**: un
  escaneo normal (`force=False`) nunca borra `.md`/`.json` de ficheros renombrados/
  movidos/eliminados — sigue siendo una laguna preexistente fuera del alcance de
  esta sesión (documentada en el AUDIT_PLAN, no en el propio pipeline normal). Si se
  pide resolverla de forma general (no solo bajo `force`), es una feature aparte.

---

## Veredicto

### 🟢 COMPLETADA

**Criterios**:
- ✅ Decisión de alcance (Propuesta A/B/C) resuelta explícitamente por el usuario
  vía `AskUserQuestion`, no asumida
- ✅ Punto de diseño abierto del AUDIT_PLAN (convención de naming del conversor)
  cerrado con investigación empírica antes de escribir código
- ✅ Cambio aditivo y compatible hacia atrás en las tres capas (`ScanCommand`, CLI,
  WebSocket) — ningún caller existente requiere cambios
- ✅ 8 tests nuevos, incluidos 4 end-to-end con Docling real cubriendo
  `ScanCommand`, CLI y WebSocket
- ✅ `ruff`, `mypy`, `pytest` (348 passed, 96% cobertura) en verde
- ⬜ Commit: pendiente de confirmación explícita del usuario (pidió "solo mensaje")

**Evidencia**:
- Branch: `develop`
- Commits: ninguno todavía — cambios en working tree, mensaje preparado en la
  respuesta del turno
- Tests: 348 passed, 96% cobertura total

**Sesión cerrada**: 2026-09-02
