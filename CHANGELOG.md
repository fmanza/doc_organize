# Changelog

Formato basado en [Keep a Changelog](https://keepachangelog.com/es/1.0.0/).
Este proyecto sigue [SemVer](https://semver.org/lang/es/) desde v0.2.0 (sin
releases publicados antes de esa versión).

## [Unreleased]

### Fixed

- `src/doc_organize/web/templates/base.html.j2`: la tabla de la pestaña "Historial de ejecuciones"
  (Escanear) mostraba scroll horizontal — el contenedor `<main>` compartido por toda la app
  (`max-w-[720px]`) era más estrecho que las 7 columnas de la tabla. Ampliado a `max-w-[920px]`.
- `pyproject.toml`: el extra `ocr-gpu` instalaba `torch`/`torchvision`/`opencv-python` pero no
  `easyocr` en sí, el paquete que Docling realmente carga para el motor OCR acelerado por GPU —
  `pip install .[ocr-gpu]` seguido de `--use-ocr --use-gpu` fallaba con
  `EasyOCR is not installed`. Añadido `easyocr>=1.7` al extra (`docs/guides/installation.md` y
  `.ai/product.md` actualizados para reflejarlo).

### Added

- `src/doc_organize/web/routes/downloads.py`: nuevo `GET /downloads/projects/{name}/export-preview`
  (`_compute_export_preview()`) — nº de ficheros y tamaño total en bytes que incluiría `export.zip`,
  sin generarlo; espeja las mismas tres fuentes que `_build_export_zip()` (`Conversión/`,
  `cache_export.json`, `DEDUP_REPORT.json`).
- `src/doc_organize/web/templates/_nav_macros.html.j2`: "Descargar export" muestra ahora esa
  estimación de tamaño/nº de archivos junto al botón (cargada vía `fetch` al `export-preview`) y,
  si el navegador soporta la File System Access API (`showDirectoryPicker`, Chrome/Edge en contexto
  seguro), permite elegir la carpeta de destino y escribe el ZIP ahí; en el resto de navegadores
  cae al comportamiento estándar (carpeta de descargas configurada del navegador).

## [0.7.0] - 2026-09-03

### Added

- `src/doc_organize/core/models.py`: `ScanRunReport` gana `discovery_duration_seconds`/
  `total_conversion_seconds` (ambos opcionales — `None` en históricos previos a estos campos,
  para no romper la carga de líneas ya escritas en `SCAN_HISTORY.jsonl`). Nuevo `DedupEventType`
  (`started`/`duplicates_found`/`group_started`/`group_resolved`/`completed`) y `DedupEvent`,
  mismo patrón que `ScanEventType`/`ScanEvent`, emitidos por `ScanCommand.deduplicate_streaming()`.
- `src/doc_organize/scan/scan_command.py`: el payload de `FILE_CONVERTED`/`OCR_PROCESSED` gana
  `duration_seconds` (ya calculado por `ConversionResult`, antes descartado); el de `SCANNED` gana
  `discovery_duration_seconds` (ya calculado por `DocumentScanner.scan_folders()`, antes descartado).
  `ScanSummary` acumula ambos (`total_conversion_seconds`, `discovery_duration_seconds`) y los
  refleja en `render()` (CLI) y en el evento `COMPLETED`.
- `src/doc_organize/dedup/deduplication.py`: `DeduplicationManager` gana `move_group()` (mueve los
  descartados de un único grupo) y `finalize_report()` (persiste `DEDUP_REPORT.json`/
  `DEDUP_HISTORY.jsonl`), ambos públicos — `resolve_duplicates()` pasa a componerlos.
- `src/doc_organize/web/routes/scan.py`: nuevo WebSocket `WS /api/projects/{name}/scan/deduplicate`,
  retransmitiendo cada `DedupEvent` en vivo (progreso por grupo de duplicados detectado/movido) —
  mismo patrón que el WebSocket de escaneo.
- `src/doc_organize/web/templates/duplicates_resolver.html.j2`: la pestaña "Buscar duplicados"
  muestra ahora una barra de progreso en vivo por grupo ("Moviendo grupo X/Y…") y la duración de la
  ejecución, en vez de un semáforo que solo simulaba "en ejecución" sobre una única llamada bloqueante.
- `src/doc_organize/web/templates/folder_selector.html.j2`: la pantalla "Escanear" muestra ahora la
  duración de descubrimiento de ficheros y de conversión acumulada, tanto en la última ejecución
  (en vivo y tras recargar) como en cada fila del histórico de ejecuciones.
- `src/doc_organize/core/constants.py`: `DEDUP_REPORT_JSON_NAME` (`DEDUP_REPORT.json`),
  `DEDUP_HISTORY_JSONL_NAME` (`DEDUP_HISTORY.jsonl`) — nombres de fichero de deduplicación
  centralizados, mismo patrón que `SCAN_HISTORY_JSONL_NAME`/`SCAN_ERRORS_HISTORY_JSONL_NAME`.

### Changed

- `src/doc_organize/web/routes/scan.py`: `_authorize_scan_websocket` renombrado a
  `_authorize_project_websocket` — ahora compartido por los WebSocket de escaneo y de deduplicación.
- `src/doc_organize/dedup/deduplication.py`, `src/doc_organize/web/routes/downloads.py`,
  `src/doc_organize/web/routes/duplicates.py`, `src/doc_organize/main.py`: los literales
  `"DEDUP_REPORT.json"`/`"DEDUP_HISTORY.jsonl"`/`"duplicados"` pasan a usar las constantes
  centralizadas de `core/constants.py` (sin cambio de valor ni de comportamiento).

### Removed

- `src/doc_organize/scan/scan_command.py`: `ScanCommand.deduplicate()` eliminado — sustituido por
  `deduplicate_streaming()` (async generator con progreso, ver "Added"). Sin variante síncrona de
  resumen final: los llamadores que solo necesitan el resumen (CLI) consumen el generador y se
  quedan con su evento `COMPLETED`.
- `src/doc_organize/web/routes/scan.py`: `POST /api/projects/{name}/scan/deduplicate` eliminado —
  sustituido por el WebSocket `WS /api/projects/{name}/scan/deduplicate` (ver "Added").

## [0.6.0] - 2026-09-03

### Added

- `src/doc_organize/core/models.py`: `DeduplicationReport` gana `started_at`/`duration_seconds`
  (ambos opcionales — `None` en históricos previos a este campo, para no romper la carga de líneas ya
  escritas en `DEDUP_HISTORY.jsonl`).
- `src/doc_organize/dedup/deduplication.py`: `DeduplicationManager.resolve_duplicates()` acepta un
  nuevo parámetro opcional `started_at: datetime | None = None` — cuando se pasa, calcula
  `duration_seconds` cubriendo desde ahí hasta que termina la resolución.
- `src/doc_organize/scan/scan_command.py`: `DeduplicationSummary` gana `duration_seconds`;
  `ScanCommand.deduplicate()` captura `started_at` antes de re-escanear/detectar duplicados, para que
  la duración cubra la operación completa de "Buscar duplicados" (mismo criterio que
  `duration_seconds` en `ScanSummary`/`ScanRunReport` para "Escanear").
- `src/doc_organize/web/routes/scan.py`: `DeduplicateFoldersResponse` gana `duration_seconds`.
- `src/doc_organize/web/routes/duplicates.py`: el formulario interactivo de resolución
  (`POST /api/projects/{name}/duplicates/resolve`) también captura y persiste `started_at`/
  `duration_seconds`, mismo criterio que la acción masiva "Buscar duplicados".
- `src/doc_organize/web/templates/duplicates_resolver.html.j2`: la pantalla "Duplicados" muestra ahora
  la duración de la última ejecución de "Buscar duplicados" (banner) y de cada ejecución del histórico,
  reutilizando el filtro Jinja `format_duration` ya existente.
- `src/doc_organize/core/models.py`: nuevo `ScanEventType.FILE_STARTED`, emitido por
  `ScanCommand._convert_documents()` justo antes de convertir cada documento, con
  `{"path", "index", "total"}` (`total` = ficheros a convertir en esta ejecución).
- `src/doc_organize/scan/scan_command.py`: el payload del evento `SCANNED` gana `to_process` (total
  real de ficheros que se van a convertir, distinto de `scanned`/`new + modified`: también incluye
  reintentos de ficheros en `ERROR` sin cambios).
- `src/doc_organize/web/templates/folder_selector.html.j2`: la pantalla "Escanear" muestra ahora una
  barra de progreso en vivo con "Procesando X/Y: nombre_de_fichero" mientras el escaneo corre, y un
  mensaje final ("Completado: N fichero(s) procesado(s)." o "Sin ficheros nuevos que convertir."); el
  registro JSON detallado de eventos pasa a un `<details>` colapsado ("Resultado del escaneo") en vez
  de ser el elemento principal de la pantalla.

## [0.5.0] - 2026-09-03

### Added

- `src/doc_organize/utils/date_format.py`: nuevo módulo `format_datetime(value, pattern=None, tz_name=None)` /
  `format_duration(seconds)`, registrados como filtros Jinja (`web/templating.py`) — centraliza cómo se
  muestran al usuario los timestamps ISO 8601 UTC que genera el resto del proyecto. Parametrizable vía las
  variables de entorno `DOC_ORGANIZE_DATE_FORMAT` / `DOC_ORGANIZE_TIMEZONE` (mismo patrón que
  `utils/logging.py`); por defecto, formato español (`dd/mm/aaaa HH:MM:SS`) y zona horaria de España
  (`Europe/Madrid`, con cambio automático de horario de verano/invierno).
- `src/doc_organize/core/models.py`: nuevo modelo `ScanRunReport` (`scan_run_id`, `started_at`,
  `finished_at`, `duration_seconds`, `total_scanned`, `completed`) — histórico de duración de ejecuciones
  de escaneo.
- `src/doc_organize/scan/scan_history_store.py`: nuevo store JSONL append-only
  (`append_scan_run(history_path, report)` / `list_scan_runs(history_path)`), exportado desde
  `doc_organize.scan`. Mismo patrón que `SCAN_ERRORS_HISTORY.jsonl`/`DEDUP_HISTORY.jsonl`, pero registra
  **toda** ejecución (completada o no), no solo las que producen error.
- `src/doc_organize/core/constants.py`: `SCAN_HISTORY_FOLDER_NAME` (`historial_escaneo`),
  `SCAN_HISTORY_JSONL_NAME` (`SCAN_HISTORY.jsonl`).
- `src/doc_organize/scan/scan_command.py`: `ScanCommand.run()`/`run_streaming()` aceptan un nuevo
  parámetro opcional `history_log_path: Path | None = None`; `ScanSummary` incluye `duration_seconds`
  (también en el resumen impreso por el CLI, línea "Tiempo de ejecución: …"). Cada ejecución —completada
  o interrumpida por una excepción— se registra en el histórico con `completed=True`/`False`.
- `src/doc_organize/web/routes/scan.py` / `web/templates/folder_selector.html.j2`: la pantalla "Escanear"
  muestra ahora la duración de la última ejecución, y una nueva pestaña "Historial de ejecuciones" lista
  cada ejecución registrada (inicio, fin, duración, documentos escaneados, si terminó o se interrumpió).
- `pyproject.toml`: nueva dependencia `tzdata` (requerida por `zoneinfo` para resolver zonas horarias
  IANA como `Europe/Madrid` en Windows).
- `scripts/build_docs_zip.py`: nuevo script para empaquetar la documentación compilada como ZIP
  con checksums SHA256 para distribución offline. Genera:
  - `dist/doc_organize-docs-{version}.zip` (sitio MkDocs completo comprimido)
  - `dist/doc_organize-docs-{version}.zip.sha256` (checksum individual)
  - `dist/CHECKSUMS.txt` (histórico de todas las builds)
- `.github/workflows/docs-zip-release.yml`: nueva automatización que en cada push a `main`/`develop`
  que afecte `docs/`, `mkdocs.yml` o `pyproject.toml`:
  1. Construye documentación con `mkdocs build --strict`
  2. Genera ZIP con `scripts/build_docs_zip.py`
  3. Crea GitHub Release con tag `docs-v{version}` y adjunta ZIP + checksums
  4. Publica en [Releases](https://github.com/fmanza/doc_organize/releases)

**Features (documentación offline):**
- ✅ Descarga offline de documentación completa con búsqueda
- ✅ Verificación de integridad por SHA256 (portable, compatible con `sha256sum -c`)
- ✅ Histórico de builds en `CHECKSUMS.txt` para auditoría
- ✅ GitHub Artifacts (retención 30 días) para CI/CD
- ✅ Error handling + validaciones (cross-platform, Python 3.11+)

**Uso:**
```bash
# Manual (local)
python scripts/build_docs_zip.py
python scripts/build_docs_zip.py --no-build  # rezip site/ existente

# Automático (CI/CD)
# En cada push que toque docs/ → GitHub Release automático
```

### Changed

- `web/templates/dashboard.html.j2`, `project_selector.html.j2`, `duplicates_resolver.html.j2`,
  `scan_errors.html.j2`: los timestamps ISO 8601 UTC que antes se mostraban crudos ahora pasan por el
  filtro `format_datetime` (formato español/España por defecto, configurable — ver `date_format.py`
  arriba).

### Fixed

- `format_datetime()` degrada a mostrar el valor original (en vez de lanzar una excepción y tumbar la
  página) ante un timestamp no parseable o una zona horaria mal configurada — mismo criterio de
  tolerancia a datos corruptos que ya aplican `load_error_history`/`_load_dedup_history`.
- La persistencia del histórico de duración de ejecuciones se realiza ahora **antes** de emitir el evento
  `COMPLETED` (no después, en un `finally`): evita una carrera intermitente con la desconexión del cliente
  WebSocket, que cierra la conexión en cuanto recibe ese evento.
- Un fallo de E/S al escribir el histórico de tiempos de escaneo o el histórico de errores de escaneo
  (permiso denegado, disco lleno…) ya no aborta un escaneo que por lo demás terminó con éxito — ambas
  escrituras son ahora best-effort (se loguea un warning en vez de propagar la excepción).

---

## [0.4.0] - 2026-08-31

⚠️ **Rompe contratos públicos** (ver "Removed"/"Changed"): firma de `ScanCommand`, flags del CLI
`scan`, payload del WebSocket de escaneo y el enum `ScanEventType`. Sin release publicado de
`doc_organize` hasta la fecha — no se ofrece guía de migración formal, solo el detalle de cada
cambio abajo.

### Added

- `src/doc_organize/scan/scan_command.py`: nuevo método `ScanCommand.deduplicate(paths,
  duplicates_dir, folders_json) -> DeduplicationSummary` — busca y mueve duplicados de forma
  independiente al escaneo, a petición explícita del usuario. Nuevo dataclass
  `DeduplicationSummary` (`groups_found`, `moved`, `warnings`), exportado desde `doc_organize.scan`.
- `src/doc_organize/main.py`: nuevo subcomando CLI `deduplicate --paths ... [--project ...]
  [--duplicates-dir ...]`, con su propia resolución de rutas (`_resolve_dedup_paths`) — no exige
  `--output-dir`/`--cache-file` como `scan`, porque no convierte ni cachea nada.
- `src/doc_organize/web/routes/scan.py`: nuevo `POST /api/projects/{name}/scan/deduplicate` —
  equivalente web del subcomando CLI, sobre todas las carpetas guardadas del proyecto.
- `src/doc_organize/dedup/deduplication.py`: `DeduplicationManager.resolve_duplicates()` añade
  además una línea a `duplicados/DEDUP_HISTORY.jsonl` (JSON Lines, append-only) por cada ejecución
  — histórico incremental y consultable, a diferencia de `DEDUP_REPORT.json` (que solo refleja la
  última). Se registra toda ejecución, incluso sin duplicados encontrados.
- `src/doc_organize/web/templates/folder_selector.html.j2`: botón "Buscar duplicados" (menú
  Escaneo) — "Escanear" nace deshabilitado y solo se habilita tras una ejecución exitosa de
  "Buscar duplicados" en la misma visita a la página (gate de cliente, sin persistencia entre
  visitas; no sustituye ningún control de seguridad existente).
- `src/doc_organize/web/routes/duplicates.py` / `duplicates_resolver.html.j2`: sección "Histórico
  de deduplicaciones" — lista todas las ejecuciones registradas en `DEDUP_HISTORY.jsonl`, cada una
  con su propio detalle de archivos (conservado/movido), en un bloque colapsable
  (`<details>`/`<summary>` nativo, sin JavaScript de terceros). El buscador y el contador de la
  página cubren los grupos de todas las ejecuciones, no solo la más reciente.
- `src/doc_organize/core/constants.py`: `SCAN_FOLDERS_JSON_NAME` — nombre centralizado del fichero
  `folders.json`, usado por `main.py`, `web/routes/scan.py` y `web/routes/duplicates.py`.

### Changed

- `src/doc_organize/web/routes/scan.py`: el WebSocket `/api/projects/{name}/scan` ya no acepta
  `paths` del cliente — resuelve siempre todas las carpetas guardadas del proyecto
  (`ScannedFoldersStore`) del lado servidor. `mark_used()` ahora marca solo las rutas ya validadas
  por `FolderValidator`, no las carpetas guardadas sin validar (evita marcar como usada — y por
  tanto no eliminable — una carpeta que ya no existe en disco).
- `src/doc_organize/web/routes/duplicates.py`: la sección "Duplicados ya resueltos" desaparece
  como bloque independiente — su contenido pasa a ser, simplemente, el detalle de la ejecución más
  reciente dentro de "Histórico de deduplicaciones". "Última deduplicación" se deriva ahora de
  `DEDUP_HISTORY.jsonl` (primera entrada) en vez de leer `DEDUP_REPORT.json` aparte — elimina una
  posible inconsistencia entre ambas lecturas si un fallo interrumpe la escritura entre los dos
  ficheros. `DEDUP_REPORT.json` se sigue escribiendo en disco sin cambios (contrato externo).
- `src/doc_organize/web/templates/duplicates_resolver.html.j2`: al resolver un conflicto desde el
  formulario interactivo, la página se refresca (antes solo mostraba un texto de resultado sin
  actualizar el estado de pendientes/histórico).
- Lecturas de fichero en `web/routes/duplicates.py` (histórico, último reporte, re-escaneo de
  duplicados pendientes) pasan a ejecutarse en un hilo aparte (`asyncio.to_thread`) para no
  bloquear el bucle de eventos — relevante porque `DEDUP_HISTORY.jsonl` crece sin límite durante la
  vida del proyecto.

### Removed

- `src/doc_organize/scan/scan_command.py`: `ScanCommand.run()`/`run_streaming()` pierden los
  parámetros `deduplicate: bool` y `duplicates_dir: Path` — la deduplicación ya no forma parte del
  pipeline de escaneo (ver `deduplicate()` en "Added").
- `src/doc_organize/main.py`: `scan` pierde los flags `--deduplicate` y `--duplicates-dir`.
- `src/doc_organize/core/models.py`: `ScanEventType.DEDUPLICATED` eliminado del enum — el escaneo
  ya no emite ningún evento de deduplicación (`deduplicate()` no emite `ScanEvent`, devuelve un
  `DeduplicationSummary` de una sola vez).

## [0.3.0] - 2026-08-31

### Added

- `src/doc_organize/web/routes/duplicates.py` /
  `src/doc_organize/web/templates/duplicates_resolver.html.j2`: la página
  "Revisar Duplicados" ahora incluye un buscador de filtrado instantáneo en
  cliente (por nombre de archivo o carpeta, sin round-trip al servidor), muestra
  la carpeta contenedora y el tamaño legible (`1.5 MB`) de cada documento en una
  tabla en vez de una lista de radios en texto plano, añade una sección de
  solo lectura "Duplicados ya resueltos" con el detalle de los grupos que un
  escaneo previo con "Deduplicar" activado ya movió automáticamente (lee
  `duplicados/DEDUP_REPORT.json`), y un contador que se actualiza a
  "X de Y grupo(s)." mientras el filtro está activo (suma pendientes + ya
  resueltos). Sin cambios en los modelos Pydantic ni en las rutas JSON
  existentes (`GET`/`POST /api/projects/{name}/duplicates...`).
- `src/doc_organize/web/routes/cache.py` /
  `src/doc_organize/web/templates/cache_viewer.html.j2`: misma mejora de
  visualización aplicada a la página "Caché" — buscador de filtrado instantáneo
  en cliente (por nombre de archivo o carpeta) y columnas Archivo/Carpeta
  separadas en vez de la ruta completa en una sola celda; el contador de
  entradas se actualiza a "X de Y entradas." mientras el filtro está activo. Sin
  cambios en `CacheEntryResponse`/`CacheListResponse` ni en las rutas JSON.

### Fixed

- `src/doc_organize/web/routes/duplicates.py`: la página "Revisar Duplicados"
  ya no muestra el mensaje ambiguo "No se detectaron duplicados" cuando un
  escaneo previo con "Deduplicar" activado ya había resuelto y movido los
  duplicados fuera de las carpetas escaneadas — un re-escaneo en vivo no podía
  encontrarlos y el mensaje contradecía lo que el propio escaneo acababa de
  informar. Ahora se explica el porqué y se lista su detalle (ver Added).
- `src/doc_organize/web/routes/duplicates.py`: un `duplicados/DEDUP_REPORT.json`
  truncado o corrupto (p. ej. por un proceso interrumpido a mitad de escritura)
  ya no produce un error 500 permanente en la página — se ignora y se degrada
  al mismo comportamiento que si el fichero no existiera.

## [0.2.0] - 2026-08-29

### Added

- `Role.allowed_scan_roots` (revisión de seguridad, revisión 9 roles y gestión de
  usuarios): un rol no-admin ahora solo puede escanear las raíces del sistema de
  archivos que un admin le haya asignado explícitamente vía `/api/roles` o
  `/admin/users`. Sin raíces configuradas, no puede escanear ninguna carpeta
  externa. Los roles `is_admin` no se ven afectados (siguen sin restricción).
  - `src/doc_organize/core/models.py`: campo `Role.allowed_scan_roots`.
  - `src/doc_organize/auth/auth_store.py`: tabla `role_scan_roots`,
    `AuthStore.create_role()`/`update_role()`/`get_role()`/`list_roles()`.
  - `src/doc_organize/web/routes/admin.py`: `CreateRoleRequest`/`UpdateRoleRequest`/
    `RoleResponse` incluyen `allowed_scan_roots`.
  - `src/doc_organize/web/templates/admin_users.html`: formulario de raíces de
    escaneo permitidas.
- `LoginRateLimiter` (`src/doc_organize/web/auth.py`): bloquea `POST /login`
  durante 60s tras 5 fallos consecutivos para el mismo (tenant_id, username) —
  mitiga la fuerza bruta sobre el usuario `admin`/`admin` de bootstrap.
  Constantes `LOGIN_MAX_ATTEMPTS`/`LOGIN_LOCKOUT_SECONDS` en
  `src/doc_organize/core/constants.py`.

### Fixed

- `src/doc_organize/web/routes/scan.py`: el WebSocket
  `/api/projects/{name}/scan` rechaza (`close 1008`) cualquier ruta fuera de las
  `allowed_scan_roots` del rol de la sesión — antes, un rol restringido a
  `project_names` concretos podía igualmente escanear cualquier ruta legible por
  el proceso servidor (incluyendo proyectos de otros tenants), evadiendo por
  completo esa restricción.
- `src/doc_organize/web/routes/auth.py`: la cookie de sesión
  (`doc_organize_session`) se marca `Secure` cuando la petición de `/login` llega
  por HTTPS — antes nunca se marcaba, permitiendo que viajara en claro sobre HTTP
  en un despliegue no-loopback sin TLS en el propio proceso.

## [0.1.0] - Fase 1

Base inicial: CLI + interfaz web multi-tenant (scan, dedup, caché, auth por
sesión), sin este archivo de changelog (añadido en 0.2.0).
