# TRACEABILITY: Resumen de Sesión

## Sesión
- **Fecha**: 2026-08-29
- **Tipo**: `audit` (`/security-review`) → `feature`/`fix` (IMPLEMENT de los hallazgos) →
  `chore` (`/version-closure`, v0.2.0)
- **Rama**: `develop`
- **Estado**: ✅ COMPLETADA (código + tests + `CHANGELOG.md` + versión listos en el working tree,
  **pendiente de commit** — no se ha ejecutado ningún `git commit`/`push` en esta sesión)

## Objetivo
Auditoría de seguridad independiente (`/security-review`) sobre la capa web multi-tenant de
`doc_organize` (auth, sesiones, control de acceso por rol) tras la revisión 9 (roles y gestión de
usuarios, commit `4231eb0`), seguida de la implementación de las correcciones y el cierre de
versión (`/version-closure`) a v0.2.0.

## Cambios Ejecutados

### ✅ 1. Auditoría de seguridad (`/security-review`)
Alcance: `auth/`, `web/auth.py`, `web/dependencies.py`, `web/routes/{auth,admin,change_password,scan,
downloads,cache,duplicates,projects}.py`, `core/constants.py`, `core/models.py`,
`validators/folder_validator.py`, `scan/scan_command.py`, `projects/project_registry.py`,
`cache/cache_manager.py`, `utils/path_utils.py`, `utils/logging.py`.

**Hallazgos**:
- 🔴 **Alto**: `WS /api/projects/{name}/scan` aceptaba `paths` arbitrarios del cliente sin
  restringir qué rutas del servidor podía escanear un rol no-admin — anulaba por completo la
  restricción `project_names` de la revisión 9 (un usuario con acceso solo a "Proyecto A" podía
  indicar la ruta de "Proyecto B" u otro tenant, convertir sus documentos dentro de "Proyecto A" y
  descargarlos vía `export.zip`).
- 🟠 **Medio**: cookie de sesión (`doc_organize_session`) fijada sin `Secure` — viajaba en claro
  sobre HTTP en modo no-loopback si el despliegue no forzaba TLS en el propio proceso.
- 🟠 **Medio**: sin límite de intentos en `POST /login`, combinado con el admin/admin de bootstrap
  predecible (slug de tenant determinista) — permitía fuerza bruta sin fricción.
- 🟡 **Bajo**: payload del WebSocket de scan sin modelo Pydantic (inconsistencia menor, no
  explotable). No se corrigió (fuera del alcance de severidad que motivó el IMPLEMENT).
- Sin hallazgos de SQL injection (todo parametrizado en `auth_store.py`/`cache_manager.py`) ni de
  fuga de secretos en logs.

### ✅ 2. IMPLEMENT — cierre del hallazgo 🔴 (elegido por el usuario: "añadir raíces permitidas por rol")
Se ofrecieron tres opciones (admin-only, allow-list por rol, solo documentar); el usuario eligió
la allow-list — preserva la autonomía de los roles restringidos a costa de un cambio de esquema.

**Archivo(s)**:
- `core/models.py`: `Role.allowed_scan_roots: list[str]` (default `[]` — sin raíces configuradas,
  un rol no-admin no puede escanear ninguna ruta externa).
- `auth/auth_store.py`: tabla `role_scan_roots` (mismo patrón que `role_projects`,
  `CREATE TABLE IF NOT EXISTS` — sin migración manual necesaria); `_insert_role_row`,
  `_load_role_scan_roots`, `create_role()`/`update_role()`/`get_role()`/`list_roles()` extendidos;
  validación: `is_admin=True` + `allowed_scan_roots` no vacía → `AuthError` (mismo criterio que
  `project_names`); degradar `is_admin` sin pasar `allowed_scan_roots` explícito la vacía (lado
  seguro, no exige el mismo `AuthError` que `project_names` porque no es una pérdida sorprendente).
- `web/routes/admin.py`: `CreateRoleRequest`/`UpdateRoleRequest`/`RoleResponse` incluyen
  `allowed_scan_roots`.
