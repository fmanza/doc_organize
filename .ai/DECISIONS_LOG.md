# DECISIONS LOG — doc_organize

Registro cronológico de decisiones arquitectónicas, técnicas y de proceso.
Formato: **Decisión → Alternativas descartadas → Razón → Impacto actual**.
Fuente: `.github/prompts/doclink_extractor_plan.md` (historial de revisiones 1–12).

> Este documento reemplaza una versión anterior que registraba decisiones de otra librería
> (motores de base de datos) — la encarnación previa de este mismo repositorio. Ver
> `.ai/architecture.md`.

---

## Revisión 1–3 — Identidad de proyecto, hashing, caché

**Decisión**: SHA-256 (no SHA-3) como único algoritmo de hashing, centralizado en
`utils/hash_utils.hash_file()`; caché en SQLite+WAL (no JSON) desde el principio.
**Alternativas descartadas**: SHA-3 (documentación previa fabricada lo mencionaba, nunca se
implementó); `cache.json` plano.
**Razón**: SQLite+WAL permite lecturas concurrentes durante escrituras, sin necesitar backup/rollback
manual; SHA-256 es el estándar de facto y ya soportado nativamente sin dependencias.
**Impacto actual**: precedente reutilizado para `auth.db` (revisión 8) — cuando hace falta
concurrencia real, SQLite, no JSON+lock salvo que la escritura sea genuinamente infrecuente
(`projects.json` sí se quedó en JSON: creación de proyecto es rara, no un hot path).

## Revisión 4 — OCR: spike empírico, no suposición

**Decisión**: `ocr_required` se detecta por `confidence.parse_score` siendo `NaN` (sin capa de
texto nativa), verificado con un spike real (3 documentos de prueba), no una suposición de diseño.
**Alternativas descartadas**: heurísticas basadas en extensión o tamaño de archivo.
**Razón**: la única forma fiable de saber si Docling extrajo texto real es preguntarle a Docling.
**Impacto actual**: reveló un hallazgo no previsto — `docling[rapidocr]` es necesario como
dependencia obligatoria para que el OCR funcione en absoluto (Docling no trae motor OCR por
defecto).

## Revisión 6 — REQ-008, gestión de proyectos

**Decisión**: cada proyecto es una carpeta con su propia `Conversión/`, `cache.db`, `duplicados/`;
registro central en `~/.doc_organize/projects.json` (JSON + `asyncio.Lock` + escritura atómica).
**Alternativas descartadas**: SQLite desde el principio (se descartó por baja frecuencia de
escritura — crear un proyecto es una acción rara y deliberada, no un hot path).
**Razón**: proporcionalidad — la complejidad de SQLite no se justifica para este patrón de acceso.
**Impacto actual**: si la concurrencia real desde `web/` lo exige en el futuro, migrar a SQLite
sigue siendo el camino documentado (mismo precedente que `cache.db`).

## Revisión 7 (❌ SUPERSEDIDA) — Autenticación por cookie de credencial única

**Decisión original**: cookie de sesión cuyo valor era el propio `DOC_ORGANIZE_API_TOKEN`
compartido, aditiva al bearer token existente.
**Por qué se descartó**: incompatible con el requisito posterior de multi-usuario/multi-tenant — no
hay forma de distinguir usuarios ni de cerrar una sesión sin invalidar todas.
**Impacto actual**: nunca se implementó; sustituida íntegramente por la revisión 8. Se conserva en
el PLAN como historial de decisión, no se borró.

## Revisión 8 — Autenticación multi-usuario y multi-tenant

**Decisión**: sesión por cookie (`HttpOnly`+`SameSite=Strict`) obtenida vía `/login`
(usuario+contraseña+tenant); tenants/usuarios/sesiones en SQLite+WAL (`auth.db`); contraseñas con
`hashlib.scrypt` (parámetros OWASP) + salt por usuario, sin dependencia nueva.
**Alternativas descartadas**: token en URL + `sessionStorage` (riesgo XSS); HTTP Basic Auth (el
navegador reenvía credenciales a cualquier origen, reabre CSRF); delegar en un reverse proxy externo.
**Razón**: el bearer token compartido no es utilizable por un navegador real sin JavaScript que lo
inyecte — hallazgo de Fase D-2a. La cookie con `SameSite=Strict` es la mitigación CSRF nativa
moderna.
**Impacto actual**: el bearer compartido (`DOC_ORGANIZE_API_TOKEN`) se retiró por completo.
`tenant_id` en `ProjectRegistry` nunca se lee de un parámetro que el cliente controle, siempre de la
sesión — invariante que cualquier ruta nueva debe respetar.

## Revisión 8, sub-paso 3 — Uniqueness de proyecto por tenant, no global

**Decisión**: el nombre de un proyecto es único **dentro de su tenant**, no globalmente — dos
tenants distintos pueden tener un proyecto con el mismo nombre.
**Razón**: consistente con el aislamiento entre tenants ya establecido para `AuthStore` (username
único por tenant, no global).
**Impacto actual**: `root_path` sigue siendo `<base_location>/<name>/` sin subcarpeta de tenant — si
dos tenants comparten literalmente la misma `base_location` con el mismo nombre, la colisión es
física (carpeta ya existe), no de registro. Limitación conocida, documentada en el docstring de
`ProjectRegistry.create_project`.

