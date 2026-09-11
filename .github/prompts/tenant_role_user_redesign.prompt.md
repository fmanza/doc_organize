# Prompt: new_feature — Rediseño de Tenant/Role/User y pantallas de administración

<!--
  Prompt concreto (no genérico) para una petición explícita del usuario:
  rediseño del modelo de acceso multi-tenant descrito en docs/functional/access.md
  y docs/functional/admin.md. Basado en la plantilla .github/prompts/new_feature.prompt.md.

  Fecha de la petición: 2026-09-11
  Fecha de esta actualización: 2026-09-11 — los 3 hallazgos Crítico de la
  auditoría de seguridad quedan RESUELTOS con decisión explícita del usuario
  (ver "Decisiones de diseño" abajo). El hallazgo Alto y los 3 Medio quedan
  registrados como condiciones a cerrar en AUDIT_PLAN antes de IMPLEMENT.

  ⚠️ Este fichero documenta una decisión de diseño, NO autoriza IMPLEMENT por sí
  solo — sigue haciendo falta pasar por PLAN → AUDIT_PLAN de /new-feature antes
  de tocar código.
-->

## Objetivo

Simplificar el modelo de acceso actual (`auth/auth_store.py`, revisión 8/9):
un tenant "default" y un rol "admin" preexistentes de fábrica (sin
aprovisionamiento manual previo por CLI), roles ya no ligados a un tenant sino
solo a usuarios, retirada de `allowed_scan_roots` en favor de un acceso
implícito por proyecto, un nuevo nivel `is_instance_admin` separado del admin
de un tenant, y dos pantallas nuevas de administración (Tenants+Usuarios,
Roles) accesibles desde la opción "Admin".

## Devuelve en este orden

1. PLAN
2. AUDIT_PLAN — parte de los hallazgos Crítico ya vienen resueltos (ver
   "Decisiones de diseño"); **debe seguir resolviendo explícitamente el
   hallazgo Alto y los 3 Medio de "Restricciones" antes de pasar a IMPLEMENT**
3. IMPLEMENT por capas
4. AUDIT_CODE
5. VERSION

## Decisiones de diseño (auditoría de seguridad, resueltas por el usuario el 2026-09-11)

Estas tres decisiones cierran los hallazgos Crítico de la auditoría previa a
este prompt. Un futuro AUDIT_PLAN debe darlas por sentadas, no volver a
abrirlas salvo que aparezca información nueva:

1. **Credenciales de fábrica (`admin`/`admin123` en el tenant `"default"`)**:
   además de forzar `must_change_password=True` en el primer login (igual que
   el bootstrap actual), **se bloquea todo acceso no-loopback mientras la
   contraseña de fábrica siga activa** — no basta con redirigir a
   `/change-password`; ninguna sesión con esa contraseña sin cambiar debe poder
   completar el flujo de login en un host no-loopback. A definir en PLAN: el
   mecanismo exacto (¿se rechaza el login en sí con un mensaje explícito, o se
   permite el login pero se bloquea cualquier otra ruta con más fuerza que hoy?)
   y qué mensaje ve el operador para saber qué hacer.

2. **Sustituto de `allowed_scan_roots`**: se retira el campo, pero un rol
   no-admin **no** queda sin restricción — su acceso de escaneo pasa a ser
   *implícito*: solo puede escanear dentro de las carpetas ya asociadas (guardadas
   en la biblioteca de carpetas, `ScannedFolder`) a los proyectos listados en su
   `project_names`. Sin selector de rutas sueltas para roles no-admin. Implica:
   - `add_folder_to_library`/`remove_folder_from_library`/el explorador de
     carpetas (`web/routes/filesystem.py`) para un rol no-admin quedan acotados
     a rutas ya dentro del árbol de carpetas de sus proyectos permitidos — a
     definir en PLAN el criterio exacto de "ya asociada" (¿cualquier ruta bajo
     el `root_path` del proyecto? ¿solo las que ya aparecen en `ScannedFolder`
     de ese proyecto?).
   - Un rol no-admin ya no puede, en ningún caso, indicar una ruta fuera de sus
     proyectos permitidos — ni para añadirla a la biblioteca ni para escanearla
     directamente.
   - Un rol admin sigue sin restricción (como hoy).

