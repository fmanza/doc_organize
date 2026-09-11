# 00_PLAN — Rediseño Tenant/Role/User

> Prompt de entrada: [`.github/prompts/tenant_role_user_redesign.prompt.md`](../../../.github/prompts/tenant_role_user_redesign.prompt.md).
> Este documento recoge, tal cual se produjeron durante la sesión `/new-feature`, las
> fases **PLAN** y **AUDIT_PLAN** que precedieron a IMPLEMENT. AUDIT_CODE y VERSION
> están resumidos en [`TRACEABILITY.md`](TRACEABILITY.md) de esta misma carpeta.

---

## PLAN

### Objetivo

Sustituir el aprovisionamiento manual (`tenant create`/`user create`) por un tenant
`"default"` + usuario `admin` de fábrica creados automáticamente al primer uso de
`AuthStore`; desacoplar `Role` de `Tenant` (solo vinculado a usuarios); retirar
`allowed_scan_roots` en favor de un acceso de escaneo implícito por proyecto; añadir
`is_instance_admin` como nivel separado del `is_admin` de tenant; y exponer dos
pantallas nuevas de administración (Tenants+Usuarios, y las Roles/Usuarios ya
existentes adaptadas).

### Rutas y componentes afectados (confirmado leyendo el código actual)

| Fichero | Cambio |
|---|---|
| `core/models.py` | `Role` pierde `tenant_id`/`allowed_scan_roots`; `User` gana `is_blocked`, `is_instance_admin` |
| `auth/auth_store.py` | Esquema SQL (`roles` sin `tenant_id`, cae `role_scan_roots`, `users` gana 2 columnas); `create_tenant` ya no crea rol/usuario; nuevo `_ensure_default_tenant_bootstrap()`; CRUD de `Role`/`can_access_project` sin `tenant_id`; `authenticate()` rechaza `is_blocked`; nuevo `set_user_blocked()` con invalidación de sesiones en la misma transacción; migración `_migrate_schema()` ampliada |
| `web/auth.py` | `AuthenticatedSession` gana `is_instance_admin` |
| `web/routes/auth.py` | `login_submit` rechaza (403) la cuenta de fábrica sin rotar en modo no-loopback |
| `web/dependencies.py` | `require_admin`→sin cambio; nuevo `require_instance_admin`; `get_allowed_scan_roots` recalculado (implícito); `authorize_project_websocket` usa `[project.root_path]`; `require_project_access`/`can_access_project` sin `tenant_id` en `Role` |
| `web/routes/scan.py`, `web/routes/filesystem.py` | Alcance implícito por `project.root_path`; `browse_directory` gana `project: str \| None` |
| `web/routes/admin.py` | Roles/Users sin `tenant_id` en firma de `AuthStore`; quita `allowed_scan_roots`; añade `is_blocked` a `User*Response`/endpoints |
| `web/routes/ai_settings.py`, `context.py` (plantillas) | `require_admin` → `require_instance_admin` |
| **Nuevo** `web/routes/tenants.py` | Pantalla + API "Tenants y usuarios", gateada por `require_instance_admin` |
| `web/templates/base.html.j2` | Bloque "Admin" reestructurado |
| `web/templates/admin_roles.html.j2` | Quita editor de raíces de escaneo; añade "usuarios asignados" (filtrado por tenant) |
| `web/templates/admin_users.html.j2` | Añade acción Bloquear/Desbloquear |
| **Nuevo** `web/templates/admin_tenants.html.j2` | Pantalla cruzada de tenants+usuarios |
| `main.py` | `tenant create` ya no crea rol/usuario; nuevo subcomando `user set-instance-admin` |
| `core/constants.py` | Nueva `DEFAULT_TENANT_ID = "default"` |
| `core/exceptions.py` | Nuevas `TenantInUseError`, `InstanceAdminRequiredError` |
| `docs/functional/access.md`, `admin.md`, `.env.example`, `mkdocs.yml`, `docs/api/index.md`, `docs/guides/quick_start.md`, `docs/guides/troubleshooting.md` | Actualización de comportamiento documentado |
| 9 ficheros de test que referencian `allowed_scan_roots`/`create_role`/`create_tenant`/`Role(`/`Tenant(` | Reescritura obligatoria |

### Decisiones de diseño desarrolladas (mecanismo exacto)

#### 1. Bloqueo de la cuenta de fábrica en modo no-loopback

