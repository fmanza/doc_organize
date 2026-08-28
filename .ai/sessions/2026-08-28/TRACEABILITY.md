# TRACEABILITY: Resumen de Sesión

## Sesión
- **Fecha**: 2026-08-28 (cierre; el trabajo cubre varias sesiones encadenadas desde el scaffold inicial)
- **Tipo**: `feature` (ciclo completo PLAN → AUDIT_PLAN → IMPLEMENT → AUDIT_CODE, Fase 1 de `doc_organize`)
  + `chore` (regeneración de `.ai/` y limpieza repo-wide de contenido del proyecto anterior, ver punto 9)
- **Rama**: `develop`
- **Estado**: ✅ COMPLETADA (Fase 1 A–D2c commiteada en `6d7c40e`; queda Fase E abierta, ver
  "Siguientes Pasos"). Limpieza de `.ai/`/`.github/`/`.claude/` (punto 9) hecha en working tree,
  **pendiente de commit** — ver mensaje preparado en esta misma sesión.

## Objetivo
Llevar `doc_organize` desde un scaffold vacío hasta una Fase 1 funcional completa: escaneo,
conversión (Docling), deduplicación, caché incremental (SQLite), gestión de proyectos, CLI, y una
interfaz web opcional con autenticación multi-usuario/multi-tenant, escaneo con progreso en tiempo
real, visor de caché, resolución interactiva de duplicados y export ZIP. Todo el trabajo vive sin
commitear desde el scaffold inicial (`git log`: solo "Initial commit" + merge de `.gitignore`).

## Cambios Ejecutados

### ✅ 0. Saneamiento de artefactos heredados (pre-Fase 1)
Antes de implementar, se detectó que `.github/` contenía documentación fabricada por una sesión
previa de GitHub Copilot (aprobaciones inventadas, versión de Docling incorrecta, conteos de líneas
falsos, un "simulacro" de código con un import que nunca existió) y contaminación de otro dominio
(instructions/onboarding describiendo `doc_organize` como "librería multimotor de bases de datos").
**Decisión del usuario**: corregir in-place, no borrar — se añadieron notas de verificación cruzada
y anexos, nunca se eliminó contenido histórico.
- **Archivos**: `.github/AUDIT_PLAN_doclink_extractor.md`, `PHASE_1_READINESS_REPORT.md`,
  `EXECUTIVE_SUMMARY.md`, `BLOCKERS_RESOLUTION.md`, `.github/adr/001-sse-vs-websocket.md`,
  `002-cache-architecture.md` (marcados ❌ SUPERSEDIDO con anexo), `.github/instructions/*.md`,
  `.github/prompts/onboarding_dev.prompt.md`

### ✅ 1. Nivel 1 — Fundacional
`core/models.py` (modelos Pydantic v2: `DocumentMetadata`, `ConversionResult`, `DuplicateGroup`,
`CacheEntry`, `Project`, `Tenant`, `User`, `Session`, `ScanEvent`, etc.), `core/exceptions.py`
(`DocOrganizeError` + jerarquía), `core/constants.py`, `utils/hash_utils.hash_file()` (SHA-256
async, única fuente de verdad), `utils/path_utils.safe_path_join()` (anti path-traversal),
`utils/logging.get_logger()` (JSON estructurado).

### ✅ 2. Nivel 2 — Servicios independientes (REQ-001 a REQ-006, REQ-008)
`validators/` (`FolderValidator`, `ProjectValidator`), `scanner/DocumentScanner` (recorrido +
hashing concurrente, symlinks como nodo opaco), `converter/DocumentConverter` + `OCRScheduler`
(Docling; detección de OCR vía spike empírico real: `confidence.parse_score` `NaN`;
`docling[rapidocr]` necesario para que el OCR funcione), `dedup/DeduplicationManager` (duplicados
exactos + conflictos de versión, `user_choice` para override), `cache/CacheManager` (SQLite+WAL),
`projects/ProjectRegistry` (JSON + `asyncio.Lock` + escritura atómica), `auth/AuthStore` (SQLite+WAL:
tenants/usuarios/sesiones, `hashlib.scrypt` + salt, logout selectivo).

