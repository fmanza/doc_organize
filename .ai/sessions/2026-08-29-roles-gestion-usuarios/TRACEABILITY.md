# TRACEABILITY: Resumen de Sesión

## Sesión
- **Fecha**: 2026-08-29
- **Tipo**: `feature` (`/new-feature`: PLAN → AUDIT_PLAN → IMPLEMENT → AUDIT_CODE → VERSION),
  seguido de un segundo ciclo PLAN → AUDIT_PLAN → IMPLEMENT para endurecer los hallazgos de
  AUDIT_CODE que quedaron documentados sin corregir
- **Rama**: `develop`
- **Estado**: ✅ COMPLETADA (commit `4231eb0` creado, con confirmación explícita del usuario)

## Objetivo
Añadir roles (flag `is_admin` + lista de proyectos permitidos) y gestión de usuarios a
`doc_organize`, con un usuario `admin`/`admin` creado automáticamente por tenant. Cierra el
pendiente "Roles/permisos dentro de un tenant" que `.ai/CURRENT_STATE.md` listaba como
simplificación deliberada desde la revisión 8.

## Cambios Ejecutados

### ✅ 1. PLAN + AUDIT_PLAN (ciclo `/new-feature`)
Tres alternativas de diseño evaluadas: `Role` como entidad reutilizable por tenant (elegida) vs.
flags sueltos en `User` vs. RBAC granular por acción (descartada, sobre-ingeniería). Veredicto
inicial **GO_CONDICIONAL** (4 condiciones: `must_change_password` desde el diseño, dependency única
`require_project_access`, test de backfill, bootstrap transaccional). El usuario pidió incorporar
las condiciones directamente al PLAN en vez de dejarlas como condiciones → veredicto revisado a
**GO**.

### ✅ 2. IMPLEMENT — roles, usuarios, bootstrap admin/admin
**Archivo(s)**: `core/models.py` (`Role` nuevo; `User.role_id`/`must_change_password`),
`core/exceptions.py` (`RoleAlreadyExistsError`, `RoleNotFoundError`, `RoleInUseError`,
`UserNotFoundError`), `core/constants.py` (`DEFAULT_ADMIN_*`, `ROLE_NAME_*`),
`auth/auth_store.py` (tablas `roles`/`role_projects`, migración idempotente con backfill,
`create_tenant()` transaccional, CRUD de roles/usuarios, `can_access_project()`,
`get_session_with_access()`, `change_password()`), `web/auth.py` (`AuthMiddleware` resuelve rol +
bloqueo por `must_change_password`), `web/dependencies.py` (`require_admin`,
`require_project_access`), `web/routes/admin.py` (nuevo, `/api/roles` + `/api/users` +
`/admin/users`), `web/routes/change_password.py` (nuevo), `web/routes/{projects,scan,cache,
downloads,duplicates}.py` (dependencia de acceso aplicada por firma), `web/app.py` (registro de
routers + filtrado de `/`), `web/templates/{admin_users.html,change_password.html,base.html}`,
`docs/api/index.md`, `.ai/architecture.md`, `.ai/CURRENT_STATE.md`, `.ai/DECISIONS_LOG.md`.

**Descripción**: `create_tenant()` crea, en una única transacción, tenant + rol `admin` + usuario
`admin`/`admin` con `must_change_password=True`. Un rol no-admin solo ve los proyectos de su
`project_names`; `require_project_access` (declarada por firma, no imperativa dentro del handler)
es la única puerta de esa comprobación en las rutas `{name}`-scoped, más el handler WebSocket de
escaneo (autenticado a mano, no soporta `Depends`). Migración idempotente en `__aenter__` retro-
asigna al rol admin cualquier usuario preexistente sin rol — nunca reduce accesos.

**Status**: ✅ 226 tests pasando (44 nuevos), `ruff`/`mypy`/`mkdocs build --strict` limpios.

### ✅ 3. AUDIT_CODE — 2 hallazgos corregidos, 5 documentados sin tocar código
- **Corregido (seguridad)**: `POST /api/users` con `role_id` opcional creaba un admin silencioso si
  se omitía (el default de `AuthStore.create_user()`, pensado para compatibilidad interna, se colaba
  hasta la API pública) — `CreateUserRequest.role_id` pasó a obligatorio.
- **Corregido (tipado)**: `_role_response`/`_user_response` en `admin.py` llevaban
  `# type: ignore[no-untyped-def]` innecesario (`disallow_untyped_defs = false` en `pyproject.toml`,
  ese error nunca se dispara) — tipados como `Role`/`User`, ignore eliminado.