3. **Nivel de instancia separado del admin de un tenant**: se añade un flag
   nuevo, **`is_instance_admin`**, independiente de `Role.is_admin` (que sigue
   significando "ve todos los proyectos de mi tenant"). Solo un usuario con
   `is_instance_admin=True` puede:
   - ver la pantalla cruzada "Tenants y usuarios" (todos los tenants, con sus
     usuarios por debajo),
   - crear/eliminar Tenants,
   - gestionar Roles/Users de **cualquier** tenant, no solo el propio.
   A definir en PLAN: dónde vive este flag (¿en `User`, ya que "los roles no
   están vinculados a un tenant, solo a usuarios"? ¿en un registro aparte, para
   no mezclar "permisos dentro de mi tenant" con "permisos de instancia" en la
   misma tabla?) y cómo se concede el primero (¿el usuario de fábrica del
   tenant `"default"` lo trae de serie? ¿es asignable a otros usuarios, y por
   quién?).

## Restricciones — condiciones pendientes de cerrar en AUDIT_PLAN

### Nivel 1 — Crítico (RESUELTO, ver "Decisiones de diseño")

1. Credenciales de fábrica sin rotación forzada explícita → **resuelto**:
   bloqueo de acceso no-loopback hasta cambiarla.
2. Eliminación de `allowed_scan_roots` sin mecanismo sustituto → **resuelto**:
   acceso implícito a las carpetas ya asociadas a los proyectos permitidos.
3. "Admin" pasa a ver/gestionar todos los tenants sin nivel separado →
   **resuelto**: nuevo flag `is_instance_admin`.

### Nivel 2 — Alto (pendiente de cerrar en AUDIT_PLAN)

4. Bloquear un usuario (`is_blocked`) debe invalidar sus sesiones activas de
   inmediato — borrar todas las filas de `sessions` de ese `user_id` en el
   mismo momento en que se marca como bloqueado, no confiar solo en impedir
   logins futuros (hoy una sesión vive hasta 24h sin comprobar en cada petición
   si el usuario sigue activo).

### Nivel 3 — Medio (a decidir en PLAN, no bloquean por sí solos)

5. Destino de los proyectos de un Tenant eliminado: la regla dada es "se puede
   eliminar si no tiene ningún usuario asociado", sin mencionar sus proyectos —
   definir si también se exige cero proyectos, o si quedan huérfanos en disco.
6. Estatus especial (o no) del Tenant `"default"`: `get_tenant_id()` lo usa hoy
   como valor implícito en modo loopback/sin sesión — definir si puede
   eliminarse igual que cualquier otro tenant.
7. Criterio de unicidad de `Role.name` sin `tenant_id`: hoy es único por tenant
   (`UNIQUE(tenant_id, name)`) — definir si pasa a ser único globalmente, y qué
   pasa si dos admins de tenants distintos editan sin saberlo el mismo rol
   compartido.

## Contexto a completar

- **Objetivo**: sustituir el aprovisionamiento manual (`tenant create`/`user create`)
  por un tenant y usuario admin de fábrica (con el bloqueo no-loopback de la
  decisión 1 mientras la contraseña siga siendo la de fábrica); simplificar
  `Role` a "sin tenant, solo vinculado a usuarios"; retirar `allowed_scan_roots`
  en favor del acceso implícito de la decisión 2; añadir `is_instance_admin`
  (decisión 3); exponer gestión de Tenants/Usuarios/Roles desde la UI.
- **Módulo(s) o clase(s) afectadas**: `auth/auth_store.py` (`Tenant`, `Role`,
  `User`, esquema SQL, `create_tenant`/`create_role`/`_get_or_create_admin_role_id`),
  `core/models.py` (`Role.tenant_id`, `Role.allowed_scan_roots`, nuevo
  `User.is_instance_admin`/`User.is_blocked`), `web/auth.py` (bootstrap +
  bloqueo no-loopback con contraseña de fábrica), `web/dependencies.py`
  (`can_access_project`, `get_allowed_scan_roots` → acceso implícito por
  proyecto, `require_project_access`, nueva dependencia `require_instance_admin`),
  `web/routes/scan.py` + `web/routes/filesystem.py` (todo lo que hoy depende de
  `allowed_scan_roots`/`paths_within_roots`, migrar al criterio implícito de la
  decisión 2), `web/routes/admin.py` + plantillas `admin_roles.html.j2`/
  `admin_users.html.j2` + pantallas nuevas (Tenants+Usuarios, gateadas por
  `is_instance_admin`), `main.py` (¿se retiran los subcomandos `tenant create`/
  `user create`, o se mantienen como vía alternativa para quien no quiera usar
  la UI de instancia?).