### ✅ 3. Nivel 3 — Orquestación: CLI y `scan/`
`main.py` (subcomandos `project`, `scan`, `web`, `tenant`, `user`). `ScanCommand` extraído a
`scan/scan_command.py` (compartido por CLI y web, ninguno de los dos lo posee): `run()` (contrato
Fase D-1 sin cambios) delega en `run_streaming()` (generador async de `ScanEvent`, Fase D-2b).

### ✅ 4. Web — `§2.7.2` (revisión 8): autenticación multi-usuario y multi-tenant
4 sub-pasos, cada uno confirmado explícitamente por el usuario antes de escribir código:
1. `auth/auth_store.py` + hashing (`scrypt` vía `asyncio.to_thread`, no bloquea el event loop)
2. Middleware de sesión: `web/auth.py` reescrito (cookie `HttpOnly`+`SameSite=Strict`, ya no bearer
   compartido), `web/routes/auth.py` (`/login`, `/logout`)
3. Tenant-scoping de `ProjectRegistry`/`routes/projects.py` (`tenant_id`, default `"default"`)
4. CLI `tenant create` / `user create` (contraseña vía `getpass`, nunca como argumento)

Hallazgo de seguridad cerrado en el propio AUDIT_PLAN: `POST /api/projects/{name}/duplicates/resolve`
(añadido más tarde en D-2c) nunca confía en rutas de archivo del cliente — recalcula los grupos de
duplicados en el servidor y solo acepta la elección si coincide con un miembro real.

### ✅ 5. Web — `§2.7.3` (revisión 10): Fase D-2b, Folder Selector + progreso WebSocket
`ScanCommand.run_streaming()` (nuevo, aditivo). `web/routes/scan.py`: página, validación de
carpetas, `WS /api/projects/{name}/scan`. **Hallazgo de diseño real**: `BaseHTTPMiddleware` no
intercepta conexiones WebSocket — la sesión se autentica a mano en el handler
(`web/auth.py::authenticate_session()`/`requires_auth()`, extraídos como funciones compartidas).

### ✅ 6. Web — `§2.7.4` (revisión 11): Fase D-2c, Cache Viewer + Export ZIP + Duplicates Resolver
`web/routes/cache.py` (solo lectura de `cache.db`), `web/routes/downloads.py` (ZIP en temporal +
`FileResponse`+`BackgroundTask`, sin cargarlo en memoria), `web/routes/duplicates.py` (re-escanea
`folders.json` en vivo; resolución con la mitigación de seguridad ya descrita). "Settings" quedó
explícitamente fuera de alcance (sin requisito real detrás).

### ✅ 7. `§15` (revisión 12): AUDIT_PLAN + IMPLEMENT del roadmap restante
Verificación del repo real (no solo lo que decía el propio PLAN) — hallazgos y su cierre:
- `mkdocs.yml` con `nav:` roto (apuntaba a ficheros de plantilla de IA inexistentes) →
  reescrito + `docs/guides/{installation,quick_start,troubleshooting}.md` +
  `docs/functional/index.md` + `docs/api/index.md` (arquitectura + `mkdocstrings`). Verificado con
  `mkdocs build --strict` (exit 0).
- Matriz de CI (`tests.yml`) testeaba 3.12-3.14, no 3.10/3.11 pese a `requires-python >=3.10` →
  ampliada a 3.10-3.14 (sin confirmar en verde: este entorno es Python 3.14 únicamente).
  `docs.yml` usaba `zensical build` (binario no declarado en `[docs]`) → `mkdocs build --strict`.
- `README.md`/`docs/index.md` eran boilerplate genérico de plantilla → reescritos con contenido real.
- Benchmark de 100 PDFs ejecutado: **84.6s, 70.9 docs/min, 0 errores** — cierra la condición crítica
  del AUDIT_PLAN original de Fase 1. Hallazgo real: el NFR "WebSocket progreso < 500ms" medía la
  cadencia de conversión de Docling (~830ms/doc), no la latencia de transporte — corregido en el PLAN.