- **Documentados, sin fix en esta fase** (ver punto 4, donde 4 de los 5 sí se corrigieron):
  entrada muerta `"/logout"` en `_PASSWORD_CHANGE_EXEMPT`; `update_role` dejaba `project_names=[]`
  en silencio al degradar `is_admin`; condición de carrera TOCTOU en
  `create_tenant`/`create_role`/`create_user` (patrón heredado de la revisión 8, extendido a
  `roles`); sobrecarga de abrir una `AuthStore` por petición en `require_project_access`; textarea
  de proyectos separados por coma no representa nombres de proyecto que contengan una coma.

### ✅ 4. Segundo ciclo PLAN + AUDIT_PLAN + IMPLEMENT — hardening de 4 de los 5 hallazgos
**Archivo(s)**: `auth/auth_store.py` (captura de `aiosqlite.IntegrityError` en los 3 `INSERT` con
riesgo de duplicado, mapeada a la excepción de dominio; extracción de `_role_name_taken`/
`_username_taken` para poder forzar la ventana de carrera de forma determinista en tests; nueva
regla en `update_role` — degradar `is_admin` sin `project_names` explícito lanza `AuthError`),
`web/auth.py` (quitado `"/logout"` de `_PASSWORD_CHANGE_EXEMPT`, ya cubierto por `_EXEMPT_PATHS`),
`web/routes/admin.py` (`admin_users_page` pasa la lista real de proyectos al template),
`web/templates/admin_users.html` (checkboxes de proyectos reales en vez de texto libre separado por
coma, deshabilitados si se marca "Admin"), `tests/unit/test_auth_store.py` (+7 tests: 3 de carrera
vía `monkeypatch` del pre-check, 4 de la nueva regla de `update_role`), `.ai/DECISIONS_LOG.md`.