## Revisión 10 — WebSocket, no Server-Sent Events, para progreso

**Decisión**: progreso de escaneo/conversión vía WebSocket (`WS /api/projects/{name}/scan`).
**Alternativas descartadas**: SSE (una versión previa del PLAN, ya corregida, lo daba por elegido).
**Razón**: registrada en `.github/adr/001-sse-vs-websocket.md` (ADR corregido tras encontrarse
desalineado con la decisión real).
**Impacto actual**: `BaseHTTPMiddleware` (usado por `AuthMiddleware`) no intercepta conexiones
WebSocket — cualquier ruta WS nueva debe autenticar la sesión a mano
(`web/auth.py::authenticate_session()`), no asumir que el middleware ya la protege.

## Revisión 10 — `ScanCommand` extraído a módulo propio (`scan/`)

**Decisión**: mover `ScanCommand`/`ScanSummary` de `main.py` a `scan/scan_command.py`.
**Razón**: pasó a ser orquestación compartida entre el CLI y la web (Fase D-2b); dejarlo en
`main.py` habría obligado a `web/` a importar del módulo del CLI, acoplando dos entry points de
orquestación que deben ser independientes.
**Impacto actual**: `main.py` reexporta `ScanCommand`/`ScanSummary` — `from doc_organize.main import
ScanCommand` sigue funcionando, sin romper imports existentes.

## Revisión 11 — Duplicates Resolver: nunca confiar en rutas de archivo del cliente

**Decisión**: `POST /api/projects/{name}/duplicates/resolve` recalcula los grupos de duplicados en
el servidor (re-escaneo vía `folders.json`) y solo acepta la elección del usuario si coincide con un
miembro real de un grupo recién detectado — nunca acepta una ruta de archivo directamente del
cliente.
**Alternativas descartadas**: que el cliente reenviara el `DuplicateGroup` completo (incluidas
rutas) tal como lo recibió — habría permitido mover un archivo arbitrario del servidor.
**Razón**: hallazgo de seguridad encontrado en el propio AUDIT_PLAN, antes de escribir código.
**Impacto actual**: `DuplicateGroup.group_id` (uuid4, nuevo en cada `find_duplicates()`) no sirve
para correlacionar el `GET` inicial con el `POST` de resolución — se usa una clave estable derivada
del contenido (`_group_key`, sha256 de las rutas ordenadas) en su lugar.

## Revisión 12 (`§15`) — CI real vs. documentación heredada

**Decisión**: la matriz de CI (`tests.yml`) se amplió a Python 3.10–3.14 para coincidir con
`requires-python >=3.10` (`pyproject.toml`); `docs.yml` se corrigió de `zensical build` (binario no
declarado como dependencia) a `mkdocs build --strict`.
**Razón**: verificación del repo real reveló que ninguno de los dos coincidía con lo que el propio
proyecto declaraba soportar/usar. La decisión de mantener MkDocs (no migrar a Zenical/Zensical) ya
estaba tomada explícitamente en el historial archivado (`.ai/doc_old/ZENICAL_MIGRATION_STATUS_UPDATE.md`,
"Opción B: mantener MkDocs ahora, Zenical después") — `docs.yml` apuntando a zensical contradecía
esa propia decisión.
**Impacto actual**: `mkdocs build --strict` es el comando de validación real (documentado en
`.github/instructions/sync.instructions.md`). No asumir que `zensical` es una herramienta disponible
en este proyecto.

## Revisión 9 — Roles, gestión de usuarios y usuario admin por defecto

**Decisión**: `Role` (rol reutilizable por tenant, `is_admin` + lista de proyectos permitidos) en vez
de flags sueltos en `User`, o un motor RBAC granular por acción; `AuthStore.create_tenant()` crea
automáticamente, en una única transacción, un rol `admin` y un usuario `admin`/`admin` marcado
`must_change_password=True`; `require_project_access`/`require_admin` como dependencies de FastAPI
declaradas por firma en cada ruta `{name}`-scoped, no lógica repetida dentro de cada handler.
**Alternativas descartadas**: `is_admin`/`allowed_projects` directos en `User` (duplica configuración
usuario a usuario, sin rol reutilizable); permisos granulares leer/escribir por proyecto (nadie lo
pidió, sobre-ingeniería); contraseña `admin`/`admin` sin ninguna mitigación (credencial pública
conocida, expuesta indefinidamente si nadie la cambia).
**Razón**: sin un bootstrap automático no había forma de crear el primer usuario de un tenant nuevo
(gap real, no solo teórico — no existía ningún comando CLI ni ruta web para ello antes de esta
revisión). `must_change_password` cierra la ventana de exposición de la credencial por defecto sin
renunciar a la conveniencia de un admin/admin conocido para el primer login.
**Impacto actual**: `create_user()` acepta `role_id` opcional — si se omite, se resuelve al rol admin
del tenant (siempre existe), preservando el comportamiento previo a esta revisión (todo usuario
nuevo gestionaba todos los proyectos del tenant por igual) sin romper ningún llamador existente.
Migración idempotente en `AuthStore.__aenter__` (`ALTER TABLE` + backfill) para bases de datos
creadas antes de esta revisión: usuarios preexistentes sin rol se retro-asignan siempre al rol admin
del tenant, nunca a un rol restringido — nunca reduce accesos.

