# TRACEABILITY: Resumen de Sesión

## Sesión
- **Fecha**: 2026-09-03
- **Tipo**: `feature` (PLAN → AUDIT_PLAN → IMPLEMENT → AUDIT_CODE) + `refactor` (PLAN → AUDIT_PLAN → IMPLEMENT → AUDIT_CODE) sobre deuda técnica que la propia feature había dejado señalada
- **Rama**: `develop`
- **Estado**: ✅ COMPLETADA (implementación, auditoría, tests y commit en verde)

## Objetivo
Extender el patrón de duración/progreso en vivo ya liberado en v0.6.0 (duración de
"Buscar duplicados" y barra de progreso de "Escanear") a las fases del pipeline
que aún carecían de él: duración por documento en conversión/OCR, duración de
descubrimiento de ficheros, y progreso en vivo real de la detección/movimiento
de duplicados (antes un semáforo que solo simulaba "en ejecución" sobre una
única llamada POST bloqueante). Excluido explícitamente del alcance:
instrumentar `OCRScheduler` (módulo con su propio ciclo de vida/tests —
`test_ocr_scheduler.py` es `@pytest.mark.slow`, usa Docling real sin mocks — por
beneficio marginal, ya que el reproceso OCR es minoritario). El usuario pidió
explícitamente el flujo `PLAN y AUDIT_PLAN` antes de implementar, y confirmó
después 4 condiciones de un `GO_CONDICIONAL` antes de pasar a `IMPLEMENT`.

Una vez cerrada la feature, el usuario pidió además una segunda pieza —
`refactor` con su propio `PLAN`/`AUDIT_PLAN` (veredicto `GO`, sin condiciones)—
para extraer a `core/constants.py` los literales `"DEDUP_REPORT.json"`/
`"DEDUP_HISTORY.jsonl"`/`"duplicados"` que la propia feature (y una sesión
anterior, `2026-09-03-errores-escaneo-logging`) había señalado como deuda
técnica fuera de alcance.

## Cambios Ejecutados

### ✅ 1. PLAN + AUDIT_PLAN — Instrumentación de duración/progreso
**Descripción**: investigación previa (agente Explore) del pipeline de escaneo
(`ScanCommand.run_streaming`) y de la acción de deduplicación (`deduplicate()`,
sin ningún evento de progreso). Halló que `ConversionResult.duration_seconds`
(por documento) y `ScanResult.scan_duration_seconds` (descubrimiento) ya se
calculaban pero se descartaban sin surface-ar en ningún evento/resumen —
candidatos de menor riesgo. AUDIT_PLAN: **GO_CONDICIONAL** con 4 condiciones —
(1) `ScanCommand.deduplicate()` síncrono se elimina (no se mantiene como
wrapper), (2) el progreso en vivo de deduplicación entra en la misma sesión,
no se aplaza, (3) nombres de los dos campos nuevos (`total_conversion_seconds`,
`discovery_duration_seconds`) propuestos por la IA y aceptados tal cual, (4)
exclusión de `OCRScheduler` reconfirmada (solo se lee un dato ya calculado en
`scan_command.py`, cero cambios en `ocr_scheduler.py`/sus tests).
**Status**: ✅ las 4 condiciones confirmadas explícitamente por el usuario.

### ✅ 2. IMPLEMENT — Duración por documento y de descubrimiento
**Archivo(s)**: `src/doc_organize/core/models.py` (`ScanRunReport` gana 2
campos opcionales), `src/doc_organize/scan/scan_command.py` (`ScanSummary`,
`run_streaming`, `_convert_documents`, `_process_ocr`), `tests/unit/test_web_scan.py`.
**Descripción**: `FILE_CONVERTED`/`OCR_PROCESSED` incluyen ahora
`duration_seconds` (de `ConversionResult`, ya calculado); `SCANNED` incluye
`discovery_duration_seconds` (de `ScanResult`, ya calculado). `ScanSummary`
acumula ambos en `total_conversion_seconds`/`discovery_duration_seconds`,
reflejados en `render()` (CLI), en el evento `COMPLETED` y persistidos en
`ScanRunReport` (campos opcionales, `None` en históricos previos — mismo
criterio que `DeduplicationReport.started_at`).
**Status**: ✅ implementado y verificado (incluida una ejecución real con
Docling, `@slow`).