- Item 4 (navegador real) no completable en este entorno (sin herramienta de automatización) —
  sustituido por un smoke test contra el servidor real arrancado (`python -m doc_organize web`).
- DoD (`§11`) actualizado a la realidad verificada.

### ✅ 8. Hallazgos de linter (SonarLint/Pylance) revisados turno a turno
- `converter.py`: sintaxis de `# noqa: BLE001 - texto libre` inválida → comentario explicativo
  movido a la línea anterior, `# noqa: BLE001` limpio.
- `scan_command.py`: `run_streaming()` con complejidad cognitiva 26/15 → extraído en 5 métodos
  privados de una responsabilidad cada uno (`_resolve_scan_paths`, `_deduplicate`,
  `_convert_documents`, `_collect_stale_ocr_candidates`, `_process_ocr`), sin cambio de contrato.
- `document_scanner.py` (Pylance "missing argument size_bytes"): **falso positivo** verificado en
  runtime — limitación conocida de Pyright con modelos Pydantic v2 autorreferenciales +
  `model_rebuild()`; no se tocó el código.
- `duplicates_resolver.html` ("Property assignment expected" en `{{ project.name | tojson }}`):
  **falso positivo** — el lenguaje JS embebido de VS Code no entiende sintaxis Jinja2; verificado
  renderizando la plantilla con un nombre con comillas y ñ, produce JS válido y bien escapado.
- `folder_selector.html`/`project_selector.html`/`login.html`: inputs sin `<label>` asociado (a11y
  real) → añadida clase `.sr-only` en `base.html` + `<label for="...">` en los 6 campos afectados,
  sin cambiar el layout visual.
- `main.py::_run_project_list`: dos `return 0` idénticos (S3516) → consolidado a un único `return 0`
  con `if/else` en vez de early-return. **Nota**: SonarLint reportó "+2 locations" no identificadas;
  no se encontraron en `main.py` (el resto de `_run_*` solo tiene un `return` cada uno) — quedan
  pendientes de que el usuario las señale específicamente.

### ✅ 9. Regeneración de `.ai/` + limpieza repo-wide de contenido del proyecto anterior
Tras confirmarse el commit `6d7c40e` (Fase 1), el usuario pidió (a) revisar `.ai/` y dejar solo lo
relacionado con `doc_organize`, y luego (b) extender esa limpieza a **todo el repositorio**,
eliminando cualquier resto del proyecto anterior que ocupó este mismo repo (una librería
multi-motor de migración/comparación de bases de datos, también llamada `doc_organize` en su
momento: módulos `_core/`, `_drivers/`, `connection/`, `metadata/`, `bulk/`, `dump/`, `comparar/`,
`migrate/`, motores MariaDB/MySQL/PostgreSQL/Oracle/SQLServer/HSQLDB/Redshift/Snowflake, clases
`BulkCrud`, `SchemaComparator`, `MySQLVariableValidator`, etc.).

- **`.ai/doc_old/`** (70 carpetas de sesión, 2026-03-22 a 2026-05-28, del proyecto anterior):
  confirmado gitignorado (`.gitignore:68`) y nunca trackeado (`git ls-files` = 0) → **no se tocó**,
  es archivo histórico legítimo tras el pivote, no plantilla contaminada.
- **Los 7 ficheros `.ai/*.md`** (`product.md`, `architecture.md`, `CURRENT_STATE.md`,
  `DECISIONS_LOG.md`, `glossary.md`, `runtime.md`, `standards.md`): regenerados por completo —
  describían o el proyecto de BBDD o un tercer dominio fabricado ("Doclink Extractor"/GitLab
  timelog), nunca actualizados desde el scaffold. Reescritos contra el código real
  (`pyproject.toml`, historial de revisiones del PLAN, `pytest`/`ruff` reales).
- **Tercer dominio fabricado descubierto**: `.github/scripts/generate_docs.py` describía
  `doc_organize` como un "extractor de timelogs de GitLab" (`python-gitlab`, `xlsxwriter`,
  `pandas`) — corregido a la descripción real (escaneo/conversión/dedup/caché).
