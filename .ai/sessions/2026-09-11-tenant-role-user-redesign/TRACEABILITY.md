# TRACEABILITY: Resumen de Sesión

## Sesión
- **Fecha**: 2026-09-11
- **Tipo**: `feature` (`/new-feature`)
- **Rama**: `develop`
- **Estado**: ✅ COMPLETADA

## Objetivo
Petición del usuario (ver [`00_PLAN.md`](00_PLAN.md) y
[`.github/prompts/tenant_role_user_redesign.prompt.md`](../../../.github/prompts/tenant_role_user_redesign.prompt.md)):
sustituir el aprovisionamiento manual (`tenant create`/`user create`) por un tenant
`"default"` + usuario `admin` de fábrica creados automáticamente; desacoplar `Role`
de `Tenant` (solo vinculado a usuarios); retirar `Role.allowed_scan_roots` en favor
de un acceso de escaneo implícito por proyecto; y añadir `is_instance_admin` como
nivel separado del `is_admin` de un rol, con una pantalla cruzada nueva ("Tenants y
usuarios") para gestionar cualquier tenant. El prompt ya traía resueltas 3 decisiones
de seguridad (Crítico) y dejaba 1 Alto + 3 Medio pendientes de cerrar en AUDIT_PLAN
— las 4 se cerraron dentro de esta misma sesión (ver `00_PLAN.md`).

## Cambios Ejecutados

### ✅ 1. Bootstrap de fábrica del tenant por defecto
**Archivo(s)**: `src/doc_organize/auth/auth_store.py`, `core/constants.py`
(`DEFAULT_TENANT_ID`).
**Descripción**: `AuthStore.__aenter__()` llama a
`_ensure_default_tenant_bootstrap()` tras la migración de esquema: si
`DEFAULT_TENANT_ID` no existe, crea tenant + rol global `admin` + usuario
`admin`/`DEFAULT_ADMIN_PASSWORD` (`must_change_password=True`,
`is_instance_admin=True`) en una transacción, idéntico en CLI y web.
`create_tenant()` (tenants adicionales) ya NO aprovisiona rol/usuario.
**Status**: ✅ `test_opening_auth_store_bootstraps_default_tenant_admin_user`,
`test_bootstrap_is_idempotent_across_reopens`,
`test_create_tenant_no_longer_bootstraps_role_or_user`
(`tests/unit/test_auth_store.py`).

### ✅ 2. Bloqueo de login de la cuenta de fábrica en modo no-loopback
**Archivo(s)**: `src/doc_organize/web/routes/auth.py`
(`is_factory_admin_account`, en `auth/auth_store.py`).
**Descripción**: `POST /login` rechaza (403, sin crear sesión) el login exacto
`tenant="default"`+`username="admin"` mientras conserve la contraseña de fábrica y
el servidor esté en modo no-loopback — el fallo NO cuenta para `LoginRateLimiter`
(la contraseña era correcta). Ningún otro usuario con `must_change_password=True`
se ve afectado.
**Status**: ✅ 4 tests nuevos en `tests/unit/test_web_auth.py`
(`test_factory_admin_login_rejected_in_non_loopback_mode`,
`..._does_not_count_against_rate_limiter`, `..._succeeds_in_loopback_mode`,
`test_other_user_with_pending_password_change_is_not_locked_out`).

### ✅ 3. `Role` global (retirada de `tenant_id` y `allowed_scan_roots`)
**Archivo(s)**: `core/models.py`, `auth/auth_store.py` (migración de esquema),
`web/routes/admin.py`, `web/dependencies.py`, `web/routes/scan.py`,
`web/routes/filesystem.py`, `web/templates/admin_roles.html.j2`.
**Descripción**: `Role.name` único globalmente; `create_role/get_role/update_role/
delete_role/list_roles/can_access_project` pierden `tenant_id`. El acceso de
escaneo de un rol no-admin pasa a ser implícito: la única raíz permitida es
`project.root_path` de cada proyecto en `project_names` — `get_allowed_scan_roots()`
ya no consulta `AuthStore` (deja de ser async). `GET /api/fs/browse` gana
`?project=` para poder acotarse a un proyecto concreto. Migración: `roles` se
reconstruye sin `tenant_id` (procedimiento oficial de SQLite,
`foreign_keys=OFF`/tabla nueva/drop/rename/`foreign_keys=ON`), desambiguando por
nombre si dos tenants tenían un rol homónimo.
**Status**: ✅ suite reescrita en `test_auth_store.py`,
`test_web_admin_routes.py`, `test_web_scan.py`, `test_web_filesystem.py`,
`test_web_project_access.py`, `test_web_projects_routes.py`,
`test_change_password.py`; migración cubierta por
`test_migration_deduplicates_role_names_across_former_tenants`.

### ✅ 4. `is_instance_admin` + pantalla "Tenants y usuarios"
**Archivo(s)**: `core/models.py` (`User.is_instance_admin`/`is_blocked`),
`auth/auth_store.py` (`set_instance_admin`, `set_user_blocked`, `delete_tenant`,
`list_tenants`, `users_for_role`), `web/dependencies.py`
(`require_instance_admin`, `require_admin_or_instance_admin`), **nuevo**
`web/routes/tenants.py` + `admin_tenants.html.j2`, `web/routes/ai_settings.py` +
`context.py` (plantillas de taxonomía: `require_admin` → `require_instance_admin`,
son recursos de instancia), `base.html.j2` (nav condicionado a
`is_admin`/`is_instance_admin`), `main.py` (`user set-instance-admin`, escape
hatch de migración — condición 1 de AUDIT_PLAN).
**Descripción**: nivel separado de `Role.is_admin` (que sigue significando "ve
todos los proyectos de mi tenant"): solo `is_instance_admin` ve la pantalla
cruzada, crea/elimina tenants, gestiona usuarios de cualquier tenant, y toca
config de instancia (IA, plantillas). Bloquear (`is_blocked=True`) invalida TODAS
las sesiones del usuario en la misma transacción — no solo impide logins futuros.
`/admin/roles` muestra "usuarios asignados" **filtrado al tenant de quien
consulta** (condición 2 de AUDIT_PLAN: un rol es global y puede estar en uso en
otro tenant a la vez, sin esto un `is_admin` vería usernames ajenos).
**Status**: ✅ `tests/unit/test_web_tenants_routes.py` (nuevo, 10 tests) +
casos de `is_blocked`/`set_instance_admin` en `test_auth_store.py`.

### ✅ 5. Bug encontrado y corregido durante el propio AUDIT_CODE: guardas de "último admin" bloqueaban vaciar un tenant
**Archivo(s)**: `auth/auth_store.py` (`delete_user`, `update_user`,
`set_user_blocked`, nuevo `_count_other_users`).
**Descripción**: las guardas de "no dejar el tenant sin admin" bloqueaban también
eliminar/bloquear/degradar al ÚLTIMO usuario que le quedaba a un tenant —
imposible entonces llegar nunca al estado "cero usuarios" que `delete_tenant`
exige (deadlock). Corregido: las 3 guardas ahora solo bloquean si dejarían a
**otros** usuarios del tenant sin ningún admin; vaciar el tenant del todo
(paso previo a `delete_tenant`) queda permitido.
**Status**: ✅ `test_delete_user_allows_deleting_sole_admin_when_they_are_the_only_user`,
`test_update_user_allows_demoting_sole_admin_when_they_are_the_only_user`,
`test_set_user_blocked_allows_blocking_sole_admin_when_they_are_the_only_user`
(y sus contrapartidas "rejects" con un segundo usuario presente).

### ✅ 6. Otros hallazgos menores de AUDIT_CODE
- `/admin/tenants` mostraba `role_id` (UUID) en bruto en la tabla de usuarios en
  vez del nombre del rol — corregido con `roles_by_id` (mismo patrón que
  `admin_users.html.j2`); test de regresión
  `test_admin_tenants_page_shows_role_name_not_raw_id`.
- `_user_from_row()` tenía un tipo mal declarado (`tuple[object, ...]` en vez de
  `sqlite3.Row`) — detectado por `mypy`, corregido.
- `ruff format src tests` sin acotar tocó 3 ficheros fuera de alcance
  (`ocr_scheduler.py`, `scan_command.py`, `duplicates.py`) — revertidos antes de
  cerrar, para no ensuciar el diff con reformateos ajenos a esta feature.

---

## Impacto

### Código
- **Archivos modificados**: 34 (ver commit).
- **Archivos creados**: `web/routes/tenants.py`, `web/templates/admin_tenants.html.j2`,
  `tests/unit/test_web_tenants_routes.py`, `docs/functional/access.md` y `admin.md`
  (ya existían sin trackear al empezar la sesión — reescritos como parte de esta
  entrega, no creados desde cero), este `TRACEABILITY.md` y `00_PLAN.md`.
- **Cambios funcionales**: sí, extensos — ver `00_PLAN.md`. Resumen de impacto en
  API pública: `AuthStore.create_role/get_role/update_role/delete_role/list_roles/
  can_access_project` pierden `tenant_id`; `create_tenant()` ya no aprovisiona
  usuario/rol (deliberado, solo `DEFAULT_TENANT_ID` recibe bootstrap); `Role`
  pierde `allowed_scan_roots`; `User`/`/api/users*` ganan `is_blocked`; nuevos
  endpoints `/api/tenants*`.

### Compatibilidad
- **BREAKING**: la firma de los métodos de `AuthStore` listados arriba cambia
  (pierden `tenant_id`); cualquier caller externo que instanciara `Role(...)` con
  `tenant_id`/`allowed_scan_roots` deja de compilar. `tenant create` (CLI) ya no
  aprovisiona un usuario automático para tenants que no sean `"default"` — cambio
  de comportamiento deliberado, documentado en `docs/functional/access.md` y
  `admin.md`.
- **NO BREAKING**: `/api/roles`/`/api/users` mantienen sus rutas; el payload de
  `POST /api/roles` pierde `allowed_scan_roots` (aditivo→retirado, no hay forma de
  hacerlo sin romper algo que dependiera de él, pero no había clientes externos
  documentados); `User`/`UserResponse` ganan campos con default seguro
  (`is_blocked=False`).
- **Pendiente de este checklist, no ejecutado en esta sesión** (fuera del alcance
  pedido): `CHANGELOG.md`/`COMPATIBILITY.md`/`pyproject.toml` — ver "Siguientes
  Pasos".

---

## Verificación
```
python -m ruff check src tests          → limpio (solo 3 hallazgos preexistentes,
                                           ajenos a esta sesión: __all__ sin ordenar
                                           en models.py, nested-with en context.py,
                                           BLE001 en scan_command.py)
python -m ruff format --check           → 6 archivos tocados por esta sesión, todos
                                           formateados
python -m mypy src                      → limpio (solo 4 errores preexistentes de
                                           stubs ausentes: yaml, pandas)
python -m pytest tests/unit             → 832 passed
python -m mkdocs build --strict         → build limpio, sin warnings ni links rotos
```

---

## Riesgos Residuales

| Riesgo | Mitigación | Status |
|--------|-----------|--------|
| Un rol es global: dos tenants pueden compartir sin querer un rol con el mismo nombre y verse afectados por la edición del otro | `/admin/roles` muestra "usuarios asignados" filtrado al propio tenant (visibilidad, no ACL); documentado como limitación aceptada en `access.md`/`admin.md` | Aceptado (decisión explícita del prompt de entrada, Nivel 3 punto 7) |
| Una instalación multi-tenant migrada desde antes de esta revisión puede quedar con tenants (no `default`) sin ningún `is_instance_admin` | Escape hatch de CLI: `python -m doc_organize user set-instance-admin <username> --tenant <id>` | Aceptado, con vía de recuperación (condición 1 de AUDIT_PLAN) |
| `RoleInUseError` se reutiliza para la guarda global de "último rol admin del sistema" (antes era por tenant) | Mismo patrón ya extendido previamente (la excepción ya cubría "último admin de rol" y "último admin de usuario" con significados distintos según el método); documentado en su docstring (`core/exceptions.py`) | Aceptado, deuda técnica nula — es una reutilización deliberada, no una fuga de abstracción nueva |
| `CHANGELOG.md`/`COMPATIBILITY.md`/`pyproject.toml` no se tocaron en esta sesión pese a que `SHARED_INSTRUCTIONS.md` los marca obligatorios para un `feat:` con API pública nueva | Ninguna todavía — pendiente de una pasada de VERSION-closure explícita | Pendiente, ver "Siguientes Pasos" |

---

## Siguientes Pasos (Recomendado)
1. Sincronizar `CHANGELOG.md` (+ `docs/CHANGELOG.md` si existe copia) y
   `COMPATIBILITY.md`/`.ai/COMPATIBILITY.md` con esta versión, y bump de
   `pyproject.toml` si corresponde — checklist completo en
   `.github/instructions/sync.instructions.md`. No se hizo en esta sesión porque
   el usuario pidió explícitamente solo "guardar la sesión" (PLAN/AUDIT_PLAN +
   cierre), no un `/version-closure` completo.
2. Decidir si se quiere migrar `tenant.md`/`admin.md` con capturas de pantalla de
   la nueva pantalla "Tenants y usuarios" (hoy solo texto/Mermaid).
3. Si aparece un caso real de dos tenants que necesiten roles con el mismo nombre
   pero permisos independientes, revisar si el riesgo residual de "rol global
   compartido" sigue siendo aceptable o si hace falta un mecanismo de "clonar rol
   por tenant".

---

## Directrices para Futuras IAs

- **[Bootstrap de fábrica vive en `AuthStore.__aenter__`, no en `web/app.py`]**:
  `_ensure_default_tenant_bootstrap()` se llama justo después de
  `_migrate_schema()`, así que funciona igual para el CLI (`main.py`) y para la
  web (`create_app()`) sin duplicar lógica — cualquier cambio al bootstrap de
  fábrica debe hacerse ahí, no en la capa web.
- **[`Role` ya no tiene `tenant_id`: `roles.name` es único GLOBALMENTE, no por
  tenant]**: antes de añadir cualquier filtro `tenant_id` a una query sobre
  `roles`, comprobar que no se está reintroduciendo un concepto retirado
  deliberadamente en esta sesión. La pertenencia de un usuario a un tenant sigue
  viviendo en `users.tenant_id`, sin cambios.
- **[Acceso de escaneo implícito = `project.root_path`, no una lista
  configurable]**: `get_allowed_scan_roots(request, project)` en
  `web/dependencies.py` es SÍNCRONA (ya no consulta `AuthStore`) y devuelve
  `[project.root_path]` para un rol restringido con ese proyecto, `[]` sin
  `project` en contexto, `None` para admin/loopback. No reintroducir una tabla
  `role_scan_roots` ni un campo `allowed_scan_roots` sin releer por qué se
  retiró (AUDIT_CODE de la sesión 2026-09-03/04 lo justificó originalmente, esta
  sesión lo sustituyó, no lo eliminó sin más).
- **[Guardas de "último admin del tenant" tienen un carve-out: vaciar el tenant
  del todo está permitido]**: `_count_other_users()` en `auth_store.py` es la
  función que decide si la guarda aplica — solo bloquea si OTROS usuarios del
  tenant quedarían sin ningún admin. Sin este carve-out, un tenant cuyo único
  usuario es su admin no podría vaciarse nunca, y `delete_tenant()` (que exige
  cero usuarios) sería inalcanzable para ese tenant. Este bug se encontró y
  corrigió DENTRO de esta misma sesión (AUDIT_CODE) — si se toca cualquiera de
  `delete_user`/`update_user`/`set_user_blocked`, preservar esta relajación.
  `set_instance_admin()` tiene su PROPIA guarda global (no por tenant,
  `InstanceAdminRequiredError`) — no confundir ambos mecanismos.
- **[`is_instance_admin` (User) es ortogonal a `Role.is_admin`]**: `is_admin` =
  "veo todos los proyectos de MI tenant"; `is_instance_admin` = "gestiono
  cualquier tenant + recursos de instancia (IA, plantillas de taxonomía)". Un
  usuario puede tener cualquier combinación de los dos. Los routers usan 3
  dependencias distintas según lo que exijan: `require_admin` (ya no se usa en
  ningún router tras esta sesión, se conserva por si hiciera falta gatear algo
  que exija ESTRICTAMENTE `is_admin` sin aceptar `is_instance_admin`),
  `require_admin_or_instance_admin` (`admin.py`: roles/usuarios del propio
  tenant), `require_instance_admin` (`tenants.py`, `ai_settings.py`, y los 3
  endpoints de escritura de `context.py` sobre plantillas de taxonomía).
- **[Migración de esquema reconstruye `roles` con el procedimiento oficial de
  SQLite, no `ALTER TABLE DROP COLUMN`]**: `tenant_id` participaba en una FK y en
  un `UNIQUE` compuesto, que SQLite no permite soltar con `DROP COLUMN`. Ver
  `_migrate_roles_schema()` en `auth_store.py` para el patrón completo
  (`foreign_keys=OFF` → tabla `roles_new` → copia con desambiguación de nombres
  duplicados → `DROP`/`RENAME` → `foreign_keys=ON`) si hace falta repetirlo para
  otra tabla en el futuro.

---

## Veredicto

### 🟢 COMPLETADA

**Criterios**:
- ✅ Las 3 decisiones de seguridad del prompt de entrada implementadas
  (bloqueo de login de fábrica, acceso de escaneo implícito, `is_instance_admin`)
- ✅ El hallazgo Alto y los 3 Medio del prompt (Nivel 2/3) cerrados explícitamente
  en `00_PLAN.md` antes de IMPLEMENT
- ✅ Las 4 condiciones de AUDIT_PLAN (GO_CONDICIONAL) satisfechas: escape hatch de
  CLI, no-enumeración cross-tenant en "usuarios asignados", tests explícitos de
  las 3 decisiones, comportamiento de `tenant create` documentado
- ✅ Bug real de deadlock ("último admin" impedía vaciar un tenant) encontrado y
  corregido dentro de la propia sesión, con tests de regresión en ambos sentidos
- ✅ Suite completa en verde (832 tests), `ruff`/`mypy`/`mkdocs build --strict`
  limpios (solo hallazgos preexistentes ajenos)
- ⬜ Sincronización `CHANGELOG.md`/`COMPATIBILITY.md`/`pyproject.toml` queda como
  trabajo explícito pendiente (ver "Siguientes Pasos"), no como deuda oculta

**Evidencia**:
- Branch: `develop`
- Commit: `e2877a4e64342a6f23175fffdd14e792194382e4` — "feat: rediseno
  Tenant/Role/User - bootstrap de fabrica, roles globales, acceso de escaneo
  implicito, is_instance_admin" (39 files changed, +3312/-877)
- Tests: `tests/unit/test_auth_store.py`, `test_web_auth.py`,
  `test_web_admin_routes.py`, `test_web_tenants_routes.py` (nuevo),
  `test_web_scan.py`, `test_web_filesystem.py`, `test_web_project_access.py`,
  `test_web_projects_routes.py`, `test_change_password.py`, `test_main.py` —
  suite completa 832 passed
- Docs: `docs/functional/access.md`, `admin.md`, `docs/api/index.md`,
  `docs/guides/quick_start.md`, `docs/guides/troubleshooting.md`, `.env.example`
  actualizados; `mkdocs build --strict` limpio

**Sesión cerrada**: 2026-09-11