### ✅ 3. IMPLEMENT — Progreso en vivo de deduplicación (WebSocket)
**Archivo(s)**: `src/doc_organize/core/models.py` (`DedupEventType`,
`DedupEvent`), `src/doc_organize/dedup/deduplication.py` (`move_group()`,
`finalize_report()` nuevos y públicos; `resolve_duplicates()` los compone),
`src/doc_organize/scan/scan_command.py` (`deduplicate()` **eliminado**,
sustituido por `deduplicate_streaming()`), `src/doc_organize/main.py`
(`_run_deduplicate` consume el generador directamente), `src/doc_organize/web/routes/scan.py`
(`POST /api/projects/{name}/scan/deduplicate` **eliminado**; nuevo
`WS /api/projects/{name}/scan/deduplicate`; `_authorize_scan_websocket`
renombrado a `_authorize_project_websocket`, compartido por ambos WebSocket),
`src/doc_organize/web/templates/duplicates_resolver.html.j2` (barra de
progreso real por grupo, semáforo conectado a eventos reales en vez de
simulados), `tests/unit/test_web_scan.py`, `tests/unit/test_web_duplicates.py`,
`tests/unit/test_main.py`.
**Descripción**: `DeduplicationManager.resolve_duplicates()` se descompuso en
dos primitivas públicas reutilizables — `move_group()` (mueve los descartados
de un único grupo) y `finalize_report()` (persiste `DEDUP_REPORT.json`/
`DEDUP_HISTORY.jsonl`) — para que `ScanCommand.deduplicate_streaming()` (nuevo
async generator) pueda yieldear `DedupEvent` (`started`/`duplicates_found`/
`group_started`/`group_resolved`/`completed`) entre medias sin duplicar la
lógica de movimiento ni de persistencia. El resolver interactivo
(`web/routes/duplicates.py::resolve_duplicates`) sigue usando
`DeduplicationManager.resolve_duplicates()` sin cambios de contrato.
**Status**: ✅ implementado y verificado, incluida la reescritura completa de
los tests que antes ejercían el `POST` (ahora WebSocket) y del CLI
(`ScanCommand().deduplicate_streaming(...)`).

### ✅ 4. AUDIT_CODE — sin bugs encontrados
**Descripción**: auditoría propia de bugs/edge cases/performance/seguridad/
tipado/deuda técnica sobre las piezas 2-3. Sin hallazgos nuevos — edge cases
revisados (grupos vacíos en dedup, excepción a mitad de `move_group()`,
campos `None` en históricos JSONL antiguos) coinciden con el comportamiento ya
existente o con patrones de riesgo ya presentes en el proyecto (p. ej. una
excepción no-`WebSocketDisconnect` durante el streaming ya no se capturaba en
`scan_websocket` tampoco, mismo perfil de riesgo, no una regresión nueva).
**Status**: ✅ 439 tests (`python -m pytest -q --no-cov`), `ruff`/`mypy`/
`mkdocs build --strict` en verde.

### ✅ 5. PLAN + AUDIT_PLAN + IMPLEMENT + AUDIT_CODE (refactor) — constantes de fichero de deduplicación
**Archivo(s)**: `src/doc_organize/core/constants.py` (nuevas
`DEDUP_REPORT_JSON_NAME`, `DEDUP_HISTORY_JSONL_NAME`),
`src/doc_organize/dedup/deduplication.py`,
`src/doc_organize/web/routes/downloads.py`,
`src/doc_organize/web/routes/duplicates.py`, `src/doc_organize/main.py`.
**Descripción**: 5 sitios (2 ficheros × 2 literales, más `"duplicados"` en
`main.py::_resolve_dedup_paths`, hallado durante la verificación de alcance del
propio PLAN) sustituidos por las constantes, mismo patrón que
`SCAN_HISTORY_JSONL_NAME`/`SCAN_ERRORS_HISTORY_JSONL_NAME`. AUDIT_PLAN: **GO**,
sin condiciones (movimiento mecánico, mismo valor, ningún test depende del
literal en el lado de producción).
**Status**: ✅ implementado; API pública sin cambios; verificado que no queda
ningún literal `"DEDUP_REPORT.json"`/`"DEDUP_HISTORY.jsonl"`/`"duplicados"`
fuera de `core/constants.py` (grep sobre `src/`).

