# TRACEABILITY: Resumen de Sesión

## Sesión
- **Fecha**: 2026-09-04
- **Tipo**: `hotfix`/`refactor`/`docs`/`chore` mixto — cierre del backlog pendiente de `/maturity-assessment` y `/audit-code` (sesiones previas del 2026-09-03/04)
- **Rama**: `develop`
- **Estado**: ✅ COMPLETADA (implementación + tests en verde)

## Objetivo
El usuario pidió un resumen de lo NO implementado tras las dos auditorías
completas de la sesión anterior (`/maturity-assessment` + `/audit-code`,
ambas ya cerradas con commits `860e456`/`84238a5`), y un PLAN priorizado para
ejecutarlo. Se agrupó en 7 bloques por naturaleza del cambio (no por fichero),
con `AUDIT_PLAN` y condiciones explícitas por bloque. El usuario confirmó
todas las condiciones e `IMPLEMENT`.

## Cambios Ejecutados

### ✅ Bloque 1 — Seguridad web (3 hallazgos EDGE CASE del `/audit-code` anterior, no BUG, por eso no entraron en el hotfix previo)
**Archivo(s)**: `web/auth.py`, `web/routes/filesystem.py`, `web/routes/scan.py`,
`tests/unit/test_web_auth.py`, `tests/unit/test_web_filesystem.py`, `tests/unit/test_web_scan.py`.
1. **Login CSRF**: `POST /login` quedaba fuera de la comprobación Origin/Referer
   que ya protegía el resto de escrituras (esa solo corre post-autenticación).
   `SameSite=Strict` no lo cubre: impide *reenviar* una cookie existente
   cross-site, no impide *fijarla* nueva vía la respuesta de login. Fix:
   misma comprobación `_origin_matches_request_host`, aplicada también a
   `POST /login` cuando `requires_auth()` es `True`.
2. **`/api/fs/browse` oráculo de existencia**: comprobaba `is_dir()` antes que
   `allowed_scan_roots` — un rol restringido distinguía "existe pero sin
   acceso" (403) de "no existe" (404) para cualquier ruta del servidor. Fix:
   invertir el orden.
3. **`list_folder_library`/`remove_folder_from_library` sin filtrar/validar
   `allowed_scan_roots`**: decisión del usuario — "se filtra" la lista;
   `remove` exige la misma validación que `add`.
**Status**: ✅ 79 tests (incluidos 7 nuevos) en verde.

### ✅ Bloque 2 — Deuda de cobertura de tests
**Archivo(s)**: `src/doc_organize/__main__.py`, `tests/unit/test_hash_utils.py` (nuevo),
`tests/unit/test_main.py`.
**Hallazgo clave**: los porcentajes de cobertura del `/maturity-assessment`
original (`__main__.py` 0%, `ocr_scheduler.py` 47%, `scan_command.py` 73%)
eran mayormente **artefactos de medir solo con `-m "not slow"`**, que excluye
el único fichero de test de `ocr_scheduler.py` (100% real) y hace bajar
`scan_command.py` del 97% real al 73% aparente. Se corrigió lo real:
- `__main__.py`: `# pragma: no cover` en el guard (shim de 3 líneas, `main()`
  ya tiene cobertura completa vía llamada directa).
- `ocr_scheduler.py`/`scan_command.py`: sin acción — ya están al 100%/97% con
  la suite completa.
- **Hueco real encontrado** (no en el informe original): ningún test
  ejercitaba `DocumentStatus.MODIFIED` de extremo a extremo — nuevo test
  `test_scan_command_second_run_reconverts_modified_file`.
- `hash_utils.py`: nuevo `test_hash_utils.py` (5 tests) — sin test dedicado
  antes, solo cobertura indirecta.
**Status**: ✅ 471 tests totales, sin regresiones.

### ✅ Bloque 3 — Docstrings + doctest en CI
**Archivo(s)**: 13 ficheros de `src/` (ver detalle abajo), `.github/workflows/tests.yml`.
**Corrección de un hallazgo erróneo de la sesión anterior**: los ítems
"`AuthStore`/`ProjectRegistry`/`DeduplicationManager`/`DocumentConverter` sin
`Example:`" eran **falsos** — las 4 clases ya tenían `Example:`. Solo
`scan_history_store.py` (2 funciones) carecía de uno de verdad — añadido.