- **API pública esperada**:
  - `Tenant`: alta por defecto ("default") al primer arranque, sin CLI previa.
  - `Role`: quitar `tenant_id` del modelo; `name` único — criterio pendiente
    (Nivel 3, punto 7); mantiene `is_admin`, `project_names`; **quita**
    `allowed_scan_roots` (sustituido por acceso implícito, decisión 2).
  - `User`: añade `is_blocked` (con invalidación de sesiones al activarse,
    Nivel 2 punto 4) y `is_instance_admin` (decisión 3).
  - UI nueva: pantalla "Tenants y usuarios" (lista tenants, expande usuarios por
    tenant; gateada por `is_instance_admin`) y pantalla "Roles" (alta/baja/edición
    sin selector de `allowed_scan_roots`).
- **Contrato de entrada**: pendiente de detallar en PLAN (payloads de los nuevos
  endpoints `/api/tenants`, cambios en `/api/roles`, `/api/users`).
- **Contrato de salida**: pendiente de detallar en PLAN.
- **Reglas de negocio** (de la petición original, textual):
  - Tenant `"default"` existe de fábrica, vinculado a un rol `"admin"` con
    permisos admin.
  - Un Tenant se puede eliminar solo si no tiene ningún usuario asociado (más
    la condición pendiente del Nivel 3, punto 5, sobre sus proyectos).
  - Rol `"admin"` de fábrica; la opción "Admin" de la UI (sin `is_instance_admin`)
    sirve para crear/gestionar Roles y Users **dentro de tu propio tenant**;
    crear/eliminar Tenants y ver la pantalla cruzada exige `is_instance_admin`
    (decisión 3) — **pendiente de aclarar en PLAN qué pasa con la gestión de IA y
    plantillas de taxonomía, hoy también bajo `/admin/*`** (¿se quedan gateadas
    por `is_admin` de tenant, como hoy, o pasan a exigir `is_instance_admin`?).
  - Un Rol no está vinculado a un Tenant, solo a usuarios; se puede eliminar si
    no tiene ningún usuario vinculado; conserva la lista de proyectos a los que
    da acceso; ya no tiene rutas de escaneo explícitas (acceso implícito,
    decisión 2).
  - Usuario de fábrica `admin`/`admin123`, vinculado al rol `admin` por defecto,
    con el bloqueo no-loopback de la decisión 1 hasta que se cambie la
    contraseña.
  - Se mantienen: usuario, contraseña, cambio de contraseña, rol.
  - Los usuarios se pueden eliminar o bloquear (`is_blocked`, sin poder acceder
    mientras estén bloqueados; invalida sesiones activas — Nivel 2, punto 4).
- **Motores o formatos afectados**: ninguno (módulo `auth/`, no toca
  scanner/converter/dedup).
- **Migraciones necesarias**: esquema SQLite de `auth.db` — quitar
  `roles.tenant_id` y la tabla `role_scan_roots`; añadir `is_blocked` e
  `is_instance_admin` en `users` (o donde PLAN decida ubicar el segundo, ver
  decisión 3); migración idempotente con el mismo criterio que
  `AuthStore._migrate_schema()`; decidir qué pasa con instalaciones existentes
  que ya tienen tenants/roles/usuarios reales (¿a quién se le asigna
  `is_instance_admin` en una base de datos que se actualiza desde la versión
  anterior?).
- **Archivos existentes a actualizar tras IMPLEMENT**: `docs/functional/access.md`,
  `docs/functional/admin.md`, `docs/guides/quick_start.md`, `.env.example`,
  `mkdocs.yml` (si cambian páginas), y esta misma sección de restricciones
  (marcar el hallazgo Alto y los 3 Medio como resueltos con su decisión final).

## Cómo usar este prompt

```
/new-feature
Lee .github/prompts/tenant_role_user_redesign.prompt.md y arranca PLAN.
Las 3 decisiones de "Decisiones de diseño" ya están tomadas — desarróllalas en
PLAN (mecanismo exacto de cada una), no las vuelvas a poner en duda. AUDIT_PLAN
debe además resolver explícitamente el hallazgo Nivel 2 (invalidar sesiones al
bloquear un usuario) y los 3 Nivel 3 antes de pasar a IMPLEMENT.
```
