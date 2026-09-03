# TRACEABILITY: Resumen de Sesión

## Sesión
- **Fecha**: 2026-09-03
- **Tipo**: `feature` (PLAN → AUDIT_PLAN → IMPLEMENT → AUDIT_CODE) + `refactor` (PLAN → AUDIT_PLAN → IMPLEMENT) sobre la deuda técnica que dejó la propia AUDIT_CODE
- **Rama**: `develop`
- **Estado**: ✅ COMPLETADA en código (implementación, auditoría y tests en verde) — **commit pendiente de confirmación del usuario** (ver "Siguientes Pasos")

## Objetivo
El usuario pidió dos funcionalidades nuevas en una sola sesión: (1) gestión de
errores de escaneo agrupados por ejecución, en una pestaña nueva "Errores de
Escaneo" con el mismo estilo visual que "Duplicados", exportable a Excel; (2)
un sistema de logging a fichero con rotación diaria y retención de 15 días,
parametrizable por nivel y por entorno (desarrollo/producción). Pidió
explícitamente el flujo `PLAN y AUDIT_PLAN` antes de implementar.

## Cambios Ejecutados

### ✅ 1. PLAN + AUDIT_PLAN — Errores de Escaneo + Logging
**Descripción**: investigación previa (agente Explore) del patrón visual de
"Duplicados" (pestañas, histórico JSONL, semáforo, bloqueo cruzado), del
pipeline de `ScanCommand` (no existía ningún concepto de "ejecución de
escaneo" persistente antes de esta sesión) y del logging existente
(`utils/logging.py`, nivel fijo, sin fichero activado por ningún caller).
AUDIT_PLAN: veredicto **GO_CONDICIONAL** con 4 condiciones — (1) alcance del
histórico agrupado por ejecución desde el primer entregable (no solo "estado
actual"), (2) nombres/valores de las variables de entorno de logging, (3)
eliminar `get_logger(log_file=...)` en vez de mantenerlo por compatibilidad,
(4) un único `.xlsx` con "Estado actual" + "Histórico" en hojas separadas.
**Status**: ✅ las 4 condiciones fueron confirmadas explícitamente por el
usuario antes de implementar.

### ✅ 2. IMPLEMENT — Logging centralizado con rotación diaria
**Archivo(s)**: `src/doc_organize/utils/logging.py`, `src/doc_organize/main.py`,
`tests/unit/test_utils_logging.py` (nuevo).
**Descripción**: `configure_logging(env, log_dir, level)` nueva, idempotente
por proceso, instala `StreamHandler` + `TimedRotatingFileHandler`
(`when="midnight"`, `backupCount=15`) sobre el logger raíz `doc_organize`.
Resolución `parámetro → variable de entorno (DOC_ORGANIZE_ENV,
DOC_ORGANIZE_LOG_LEVEL, DOC_ORGANIZE_LOG_DIR) → default por entorno` (dev:
`DEBUG`/`./logs`; producción: `INFO`/ruta persistente por usuario del SO).
`get_logger(name)` simplificado: ya no instala handlers propios (los loggers
de módulo propagan por jerarquía al logger raíz) y **pierde el parámetro
`log_file`** (condición 3). `main()` llama a `configure_logging()` una única
vez, antes de despachar cualquier subcomando (CLI y `web`); `create_app()`
deliberadamente NO la llama (factoría pura, sin efectos secundarios de
logging global).
**Status**: ✅ implementado y verificado.

### ✅ 3. IMPLEMENT — Pestaña "Errores de Escaneo"
**Archivo(s)**: `src/doc_organize/core/models.py` (`ScanErrorEntry`,
`ScanErrorReport`), `src/doc_organize/scan/scan_command.py`,
`src/doc_organize/web/routes/scan_errors.py` (nuevo),
`src/doc_organize/web/routes/scan.py`, `src/doc_organize/web/routes/downloads.py`,
`src/doc_organize/web/app.py`, `src/doc_organize/web/templates/scan_errors.html.j2`
(nuevo), `src/doc_organize/web/templates/_nav_macros.html.j2`, `src/doc_organize/main.py`,
`tests/unit/test_web_scan_errors.py` (nuevo), `tests/unit/test_web_downloads.py` (extendido).
**Descripción**: `ScanCommand.run`/`run_streaming` ganan `error_log_path:
Path | None`; al completar una ejecución con errores (conversión/OCR fallidos
o con reintento agotado), persiste un `ScanErrorReport` (con `scan_run_id`
UUID4) como línea JSONL append-only en `errores_escaneo/SCAN_ERRORS_HISTORY.jsonl`
(mismo patrón que `DEDUP_HISTORY.jsonl`) — solo si hubo al menos un error, para
no crecer con cada escaneo rutinario. Pestaña nueva con dos vistas: "Estado
actual" (lectura de `cache.db` filtrando `conversion_status=ERROR`) e
"Histórico" (agrupado por `scan_run_id`, con buscador cliente-side igual que
Duplicados). Export a Excel: un único `.xlsx` con ambas vistas en hojas
separadas ("Estado actual" / "Histórico"), reutilizando `_excel_safe()`
(neutralización de inyección de fórmulas).
**Status**: ✅ implementado y verificado, incluido contra proyectos con y sin
errores previos.

### ✅ 4. AUDIT_CODE — 4 bugs reales encontrados y corregidos
**Descripción**: auditoría propia de bugs/edge cases/performance/seguridad/
tipado/deuda técnica. Encontró y corrigió 4 problemas reales (no solo
teóricos, confirmados al correr la suite completa):
1. **Orden no determinista** de `ScanErrorEntry` dentro de un `ScanErrorReport`
   (`entries` en `ScanCommand` recorre un `set`) → `_collect_error_entries()`
   ahora ordena por `file_path`.
2. **Idempotencia de `configure_logging()` basada en `root.handlers`**: pytest
   inyecta sus propios `LogCaptureHandler` en cualquier logger con
   `propagate=False` (el que yo mismo fijé) antes de cada test, produciendo
   falsos positivos de "ya configurado" que rompían la suite completa (pero
   no el fichero de test de logging aislado — por eso no se detectó hasta
   correr todo) → sustituido por un flag interno de módulo (`_configured`).
3. **Contaminación real del repositorio**: `test_main.py` invoca `main()` de
   verdad, disparando `configure_logging()` sin control y escribiendo un
   `logs/doc_organize.log` real (~290 KB) en la raíz del repo al correr los
   tests (mitigado en git por `.gitignore` `*.log`, pero no en disco) → nueva
   fixture de sesión autouse en `tests/conftest.py` que fija
   `DOC_ORGANIZE_LOG_DIR` a una carpeta temporal antes de cualquier test.
4. **Fallo de limpieza en Windows** de esa misma fixture: `TemporaryDirectory`
   (cleanup automático) fallaba con `PermissionError` porque el
   `TimedRotatingFileHandler` real mantiene el fichero de log abierto durante
   toda la sesión de pytest → cambiado a `mkdtemp()` + `shutil.rmtree(...,
   ignore_errors=True)`.
**Status**: ✅ los 4 confirmados y corregidos; suite completa reejecutada en
verde tras cada corrección.

### ✅ 5. PLAN + AUDIT_PLAN + IMPLEMENT (refactor) — deuda técnica de la AUDIT_CODE
**Archivo(s)**: `src/doc_organize/web/scan_errors_data.py` (nuevo),
`src/doc_organize/web/routes/scan_errors.py`, `src/doc_organize/web/routes/downloads.py`,
`src/doc_organize/web/routes/duplicates.py`, `src/doc_organize/web/routes/scan.py`,
`src/doc_organize/core/constants.py`.
**Descripción**: la propia AUDIT_CODE señaló dos deudas: (a) `downloads.py`
importaba `_load_current_errors`/`_load_error_history` como funciones
"privadas" de `web/routes/scan_errors.py` (acoplamiento cruzado entre
routers no declarado); (b) el literal `"duplicados"` repetido sin constante
en 4 sitios. AUDIT_PLAN: **GO**, riesgo de regresión nulo (movimiento
mecánico, mismo valor). Se extrajeron `load_current_errors`/
`load_error_history` a `web/scan_errors_data.py` (módulo compartido no-router,
mismo criterio que `web/templating.py`/`web/pagination.py`/`web/dependencies.py`)
y se añadió `DUPLICATES_FOLDER_NAME` en `core/constants.py`, sustituyendo los
4 usos literales.
**Status**: ✅ implementado; API pública sin cambios (ambas funciones eran
privadas, sin consumidores externos ni en tests).

---

## Impacto

### Código
- **Archivos modificados**: `src/doc_organize/core/constants.py`,
  `src/doc_organize/core/models.py`, `src/doc_organize/main.py`,
  `src/doc_organize/scan/scan_command.py`, `src/doc_organize/utils/logging.py`,
  `src/doc_organize/web/app.py`, `src/doc_organize/web/routes/downloads.py`,
  `src/doc_organize/web/routes/duplicates.py`, `src/doc_organize/web/routes/scan.py`,
  `src/doc_organize/web/templates/_nav_macros.html.j2`, `tests/conftest.py`,
  `tests/unit/test_web_downloads.py`.
- **Archivos nuevos**: `src/doc_organize/web/routes/scan_errors.py`,
  `src/doc_organize/web/scan_errors_data.py`,
  `src/doc_organize/web/templates/scan_errors.html.j2`,
  `tests/unit/test_utils_logging.py`, `tests/unit/test_web_scan_errors.py`.
- **Cambios funcionales**: sí — nueva pestaña/página/API de descarga
  "Errores de Escaneo"; `ScanCommand.run`/`run_streaming` ganan
  `error_log_path` (opcional, default `None`, retrocompatible);
  `ScanErrorEntry`/`ScanErrorReport` nuevos en `core/models.py`; sistema de
  logging a fichero real (antes no existía ningún fichero de log en ningún
  entorno).

### Compatibilidad
- **BREAKING**: `utils.logging.get_logger(name, log_file=...)` pierde el
  parámetro `log_file` (condición 3 confirmada explícitamente por el
  usuario). Sin impacto interno: ningún caller del propio paquete lo usaba
  (confirmado por grep antes del cambio); si algún consumidor externo de la
  librería lo usaba, deja de funcionar y debe migrar a `configure_logging()`.
- **NO BREAKING**: el resto de cambios son aditivos (nuevos parámetros
  opcionales con default, nuevos modelos, nuevas rutas).

---

## Verificación
```
python -m ruff check src tests           → All checks passed!
python -m ruff format --check <tocados>  → sin cambios pendientes
python -m mypy src                       → Success: no issues found in 50 source files
python -m pytest -q --no-cov             → 406 passed
```
Verificado además que la suite completa no deja `logs/` ni ningún otro
artefacto en la raíz del repositorio tras ejecutarse.

---

## Riesgos Residuales

| Riesgo | Mitigación | Status |
|--------|-----------|--------|
| `SCAN_ERRORS_HISTORY.jsonl` no tiene purga/rotación (crece indefinidamente, a diferencia de `doc_organize.log` que sí rota a 15 días) | Mismo patrón ya aceptado para `DEDUP_HISTORY.jsonl`; solo se añade línea cuando hay error, no en cada escaneo | Aceptado por precedente, no mitigado |
| `_load_current_errors`/export de caché cargan toda `cache.db` en memoria y filtran en Python (sin `WHERE conversion_status='error'` a nivel SQL) | Mismo patrón que el export de caché ya existente; volumen típico de errores es pequeño frente al total de la caché | Aceptado por precedente, no mitigado |
| `TimedRotatingFileHandler` no es seguro entre múltiples procesos (varios workers de uvicorn escribiendo al mismo fichero) | Hoy `_run_web` no expone `--workers` (un único proceso); documentado en el diseño de `configure_logging()` como limitación conocida | Aceptado, no aplica todavía |
| `get_logger(log_file=...)` eliminado sin período de deprecación | Decisión explícita del usuario (condición 3); ningún caller interno lo usaba | Aceptado por decisión explícita |

---

## Siguientes Pasos (Recomendado)
1. **Confirmar y crear el/los commit(s)** — todo el trabajo de esta sesión
   está en el working tree sin commitear; pendiente de que el usuario
   confirme el mensaje de commit (propuesto: `feat: añadir gestión de
   errores de escaneo y logging a fichero con rotación diaria` +
   `refactor: extraer consultas de errores de escaneo y constante de carpeta
   duplicados`, o combinados según prefiera).
2. Si se quiere parametrizar el nivel de log también desde la CLI (no solo
   por variable de entorno), añadir flags `--log-level`/`--log-dir` en
   `main.py::build_parser()` — evaluado y descartado en esta sesión por
   alcance (las variables de entorno ya cubren lo pedido).
3. Si el volumen de errores/histórico crece de forma notable en el futuro,
   revisar el par de riesgos residuales de performance (filtro SQL en
   `CacheManager`, purga de `SCAN_ERRORS_HISTORY.jsonl`).

---

## Directrices para Futuras IAs

- **[`configure_logging()` se llama una única vez, solo en `main.py::main()`]**:
  centraliza ahí toda la configuración de logging del proceso (CLI y `web`,
  que se arranca desde el mismo `main()`). `web.create_app()` es una factoría
  pura y deliberadamente NO llama a `configure_logging()` — así los tests que
  instancian la app directamente (todos los `test_web_*.py`) no activan
  logging a fichero por accidente.
- **[Idempotencia de `configure_logging()` NUNCA debe basarse en
  `logger.handlers`]**: pytest (`_pytest.logging`) añade sus propios
  `LogCaptureHandler` a cualquier logger con `propagate=False` antes de cada
  test, lo que rompe cualquier comprobación tipo `if logger.handlers: return`.
  Usar un flag de módulo dedicado (`_configured` en `utils/logging.py`) para
  cualquier lógica de "solo una vez" sobre un logger con `propagate=False`.
- **[Tests que invocan `main()` de verdad activan logging real]**:
  `test_main.py` llama a `main([...])` directamente (sin mocks), así que
  dispara `configure_logging()` de verdad. `tests/conftest.py` tiene una
  fixture de sesión autouse (`_isolate_doc_organize_logs`) que fija
  `DOC_ORGANIZE_LOG_DIR` a una carpeta temporal (`tempfile.mkdtemp`, cleanup
  `ignore_errors=True` por el file handle abierto en Windows) antes de
  cualquier test — necesaria para no escribir `logs/` en la raíz del repo al
  correr `pytest`.
- **[No existía ningún concepto de "ejecución de escaneo" persistente antes
  de esta sesión]**: `ScanCommand` solo mantenía estado acumulado por fichero
  en `cache.db`, nunca un histórico por pasada. `scan_run_id` (UUID4) +
  `ScanErrorReport` en `errores_escaneo/SCAN_ERRORS_HISTORY.jsonl` es el
  primer precedente de este concepto — reutilizable si en el futuro se quiere
  un histórico similar para escaneos completos (no solo errores).
  `_collect_error_entries()` (`scan_command.py`) es el método a extender si
  se necesita más detalle por ejecución.
- **[Exportar "vista actual" + "histórico" combinados en Excel = un único
  `.xlsx` con `pd.ExcelWriter` y varias hojas]**: patrón establecido en
  `_build_scan_errors_export_xlsx` (`web/routes/downloads.py`) — preferirlo
  sobre generar varios ficheros cuando el usuario pide "un fichero completo".
- **[Constantes de subcarpetas de proyecto viven en `core/constants.py`]**:
  `SCAN_FOLDERS_JSON_NAME`, `SCAN_ERRORS_FOLDER_NAME`,
  `SCAN_ERRORS_HISTORY_JSONL_NAME`, `DUPLICATES_FOLDER_NAME` — seguir este
  patrón para cualquier subcarpeta/fichero nuevo de proyecto en vez de
  repetir el literal entre routers (nótese que `DEDUP_REPORT.json`/
  `DEDUP_HISTORY.jsonl` como nombres de fichero siguen sin constante — deuda
  preexistente identificada pero no resuelta en esta sesión, fuera de
  alcance de lo pedido).
- **[Módulos compartidos entre routers viven en `web/*.py`, no dentro de
  `web/routes/*.py`]**: ver `web/scan_errors_data.py`, mismo criterio que
  `web/templating.py`, `web/pagination.py`, `web/dependencies.py`. Si dos
  routers necesitan la misma consulta/lógica, extraerla ahí desde el
  principio en vez de importar un símbolo con guion bajo de otro router.

---

## Veredicto

### 🟡 GO_CONDICIONAL

**Criterios**:
- ✅ PLAN/AUDIT_PLAN ejecutados y las 4 condiciones de GO_CONDICIONAL
  confirmadas explícitamente por el usuario antes de implementar
- ✅ IMPLEMENT completo para ambas funcionalidades (Errores de Escaneo +
  logging), verificado con `ruff`/`mypy`/`pytest`
- ✅ AUDIT_CODE propia con 4 bugs reales encontrados y corregidos (no solo
  teóricos — confirmados al fallar la suite completa)
- ✅ Refactor de la deuda técnica señalada por la propia auditoría, con su
  propio PLAN/AUDIT_PLAN, sin cambios funcionales ni de API pública
- ✅ Suite completa en verde (406 passed), sin dejar artefactos en el repo
- ⬜ **Commit pendiente**: todo el trabajo está en el working tree sin
  commitear, a la espera de confirmación explícita del usuario sobre el
  mensaje de commit

**Evidencia**:
- Branch: `develop`
- Commits: ninguno todavía (working tree con cambios sin commitear)
- Tests: 406 passed (`python -m pytest -q --no-cov`)

**Sesión abierta**: 2026-09-03 (pendiente de cierre tras el commit)