**El hallazgo real y mayor**: `pytest --doctest-modules src` reveló **13
fallos** (no solo "ejemplos faltantes") — rutas ficticias (`/repo/...`),
variables fantasma no definidas, `await` suelto sin función envolvente,
booleans dependientes del entorno, y un repr específico de Windows. Además,
al investigar, se descubrió que 2 ejemplos que "pasaban" (`AuthStore`,
`CacheManager`) escribían a rutas relativas reales (`./auth.db`, `./cache.db`)
sin limpiar — dejaron ficheros reales en la raíz del repo, ya eliminados.

**Fix por categoría** (15 puntos en 13 ficheros):
- `cache_manager.py` (×3: clase + `count_entries` + `load_cache_page`),
  `auth_store.py`, `project_registry.py`, `scanned_folders_store.py`,
  `hash_utils.py`: `tempfile.mkdtemp()` real en vez de rutas relativas/ficticias.
- `deduplication.py`: ejemplo reescrito con `DocumentMetadata` reales sobre
  ficheros reales en un temp dir (antes usaba una variable `documents` fantasma).
- `document_scanner.py`, `folder_validator.py`: mismo criterio, con contenido
  real de prueba.
- `converter.py`, `ocr_scheduler.py`: marcados `# doctest: +SKIP` deliberado —
  necesitan Docling real (carga de modelo incluida), mismo motivo por el que
  sus tests reales son `@pytest.mark.slow`; forzar esto en cada doctest de CI
  sería la misma máquina pesada solo para un docstring.
- `av_detector.py`, `gpu_detector.py`: el valor real (`ready`/`gpu_active`)
  depende del entorno — se verifica `isinstance(..., bool)` en vez de un
  valor fijo.
- `path_utils.py`: el repr `WindowsPath(...)` difiere Windows/POSIX — se
  compara `.parts[-3:]` (sin unidad), portable.
**Status**: ✅ 26/26 doctests en verde, verificado dos veces seguidas
(idempotencia — el bug original de `AuthStore` era precisamente que la
segunda ejecución fallaba). `pytest --doctest-modules src --no-cov -q` añadido
como paso nuevo en `tests.yml` (mismo job `test`, 8 combos de la matriz).

### ✅ Bloque 5 — Higiene de tipado
**Archivo(s)**: `converter/converter.py`, `scanner/document_scanner.py`.
- 3 `Any` sin comentario (`docling_result`, `document`) → comentario
  explicando el motivo (`docling.*` con `follow_imports = "skip"` en mypy).
- 4 `# pyright: ignore[reportCallIssue]` vestigiales eliminados (el proyecto
  usa mypy, no pyright; verificado que mypy ya pasaba limpio sin ellos).
**Status**: ✅.

### ✅ Bloque 4 — Edge cases de robustez (revisados ítem a ítem, no como lote)
**Archivo(s)**: `web/app.py`, `web/routes/scan.py`, `utils/date_format.py`,
`main.py`, `core/models.py`, `dedup/deduplication.py`, `scan/scan_command.py`,
`web/routes/duplicates.py`, `web/templates/duplicates_resolver.html.j2`, y
tests correspondientes.

Revisión ítem a ítem (12-20) con recomendación propia por ítem; el usuario
confirmó todas salvo el 18, donde pidió explícitamente "nivel de resiliencia".

- **12 (fix) — sin guarda de concurrencia entre operaciones del mismo proyecto**:
  `app.state.active_project_operations` (`set` de `(tenant_id, nombre_proyecto)`,
  compartido por app, mismo criterio que `project_registry`) — `scan_websocket`
  y `deduplicate_websocket` reservan la clave al empezar y la liberan en un
  `finally`; una segunda conexión sobre el MISMO proyecto se rechaza con
  `code=1008` mientras la primera sigue en curso. Cubre tanto dos escaneos
  como un escaneo+deduplicación cruzados.
- **13, 14, 16, 17, 19 (aceptados tal cual, sin cambio de código)**: cada uno
  con justificación propia (trade-off estándar de WebSocket, coste de `stat()`
  despreciable, reprocesamiento sin pérdida de datos real, prerrequisito de
  explotación ya implica compromiso previo, comportamiento consistente con el
  resto del CLI).
- **15 (fix) — `format_duration()` sin guarda ante duración negativa**:
  `duration_seconds` se calcula con reloj de pared, no monótono; un ajuste
  del reloj hacia atrás podía producir `"-1m 55s"`. Ahora `max(0, round(seconds))`.