---

## Impacto

### Código
- **Archivos modificados**: `.ai/glossary.md`, `docs/functional/dedup.md`,
  `docs/functional/index.md`, `src/doc_organize/core/constants.py`,
  `src/doc_organize/core/models.py`, `src/doc_organize/dedup/deduplication.py`,
  `src/doc_organize/main.py`, `src/doc_organize/scan/scan_command.py`,
  `src/doc_organize/web/dependencies.py`, `src/doc_organize/web/routes/downloads.py`,
  `src/doc_organize/web/routes/duplicates.py`, `src/doc_organize/web/routes/scan.py`,
  `src/doc_organize/web/templates/duplicates_resolver.html.j2`,
  `src/doc_organize/web/templates/folder_selector.html.j2`,
  `tests/unit/test_main.py`, `tests/unit/test_web_duplicates.py`,
  `tests/unit/test_web_scan.py`.
- **Archivos nuevos**: ninguno (todo el código nuevo vive en módulos existentes).
- **Cambios funcionales**: sí — duración por documento/descubrimiento surfaced
  en eventos y resúmenes; progreso en vivo real de deduplicación (antes
  simulado); dos primitivas públicas nuevas en `DeduplicationManager`.

### Compatibilidad
- **BREAKING**: `ScanCommand.deduplicate()` eliminado (usar
  `deduplicate_streaming()`); `POST /api/projects/{name}/scan/deduplicate`
  eliminado (usar `WS /api/projects/{name}/scan/deduplicate`). Decisión
  explícita del usuario (condición 1 del `GO_CONDICIONAL`); sin consumidores
  internos del contrato anterior que quedaran sin migrar (CLI y web
  actualizados en la misma sesión).
- **NO BREAKING**: el resto de cambios son aditivos (campos opcionales nuevos,
  claves nuevas en payloads de eventos existentes, métodos públicos nuevos).
  El refactor de constantes (pieza 5) no cambia ningún valor ni comportamiento.

---

## Verificación
```
python -m ruff check src tests           → All checks passed!
python -m mypy src                       → Success: no issues found in 52 source files
python -m pytest -q --no-cov             → 439 passed (incluye @slow, Docling real)
python -m mkdocs build --strict          → Documentación construida sin errores
```

---

## Riesgos Residuales

| Riesgo | Mitigación | Status |
|--------|-----------|--------|
| Una excepción no-`WebSocketDisconnect` durante `deduplicate_streaming()` (p. ej. permiso denegado moviendo un fichero) propaga sin yieldear `COMPLETED` ni escribir historial | Mismo perfil de riesgo que `scan_websocket`/`run_streaming()` ya tenían antes de esta sesión (no es una regresión nueva); no se ha hecho más robusto en ninguno de los dos porque no formaba parte del alcance pedido | Aceptado por precedente, no mitigado |
| `S1192` (Sonar): el literal `"Project not found"` se repite 3 veces en `web/routes/scan.py` (2 ya preexistían; la ruta WebSocket nueva de deduplicación añade la 3ª) | Cosmético, sin extraer constante — no forma parte del alcance pedido | Aceptado, no mitigado |
| `DEDUP_HISTORY.jsonl`/`SCAN_HISTORY.jsonl` siguen sin purga (crecen indefinidamente) | Riesgo ya señalado y aceptado por precedente en sesiones anteriores (`2026-09-03-errores-escaneo-logging`, `2026-09-03-historial-escaneo-fecha-docs-offline`) | Aceptado por precedente, no mitigado |

---

## Siguientes Pasos (Recomendado)
1. `git push` a `origin/develop` — pendiente de confirmación explícita del
   usuario (no ejecutado en esta sesión).
