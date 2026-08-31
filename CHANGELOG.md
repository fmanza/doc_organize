# Changelog

Formato basado en [Keep a Changelog](https://keepachangelog.com/es/1.0.0/).
Este proyecto sigue [SemVer](https://semver.org/lang/es/) desde v0.2.0 (sin
releases publicados antes de esa versión).

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