- `web/templates/admin_users.html`: textarea "Raíces de escaneo permitidas (una por línea)",
  deshabilitado/vaciado junto con los checkboxes de proyecto cuando se marca "Admin".
- `web/routes/scan.py`: `_paths_within_roots()` — para roles no-admin, cada `path` del payload debe
  ser subruta de alguna `allowed_scan_roots` (`utils.path_utils.is_subpath`); si no, `close(1008,
  "Forbidden path")`. Admin y loopback/sin-auth siguen sin restricción.
- **Status**: ✅ Implementado, probado (8 tests nuevos), `ruff`/`mypy` limpios.

### ✅ 3. IMPLEMENT — cierre de los hallazgos 🟠
**Archivo(s)**:
- `web/routes/auth.py`: `response.set_cookie(..., secure=request.url.scheme == "https")` — activa
  `Secure` solo si la propia petición llegó por HTTPS (no rompe loopback/tests sobre HTTP puro).
- `web/auth.py`: `LoginRateLimiter` (nueva clase) — bloquea `POST /login` 60s tras 5 fallos
  consecutivos del mismo `(tenant_id, username)`; en memoria del proceso, sin persistencia.
  `core/constants.py`: `LOGIN_MAX_ATTEMPTS=5`, `LOGIN_LOCKOUT_SECONDS=60.0`.
- `web/app.py`: `app.state.login_rate_limiter = LoginRateLimiter()` (una instancia por app, no por
  petición — el contador debe sobrevivir entre llamadas).
- `web/routes/auth.py::login_submit`: consulta `is_locked()` antes de autenticar (→ `429` si
  bloqueado), `record_failure()`/`record_success()` según el resultado.
- **Status**: ✅ Implementado, probado (4 tests nuevos: cookie con/sin `https`, lockout, reset tras
  éxito).

### ✅ 4. `/version-closure` → v0.2.0
Sin `CHANGELOG.md` previo ni tags de versión en el repo (estaba en `0.1.0` desde el commit inicial
pese a dos merges de feature) — se preguntó al usuario el bump objetivo; eligió **minor (0.2.0)**
por tratarse de una extensión visible del modelo de roles (`allowed_scan_roots`), no solo un fix
interno.

**Archivo(s)**:
- `pyproject.toml`: `version = "0.1.0"` → `"0.2.0"` (`requires-python` sin tocar, según
  `sync.instructions.md §4`).
- `CHANGELOG.md` (nuevo, no existía): entrada `## [0.2.0] - 2026-08-29` con `Added`/`Fixed`,
  referenciando módulo por ítem.
- **Status**: ✅ Creado/actualizado; `mkdocs build --strict` verificado tras el cambio (aplica por
  `sync.instructions.md` `applyTo: CHANGELOG.md,...`).

---

## Impacto

### Código
- **Archivos modificados**: `pyproject.toml`, `src/doc_organize/{auth/auth_store.py,
  core/constants.py, core/models.py, web/app.py, web/auth.py,
  web/routes/{admin.py,auth.py,scan.py}, web/templates/admin_users.html}`,
  `tests/unit/{test_auth_store.py, test_web_admin_routes.py, test_web_auth.py, test_web_scan.py}`
- **Archivos nuevos**: `CHANGELOG.md`, `.ai/sessions/2026-08-29/TRACEABILITY.md` (este fichero)
- **Cambios funcionales**: sí — ver "Impacto en API pública" más abajo (campo nuevo en `Role`,
  parámetro nuevo en `AuthStore`, `429` nuevo en `/login`, comportamiento de escaneo restringido
  por defecto para roles no-admin sin `allowed_scan_roots` asignadas).

### Compatibilidad
- **BREAKING** (interno, sin consumidores externos): ninguno en firma — todos los campos/parámetros
  nuevos son aditivos con default. **Comportamiento** sí cambia: un rol no-admin que antes escaneaba
  cualquier ruta ahora necesita `allowed_scan_roots` asignadas explícitamente por un admin tras
  desplegar (ver `CHANGELOG.md` → Migraciones en la respuesta de `/version-closure` de esta sesión).