- **~28 ficheros en `.github/`+`.claude/`** con vocabulario/ejemplos del proyecto de BBDD
  (`zensical` como builder de docs nunca adoptado, ejemplos con `postgres`/`mariadb`/`Oracle`,
  `SyncDatabaseManager`/`AsyncDatabaseManager`, rutas `metadata/mariadb/`, `bulk/crud.py`, la
  sección completa "Sync/Async Contract Validation" en `TESTING_GUIDE.md` que importaba
  `SyncDatabaseManager` y mencionaba "Util_bbdd" por nombre): corregidos con ejemplos reales de
  `doc_organize` (scanner/converter/dedup/cache/auth), o marcados con nota de verificación cuando
  el artefacto que describían (`scripts/build_docs_zip.py`, `docs_build_plugin.py`) no existe en
  el repo.
- **Distinción preservada** (memoria de sesiones previas): la documentación de gobernanza fabricada
  por una sesión anterior de Copilot sobre el dominio *actual* (`BLOCKERS_RESOLUTION.md`,
  `EXECUTIVE_SUMMARY.md`, ADRs, `PHASE_1_READINESS_REPORT.md`) ya se había corregido in-place con
  notas, no se borró — esa categoría **no** se tocó en esta pasada, solo el contenido del proyecto
  de BBDD.
- **No editado deliberadamente**: `.claude/settings.json` (gitignorado, config personal del
  usuario — solo señalado, no modificado); `scripts/build_docs_zip.py` (no existe, escribirlo sería
  feature nueva, no limpieza).

Verificación final: sweep con `ripgrep` (respeta `.gitignore`) sobre todo el repo para
`postgres|mysql|mariadb|oracle|sqlserver|hsqldb|redshift|snowflake` y nombres de clase del proyecto
anterior — sin coincidencias fuera de `.ai/doc_old/` y tres notas históricas ya correctamente
enmarcadas como "antes de la corrección".

---

## Impacto

### Código
- **Módulos nuevos**: `auth/`, `scan/`, `web/` (+ 6 subrutas), `core/constants.py`,
  `core/exceptions.py`, `utils/logging.py`, `utils/path_utils.py`, `main.py`
- **Tests**: 182 pasan (suite completa, incluidos los `@pytest.mark.slow` con Docling real)
- **Cobertura**: 97% global; 100% en la mayoría de `web/routes/*.py`
- **Cambios funcionales**: sí — Fase 1 completa (antes: scaffold vacío)

### Compatibilidad
- **BREAKING** (interno, sin usuarios externos todavía): `ProjectRegistry.create_project/
  list_projects/get_project` ganaron `tenant_id` (con default `"default"`, no rompe el uso sin
  tenant); `create_app()` perdió `api_token`, ganó `auth_db_path`; se retiró
  `DOC_ORGANIZE_API_TOKEN`/bearer compartido en favor de sesión por usuario.
- **NO BREAKING**: `ScanCommand.run()` (CLI) mantiene su firma y tipo de retorno de Fase D-1 pese a
  la reescritura interna de `run_streaming()`.

### Documentación (punto 9)
- **30 ficheros modificados** en `.ai/`, `.github/`, `.claude/` (solo Markdown + 1 `.py` + 2 `.yml`)
- **Sin cambios de código fuente ni tests** — `pytest`/`ruff`/`mypy` no vuelven a correr por este
  punto, no aplica
- **Cambios funcionales**: no — solo documentación/gobernanza IA

---

## Verificación
```
python -m ruff check src tests    # All checks passed
python -m mypy src                # Success: no issues found in 40 source files
python -m pytest                  # 182 passed
mkdocs build --strict             # exit 0, sin warnings de links rotos
```
Smoke test manual contra el servidor real (`python -m doc_organize web`, arrancado y detenido para
la verificación): las 6 páginas cargan, login/logout fijan/borran la cookie real, `duplicates`
detecta un grupo real, export ZIP descarga un fichero válido.

---

## Riesgos Residuales