- **18 (fix, resiliencia pedida explícitamente)** — `move_group()` ahora
  aísla el fallo de UN fichero (`OSError`, incluye `FileExistsError` de la
  colisión doble del hotfix anterior) sin abortar el resto del grupo/lote,
  mismo criterio que `DocumentConverter.convert_document()` por documento.
  Cambio de contrato: `move_group()` devuelve ahora `(exact, version,
  rutas_fallidas)` (antes 2-tupla); `DeduplicationReport`/`DeduplicationSummary`/
  `ResolveDuplicatesResponse` ganan `failed_paths`, persistido en
  `DEDUP_REPORT.json`/`DEDUP_HISTORY.jsonl` y mostrado en la UI (banner de
  "Buscar duplicados" y resultado de "Resolver duplicados") en vez de perderse
  en silencio.
- **20 (fix) — asimetría de logging `_resolve_scan_paths`/`_resolve_dedup_paths`**:
  `_resolve_dedup_paths` ahora avisa igual que su análogo al combinar
  `--project` con `--duplicates-dir` explícito.

**Status**: ✅ 478 tests totales (7 nuevos: 3 de concurrencia, 1 de duración
negativa, 2 de resiliencia de `move_group`/`deduplicate_streaming`, 1 de la
asimetría de logging), sin regresiones. `ruff`/`mypy`/`--doctest-modules`
(26/26) limpios.

### ⏸️ Diferido, sin cambios
- Ítem 10 original (consistencia de docstrings de métodos privados): de
  prioridad baja, no se retomó tras encontrarse el hallazgo mayor del ítem 11.
- Migración a `enum.StrEnum` (`UP042`, ya diferida en la sesión del 2026-09-03/04).
- `README.md` ejemplo con versión obsoleta y `LICENSE` (nombre legal) — ambos
  ya identificados como fuera de mi alcance a decidir.

---

## Impacto

### Código
- **Archivos modificados**: 27 (ver `git status`), + `tests/unit/test_hash_utils.py` nuevo.
- **Cambios funcionales**: sí en Bloque 1 (3 fixes de seguridad) y Bloque 4
  (guarda de concurrencia por proyecto, resiliencia por fichero en dedup,
  guarda de duración negativa, aviso de logging); solo docstrings/comentarios/CI
  en los bloques 2, 3, 5.

### Compatibilidad
- **BREAKING**: ninguno en API pública externa. `DeduplicationManager.move_group()`
  (público pero de uso interno entre `resolve_duplicates()`/`deduplicate_streaming()`)
  cambia de 2-tupla a 3-tupla — sin consumidores externos al propio paquete.
- **NO BREAKING**: `DeduplicationReport.failed_paths`/`DeduplicationSummary.failed_paths`/
  `ResolveDuplicatesResponse.failed_paths` son campos nuevos con default `[]` —
  históricos JSONL previos sin este campo se siguen leyendo igual.

---

## Verificación
```
python -m ruff check src tests             → All checks passed!
python -m mypy src                         → Success: no issues found in 52 source files
python -m pytest --doctest-modules src -q  → 26 passed (dos ejecuciones seguidas, idempotente)
python -m pytest -q --no-cov               → 478 passed
```

---

## Riesgos Residuales

| Riesgo | Mitigación | Status |
|--------|-----------|--------|
| Los ejemplos `Example:` con `tempfile.mkdtemp()` no limpian el directorio temporal tras ejecutarse | Mismo criterio que el resto de ejemplos ya existentes en el proyecto (ninguno limpiaba) — no es una convención nueva que se rompa | Aceptado, consistente con lo ya establecido |
| `app.state.active_project_operations` es un `set` en memoria de proceso, no distribuido | Solo relevante si se despliega con más de un worker/proceso — hoy `_run_web` no expone `--workers` (un único proceso), mismo límite ya documentado para `TimedRotatingFileHandler` en `utils/logging.py` | Aceptado, no aplica todavía |

---

## Siguientes Pasos (Recomendado)
1. Commit + confirmar push.
2. Si en el futuro se despliega con múltiples workers, revisar si la guarda
   de concurrencia del bloque 4 (ítem 12) necesita moverse a un mecanismo
   compartido entre procesos (mismo límite ya aceptado para el logging a fichero).

---

## Directrices para Futuras IAs

- **[Los porcentajes de cobertura reportados por una auditoría pueden ser
  artefactos de cómo se midió, no del código]**: si un informe de madurez usa
  `-m "not slow"` para medir cobertura, cualquier módulo cuyo ÚNICO test viva
  en un fichero `@pytest.mark.slow` (como `ocr_scheduler.py`) aparecerá con
  cobertura artificialmente baja. Antes de escribir tests para "cerrar" un
  hueco de cobertura reportado, remedir con la suite completa.