`requires_auth(security)` es una propiedad **del servidor** (cómo está *bind*eado), no
del cliente que llama — "no-loopback" = "esta instancia entera exige sesión", no
"esta IP concreta". Mecanismo elegido: **rechazar el login en sí**, no solo redirigir
tras entrar.

En `login_submit` (`web/routes/auth.py`), tras `store.authenticate()` con éxito y
**antes** de `create_session()`:
```python
if requires_auth(request.app.state.security) and is_factory_admin_account(user):
    return 403 + plantilla con mensaje explícito
```
`is_factory_admin_account(user)` = `user.tenant_id == DEFAULT_TENANT_ID and
user.username == DEFAULT_ADMIN_USERNAME and user.must_change_password`. No cuenta
como fallo en `LoginRateLimiter` (la contraseña era correcta; no es señal de
adivinación).

Por qué rechazar el login entero y no solo reforzar el bloqueo tras entrar:
`/change-password` exige sesión ya creada — si se permitiera crear la sesión, un
atacante que adivine `admin`/contraseña de fábrica podría cambiarla él mismo (toma de
control), aunque no pudiera ver nada más. Bloquear el login entero fuerza que la
rotación ocurra desde loopback (canal ya considerado de confianza en el resto de la
app). Solo afecta a esta identidad exacta (tenant `default` + username `admin`); un
usuario con `must_change_password=True` por reseteo de un admin sigue pudiendo
iniciar sesión en no-loopback con normalidad.

#### 2. Acceso de escaneo implícito = `project.root_path`

Criterio elegido: cualquier ruta bajo `project.root_path` de un proyecto al que el rol
tiene acceso (no "ya en `ScannedFolder`" — sería circular, imposible añadir la
primera carpeta).

- `scan.py` (`list_folder_library`/`add_folder_to_library`/`remove_folder_from_library`):
  `allowed_roots = None if is_admin else [project.root_path]` calculado localmente.
- `authorize_project_websocket`: resuelve el `Project` para devolver
  `(tenant_id, [project.root_path])` en vez de `role.allowed_scan_roots`.
- `filesystem.py::browse_directory`: gana `project: str | None = None`. Con `project`
  dado y rol no-admin: exige acceso a ese proyecto (404 si no) y usa
  `[project.root_path]`. Sin `project` y rol no-admin: `allowed_roots = []` (todo 403).
- Se retira `Role.allowed_scan_roots`, la tabla `role_scan_roots`, el editor de
  "raíces de escaneo" en `admin_roles.html.j2`.

#### 3. `is_instance_admin`

Vive en `User` (columna nueva, no tabla aparte). Se concede: de fábrica al usuario
`admin` del tenant `default`; después, solo otro `is_instance_admin=True` puede
marcarlo/desmarcarlo (pantalla "Tenants y usuarios",
`PATCH /api/tenants/{tenant_id}/users/{user_id}`). No autoconcedible. Guarda: no se
puede quitar al último `is_instance_admin` del sistema.

Resuelve la pregunta abierta del prompt sobre IA/plantillas de taxonomía: como
`InstanceSecretsStore`/`TaxonomyTemplateRegistry` ya son *de instancia* (no por
tenant), pasan de `require_admin` a `require_instance_admin`.

### Bootstrap sin CLI previa

`create_tenant(name)` deja de crear rol+usuario automáticamente. Solo el tenant
`default` recibe bootstrap automático, en `AuthStore.__aenter__` (funciona igual
desde CLI y web): `_ensure_default_tenant_bootstrap()` — si `default` no existe, crea
tenant + rol global `admin` + usuario `admin`/`DEFAULT_ADMIN_PASSWORD`
(`must_change_password=True`, `is_instance_admin=True`) en una transacción.
`tenant create` (CLI) sigue existiendo para tenants adicionales, pero ya no
aprovisiona su primer usuario.

### Migración de esquema

`_migrate_schema()`: añade `users.is_blocked`/`users.is_instance_admin`, quita
`tenant_id` de `roles` (reconstrucción de tabla siguiendo el procedimiento oficial de
SQLite: `foreign_keys=OFF`, tabla nueva, copia, drop, rename, `foreign_keys=ON`) y
elimina `role_scan_roots`. Backfill de `is_instance_admin`: usuarios con
`tenant_id="default" AND is_admin` → `True`; si no hay ninguno, promociona al usuario
más antiguo de toda la tabla — nunca deja la instalación sin ningún instance-admin.

