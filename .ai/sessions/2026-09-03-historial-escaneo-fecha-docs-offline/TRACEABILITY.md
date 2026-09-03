# TRACEABILITY: Resumen de Sesión

<!-- Reconstruido a partir de los commits ya creados (f66f01b, c480bd1, 4890afc) y
del CHANGELOG.md: la parte interactiva de esta sesión quedó fuera del contexto
retenido al reanudar la conversación (resumen/compactación), así que el detalle de
"Cambios Ejecutados" se apoya en la evidencia de git (mensajes de commit, diffs,
CHANGELOG), no en una narración turno a turno. -->

## Sesión
- **Fecha**: 2026-09-03
- **Tipo**: `feature` + `fix` + `docs` (cierre de versión `0.5.0`)
- **Rama**: `develop`
- **Estado**: ✅ COMPLETADA (commits ya creados, `pyproject.toml`/`CHANGELOG.md` sincronizados)

## Objetivo
Tres piezas de trabajo cerradas en la release `0.5.0`: (1) corregir que el
escaneo redescubría sus propias imágenes extraídas en `Conversión/` como
documentos nuevos; (2) mostrar tiempos de ejecución de escaneo y fechas
localizadas (español/`Europe/Madrid`) en vez de timestamps ISO 8601 crudos en
toda la UI; (3) documentar instalación de OCR/audio-vídeo por sistema
operativo y automatizar la distribución offline de la documentación (ZIP +
checksums vía GitHub Actions).

## Cambios Ejecutados

### ✅ 1. fix — excluir `output_dir` del propio escaneo
**Commit**: `f66f01b`
**Archivo(s)**: `src/doc_organize/scan/scan_command.py`,
`src/doc_organize/scanner/document_scanner.py`,
`tests/unit/test_document_scanner.py`.
**Descripción**: `DocumentScanner.scan_folders()` no excluía `output_dir`
(`Conversión/`) de su propio recorrido — las imágenes extraídas en
conversiones previas (`img/<stem>/*.png`, con `extract_images=True`) se
redescubrían como documentos nuevos en el siguiente escaneo. Al reconvertir
secuencialmente el documento original, su carpeta `img/<stem>/` se borraba y
regeneraba a mitad de escaneo, y la "conversión" de esa imagen fallaba con
`FileNotFoundError` (el propio origen del reporte que motivó la sesión previa
de reintentos de `ERROR`, `2026-09-02-reintento-conversiones-error`, pero como
síntoma nuevo). `DocumentScanner.scan_folders()` gana `exclude_dir: Path |
None = None` (opt-in); `ScanCommand.run_streaming()` lo usa pasando
`output_dir` ya resuelto.
**Status**: ✅ commiteado, con test de regresión en `test_document_scanner.py`.

### ✅ 2. feat — historial de duración de ejecuciones de escaneo
**Archivo(s)**: `src/doc_organize/core/models.py` (`ScanRunReport`),
`src/doc_organize/scan/scan_history_store.py` (nuevo),
`src/doc_organize/scan/scan_command.py`, `src/doc_organize/core/constants.py`
(`SCAN_HISTORY_FOLDER_NAME`, `SCAN_HISTORY_JSONL_NAME`),
`src/doc_organize/web/routes/scan.py`,
`src/doc_organize/web/templates/folder_selector.html.j2`,
`tests/unit/test_scan_history_store.py` (nuevo), `tests/unit/test_scan_command.py`,
`tests/unit/test_web_scan.py`, `tests/unit/test_main.py`.
**Descripción**: `ScanRunReport` (`scan_run_id`, `started_at`, `finished_at`,
`duration_seconds`, `total_scanned`, `completed`) persistido en
`historial_escaneo/SCAN_HISTORY.jsonl` (append-only) vía
`scan_history_store.append_scan_run()`/`list_scan_runs()` — mismo patrón que
`SCAN_ERRORS_HISTORY.jsonl`/`DEDUP_HISTORY.jsonl`, pero registra **toda**
ejecución (completada o no), no solo las que producen error. `ScanCommand.run`/
`run_streaming` ganan `history_log_path: Path | None = None` y `ScanSummary`
gana `duration_seconds` (reflejado en el CLI: "Tiempo de ejecución: …"). Una
ejecución interrumpida por una excepción se registra igualmente, con
`completed=False`. Pantalla "Escanear" muestra la duración de la última
ejecución + pestaña nueva "Historial de ejecuciones".
**Status**: ✅ commiteado (`4890afc`), con tests unitarios del store y de la
integración con `ScanCommand`/la ruta web.

