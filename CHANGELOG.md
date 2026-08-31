# Changelog

Formato basado en [Keep a Changelog](https://keepachangelog.com/es/1.0.0/).
Este proyecto sigue [SemVer](https://semver.org/lang/es/) desde v0.2.0 (sin
releases publicados antes de esa versión).

## [0.3.0] - 2026-08-31

### Added

- `src/doc_organize/web/routes/duplicates.py` /
  `src/doc_organize/web/templates/duplicates_resolver.html.j2`: la página
  "Revisar Duplicados" ahora incluye un buscador de filtrado instantáneo en
  cliente (por nombre de archivo o carpeta, sin round-trip al servidor), muestra
  la carpeta contenedora y el tamaño legible (`1.5 MB`) de cada documento en una
  tabla en vez de una lista de radios en texto plano, y añade una sección de
  solo lectura "Duplicados ya resueltos" con el detalle de los grupos que un
  escaneo previo con "Deduplicar" activado ya movió automáticamente (lee
  `duplicados/DEDUP_REPORT.json`). Sin cambios en los modelos Pydantic ni en las
  rutas JSON existentes (`GET`/`POST /api/projects/{name}/duplicates...`).

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