- **[Un `Example:` de docstring que nunca se ejecutó puede llevar años
  desincronizado sin que nadie lo note]**: `pytest --doctest-modules src`
  reveló 13 fallos en un proyecto con `ruff`/`mypy`/`pytest` siempre en verde
  — ninguna de esas otras puertas de calidad detecta un docstring roto. Si se
  añade un `Example:` nuevo, verificarlo con este comando antes de darlo por
  bueno (dos de los que "pasaban" a la primera, `AuthStore`/`CacheManager`,
  escribían a rutas relativas reales del cwd — un problema silencioso incluso
  cuando el ejemplo "funciona").
- **[Ejemplos que requieren Docling real (`DocumentConverter`/`OCRScheduler`)
  se marcan `# doctest: +SKIP`, no se fuerza una conversión real]**: mismo
  criterio que `@pytest.mark.slow` para los tests reales — el coste (carga de
  modelo) es desproporcionado para verificar un docstring en cada job de CI.
  `# doctest: +SKIP` en la última línea de un ejemplo (`asyncio.run(main())`)
  solo omite ESA línea — las líneas anteriores (imports, `def main():`) sí se
  ejecutan/definen, así que siguen dando señal de que el resto del ejemplo es
  sintácticamente válido.
- **[Valores que dependen del entorno real (`detect_gpu_status()`,
  `detect_av_status()`) no se afirman con un valor fijo en un doctest]**:
  usar `isinstance(..., bool)` (o similar) en vez de `True`/`False` — el
  valor real cambia según qué esté instalado en la máquina que ejecute CI.
- **[`WindowsPath`/`PosixPath` difieren en su `repr()` — nunca comparar el
  repr completo de un `Path` en un doctest que deba pasar en ambos SO]**:
  comparar `.parts[-N:]` (sin la unidad/raíz) o `.name`/`.as_posix()` según
  el caso.
- **[Un lock que protege un recurso compartido entre WebSockets debe vivir en
  `app.state`, nunca en una variable de módulo ni en la función misma]**:
  `active_project_operations` sigue exactamente el mismo patrón ya establecido
  para `project_registry` (sesión `2026-09-04-audit-code-hotfixes`) — un `set`
  por app, reservado al empezar una operación y liberado en un `finally`, para
  que sobreviva a cualquier `return` intermedio (payload inválido, sin
  carpetas, fuera de `allowed_scan_roots`, etc.).
- **[Cuando se pide "resiliencia" para un bucle que mueve/procesa varios
  ítems, el contrato de la función cambia, no solo su cuerpo]**: aislar el
  fallo de un `move_group()` por fichero obligó a propagar `failed_paths` por
  toda la cadena (`DeduplicationManager` → `ScanCommand.deduplicate_streaming()`
  → `DedupEvent`/`DeduplicationSummary` → respuesta HTTP → JS de la plantilla)
  para que la información no se pierda en silencio en ningún punto intermedio
  — "resiliente" sin "visible" solo mueve el problema de "crash" a "éxito
  silencioso pero incompleto", igualmente malo.
- **[`OSError` ya incluye `FileExistsError`/`PermissionError`/`FileNotFoundError`
  en su jerarquía]**: un único `except OSError` en `move_group()` captura tanto
  el caso "fichero bloqueado por otra app" como el de "colisión doble tras
  sufijo de hash" (el `FileExistsError` explícito del hotfix anterior) sin
  necesitar dos ramas — verificar la jerarquía de excepciones builtin antes de
  añadir un segundo `except` que ya sería redundante.

---

## Veredicto

### 🟢 COMPLETADA (Bloques 1-5, backlog completo del `/maturity-assessment` + `/audit-code`)

**Criterios**:
- ✅ Los 5 bloques implementados con tests de regresión donde aplica (Bloque 4
  revisado ítem a ítem, no como lote, según lo acordado)
- ✅ Suite completa en verde (478 passed), `ruff`/`mypy` limpios
- ✅ `pytest --doctest-modules src` verde y verificado idempotente (2 ejecuciones)
- ✅ CI actualizado (`tests.yml`) para no volver a desincronizarse
- ⬜ Commit: pendiente de esta misma sesión

**Evidencia**:
- Branch: `develop`
- Tests: 478 passed (`python -m pytest -q --no-cov`)

**Sesión cerrada**: 2026-09-04
