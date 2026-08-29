# Changelog

Formato basado en [Keep a Changelog](https://keepachangelog.com/es/1.0.0/).
Este proyecto sigue [SemVer](https://semver.org/lang/es/) desde v0.2.0 (sin
releases publicados antes de esa versión).

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