### Reglas cerradas para Nivel 2/3 (antes abiertas en el prompt)

| # | Regla cerrada |
|---|---|
| Nivel 2.4 | `set_user_blocked(tenant_id, user_id, True)` borra `sessions` del `user_id` en la misma transacción que fija `is_blocked=1`; `authenticate()` rechaza usuarios bloqueados |
| Nivel 3.5 | `delete_tenant` exige **cero usuarios Y cero proyectos** |
| Nivel 3.6 | `default` se puede borrar igual que cualquier tenant; se documenta que hacerlo y luego reactivar loopback lo recrea de fábrica en el siguiente `AuthStore.__aenter__` (no queda nunca sin admin) |
| Nivel 3.7 | `roles.name` único globalmente; cualquier `is_admin` de tenant conserva CRUD de roles, mitigado por: `/admin/roles` muestra usuarios asignados **filtrados al tenant del que consulta** |

---

## AUDIT_PLAN

**Riesgos funcionales**
- `tenant create` deja de aprovisionar automáticamente el primer usuario de tenants
  *no*-default — cambio de comportamiento documentado, no un bug.
- Migración de `is_instance_admin` puede dejar tenants creados vía `tenant create`
  (no el `default`) sin ningún `is_instance_admin` tras actualizar — por diseño
  (mínimo privilegio), mitigado por el escape hatch de CLI (condición 1).

**Riesgos técnicos (LSP/ISP)**
- `AuthStore.create_role/get_role/update_role/delete_role/list_roles/can_access_project`
  pierden el parámetro `tenant_id` — simplifica el contrato (ISP). Ondas:
  `web/routes/admin.py`, `web/dependencies.py`, `web/routes/scan.py`, y 9 ficheros de
  test.
- `AuthenticatedSession` gana `is_instance_admin`; `get_session_with_access()` cambia
  su `SELECT`/join.
- `authorize_project_websocket` cambia la semántica de su 2º valor de retorno — blast
  radius contenido a `scan.py` (`context.py` ya lo ignora).

**Riesgos de seguridad**
- El bloqueo de login de fábrica debe activarse **exactamente** con
  `(tenant=="default", username=="admin", must_change_password==True)` y con ningún
  otro usuario.
- "Usuarios asignados" en `/admin/roles` debe impedir que un admin de tenant vea
  usuarios/tenants ajenos a través de un rol compartido — regla de no-enumeración
  **nueva**, introducida por este propio rediseño.
- `browse_directory(project=...)` debe aplicar 403 (sin acceso) antes que 404 (no
  existe), igual que ya hace la variante sin `project`.
- Invalidar sesiones al bloquear debe ir en la misma transacción SQLite que el
  `UPDATE is_blocked`.

**Simplificaciones posibles**
- Rechazada: ACL completo de "rol pertenece a tenant X" para cerrar del todo el
  Nivel 3.7 — el propio prompt lo marca como no bloqueante; visibilidad + documentación
  es proporcionado.
- Rechazada: endpoints cruzados en `admin.py` en vez de un router nuevo — mezclaría
  `require_admin` y `require_instance_admin` en el mismo `APIRouter`, perdiendo la
  garantía "imposible olvidar la dependencia".

**Condiciones (GO_CONDICIONAL → GO)**
1. Añadir escape hatch de CLI: `python -m doc_organize user set-instance-admin
   <username> --tenant <id>` — sin él, una instalación multi-tenant migrada sin
   ningún instance-admin en un tenant no-default no tiene forma de recuperarse sin
   editar `auth.db` a mano.
2. "Usuarios asignados" de `/admin/roles` filtrado por tenant para un `is_admin`
   no-instance.
3. Tests explícitos, antes de cerrar AUDIT_CODE, para: bloqueo de login de fábrica
   (positivo y negativo), acceso de escaneo implícito, invalidación de sesión al
   bloquear.
4. Documentar en VERSION como cambio de comportamiento deliberado (no regresión) que
   `tenant create` ya no aprovisiona usuario/rol automático salvo para `"default"`.

**Veredicto: GO_CONDICIONAL** — las 4 condiciones se incorporaron al PLAN antes de
IMPLEMENT y se verificaron cumplidas en AUDIT_CODE (ver `TRACEABILITY.md`).