### ✅ 3. feat — formato de fecha/hora localizado
**Archivo(s)**: `src/doc_organize/utils/date_format.py` (nuevo),
`src/doc_organize/web/templating.py`,
`src/doc_organize/web/templates/dashboard.html.j2`,
`project_selector.html.j2`, `duplicates_resolver.html.j2`,
`scan_errors.html.j2`, `folder_selector.html.j2`,
`tests/unit/test_date_format.py` (nuevo), `tests/unit/test_web_templating.py`,
`tests/unit/test_web_duplicates.py`, `tests/unit/test_web_scan_errors.py`.
**Descripción**: `format_datetime(value, pattern=None, tz_name=None)` /
`format_duration(seconds)`, registrados como filtros Jinja
(`web/templating.py`), centralizan cómo se muestran los timestamps ISO 8601
UTC que genera el resto del proyecto. Parametrizable vía
`DOC_ORGANIZE_DATE_FORMAT`/`DOC_ORGANIZE_TIMEZONE` — mismo patrón de
resolución `parámetro → variable de entorno → default` ya establecido por
`utils/logging.py` en la sesión `2026-09-03-errores-escaneo-logging`. Default:
`dd/mm/aaaa HH:MM:SS`, zona `Europe/Madrid` (con cambio automático de horario
de verano/invierno, de ahí que un timestamp de agosto se vea +2h en vez de
+1h). Nueva dependencia `tzdata` en `pyproject.toml` (necesaria para
`zoneinfo` en Windows). Las 5 plantillas que mostraban ISO 8601 crudo pasan
ahora por este filtro.
**Status**: ✅ commiteado, con test de degradación (`format_datetime` no
lanza excepción ante timestamp corrupto o zona horaria mal configurada —
devuelve el valor original, mismo criterio de tolerancia que
`load_error_history`/`_load_dedup_history`).

### ✅ 4. fix — robustez de la persistencia de históricos durante el escaneo
**Descripción**: dos correcciones incluidas en el mismo commit de release
(`4890afc`): (a) la persistencia del histórico de duración se mueve a
**antes** de emitir el evento `COMPLETED` (no en un `finally` posterior) para
evitar una carrera intermitente con la desconexión del cliente WebSocket, que
cierra la conexión en cuanto recibe ese evento; (b) un fallo de E/S al
escribir el histórico de tiempos o el de errores de escaneo (permiso
denegado, disco lleno) ya no aborta un escaneo que por lo demás terminó con
éxito — ambas escrituras son ahora best-effort (warning logueado, sin
propagar la excepción).
**Status**: ✅ commiteado.

### ✅ 5. docs — instalación de OCR/audio-vídeo por SO + distribución offline
**Commit**: `c480bd1` (guías) + `4890afc` (automatización).
**Archivo(s)**: `docs/guides/installation.md`, `docs/guides/troubleshooting.md`,
`scripts/build_docs_zip.py` (nuevo), `.github/workflows/docs-zip-release.yml`
(nuevo).
**Descripción**: instrucciones específicas de Windows/Linux/macOS para el
extra `ocr-gpu` (CUDA, `libGL.so.1`, aviso EasyOCR/MPS en Mac) y para el extra
`av` (instalación de `ffmpeg` por SO + restricción de Python 3.11-3.13 por
`numba`/`llvmlite`), con 3 entradas de troubleshooting nuevas. Script
`build_docs_zip.py` empaqueta el sitio MkDocs compilado en un `.zip` +
checksums SHA256 (`dist/doc_organize-docs-{version}.zip[.sha256]`,
`CHECKSUMS.txt` histórico). Workflow `docs-zip-release.yml`: en cada push a
`main`/`develop` que toque `docs/`, `mkdocs.yml` o `pyproject.toml`, construye
con `mkdocs build --strict`, empaqueta y publica una GitHub Release
(`docs-v{version}`) con el ZIP + checksums adjuntos.
**Status**: ✅ commiteado; `mkdocs build --strict` verificado en esta
actualización de la sesión (sin errores ni warnings de links rotos).