| Riesgo | Mitigación | Status |
|--------|-----------|--------|
| Matriz de CI ampliada (3.10/3.11) sin confirmar en verde | Solo lo puede confirmar un push real | Pendiente |
| Web UI nunca probada en navegador real | Sin herramienta de automatización en este entorno | Pendiente genuino |
| `mkdocs build --strict` roto históricamente sin que nadie lo notara | Corregido y verificado esta sesión | ✅ Cerrado |
| Sin rate-limiting en `/login` (coste real de `scrypt` por intento) | Documentado, condición de diseño 2 de `§2.7.2` | Pendiente |
| Sin roles/permisos por tenant | Simplificación deliberada, documentada | Aceptado para MVP |
| `AuthStore.tenant_exists()` no validado en `ProjectRegistry` | Analizado en `§14.1`; vector no alcanzable con el código actual | Aceptado, opción D recomendada a futuro |
| Anidamiento de rutas en `Conversión/` (ruta absoluta completa) | Analizado en `§14.2`; riesgo de `MAX_PATH` en Windows con carpetas muy anidadas | Documentado, opción B recomendada a futuro |

---

## Siguientes Pasos (Recomendado)
1. `git add`/commit/push de la limpieza de documentación (punto 9, working tree — ver mensaje
   preparado para GitHub, entregado aparte).
2. Confirmar en verde la matriz de CI ampliada (3.10-3.14) en el próximo push.
3. Probar las 6 páginas web en un navegador real (Chrome como mínimo).
4. Fase E: tests de integración adicionales, documentación ampliada.
5. Rate-limiting en `/login` antes de exponer fuera de loopback.
6. Revisar `§14`/`§15` del PLAN (`.github/prompts/doclink_extractor_plan.md`) para las decisiones de
   alcance abiertas de baja prioridad (tokens de API personales, roles por tenant).
7. Decidir si escribir `scripts/build_docs_zip.py` (no existe; dos workflows y varias guías lo
   referencian) o retirar esa funcionalidad aspiracional de raíz — decisión de producto, no de
   limpieza.

---

## Directrices para Futuras IAs

- **[fuente de verdad]**: el PLAN completo y auditado vive en
  `.github/prompts/doclink_extractor_plan.md` (versión 3.1 a fecha de esta sesión) — cualquier
  duda de diseño/arquitectura/estado se resuelve ahí primero, no releyendo el código desde cero.
- **[hashing]**: `utils/hash_utils.hash_file()` es la única fuente de verdad de SHA-256 en todo el
  proyecto; `scanner/` y `cache/` delegan en ella, nunca reimplementan hashing.
- **[paths]**: `utils/path_utils.safe_path_join()` es obligatorio para cualquier construcción de
  ruta a partir de un segmento elegido por el usuario (nombre de proyecto, destino de duplicados).
- **[orquestación compartida]**: `ScanCommand` (en `scan/scan_command.py`, no en `main.py` ni en
  `web/`) es el único punto que orquesta escaneo+caché+dedup+conversión+OCR; tanto el CLI como
  `web/routes/scan.py` lo consumen sin duplicar lógica. Cualquier cambio de pipeline va ahí.
- **[auth]**: la sesión web es por cookie `HttpOnly`+`SameSite=Strict` (revisión 8), nunca bearer
  token compartido — ese mecanismo fue retirado deliberadamente. `AuthMiddleware`
  (`BaseHTTPMiddleware`) protege rutas HTTP pero **no** WebSocket; cualquier ruta WS nueva debe
  autenticar a mano vía `web/auth.py::authenticate_session()`/`requires_auth()`.
- **[multi-tenant]**: `tenant_id` en `ProjectRegistry` **nunca** debe leerse de un parámetro que el
  cliente controle (query/body) — siempre de `get_tenant_id(request)`, que resuelve desde la sesión
  o cae a `"default"` (loopback/CLI). Romper este invariante reabre fuga entre tenants.
- **[duplicates resolve]**: `POST .../duplicates/resolve` nunca debe aceptar una ruta de archivo
  directamente del cliente — debe recalcular los grupos en servidor y correlacionar por una clave
  derivada del contenido (`_group_key`, sha256 de las rutas ordenadas). Ver `web/routes/duplicates.py`
  para el patrón exacto si se añade una funcionalidad similar.