- **NO BREAKING**: `ScanCommand`, `AuthStore.authenticate()`/`create_session()`, contrato de
  `RoleResponse` para clientes que toleran campos desconocidos.

---

## Verificación
```
python -m ruff check src tests     → All checks passed
python -m mypy src                 → Success: no issues found in 42 source files
python -m pytest tests/unit -m "not slow"   → 233 passed (247 recolectados en total, con @slow)
python -m build                    → doc_organize-0.2.0.tar.gz + .whl construidos sin error
mkdocs build --strict              → exit 0, sin warnings de links rotos
```
No se ejecutó la suite `@pytest.mark.slow` (conversión Docling real) en esta sesión por tiempo —
sin cambios en `converter/`/`scan_command.py` que la afecten, riesgo bajo.

---

## Riesgos Residuales

| Riesgo | Mitigación | Status |
|--------|-----------|--------|
| Roles no-admin existentes en despliegues reales quedan sin capacidad de escaneo hasta que un admin les asigne `allowed_scan_roots` | Documentado en `CHANGELOG.md` § Migraciones; acción manual del operador | Pendiente (acción de despliegue, no de código) |
| `LoginRateLimiter` en memoria de proceso: no distribuido, se resetea al reiniciar el servidor | Aceptado — suficiente para frenar el admin/admin de bootstrap; no es mecanismo de auditoría | Aceptado para este alcance |
| Cookie `Secure` depende de que el proceso reciba el esquema real (`request.url.scheme`) — un proxy TLS que no reenvíe `X-Forwarded-Proto`/no use `ProxyHeadersMiddleware` dejaría la cookie sin `Secure` en producción | Documentado en el comentario de `routes/auth.py`; requiere configuración correcta del proxy, no verificable desde este repo | Pendiente (config de despliegue) |
| `pytest -m slow` no ejecutado esta sesión | Sin cambios en el código que cubre; riesgo bajo | Pendiente, recomendado antes de release real |
| ~~`.ai/CURRENT_STATE.md` sigue listando "Rate-limiting en /login" como pendiente~~ | Cerrado: el usuario pidió a continuación actualizar también `CURRENT_STATE.md`/`DECISIONS_LOG.md` (revisión 13 añadida, pendiente movido a cerrado) | ✅ Cerrado en esta misma sesión |

---

## Siguientes Pasos (Recomendado)
1. `git add`/commit de los cambios de esta sesión (código + tests + `CHANGELOG.md` +
   `pyproject.toml`) — mensaje de commit ya preparado en la respuesta de `/version-closure` de esta
   misma sesión, ningún commit ejecutado todavía.
2. ~~Actualizar `.ai/CURRENT_STATE.md`~~ — hecho en esta misma sesión (ver más abajo), cierra el
   pendiente "Rate-limiting en /login" y refleja v0.2.0.
3. Para cualquier despliegue no-loopback ya en producción: asignar `allowed_scan_roots` a los roles
   no-admin existentes antes/inmediatamente después de desplegar esta versión.
4. Ejecutar `pytest -m slow` antes de un release real (no cubierto en esta sesión).
5. Verificar en el entorno de despliegue real que el proxy (si lo hay) reenvía el esquema HTTPS
   correctamente para que la cookie `Secure` se active.

---

## Directrices para Futuras IAs

- **[control de acceso por escaneo]**: `Role.allowed_scan_roots` (revisión de seguridad, esta
  sesión) es la única barrera real contra que un rol restringido a `project_names` escanee rutas
  fuera de su alcance vía `WS /api/projects/{name}/scan`. Cualquier endpoint nuevo que acepte una
  ruta de sistema de archivos elegida por el cliente para un rol no-admin **debe** pasar por
  `utils.path_utils.is_subpath()` contra las raíces del rol — el patrón está en
  `web/routes/scan.py::_paths_within_roots()`. `is_admin=True` sigue sin restricción (ve/escanea
  todo el tenant), igual que con `project_names`.