---

## Impacto

### Código
- **Archivos modificados/creados** (24 en el commit de release + 3 en el fix
  previo): ver `git show --stat f66f01b`/`4890afc` para el detalle completo;
  resumen por área en "Cambios Ejecutados" arriba.
- **Cambios funcionales**: sí — nuevo modelo `ScanRunReport`, nuevo store
  `scan_history_store`, nuevo módulo `utils/date_format.py`, nueva pestaña
  "Historial de ejecuciones", exclusión de `output_dir` del escaneo,
  escritura best-effort de históricos.

### Compatibilidad
- **BREAKING**: ninguno.
- **NO BREAKING**: `history_log_path` en `ScanCommand.run`/`run_streaming` es
  un parámetro opcional nuevo (default `None`); `format_datetime`/
  `format_duration` son filtros Jinja añadidos, no sustituyen ningún filtro
  existente; `exclude_dir` en `DocumentScanner.scan_folders()` es opt-in.

---

## Verificación
```
python -m ruff check src tests        → All checks passed!
python -m mypy src                    → Success: no issues found in 52 source files
python -m pytest -q --no-cov          → 435 passed
python -m mkdocs build --strict       → Documentación construida sin errores
```
(Re-ejecutado íntegramente al escribir esta traceability, sobre el HEAD real
del repo tras los 3 commits — no una promesa, sino la verificación del estado
actual en `develop`.)

---

## Riesgos Residuales

| Riesgo | Mitigación | Status |
|--------|-----------|--------|
| `historial_escaneo/SCAN_HISTORY.jsonl` no tiene purga (crece con cada escaneo, a diferencia de `doc_organize.log` que rota a 15 días) | Mismo patrón ya aceptado para `DEDUP_HISTORY.jsonl`/`SCAN_ERRORS_HISTORY.jsonl` (ver sesión `2026-09-03-errores-escaneo-logging`) | Aceptado por precedente, no mitigado |
| Zona horaria por defecto fija a `Europe/Madrid` si `DOC_ORGANIZE_TIMEZONE` no se define | Coherente con que el proyecto es de un usuario en España; parametrizable por variable de entorno para otros despliegues | Aceptado por diseño |
| `docs-zip-release.yml` crea una GitHub Release en cada push a `main`/`develop` que toque `docs/` | Filtro de paths ya acota el disparo a cambios relevantes; revisar si genera releases con demasiada frecuencia en la práctica | A vigilar tras las primeras ejecuciones reales en CI |

---

## Siguientes Pasos (Recomendado)
1. Confirmar que el workflow `docs-zip-release.yml` se comporta como se
   espera en el primer push real a `main`/`develop` que toque `docs/` (no
   verificable localmente, solo en GitHub Actions).
2. Si `historial_escaneo/SCAN_HISTORY.jsonl` crece de forma notable en
   proyectos con escaneos muy frecuentes, revisar una política de purga
   (mismo riesgo ya señalado para los históricos de errores/duplicados).

---

## Directrices para Futuras IAs

- **[`output_dir` debe excluirse explícitamente del propio escaneo]**:
  `DocumentScanner.scan_folders(..., exclude_dir=output_dir)` — cualquier
  pipeline futuro que escanee y escriba salida bajo una ruta potencialmente
  incluida en las carpetas de entrada debe pasar `exclude_dir`, o repetirá el
  bug de redescubrir sus propias imágenes/salidas extraídas como documentos
  nuevos.