2. Si se detecta que el perfil de riesgo de excepciones no capturadas durante
   el streaming (escaneo o deduplicación) causa problemas reales en producción,
   revisar un manejo más robusto en ambos WebSocket a la vez (mismo patrón,
   no solo el de deduplicación).

---

## Directrices para Futuras IAs

- **[`DeduplicationManager.move_group()`/`finalize_report()` son las primitivas
  a reutilizar para cualquier progreso granular de deduplicación]**:
  `resolve_duplicates()` (todo de una vez, usado por el resolver interactivo)
  y `ScanCommand.deduplicate_streaming()` (con progreso por grupo, usado por
  "Buscar duplicados") componen las mismas dos primitivas — no dupliques la
  lógica de mover un grupo ni de persistir el reporte en un tercer sitio.
- **[Un método de orquestación que emite progreso no necesita una variante
  síncrona "resumen final" en la misma clase]**: `ScanCommand.run()` sí
  mantiene ese wrapper sobre `run_streaming()` (precedente previo), pero
  `deduplicate()` se eliminó deliberadamente en vez de mantenerlo (decisión
  explícita del usuario) — los llamadores que solo quieren el resumen
  (`main.py::_run_deduplicate`) consumen el generador y se quedan con el
  evento `COMPLETED`. Si aparece un tercer caso similar, no asumas que "debe"
  llevar wrapper: pregunta el criterio explícitamente, como en esta sesión.
- **[`_authorize_project_websocket` (antes `_authorize_scan_websocket`) es
  compartido por cualquier WebSocket nuevo de `web/routes/scan.py` que opere
  sobre las carpetas guardadas de un proyecto]**: reutilízalo en vez de
  reimplementar la resolución de `tenant_id`/`allowed_scan_roots` — ya cubre
  tanto escaneo como deduplicación.
- **[Un dato ya calculado y descartado (logueado pero no persistido/emitido)
  es una señal de instrumentación de bajo riesgo]**: tanto
  `ConversionResult.duration_seconds` como `ScanResult.scan_duration_seconds`
  ya existían antes de esta sesión — el trabajo fue "plumbing", no cálculo
  nuevo. Al buscar candidatos de instrumentación futura en este proyecto,
  grepear primero qué duraciones ya se calculan y solo se loguean.
- **[Constantes de fichero/carpeta de proyecto viven en `core/constants.py`,
  sin excepción]**: `DEDUP_REPORT_JSON_NAME`/`DEDUP_HISTORY_JSONL_NAME` cierran
  la deuda que había quedado señalada en `2026-09-03-errores-escaneo-logging`
  (que dejó `DEDUP_REPORT.json`/`DEDUP_HISTORY.jsonl` fuera de alcance). Antes
  de dar una tarea de este tipo por completa, grepea el literal exacto sobre
  todo `src/` (no solo los sitios ya conocidos) — en esta sesión reveló un
  cuarto sitio (`main.py`, literal `"duplicados"`) que no estaba en la lista
  inicial de deuda señalada.

---

## Veredicto

### 🟢 COMPLETADA

**Criterios**:
- ✅ PLAN/AUDIT_PLAN ejecutados para ambas piezas (feature con 4 condiciones
  `GO_CONDICIONAL` confirmadas explícitamente; refactor con `GO` sin condiciones)
- ✅ IMPLEMENT completo para ambas piezas, verificado con `ruff`/`mypy`/`pytest`/`mkdocs`
- ✅ AUDIT_CODE propio para ambas piezas, sin hallazgos nuevos
- ✅ Suite completa en verde (439 passed, incluidos `@slow`), sin dejar
  artefactos en el repo
- ✅ CHANGELOG.md y `pyproject.toml` (0.7.0) sincronizados en el mismo commit
  de release (mismo patrón que v0.6.0/v0.5.0)
- ⬜ Push a `origin/develop`: pendiente de confirmación explícita del usuario

**Evidencia**:
- Branch: `develop`
- Commits: ver `git log` (commit de release `v0.7.0` creado en esta sesión,
  bundling código + CHANGELOG + versión, mismo patrón que el commit `5704c68`
  de v0.6.0)
- Tests: 439 passed (`python -m pytest -q --no-cov`)

**Sesión cerrada**: 2026-09-03