- **[allow-list vacía ≠ sin restricción]**: en este proyecto, `allowed_scan_roots == []` para un rol
  no-admin significa "no puede escanear ninguna ruta externa", no "sin restricción" — lo contrario
  de cómo se interpretaría una lista vacía en otros contextos del mismo código (p. ej.
  `project_names` vacía + `is_admin=True` sí significa "ve todo"). No confundir los dos significados
  al tocar `Role`.
- **[rate limiting de login]**: `web.auth.LoginRateLimiter` vive en `app.state.login_rate_limiter`
  (una instancia por app FastAPI, creada en `web/app.py::create_app()`), no un singleton de módulo
  ni un objeto por petición — cualquier código que lo consuma debe leerlo de `request.app.state`,
  nunca instanciar uno nuevo.
- **[cookie Secure condicional]**: el criterio es `request.url.scheme == "https"`, evaluado en cada
  petición de login — no una constante de configuración. Si se despliega detrás de un proxy que
  termina TLS y reenvía HTTP plano al proceso, hace falta `ProxyHeadersMiddleware`
  (`uvicorn`/`starlette`) con los headers `X-Forwarded-*` configurados para que `request.url.scheme`
  refleje el esquema real — si no, la cookie nunca se marcará `Secure` aunque el usuario navegue por
  HTTPS. No verificado en este repo (fuera de alcance, es config de despliegue).
- **[versión y changelog]**: antes de esta sesión el proyecto no tenía `CHANGELOG.md` ni tags pese a
  llevar features mergeadas desde `0.1.0` — `CHANGELOG.md` (raíz) es ahora la fuente de verdad de
  versión junto a `pyproject.toml`; seguir el formato `## [X.Y.Z] - YYYY-MM-DD` con secciones
  `Added`/`Fixed` y referencia de módulo por ítem (`sync.instructions.md §1`) en cierres futuros.
- **[gobernanza `.ai/`]**: `.ai/CURRENT_STATE.md` y `.ai/DECISIONS_LOG.md` sí se actualizaron en
  esta sesión (a petición explícita, en dos turnos separados) — quedaron sincronizados con la
  revisión 13. Aun así, no asumir que están al día en sesiones futuras sin cotejarlos contra
  `git log`/`CHANGELOG.md`: en esta misma sesión estuvieron desactualizados durante un turno porque
  el primer pedido del usuario limitó el alcance solo a `.ai/sessions`.

---

## Veredicto

### 🟢 COMPLETADA

**Criterios**:
- ✅ Auditoría de seguridad completada con hallazgos verificables (evidencia archivo:línea) y
  remediación accionable por hallazgo
- ✅ Hallazgo 🔴 y ambos 🟠 implementados según la opción elegida explícitamente por el usuario en
  cada punto de decisión (allow-list por rol; no admin-only ni solo documentar)
- ✅ `ruff check`, `mypy src`, `pytest tests/unit -m "not slow"` (233 passed), `python -m build`,
  `mkdocs build --strict` — todos en verde
- ✅ `pyproject.toml` en `0.2.0`, `CHANGELOG.md` creado y poblado
- ⬜ Commit/push — explícitamente no ejecutado en esta sesión (el usuario no lo pidió)
- ⬜ `pytest -m slow` — no ejecutado, riesgo bajo documentado arriba

**Evidencia**:
- Branch: `develop` (sin commits nuevos en esta sesión — working tree con los cambios)
- Commits: ninguno todavía; mensaje `security: restringir rutas de escaneo por rol, cookie Secure y
  rate limiting de login` preparado en la respuesta de `/version-closure`
- Tests: 233 passed (`-m "not slow"`), 247 recolectados en total; 8 tests nuevos para
  `allowed_scan_roots`, 4 para cookie `Secure`/rate limiting

**Sesión cerrada**: 2026-08-29