- **[Los históricos JSONL de proyecto siguen un patrón único ya establecido]**:
  `scan_history_store.py` (`historial_escaneo/SCAN_HISTORY.jsonl`) es el
  tercer histórico con este patrón append-only, tras `DEDUP_HISTORY.jsonl` y
  `SCAN_ERRORS_HISTORY.jsonl` (sesión `2026-09-03-errores-escaneo-logging`) —
  diferencia clave: este registra **toda** ejecución, no solo las
  "interesantes" (con error/duplicados). Cualquier histórico nuevo de este
  tipo debe decidir explícitamente cuál de los dos criterios de "cuándo
  añadir una línea" aplica.
- **[Escrituras de histórico son best-effort, nunca deben abortar un escaneo
  exitoso]**: decisión de diseño explícita de esta sesión — un fallo de E/S
  al persistir `SCAN_HISTORY.jsonl`/`SCAN_ERRORS_HISTORY.jsonl` se loguea
  como warning, nunca propaga. Igual que el límite de reintentos
  (`2026-09-02-reintento-conversiones-error`), un mecanismo de
  telemetría/histórico no debe poder convertir un escaneo que por lo demás
  tuvo éxito en un fallo visible para el usuario.
- **[`utils/date_format.py` sigue el mismo patrón de parametrización que
  `utils/logging.py`]**: parámetro explícito → variable de entorno
  (`DOC_ORGANIZE_DATE_FORMAT`/`DOC_ORGANIZE_TIMEZONE`) → default. Cualquier
  configuración nueva de "cómo se muestra/comporta algo, con opción de
  override" en este proyecto debería seguir esta misma jerarquía de
  resolución para ser consistente.
- **[`format_datetime`/`format_duration` degradan, nunca lanzan]**: un
  timestamp corrupto o una zona horaria mal configurada devuelve el valor
  original en vez de tumbar la página con un 500 — mismo criterio de
  tolerancia a datos corruptos que `load_error_history`/`_load_dedup_history`
  aplican a líneas JSONL inválidas. Cualquier filtro Jinja que renderice
  datos persistidos (no generados en el momento) debería seguir este mismo
  criterio de "degradar, no romper la página".
- **[Persistir históricos antes de emitir el evento `COMPLETED`, no después]**:
  el cliente WebSocket cierra la conexión en cuanto recibe `COMPLETED` — toda
  escritura que deba completarse "durante" el escaneo (históricos,
  telemetría) debe ejecutarse antes de ese `yield`, nunca en un `finally`
  posterior o en un paso que dependa de que la conexión siga abierta.
- **[Esta traceability se reconstruyó desde `git log`/`CHANGELOG.md`, no
  desde la conversación]**: si en el futuro una sesión queda con
  documentación pendiente tras una compactación de contexto, el propio
  `CHANGELOG.md` (cuando está bien mantenido, como en este caso) es
  suficiente fuente para reconstruir un `TRACEABILITY.md` fiel — no hace
  falta inventar detalle que no está en la evidencia de git.

---

## Veredicto

### 🟢 COMPLETADA

**Criterios**:
- ✅ Los 3 commits (`f66f01b`, `c480bd1`, `4890afc`) ya existen en `develop`
- ✅ `pyproject.toml` (`0.5.0`) y `CHANGELOG.md` sincronizados (checklist
  `sync.instructions.md` §1 y §4)
- ✅ `mkdocs build --strict` verificado sin errores en esta actualización
- ✅ Suite completa en verde (435 passed) sobre el HEAD real
- ✅ Documentación de sesión (`.ai/sessions/`) creada retroactivamente para
  cerrar el hueco de gobernanza dejado por la compactación de contexto

**Evidencia**:
- Branch: `develop`
- Commits: `f66f01b`, `c480bd1`, `4890afc`
- Tests: 435 passed (`python -m pytest -q --no-cov`)

**Sesión cerrada**: 2026-09-03