- **[docs]**: `mkdocs build --strict` es el comando de validación real (ver
  `.github/instructions/sync.instructions.md` §Comando de validación final) — úsalo tras tocar
  `docs/` o `mkdocs.yml`, no asumas que el `nav:` está bien.
- **[CI real]**: `.github/workflows/tests.yml` usa `mkdocs`/`pytest`/`ruff`/`mypy` reales; **no**
  `zensical` (paquete no declarado en pyproject.toml, se corrigió un uso indebido en `docs.yml`).
- **[`.ai/doc_old/`]**: contiene el historial de sesiones de una encarnación **anterior y distinta**
  de este mismo repositorio (un comparador de esquemas de BBDD, módulo `comparar/` que ya no
  existe) — es archivo histórico legítimo tras un pivote de proyecto, no plantilla contaminada; no
  usar su contenido como referencia de dominio, solo (si acaso) como referencia de formato.
- **[dos categorías distintas de "contenido incorrecto" en `.github/`/`.claude/`]**: (1) vocabulario
  del proyecto de BBDD anterior (motores, `SyncDatabaseManager`, `bulk/`, `migrate/`, etc.) — el
  usuario autorizó explícitamente **borrar/reemplazar** esto en la sesión del punto 9; (2)
  documentación de gobernanza IA fabricada por una sesión previa de Copilot sobre el dominio
  *actual* (aprobaciones inventadas, versiones/conteos falsos) — el usuario pidió **corregir
  in-place con nota, nunca borrar**. Antes de tocar cualquier fichero de `.github/`/`.claude/` con
  contenido sospechoso, identificar a cuál de las dos categorías pertenece.
- **[herramientas]**: `hashlib.scrypt`, `getpass`, `secrets` son operaciones síncronas/bloqueantes
  que se ejecutan vía `asyncio.to_thread()` en este proyecto — patrón ya establecido, replicarlo
  para cualquier operación CPU-bound o de I/O bloqueante nueva.
- **[falsos positivos conocidos]**: Pylance reporta "missing argument" en la construcción de
  `DirectoryTreeNode` (modelo Pydantic v2 autorreferencial) — es un falso positivo verificado en
  runtime, no un bug. El JS embebido de VS Code marca error de sintaxis en `{{ ... | tojson }}`
  dentro de `<script>` en las plantillas Jinja2 — también falso positivo (el JS parser no entiende
  Jinja). No "arreglar" ninguno de los dos sin evidencia nueva de que sí son reales.

---

## Veredicto

### 🟢 COMPLETADA (Fase 1 A–D2c) — Fase E queda como GO_CONDICIONAL, explícitamente abierta

**Criterios**:
- ✅ REQ-001 a REQ-008 implementados con acceptance tests
- ✅ CLI completo (`project`, `scan`, `web`, `tenant`, `user`)
- ✅ Interfaz web completa: auth multi-tenant, Folder Selector + WebSocket, Cache Viewer, Export
  ZIP, Duplicates Resolver
- ✅ `pytest` (182 passed), `ruff check` (limpio), `mypy src` (limpio), `mkdocs build --strict`
  (limpio)
- ✅ Todo hallazgo de seguridad identificado en un AUDIT_PLAN se cerró en el propio diseño antes de
  escribir código (WebSocket sin auth de `BaseHTTPMiddleware`, path traversal en
  `duplicates/resolve`)
- ⬜ Fase E (tests de integración adicionales, documentación ampliada) — explícitamente pendiente
- ⬜ Verificación en navegador real y confirmación de CI en verde — pendientes, no asumidos como hechos

**Evidencia**:
- Branch: `develop`
- Commits: `6d7c40e` (Fase 1 completa, feat) ya en el historial; la limpieza de documentación
  (punto 9) sigue en el working tree, sin commitear — ver mensaje de GitHub preparado en esta misma
  sesión
- Tests: 182 passed, 97% cobertura (sin cambios desde `6d7c40e`, el punto 9 no toca código)

**Sesión cerrada**: 2026-08-28
