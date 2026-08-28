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