## Revisión 9, sub-paso 2 — Endurecimiento tras AUDIT_CODE

**Decisión**: `create_tenant`/`create_role`/`create_user` capturan `aiosqlite.IntegrityError` en el
`INSERT` (no solo el `SELECT` previo) y lo traducen a la excepción de dominio correspondiente;
`update_role` exige `project_names` explícito al degradar `is_admin` de `True` a `False`; `role_id`
pasa a ser obligatorio en `POST /api/users`; el selector de proyectos de un rol en `/admin/users` pasa
de texto libre separado por comas a checkboxes de los proyectos reales del tenant.
**Alternativas descartadas**: dejar el pre-check (`SELECT` antes del `INSERT`) como única defensa
contra duplicados — funciona en el caso común pero deja una ventana de carrera real entre dos
peticiones concurrentes; dejar `update_role` vaciando `project_names` en silencio al degradar un rol
admin sin pedirlo explícitamente.
**Razón**: hallazgos de AUDIT_CODE sobre la implementación de roles/usuarios (revisión 9, sub-paso 1).
El pre-check de duplicados seguía el mismo patrón usado desde la revisión 8 para tenants/usuarios —
esta revisión lo corrige ahí también, no solo en el código nuevo de roles. `role_id` opcional en
`AuthStore.create_user()` seguía siendo el default correcto para llamadores internos (preserva
compatibilidad tras la revisión 9, sub-paso 1); el problema era exponer ese default hasta la API
pública de gestión de usuarios, no el default en sí.
**Impacto actual**: ningún cambio de firma pública salvo `CreateUserRequest.role_id` (ahora
obligatorio en la API HTTP, ver `docs/api/index.md`); `AuthStore.create_user()` mantiene `role_id`
opcional para no romper compatibilidad interna. `update_role` con `is_admin=False` y sin
`project_names` ahora lanza `AuthError` en vez de vaciar la lista en silencio — cualquier integración
existente que dependiera de ese vaciado implícito debe pasar `project_names=[]` explícitamente.

## Revisión 13 — Auditoría de seguridad post-revisión 9: `allowed_scan_roots`, cookie `Secure`, rate limiting de login

**Decisión**: `Role.allowed_scan_roots: list[str]` (default `[]`) como allow-list explícita de
raíces del sistema de archivos que un rol no-admin puede escanear vía `WS
/api/projects/{name}/scan`; cookie de sesión marcada `Secure` cuando `request.url.scheme ==
"https"`; `LoginRateLimiter` en memoria (`app.state.login_rate_limiter`) que bloquea `POST /login`
60s tras 5 fallos consecutivos del mismo `(tenant_id, username)`.
**Alternativas descartadas**: para el hallazgo de rutas de escaneo, (a) restringir la elección de
carpeta nueva a roles `is_admin=True` únicamente — más simple, pero le quita a los roles
restringidos la posibilidad de añadir carpetas de origen nuevas por su cuenta; (b) solo documentar
el riesgo sin tocar código. El usuario, consultado explícitamente, eligió la allow-list por rol
(opción (c)) por preservar la autonomía de los roles restringidos. Para la cookie, marcar `Secure`
incondicionalmente — descartado porque rompe el flujo sobre HTTP puro (loopback, tests con
`httpx.AsyncClient`/`http.cookiejar`, que no reenvía cookies `Secure` fuera de HTTPS).
**Razón**: auditoría de seguridad (`/security-review`) encontró que `FolderValidator` solo valida
existencia/redundancia de una ruta, nunca su procedencia — un rol restringido a `project_names`
concretos podía indicar cualquier ruta legible por el proceso servidor (incluidos proyectos de
otros tenants), evadiendo por completo esa restricción y exfiltrando sus documentos vía
`export.zip`. La cookie sin `Secure` permitía que el token de sesión viajara en claro sobre HTTP en
modo no-loopback. La ausencia de rate limiting en `/login`, combinada con el admin/admin de
bootstrap (slug de tenant determinista), permitía fuerza bruta sin fricción antes del primer login
legítimo.
**Impacto actual**: un rol no-admin sin `allowed_scan_roots` asignadas explícitamente **no puede
escanear ninguna ruta externa** (antes sí podía, de forma no intencionada) — cualquier tenant en
producción con roles restringidos debe recibir esa asignación de un admin tras desplegar esta
versión, o esos roles no podrán iniciar ningún escaneo nuevo. `Role.allowed_scan_roots` persiste en
tabla nueva `role_scan_roots` (mismo patrón que `role_projects`, sin migración manual). Detalle
completo, hallazgos y evidencia: `.ai/sessions/2026-08-29/TRACEABILITY.md`. Cierra v0.2.0
(`CHANGELOG.md`, primera versión con changelog formal del proyecto).