**Decisión explícita de alcance**: la sobrecarga de conexión SQLite por petición (hallazgo #6) se
difiere — sin evidencia de que sea un problema real a la escala de este proyecto.

**Status**: ✅ 233 tests pasando, `ruff`/`mypy`/`mkdocs build --strict` limpios.

### ✅ 5. VERSION + commit
Mensaje de commit preparado (changelog por módulo, impacto en API pública, rollback, pruebas
sugeridas) y confirmado explícitamente por el usuario antes de ejecutar `git commit`.

---

## Impacto

### Código
- **Archivos modificados/creados**: ver puntos 2 y 4 arriba (26 archivos en el commit final).
- **Cambios funcionales**: sí — nuevo modelo de permisos por rol, nuevo flujo de login obligatorio
  (`must_change_password`), nuevas rutas `/admin/users`, `/api/roles`, `/api/users`,
  `/change-password`.

### Compatibilidad
- **BREAKING (interno)**: `AuthStore.update_role()` con `is_admin=False` exige `project_names`
  explícito cuando el rol era admin (antes vaciaba la lista en silencio). `CreateUserRequest.role_id`
  obligatorio en la API HTTP (endpoint nuevo en esta misma sesión, sin consumidores previos que
  pudieran rompérse).
- **NO BREAKING**: `AuthStore.create_user()` mantiene `role_id`/`must_change_password` opcionales
  (default: rol admin del tenant, `False`) — ningún llamador existente se rompe. La migración de
  `auth.db` preexistentes es puramente aditiva (nuevas columnas/tablas) y retro-asigna siempre al
  rol admin, nunca reduce accesos.

---

## Verificación
```
python -m ruff check src tests    → All checks passed
python -m mypy src                 → Success: no issues found in 42 source files
python -m pytest                    → 233 passed, 95% cobertura
mkdocs build --strict                → exit 0, sin links rotos
```

---

## Riesgos Residuales

| Riesgo | Mitigación | Status |
|--------|-----------|--------|
| Sobrecarga de una conexión SQLite nueva por petición para `require_project_access` en roles no-admin | Mismo patrón "una conexión por petición" ya usado en el resto de la app; sub-milisegundo en SQLite local | Diferido deliberadamente, no bloqueante |
| Tokens de API personales por usuario (acceso programático sin sesión de navegador) — pendiente ya anotado en `CURRENT_STATE.md` antes de esta sesión | Fuera de alcance de esta sesión | Pendiente, sin cambios |
| `.ai/CURRENT_STATE.md` seguía listando "Rate-limiting en `/login`" como pendiente al cerrar esta sesión | Ver nota de continuidad más abajo — una sesión posterior el mismo día ya lo abordó, sobre el mismo working tree | Ver `.ai/sessions/2026-08-29/TRACEABILITY.md` |

---

## Siguientes Pasos (Recomendado)
1. `git push` de `develop` si se quiere compartir el commit `4231eb0` (no ejecutado en esta sesión —
   el usuario no lo pidió).
2. Cerrar el pendiente "Tokens de API personales por usuario" de `.ai/CURRENT_STATE.md` cuando haya
   prioridad, en una sesión `/new-feature` aparte.
3. **Nota de continuidad**: existe `.ai/sessions/2026-08-29/TRACEABILITY.md` — una sesión distinta,
   el mismo día, que partió de este commit (`4231eb0`) para hacer `/security-review` sobre la capa
   de roles/auth y cerrar sus hallazgos (`Role.allowed_scan_roots`, rate-limiting de `/login`, cookie
   `Secure`, versión 0.2.0). Al retomar trabajo en esta área, leer ambos ficheros de traceabilidad,
   no solo este.

---

## Directrices para Futuras IAs

- **[bootstrap de tenant]**: `AuthStore.create_tenant()` es transaccional (tenant + rol admin +
  usuario `admin`/`admin` en un único `commit`/`rollback`) — no reimplementar esto llamando a
  `create_role()`/`create_user()` sueltos dentro, porque cada uno hace su propio `commit()`
  prematuro y rompería la atomicidad. Usa los helpers privados `_insert_role_row`/`_insert_user_row`
  (sin `commit()` propio), como ya está hecho.
- **[semántica de `project_names` vacía]**: `is_admin=True` siempre implica `project_names=[]`
  (`create_role`/`update_role` lo validan) — un rol admin nunca tiene lista explícita, ve todo el
  tenant. `project_names=[]` en un rol **no-admin** significa "no ve ningún proyecto", no "sin
  restricción" — no confundir los dos significados.
- **[degradar `is_admin`]**: `update_role(is_admin=False)` sobre un rol que era admin exige
  `project_names` explícito (puede ser `[]`) desde esta sesión — omitirlo lanza `AuthError` en vez
  de vaciar la lista en silencio (era el comportamiento hasta el punto 4 de esta sesión).
- **[carrera de duplicados]**: `create_tenant`/`create_role`/`create_user` capturan
  `aiosqlite.IntegrityError` en el `INSERT` como última defensa, no solo el `SELECT` previo
  (`tenant_exists`/`_role_name_taken`/`_username_taken`) — cualquier `create_*` nuevo en `AuthStore`
  que añada una restricción `UNIQUE` debe seguir el mismo patrón, y los tests de esa ventana de
  carrera se fuerzan con `monkeypatch` sobre esos tres métodos (deterministas, sin depender de
  timing real).
- **[`require_project_access`]**: dependency única en `web/dependencies.py`, declarada por firma
  (`dependencies=[Depends(require_project_access)]`) en cada ruta `{name}`-scoped — nunca
  reimplementar el chequeo dentro del handler. El WebSocket de `web/routes/scan.py` es la única
  excepción real (no soporta `Depends`) y replica la llamada a `AuthStore.can_access_project()` a
  mano; cualquier endpoint WebSocket nuevo debe hacer lo mismo.
- **[sesión concurrente detectada]**: esta sesión **no** incluye `Role.allowed_scan_roots` ni
  rate-limiting de `/login` — esos cambios (y la subida a v0.2.0) llegaron en una sesión distinta,
  el mismo día, sobre el mismo working tree, después del commit `4231eb0`. Ver
  `.ai/sessions/2026-08-29/TRACEABILITY.md` antes de asumir que `auth_store.py`/`admin.py`/
  `scan.py` siguen exactamente como los dejó esta sesión.

---

## Veredicto

### 🟢 COMPLETADA

**Criterios**:
- ✅ PLAN/AUDIT_PLAN con veredicto GO antes de escribir código, en ambos ciclos
- ✅ IMPLEMENT completo, con tests para cada pieza (transaccionalidad del bootstrap, filtrado por
  rol, gate de cambio de contraseña, carrera de duplicados, degradación de `is_admin`)
- ✅ AUDIT_CODE con hallazgos verificados en el código real (no solo en memoria), 2 corregidos de
  inmediato y los 5 restantes documentados con severidad y decisión explícita
- ✅ `ruff check`, `mypy src`, `pytest` (233 passed), `mkdocs build --strict` — todos en verde antes
  del commit
- ✅ Commit creado solo tras confirmación explícita del usuario, excluyendo un archivo modificado
  ajeno a la sesión (`doc_organize.code-workspace`)

**Evidencia**:
- Branch: `develop`
- Commits: `4231eb0` — "feat: roles y gestión de usuarios con admin por defecto" (26 archivos,
  +2185/-78)
- Tests: 233 passed, 95% cobertura, 51 tests nuevos/modificados en `tests/unit/test_auth_store.py` +
  3 ficheros de test nuevos (`test_change_password.py`, `test_web_admin_routes.py`,
  `test_web_project_access.py`)

**Sesión cerrada**: 2026-08-29
