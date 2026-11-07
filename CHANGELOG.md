# Changelog

Formato basado en [Keep a Changelog](https://keepachangelog.com/es/1.0.0/).
Este proyecto sigue [SemVer](https://semver.org/lang/es/) desde v0.2.0 (sin
releases publicados antes de esa versión).

## [Unreleased]

## [1.3.0] - 2026-11-07

Petición de doc_organize_web (G41 / L-19). Sin cambios incompatibles: con los valores por defecto el escaneo recorre
lo mismo que en 1.2.0. Firmas en [Escaneo](docs/api/scan.md#exclusiones-exclude_paths-ignore_patterns-g41) y
[Scanner](docs/api/scanner.md).

### Añadido

- **Exclusiones en el escaneo (G41)**: `ScanOptions.exclude_paths: list[str] = []` (carpetas o ficheros, rutas
  absolutas, que no se recorren ni ellos ni su contenido) e `ignore_patterns: list[str] = []` (patrones `fnmatch` sobre
  el nombre de cada fichero o carpeta, sin distinguir mayúsculas, que se suman a `IGNORED_NAMES`). También en
  `DocumentScanner.scan_folders(..., exclude_paths=, ignore_patterns=)`, *keyword-only*; `exclude_dir` sigue igual.
  - Las rutas excluidas se comparan resueltas con `os.path.normcase` (sin mayúsculas en Windows, exactas en POSIX). Se
    resuelve su carpeta padre, así que excluir un enlace o una *junction* lo quita sin seguirlo. Una exclusión que no
    existe no es un error; una que es la carpeta escaneada, o la contiene, deja esa raíz vacía.
  - Los patrones no se aplican a las carpetas escaneadas. Cada uno: no vacío, sin `/` ni `\`, hasta 64 caracteres
    (`ValidationError` si no).
  - Lo excluido no es un error: no va a `unreadable_dirs`/`unreadable_files`, ni a `io_errors`, ni a los avisos.
- **Lo ya convertido**: sin `force` se conservan su salida y su entrada de caché, y al quitar la exclusión vuelve como
  `unchanged` (no se reconvierte). Con `force` cuenta como eliminado, igual que un fichero borrado: se borran su salida
  y su entrada de caché, y si después se quita la exclusión vuelve como `new`. Siguen protegidos los documentos de
  carpetas o ficheros que no se pudieron leer.
- `ScanSummary.excluded_cached` (clave nueva de `COMPLETED`): entradas de la caché anterior al escaneo bajo una
  exclusión o que encajan con un patrón en algún tramo de su ruta bajo la carpeta escaneada. Se cuenta desde la caché,
  sin recorrer el disco.

### Rendimiento

- Los patrones se compilan en una sola expresión (`fnmatch.translate`): con 30 patrones, recorrer 100 000 entradas
  tarda lo mismo que sin ellos (~3,7 s en disco local, Windows, Python 3.14, sin contar el hash). Excluir solo quita
  trabajo.

## [1.2.0] - 2026-11-06

Petición de doc_organize_web (G40 / L-18). Sin cambios incompatibles: con los valores por defecto las páginas de la
caché salen en el mismo orden que en 1.1.1. Firmas en [Cache](docs/api/cache.md).

### Añadido

- **Orden de las páginas de la caché (G40)**: `CacheManager.load_cache_page(..., order_by: CacheOrderBy = "file_path",
  descending: bool = False)`. `CacheOrderBy` (en `doc_organize.cache`) admite `"file_path"`, `"timestamp"`,
  `"conversion_status"`, `"status"`, `"size_bytes"` y `"error_retry_count"`. Los empates se resuelven siempre por
  `file_path` ascendente, también en descendente, así que el orden es total y el mismo en cualquier caché. Los `NULL`
  (`size_bytes` de entradas anteriores a 1.1.0, `conversion_status` sin valor) van al final en los dos sentidos. Se
  combina con `search`, `relative_to` y `conversion_status` igual que antes; `count_entries` no cambia. Un `order_by`
  que no está en la lista lanza `ValueError`: nunca se pasa un nombre libre al SQL.
- Una caché anterior a 1.1.0 abierta con `read_only=True` (sin la columna `size_bytes`) se puede ordenar por
  `size_bytes`: todas las entradas empatan y quedan por `file_path`.

### Rendimiento

- Sin índices nuevos ni migración. Cada conexión de `CacheManager` fija `PRAGMA temp_store=MEMORY` (afecta solo a la
  conexión, no al fichero, así que vale en solo lectura) y, para un orden que no es `file_path`, ordena solo las
  claves y después lee las filas de la página. Con 100 000 entradas, una página con offset alto tarda ~80–150 ms en
  cualquier orden y dirección, con o sin filtros (disco local, Windows, Python 3.14); antes, ordenando filas completas
  con el valor por defecto de SQLite, ~1 s. Se descartaron los índices: daban ~7 ms, pero multiplicaban por cuatro el
  tamaño de `cache.db` (cada uno repite `file_path`) y el coste de cada escritura del escaneo.

## [1.1.1] - 2026-11-06

Corrección. Sin cambios de API.

### Corregido

- En Windows, `ProjectRegistry.delete_project` fallaba con `ProjectError` («Acceso denegado», `WinError 5`) si el
  proyecto contenía un fichero de solo lectura, y dejaba el proyecto registrado y borrado a medias. Esos ficheros llegan
  al proyecto porque las copias (duplicados en modo copia, salida del `Reorganizer`) usan `shutil.copy2`, que conserva
  el atributo de solo lectura del original (carpetas de red, CDs, descargas). Ahora se quita el atributo y se reintenta
  el borrado; nunca a través de un enlace o una *junction*, y cualquier otro error se propaga como antes. Mismo
  arreglo en `move_project_root` entre volúmenes (copiar y borrar el origen), `Reorganizer.delete_output` y
  reconstrucción, `ProjectHistoryCleaner.clear` y `ContextRegistry.delete_context`. En Linux y macOS no cambia nada.
- Un proyecto que quedó borrado a medias con 1.1.0 o anterior se termina de borrar llamando otra vez a
  `delete_project`.

## [1.1.0] - 2026-11-06

Peticiones de doc_organize_web (L-16 / G38, L-9 / G11 y G25). Sin cambios incompatibles: todo lo nuevo es opcional y,
con los valores por defecto, un escaneo se comporta como en 1.0.1, salvo en lo que lista «Cambios de comportamiento».
Firmas en [Escaneo](docs/api/scan.md) y en las páginas de API de cada módulo.

### Añadido

- **Escaneos por tramos (G38)**: `ScanOptions.max_documents: int | None = None`. El escaneo para de forma ordenada
  tras N conversiones de Docling, contando por separado la primera pasada y la de OCR. Guarda la caché y el informe de
  errores, y termina con `COMPLETED`. `ScanSummary` gana `remaining` (conversiones pendientes) y
  `stopped_reason` (`"max_documents"` o `None`). La llamada siguiente hace solo lo que falta.
- **Timeout por documento (G11)**: `ScanOptions.document_timeout_s: float | None = None` y
  `DocumentConverter.convert_document(timeout_s=)`. El documento que lo supera queda en `ERROR` con la causa y el
  escaneo sigue. El hilo de Docling no se puede interrumpir: termina en segundo plano y su resultado se descarta. Su
  convertidor se descarta también, así que hay un pico temporal de memoria.
- **Reintentos de E/S (G11)**: `ScanOptions.io_retries: int = 0` e `io_retry_backoff_s: float = 1.0`, con espera
  exponencial. Cubren listar carpetas, leer metadatos y calcular hashes (`DocumentScanner(io_retries=,
  io_retry_backoff_s=)`) y copiar a duplicados (`DeduplicationManager(...)` y
  `ScanCommand.deduplicate_streaming(io_retries=, io_retry_backoff_s=)`). No se reintentan `FileNotFoundError`,
  `NotADirectoryError`, `IsADirectoryError` ni `FileExistsError`. Mover duplicados no se reintenta.
- **Sin rehashear lo que no cambia (G11)**: `ScanOptions.reuse_unchanged_hashes: bool = False` y
  `DocumentScanner.scan_folders(known_entries=)`. Si tamaño y fecha de modificación coinciden con la caché, se
  reutiliza el hash.
- **Ficheros que no se pueden leer (G11)**: `ScanResult.unreadable_files` (ruta → error) y `ScanSummary.io_errors`.
- **Duplicados desde la caché (G25)**: `CacheEntry.size_bytes: int | None = None`, guardado por cada escaneo (columna
  nueva en `cache.db` con migración aditiva). `DocumentMetadata.from_cache_entry(entry)` construye los metadatos sin
  leer el fichero y lanza `ValueError` si la entrada es anterior a 1.1.0. Los `CacheEntry` serializados antes se siguen
  leyendo, y `CacheManager(read_only=True)` abre una caché antigua sin la columna (la lee como `None`).
- **OCR por partes (G38)**: `OCRScheduler.process_with_ocr(timeout_s=, cancel_token=, max_documents=)`. Para entre
  documentos y devuelve los resultados ya procesados.
- `tests/integration/test_scan_memory_growth.py`: medida del RSS cada 50 conversiones en un escaneo sintético largo con
  OCR. Solo corre con `DOC_ORGANIZE_MEMORY_TEST=1`, no en el CI. Resultados en
  [Memoria en escaneos largos](docs/guides/troubleshooting.md#memoria-en-escaneos-largos).

### Cambios de comportamiento

- **Cancelar durante el OCR conserva lo procesado (G38)**: el `CancelToken` se atiende entre documentos del lote de
  OCR. Lo ya procesado se guarda en la caché como `SUCCESS` y el resto sigue `OCR_PENDING`. Hasta 1.0.1 la cancelación
  también paraba entre documentos, pero descartaba los resultados del lote, así que tras partir el escaneo se rehacía
  todo el OCR.
- **Liberación de memoria (G38)**: durante la conversión y el OCR se hace `gc.collect()` cada 10 documentos y, en Linux
  con glibc, `malloc_trim(0)`. También al acabar la primera pasada, antes de cargar los modelos del OCR. Con documentos
  sintéticos: en Linux el RSS de la primera pasada queda plano (1 037 MiB a los 200 documentos, frente a 1 512 MiB); en
  Windows el final baja de 5 332 a 3 042 MiB. Cuesta unos 40 ms por documento repartidos.
- **Un fichero que se lista pero no se puede leer** (no uno borrado durante el escaneo) aparece en los avisos de
  `SCANNED`, en el `ScanErrorReport` y en `ScanSummary.io_errors`. Con `force` ya no se da por eliminado: se conservan
  su salida y su entrada de caché, como con las carpetas ilegibles desde 0.12.0. Antes se omitía en silencio.
- **Las *junctions* de Windows no se siguen**, igual que los enlaces simbólicos. Una *junction* dentro de la carpeta
  escaneada podía llevar el escaneo fuera de ella.
- El evento `COMPLETED` (y `ScanSummary`) lleva siempre tres claves nuevas: `io_errors`, `remaining` y
  `stopped_reason`.

### Documentación

- Página nueva [Escaneo](docs/api/scan.md): `ScanCommand`, todos los campos de `ScanOptions` y `ScanSummary`.
- [Scanner](docs/api/scanner.md): corregida la firma, que documentaba un `scan(paths, ignore_patterns)` inexistente en
  lugar de `scan_folders`. [Cache](docs/api/cache.md): corregido el esquema, al que le faltaban dos columnas y que
  listaba un `PRAGMA synchronous=NORMAL` que el código nunca fija.

### Investigado sin reproducir

- El agotamiento de 6 GiB con 521 documentos reales (G38) no se reproduce con documentos sintéticos en Linux. Ni
  siquiera un PDF escaneado de 40 páginas con OCR pasa de 2,9 GiB de pico. En Windows queda un crecimiento nativo de
  unos 9 MiB por PDF en el pipeline de *layout* de Docling que no se libera desde Python. Para acotar la memoria en
  cualquier caso: `max_documents` con un proceso nuevo por tramo.

## [1.0.1] - 2026-11-06

Corrección (G39 / L-17, petición de doc_organize_web). Sin cambios de API.

### Corregido

- Con OCR activado, los documentos que no son PDF ni imagen (`.docx`, `.xlsx`, `.pptx`, `.html`…) ya no pasan por la
  fase `ocr` ni se convierten dos veces, y `ScanSummary.ocr_required` ya no los cuenta. `DocumentConverter._needs_ocr`
  usaba solo `confidence.parse_score` siendo `NaN`. Docling solo calcula ese valor en `StandardPdfPipeline`; en
  `SimplePipeline` se queda `NaN` por defecto. Ahora un documento requiere OCR solo si es `InputFormat.PDF` o
  `InputFormat.IMAGE` y su `parse_score` es `NaN`.

### Caché existente

- Las entradas `OCR_PENDING` de otros formatos que ya hay en la caché **se reprocesan una sola vez** en el siguiente
  escaneo con OCR (`ScanOptions(use_ocr=True)` / `--use-ocr`) y quedan en `SUCCESS`. No hace falta migrar nada ni
  borrar la caché. Ese reproceso usa el mismo camino que ya recoge los `OCR_PENDING` sin cambios, y ahora devuelve
  `ocr_required=False`. Mientras no se escanee con OCR, esas entradas siguen apareciendo como `OCR_PENDING`.

## [1.0.0] - 2026-11-06

Versión final de la librería pura (L-15). El código y la API son exactamente los de
[1.0.0rc2](#100rc2---2026-11-05): solo cambian la versión y este CHANGELOG. Se publica tras cerrar doc_organize_web su
Fase 10 (v1.0.0rc1 de doc_organize_web, validada con doc_organize 1.0.0rc2: 495 tests de backend, E2E 18/18, carga con
100 000 documentos y las variantes GPU, LibreOffice y AV).

### Breaking changes

Frente a 0.14.0, los de [1.0.0rc1](#100rc1---2026-11-05) (tabla con cada elemento retirado y su sustituto). En
resumen:

- Sin web integrada ni autenticación: fuera `doc_organize.web`, `doc_organize.auth`, el extra `[web]`, los
  subcomandos `web`, `tenant` y `user` y los flags `--auth-db-path` y `--templates-path`. La web es
  [doc_organize_web](https://github.com/fmanza/doc_organize_web).
- Sin multi-tenant: `Project.tenant_id`, `Context.tenant_id` y el parámetro `tenant_id` de `ProjectRegistry`
  desaparecen; el nombre de un proyecto es único en todo el registro (los JSON antiguos se siguen leyendo).
- Sin secretos de instancia: `InstanceSecretsStore`, `secrets_cipher` y las `*_config_from_store_or_env`; se usan las
  `*_config_from_env()` o se construye el `*Config` en el consumidor.
- Sin lo obsoleto desde 0.13.0: `MkDocsGenerator` (usa `SiteGenerator`) y `Context.mkdocs_generated` /
  `Context.mkdocs_site_built` (usa `site_generated` / `site_built`).
- Sin los modelos, excepciones y constantes que solo usaban la web y `auth/` (`Tenant`, `User`, `AuthError`,
  `DEFAULT_TENANT_ID`…).

Guía para quien usaba la web integrada: [De la web integrada a doc_organize_web](docs/guides/migracion_web.md).

### Firmas finales

Las de [1.0.0rc2](#100rc2---2026-11-05), sin cambios.

## [1.0.0rc2] - 2026-11-05

Segunda versión candidata de la 1.0.0: la librería pura de 1.0.0rc1 (L-11, L-12) más su documentación e
instrucciones IA (L-13, L-14). El código y la API son los de 1.0.0rc1; cambian los docstrings (y por eso el wheel), las
guías y las instrucciones, y las rc salen ya marcadas como pre-release. La 1.0.0 final (L-15) se publica cuando
doc_organize_web cierre su Fase 10. 1.0.0rc1 se mantiene publicada tal cual (sus SHA-256 no cambian).

### Breaking changes

Ninguno nuevo respecto a 1.0.0rc1. Frente a 0.14.0, todos los de [1.0.0rc1](#100rc1---2026-11-05) (tabla con cada
elemento retirado y su sustituto); guía para quien usaba la web integrada:
[De la web integrada a doc_organize_web](docs/guides/migracion_web.md).

### Added

- Guía [De la web integrada a doc_organize_web](docs/guides/migracion_web.md): qué sustituye a cada pantalla y a cada
  endpoint (tabla de `PARIDAD.md` de doc_organize_web), que los datos no se migran (doc_organize_web guarda los
  proyectos en su `config.db` y empieza limpio) y cómo desplegar la web.
- Sección «Breaking changes» en [1.0.0rc1](#100rc1---2026-11-05), con cada elemento retirado y su sustituto.
- Inicio rápido con un ejemplo de uso como librería (`ProjectRegistry`, `ProjectLayout`, `ScanCommand`).

### Changed

- Navegación del sitio sin la web: la sección «Histórico» sale del `nav` (las páginas siguen publicadas y se enlazan
  desde la guía de migración). Instalación e inicio rápido solo hablan del CLI y la librería.
- Guías funcionales (contexto, deduplicación, proyectos, LiteLLM, resolución de problemas) en términos de librería, sin
  pantallas, botones ni endpoints de la web integrada. Las reglas que imponía la web (una operación a la vez, campos
  excluyentes al construir el contexto, confirmar los grupos por similitud) se documentan como responsabilidad del
  consumidor.
- Docstrings y comentarios de `src/` sin referencias a `web/`, `auth/`, `AuthStore` ni plantillas Jinja (se
  renderizan en la referencia de la API).
- Instrucciones IA (`.github/SHARED_INSTRUCTIONS.md`, `instructions/architecture` y `docs`, skills,
  `.claude/TESTING_GUIDE.md`, `CLAUDE.md`) sin reglas de la web: fuera las de plantillas Jinja2, Tailwind y JS inline,
  WebSocket, `auth.db` y tenants; la arquitectura descrita es la real de 1.0.0.

- `release.yml` publica como pre-release las versiones `aN`, `bN` y `rcN` (1.0.0rc1 se marcó a mano).

### Removed

- Skills `access-doc-review` y `tenant-role-user-redesign`: validaban o rediseñaban código retirado en 1.0.0. Siguen en
  el historial de git.

### Firmas finales

La API pública de la 1.0.0 tal como queda en el tag `v1.0.0rc2` (verificado con `inspect.signature` y
`model_fields`): los 84 nombres de `doc_organize.__all__`. Solo cambia, frente a 0.14.0, lo que sigue; el resto de
firmas son las de las «Firmas finales» de 0.14.0, 0.13.0 y 0.12.0.

```python
# doc_organize.ProjectRegistry (L-12): sin tenant_id; el nombre es único en todo el registro
async def create_project(self, name: str, base_location: str | Path) -> Project
async def list_projects(self) -> list[Project]
async def get_project(self, name: str) -> Project
async def delete_project(self, name: str) -> None
async def move_project_root(self, name: str, destination_parent: str | Path) -> Project

# doc_organize.Project (L-12): sin tenant_id (un projects.json antiguo con el campo se lee y lo ignora)
class Project(BaseModel):
    name: str
    root_path: str
    created_at: str

# doc_organize.Context (L-12): sin tenant_id ni las propiedades mkdocs_generated / mkdocs_site_built
class Context(BaseModel):
    ...
    site_generated: bool = False  # validation_alias: "site_generated" | "mkdocs_generated" (context.json antiguos)
    site_built: bool = False      # validation_alias: "site_built" | "mkdocs_site_built"

# doc_organize.ai (L-12): solo las *_config_from_env; las *_config_from_store_or_env no existen
def litellm_classification_config_from_env() -> LiteLLMClassificationConfig
def litellm_taxonomy_classification_config_from_env() -> LiteLLMTaxonomyClassificationConfig
def litellm_taxonomy_manifest_draft_config_from_env() -> LiteLLMTaxonomyManifestDraftConfig
def litellm_usage_config_from_env() -> LiteLLMUsageConfig
def github_copilot_usage_config_from_env() -> GitHubCopilotUsageConfig
```

- `doc_organize.__all__` pierde `MkDocsGenerator` (usa `SiteGenerator`); no gana ningún nombre.
- CLI (`python -m doc_organize`): `project`, `scan`, `deduplicate` y `export`, con los mismos flags que en 0.14.0.
  `web`, `tenant` y `user` terminan con `invalid choice` (código 2).
- Extras: `export`, `site`, `ocr-gpu`, `av`, `ai`, `context`, `docs` y `dev`; sin `web`.

## [1.0.0rc1] - 2026-11-05

Librería pura (L-11, L-12): se retiran la web integrada, `auth/` y lo que quedó obsoleto en 0.14.0. doc_organize_web
0.10.0 cubre la paridad completa (su `PARIDAD.md`, todas las filas ✅). **Incompatible (MAJOR)**. La 1.0.0 final sale
al cerrar la Fase 10 de doc_organize_web. Lo que se queda (escaneo, caché, deduplicación, contexto, exportación,
clientes de IA y `*_config_from_env`, `projects.layout`, diagnóstico y los comandos `scan`, `project`, `deduplicate`
y `export` del CLI) se comporta igual que en 0.14.0. También se retira lo obsoleto desde 0.13.0 (`MkDocsGenerator` y
los alias `mkdocs_*` de `Context`).

### Breaking changes

| Retirado | Sustituto |
|---|---|
| `doc_organize.web` (FastAPI, plantillas Jinja, WebSocket) y `python -m doc_organize web` | [doc_organize_web](https://github.com/fmanza/doc_organize_web); ver [De la web integrada a doc_organize_web](docs/guides/migracion_web.md) |
| `doc_organize.auth` (`AuthStore`, usuarios, tenants, roles, sesiones, `auth.db`) | Usuarios, tenants y roles de doc_organize_web, en su `config.db` (sin migración) |
| Subcomandos `tenant` y `user`, y los flags `--auth-db-path` y `--templates-path` | `python -m app.cli create-admin` y las pantallas de administración de doc_organize_web |
| Extra `[web]` | `pip install doc_organize` (el CLI y la librería no lo necesitaban); la web se despliega aparte |
| `InstanceSecretsStore`, `secrets_cipher` y las cinco `*_config_from_store_or_env` (con `SecretValueReader`) | Construir el `*Config` en el consumidor, o las `*_config_from_env()` |
| `Project.tenant_id`, `Context.tenant_id` y el parámetro `tenant_id` de `ProjectRegistry` | Ninguno: el nombre de un proyecto es único en todo el registro. Los JSON antiguos se siguen leyendo |
| `MkDocsGenerator` | `SiteGenerator` |
| `Context.mkdocs_generated` / `Context.mkdocs_site_built` | `Context.site_generated` / `Context.site_built` (un `context.json` antiguo con las claves `mkdocs_*` se sigue leyendo) |
| `Tenant`, `Role`, `User`, `Session`, `SecurityConfig`, `DirectoryListing` (`core.models`) | Ninguno (solo los usaba la web) |
| `AuthError` y subclases, `SecretsCipherError`, `SecretsEncryptionNotConfiguredError` (`core.exceptions`) | Ninguno (solo los usaba `auth/`) |
| Constantes de autenticación de `core.constants` (`DEFAULT_TENANT_ID`, `SCRYPT_*`, `LOGIN_*`…) | Ninguno |

### Removed

- **L-11**: `doc_organize.web` entero (aplicación FastAPI, rutas, plantillas Jinja, `ai_settings_config`,
  `scan_errors_data`, `pagination`) y `doc_organize.auth` entero (`AuthStore`, `InstanceSecretsStore`,
  `secrets_cipher`, tiendas de tenants, usuarios, roles y sesiones, migraciones). También el módulo interno de
  avisos de L-10 (`_deprecations`).
- **L-11**: los subcomandos `web`, `tenant` y `user` del CLI y sus flags `--auth-db-path` y `--templates-path`.
  argparse los rechaza como cualquier comando desconocido (código de salida 2).
- **L-11**: el extra `[web]`, y de `dev` FastAPI, uvicorn, Starlette, Jinja2, `python-multipart` y `cryptography`
  (este último solo lo usaba `auth/secrets_cipher.py`).
- **L-12**: `tenant_id` de `Project` y de `Context`, y el parámetro `tenant_id` de `ProjectRegistry.create_project`,
  `list_projects`, `get_project`, `delete_project` y `move_project_root`. El nombre de un proyecto pasa a ser único
  en todo el registro.
- **L-12**: las cinco `*_config_from_store_or_env` de `doc_organize.ai` y `ai/_secrets.py` (`SecretValueReader`). Se
  quedan las `*_config_from_env` y los clientes, que reciben el `*Config` del consumidor.
- De `core`, lo que solo usaban la web y `auth/`: los modelos `Tenant`, `Role`, `User`, `Session`, `SecurityConfig` y
  `DirectoryListing`; `AuthError` y sus subclases (`Tenant*`, `User*`, `Role*`, `InstanceAdminRequiredError`,
  `SecretsCipherError`, `SecretsEncryptionNotConfiguredError`); y las constantes de autenticación
  (`DEFAULT_AUTH_DB_NAME`, `DEFAULT_TENANT_ID`, `SCRYPT_*`, `SESSION_LIFETIME_HOURS`, `LOGIN_*`, `USERNAME_*`,
  `ROLE_NAME_*`, `TENANT_ID_MAX_LENGTH`, `DEFAULT_ADMIN_*`). Ninguno estaba en `doc_organize.__all__`.
- Lo obsoleto desde 0.13.0: `MkDocsGenerator` (alias de `SiteGenerator`; sale de `doc_organize.__all__` y de
  `doc_organize.context`) y las propiedades `Context.mkdocs_generated` / `mkdocs_site_built`. Un `context.json`
  antiguo con esas claves se sigue leyendo (`site_generated` / `site_built`).
- Tests de lo retirado: los 16 `tests/unit/test_web_*`, `tests/unit/auth/` y los de `AuthStore`,
  `InstanceSecretsStore`, `secrets_cipher`, cambio de contraseña, `app.state` y configuración de IA por familias.

### Changed

- Un `projects.json` o `context.json` de 0.14.0 con `tenant_id` se sigue leyendo: el campo se ignora, y desaparece de
  `projects.json` en la siguiente escritura del registro. Si un registro antiguo tenía el mismo nombre en dos tenants
  (solo ocurre si se usó `tenant create` en la web integrada), `get_project` devuelve el primero y `project list`
  muestra los dos; renombra o elimina uno de ellos.
- `ProjectAlreadyExistsError` ya no menciona el tenant en su mensaje.
- La documentación de la web integrada (acceso, panel de administración, configuración de IA, rutas HTTP,
  `web/STATE.md` y `docs/adr/ADR-004-GIL-Thread-Safety.md`) pasa a `docs/historico/` con una nota, sin borrarse.

### Added

- `tests/unit/test_library_architecture.py`: falla si `src/` vuelve a importar FastAPI, Starlette, uvicorn, Jinja2 o
  `python-multipart`, si reaparecen `doc_organize.web` o `doc_organize.auth`, si `_EXPORTS` expone algo de web, auth o
  tenants, o si `pyproject.toml` vuelve a declarar el extra `[web]` o esas dependencias.

### Migración desde 0.14.0

- Interfaz web, usuarios, tenants y roles: [doc_organize_web](https://github.com/fmanza/doc_organize_web).
- `registry.create_project(name, base, tenant_id=...)` → `registry.create_project(name, base)` (ídem en el resto de
  métodos de `ProjectRegistry`); `project.tenant_id` ya no existe.
- `*_config_from_store_or_env(store)` → construir el `*Config` en el consumidor, o `*_config_from_env()`.
- `MkDocsGenerator()` → `SiteGenerator()`; `context.mkdocs_generated` / `mkdocs_site_built` → `site_generated` / `site_built`.

## [0.14.0] - 2026-11-03

Sub-fase B de `ContextBuilder` y clientes de `doc_organize.ai` seguros para consumidores multiusuario (peticiones de
la Fase 8 de doc_organize_web, tareas L-3a…L-3e; cierra los huecos G33–G36) e integridad del contexto (L-8d…L-8f;
cierra G30–G32), y deprecación de la web integrada (L-10). Aditivo y compatible: sin los
parámetros nuevos, todo se comporta igual que en 0.13.0 salvo lo indicado en «Changed», «Deprecated» y «Security».

### Added

- **L-3a (G33)**: `ContextBuilder.build(ai_max_failures=)`: detiene la Sub-fase B tras N errores de conexión
  seguidos (una respuesta del servidor, aunque sea un 5xx, corta la racha). `Context.ai_classification_stopped`
  (`"auth"`, `"connection"`, `"budget"` o `None`) y el alias de tipo `AiClassificationStopReason` en `core.models`.
- **L-3b (G34)**: `retries` (por defecto `0`) y `retry_backoff_s` (por defecto `0.5`) en las cinco `*Config` de
  `doc_organize.ai` y en `AiHttpClientBase`. Solo se reintenta un timeout o un error de transporte, con espera
  creciente (`backoff · 2^n`); nunca una respuesta HTTP (ni 4xx ni 5xx).
- **L-3b (G34)**: `ContextBuilder.build(ai_max_documents=)`, tope de documentos enviados a la IA por construcción; al
  alcanzarlo con documentos pendientes, para con `"budget"`.
- **L-3c (G35)**: recuentos de la Sub-fase B en `Context`: `ai_documents_sent`, `ai_documents_classified` y
  `ai_documents_failed` (por defecto `0`), con `sent = classified + failed + enviados sin asignación`. Un
  `context.json` antiguo se sigue leyendo.
- **L-8d (G30)**: `resolve_organized_paths(domain, project_root)` (exportada en `doc_organize`), con la ruta del `.md`
  copiado de cada documento relativa a la carpeta reorganizada, y `DomainDocument.organized_path`, que rellenan
  `ContextBuilder.build()` y `Reorganizer.reorganize()` (solo informativo: nunca se usa el valor leído de disco).
- **L-3d (G36)**: `select_document_sample(roots=)`: la carpeta de cada documento de la muestra es relativa a la raíz
  escaneada que lo contiene y nunca muestra nombres por encima de ella (mismo criterio que
  `json_source_path="relative"`, G23).

### Changed

- **L-3a (G33)**: un error de autenticación (401/403) detiene la Sub-fase B en el acto, en los dos modos (con la clave
  rechazada se hace exactamente 1 petición en toda la construcción). Antes se intentaba cada documento pendiente y
  cada uno fallaba igual. Los documentos pendientes de una Sub-fase B detenida no se leen ni se envían, pero siguen
  emitiendo su evento de progreso, y el contexto se construye y persiste igualmente.
- **L-8d (G30)**: dos documentos del mismo dominio y tipo con el mismo `stem` sin distinguir mayúsculas (en SMB «Acta» y
  «acta» son la misma carpeta) ya no comparten carpeta: todos van a `<stem>-<8 hex>/` (SHA-256 del `.md` relativo a la
  raíz del proyecto; determinista). Antes el último sobrescribía a los demás. Sin colisiones, las rutas no cambian.
- **L-8f (G32)**: `Context` valida `output_folder_name` con `validate_output_folder_name`. `Context(...)` con un nombre
  no válido da `ValidationError`, y `ContextRegistry.load_context` rechaza con `ContextError` un `context.json` con
  `..`, una ruta absoluta o un nombre reservado (p. ej. `Conversión`) en vez de usarlo para copiar y borrar.
  `Reorganizer.reorganize`/`delete_output` y `SiteGenerator.generate` lo vuelven a validar (`InvalidPathError`).
- CI: `ruff` admite hasta la 0.17 (`<0.18`, antes `<0.16`). Corregidos los 14 avisos de las reglas que activa por
  defecto (deuda de la 0.9.3): `__all__` ordenados, `noqa` sin uso, variables desempaquetadas sin usar en tests,
  `with`/`if` anidados unidos en `web/routes/context.py` y `web/routes/duplicates.py`, `ClassVar` en
  `_ProgressTracker._PHASES`, variable de bucle que ocultaba el parámetro `conversion_status` en
  `CacheManager.load_cache_page` y `noqa: PLE0604` justificado en `doc_organize.__all__`. Sin cambios funcionales.

### Deprecated

- **L-10**: la web integrada, porque doc_organize_web 0.9.0 cubre la paridad funcional (salvo roles y tenants, su
  Fase 9, que la web integrada sigue cubriendo hasta entonces). Se retira en 1.0.0 (L-11); hasta entonces sigue
  congelada (solo hotfix) y funciona igual:
  - `import doc_organize.web` y `import doc_organize.auth` (también sus submódulos) emiten `DeprecationWarning`,
    atribuido a la línea que importa (no a doc_organize ni a la maquinaria de import).
  - Los subcomandos `web`, `tenant` y `user` del CLI escriben el aviso una vez por stderr (nunca por stdout) con el
    enlace a https://github.com/fmanza/doc_organize_web; su ayuda lleva «[obsoleto]». Mismo código de salida.
  - `doc_organize.main` ya no importa `doc_organize.auth` al cargarse: `scan`, `project`, `deduplicate` y `export` no
    avisan ni cargan la web.
  - Se quedan en la librería `core/`, `utils/`, `validators/`, `scanner/`, `converter/`, `dedup/`, `cache/`, `scan/`,
    `context/`, `ai/`, `projects/`, `export/` y el CLI de librería.

### Security

- **L-3e**: `LiteLLMUsageClient.get_usage()` ya no pone la virtual key propia en la query (`/key/info?key=...`):
  `httpx` escribe cada URL en INFO y la clave acababa en los logs. Sin `key`, o con la misma clave del Bearer, no se
  envía `key=` (LiteLLM consulta entonces la clave del header; verificado en `info_key_fn`:
  `key = key or user_api_key_dict.api_key`). Con otra clave se sigue enviando, con el riesgo documentado (mejor pasar
  su hash SHA-256, que LiteLLM acepta). Los avisos de reintento no llevan la URL.
- **L-8e (G31)**: `context.json`, `index.json`, `DOMAIN.md`, `index.md`, `zensical.toml` y `taxonomy_manifest.md` se
  escriben en un temporal con nombre aleatorio creado en exclusiva (`tempfile.mkstemp`: `O_CREAT | O_EXCL` y
  `O_NOFOLLOW` donde existe) y luego `os.replace`, nunca con `write_text` sobre un `<fichero>.tmp` de nombre fijo: un
  enlace puesto con ese nombre desde el recurso de red ya no desvía la escritura. El fichero conserva sus permisos.

### Firmas finales

Todo lo nuevo o cambiado en la API pública de 0.14.0, tal como queda en el tag `v0.14.0` (verificado con
`inspect.signature` y `model_fields`). Los parámetros nuevos son *keyword-only* y con valor por defecto.

```python
# doc_organize.ContextBuilder (L-3a, L-3b)
async def build(
    self,
    project: Project,
    documents: list[ConversionResult],
    candidate_domains: list[str] | None = None,
    threshold: float = 0.5,
    ai_classification_enabled: bool = False,
    ai_classification_client: DomainClassificationClient | None = None,
    output_folder_name: str = "organizado",
    on_ai_progress: Callable[[int, int, str], Awaitable[None]] | None = None,
    taxonomy_manifest: TaxonomyManifest | None = None,
    taxonomy_classification_client: TaxonomyClassificationClient | None = None,
    taxonomy_template_name: str | None = None,
    *,
    on_progress: ProgressCallback | None = None,
    cancel_token: CancelToken | None = None,
    ai_max_failures: int | None = None,   # nuevo; < 1 -> ValueError
    ai_max_documents: int | None = None,  # nuevo; < 0 -> ValueError
) -> Context

# doc_organize.core.models (L-3a, L-3c)
AiClassificationStopReason = Literal["auth", "connection", "budget"]

class Context(BaseModel):
    ...
    output_folder_name: str = "organizado"  # ahora validado con validate_output_folder_name (L-8f)
    ai_classification_stopped: AiClassificationStopReason | None = None
    ai_documents_sent: int = 0        # ge=0
    ai_documents_classified: int = 0  # ge=0
    ai_documents_failed: int = 0      # ge=0

class DomainDocument(BaseModel):
    ...
    organized_path: str | None = None  # L-8d: .md copiado, POSIX, relativo a la carpeta reorganizada

# L-3b: en LiteLLMClassificationConfig, LiteLLMTaxonomyClassificationConfig, LiteLLMTaxonomyManifestDraftConfig,
# LiteLLMUsageConfig y GitHubCopilotUsageConfig
    retries: int = 0              # ge=0; solo timeout / error de transporte, nunca HTTP
    retry_backoff_s: float = 0.5  # ge=0.0; espera retry_backoff_s * 2**n

# doc_organize.context.select_document_sample (L-3d)
async def select_document_sample(
    documents: list[ConversionResult], sample_size: int, *, roots: Sequence[str] | None = None
) -> list[SampledDocument]

# doc_organize.ai.LiteLLMUsageClient (L-3e; firma sin cambios, comportamiento nuevo)
async def get_usage(self, *, key: str | None = None) -> UsageSnapshot  # sin ?key= si key es None o la propia

# doc_organize.resolve_organized_paths / doc_organize.context.resolve_organized_paths (L-8d)
def resolve_organized_paths(domain: Domain, project_root: str | Path) -> list[str]
```

Sin cambios de firma, pero con comportamiento nuevo: `Reorganizer.reorganize`, `Reorganizer.delete_output` y
`SiteGenerator.generate` (validan `output_folder_name`, `InvalidPathError`; rutas desde `resolve_organized_paths`),
`ContextRegistry.load_context` (`ContextError` si `output_folder_name` no es válido) y `save_taxonomy_manifest`
(escritura atómica sin seguir enlaces, L-8e).

Obsoletos (L-10, se retiran en 1.0.0): `doc_organize.web`, `doc_organize.auth` y los subcomandos `web`, `tenant` y
`user` del CLI.

## [0.13.0] - 2026-11-02

Contexto y taxonomías para la Fase 7 de doc_organize_web (tareas L-8 y L-8a…L-8c de su plan; cierra los huecos G10 y
G27–G29). Aditivo y compatible salvo lo indicado en «Changed», «Deprecated» y «Security».

> **Nota de versión**: el plan de doc_organize_web reservaba la 0.13.0 para L-10 (deprecación de la web integrada);
> esa tarea pasa a la siguiente MINOR.

### Added

- **L-8 (G10)**: `SiteGenerator` (sitio de contexto con Zensical) y `SiteResult`. `generate` escribe `zensical.toml`
  en la raíz del proyecto y `index.md` en la carpeta reorganizada y, con `build=True` (por defecto), ejecuta
  `zensical build` (el del mismo entorno o el del `PATH`) hacia `site_dir`, con `timeout` opcional. `build_site`
  construye sobre una configuración ya escrita y `delete_site` borra la configuración (también un `mkdocs.yml`
  anterior), el sitio y la caché de Zensical (`.cache/`).
- **L-8 (G10)**: `SiteBuildError` (subclase de `DocOrganizeError`) si falta `zensical`, el build termina con error (con
  su salida) o se pasa de tiempo: nunca un sitio sin construir en silencio.
- **L-8 (G10)**: `Context.site_generated` y `Context.site_built`; un `context.json` antiguo (`mkdocs_generated`,
  `mkdocs_site_built`) se sigue leyendo.
- **L-8a (G27)**: `Context.reorganize_failed_documents` y `Reorganizer.reorganize(on_document_failed=)`
  (`index, total, source_path, error`); `ContextBuildEventType.DOCUMENT_FAILED` (`"document_failed"`) para quien
  retransmita el progreso. `Reorganizer.check_output_root`.
- **L-8a (G27)**: `copy_file_nofollow`, `copy_tree_nofollow` y `ensure_tree_has_no_symlinks` en
  `doc_organize.utils.path_utils`, con el mismo criterio que la deduplicación de 0.12.1 (cuyos helpers comparten).
- **L-8b (G28)**: rutas del contexto en `ProjectLayout`: `context_file`, `domains_dir`, `taxonomy_manifest_file`,
  `site_config_file`, `site_cache_dir`, `legacy_mkdocs_config_file` y `reorganized_dir(output_folder_name)` (validado).
  `RESERVED_OUTPUT_FOLDER_NAMES` (nombres que no puede usar `output_folder_name`: `Conversión`, `duplicados`,
  `errores_escaneo`, `historial_escaneo`, `domains`, `site`, `.cache` y los ficheros de la raíz) y
  `validate_output_folder_name`, que compara sin mayúsculas, sin puntos ni espacios finales y en NFC. Constantes
  nuevas en `core.constants` (`CONTEXT_FILE_NAME`, `DOMAINS_FOLDER_NAME`, `TAXONOMY_MANIFEST_FILE_NAME`,
  `SITE_FOLDER_NAME`, `SITE_CONFIG_FILE_NAME`, `SITE_CACHE_FOLDER_NAME`, `LEGACY_MKDOCS_CONFIG_NAME`).
- **L-8c (G29)**: plantillas de taxonomía como texto en `doc_organize.context.taxonomy_templates`:
  `parse_taxonomy_template` (mismos errores que al cargar un fichero), `render_taxonomy_template` (ida y vuelta
  estable: `parse(render(m)) == m`, también con saltos de línea o `---` en los textos), `list_builtin_templates` y
  `load_builtin_template`, sin carpeta de usuario ni `Path.home()`. `TaxonomyTemplateRegistry` las usa por dentro.
- API pública: `SiteGenerator`, `SiteResult`, `SiteBuildError`, `parse_taxonomy_template`, `render_taxonomy_template`,
  `list_builtin_templates`, `load_builtin_template`, `RESERVED_OUTPUT_FOLDER_NAMES` y `validate_output_folder_name`.

### Changed

- **L-8**: el extra `site` instala `zensical>=0.0.71` en lugar de `mkdocs`. La configuración generada no añade
  JavaScript propio, `extra_javascript`, plugins ni extensiones Markdown; fija `theme.language = "es"` y
  `theme.font = false` (sin Google Fonts). Un contexto con `mkdocs.yml` pasa a Zensical al reconstruirlo (se borra
  `mkdocs.yml`).
- **L-8**: `MkDocsGenerator` es ahora la misma clase que `SiteGenerator` (ver «Deprecated»): su `generate` devuelve
  `SiteResult` en lugar de `(ruta, site_built)` y lanza `SiteBuildError` en lugar de devolver `site_built=False`.
- **L-8a**: `Reorganizer` captura los `OSError` de cada documento (antes uno abortaba toda la reorganización): ese
  documento falla, se borra lo copiado de él y el resto sigue.
- **L-8b**: la web integrada usa `ProjectLayout`, `RESERVED_OUTPUT_FOLDER_NAMES` y `validate_output_folder_name` en
  lugar de sus copias; además de lo que ya rechazaba, rechaza `.cache` y los nombres de ficheros de la raíz. Construye
  el sitio con `SiteGenerator` (si no puede, `site_built=False` y aviso en el log, como antes), avisa de los documentos
  que no se pudieron copiar y su respuesta JSON añade `site_generated`, `site_built` y `reorganize_failed_count`
  (conserva `mkdocs_generated`/`mkdocs_site_built`).
- **L-8c**: `TaxonomyTemplateRegistry(templates_dir=None)` calcula `~/.doc_organize/taxonomy_templates` al crearse,
  no al importar el módulo. Al guardar, un `title`/`description` vacío (`""`) se escribe en lugar de omitirse, para
  que se relea igual.

### Deprecated

- `MkDocsGenerator` (alias de `SiteGenerator`, `DeprecationWarning` al crearlo) y `Context.mkdocs_generated` /
  `Context.mkdocs_site_built` (propiedades que leen y escriben `site_generated` / `site_built`). Se retiran en 1.0.0.

### Security

- **L-8a (G27)**: `Reorganizer` ya no sigue enlaces simbólicos (ni uniones de Windows). Antes copiaba con
  `shutil.copy2`/`copytree`, que siguen los enlaces: un original, `.md`, `.json` o carpeta de imágenes cambiado por un
  enlace copiaba a la carpeta reorganizada (y al sitio) un fichero de fuera. Ahora todo se comprueba con `lstat` antes
  de copiar y, en POSIX, se copia con descriptores abiertos tramo a tramo con `O_NOFOLLOW`, así que un enlace puesto
  entre la comprobación y la copia tampoco se sigue. La carpeta reorganizada no puede ser ni pasar por un enlace
  (`InvalidPathError` antes de tocar nada); un enlace en el lugar de la carpeta de un dominio se quita sin tocar su
  destino. Consecuencia, como en 0.12.1: una ruta que pase por un enlace del sistema (p. ej. `/tmp` en macOS) falla.
- **L-8**: Zensical inserta sin escapar las etiquetas del `nav` y `site_name`, y el tema pone el título de cada página
  en `<title>` deshaciendo las entidades: un título de documento como `</title><script>…</script>` se ejecutaba (con
  MkDocs, igual en el `nav`). `SiteGenerator` escribe esos textos sin `<`/`>` (pasan a `＜`/`＞`) y con `&` y comillas
  escapados. El HTML incrustado en el propio Markdown sigue llegando tal cual al sitio (comportamiento por defecto de
  Zensical, como con MkDocs): quien sirva el sitio debe aislarlo (otro origen o `Content-Security-Policy`); ver
  «Seguridad del sitio» en `docs/functional/context.md`.
- **L-8c**: `TaxonomyTemplateRegistry.delete_template` valida el nombre como el resto de métodos: antes
  `delete_template("../x")` borraba `<templates_dir>/../x.md`.

### Firmas finales (para doc_organize_web)

```python
# doc_organize (y doc_organize.context)
@dataclass(frozen=True)
class SiteResult:
    config_path: Path
    index_path: Path
    site_dir: Path
    site_built: bool

class SiteGenerator:
    async def generate(self, project: Project, context: Context, *, build: bool = True,
                       site_dir: Path | None = None, timeout: float | None = None) -> SiteResult
    async def build_site(self, project: Project, *, timeout: float | None = None) -> None
    async def delete_site(self, project: Project, *, site_dir: Path | None = None) -> None

class SiteBuildError(DocOrganizeError): ...
class MkDocsGenerator(SiteGenerator): ...   # obsoleto, DeprecationWarning; se retira en 1.0.0

class Reorganizer:
    async def reorganize(self, project: Project, context: Context,
                         on_document_copied: Callable[[int, int, str], Awaitable[None]] | None = None, *,
                         on_document_failed: Callable[[int, int, str, str], Awaitable[None]] | None = None) -> Path
    @staticmethod
    def check_output_root(output_root: Path) -> None          # InvalidPathError si es o pasa por un enlace

class Context(BaseModel):
    reorganize_failed_documents: list[str]
    site_generated: bool                                       # acepta también "mkdocs_generated"
    site_built: bool                                           # acepta también "mkdocs_site_built"
    mkdocs_generated: bool    # propiedad obsoleta
    mkdocs_site_built: bool   # propiedad obsoleta

# doc_organize.projects.layout (y doc_organize.*)
RESERVED_OUTPUT_FOLDER_NAMES: frozenset[str]
def validate_output_folder_name(name: str) -> str               # InvalidPathError
class ProjectLayout:
    context_file: Path; domains_dir: Path; taxonomy_manifest_file: Path        # propiedades
    site_dir: Path; site_config_file: Path; site_cache_dir: Path; legacy_mkdocs_config_file: Path
    def reorganized_dir(self, output_folder_name: str) -> Path  # InvalidPathError

# doc_organize.context.taxonomy_templates (y doc_organize.context, doc_organize)
def parse_taxonomy_template(text: str, *, source: str = "<texto>") -> TaxonomyManifest   # TaxonomyTemplateError
def render_taxonomy_template(manifest: TaxonomyManifest, body: str = "") -> str
def list_builtin_templates() -> list[TaxonomyTemplateSummary]
def load_builtin_template(name: str) -> TaxonomyManifest                                  # TaxonomyTemplateError

# doc_organize.utils.path_utils
def copy_file_nofollow(source: str | Path, target: str | Path, *, overwrite: bool = False) -> None
def copy_tree_nofollow(source_dir: str | Path, target_dir: str | Path) -> None
def ensure_tree_has_no_symlinks(path: str | Path) -> Path

# doc_organize.core.models
class ContextBuildEventType(str, Enum):
    DOCUMENT_FAILED = "document_failed"                        # data: index, total, path, error
```

## [0.12.1] - 2026-11-02

Ruta relativa en `duplicados/` y movimiento sin seguir enlaces simbólicos para doc_organize_web (tarea L-11a de su
plan; cierra los huecos G24 y G26). Aditivo y compatible, salvo que ya no se mueven ni copian rutas que pasen por un
enlace (ver «Security»).

### Added

- **L-11a (G24)**: parámetro opcional `relative_to` en `DeduplicationManager.resolve_duplicates`, `move_group` y
  `_move_to_duplicates`, y en `ScanCommand.deduplicate_streaming`. Si se indica, cada descartado se lleva a
  `duplicates_dir / <ruta relativa a relative_to>` (`duplicados/2024/a.pdf`) en lugar de replicar su ruta absoluta
  (`duplicados/mnt/origen/2024/a.pdf`), que revelaba rutas del servidor. Un documento que no cuelgue de
  `relative_to` (comparando rutas resueltas) es un fallo por fichero (`OSError` → `failed_paths`), nunca se escribe
  fuera de `duplicates_dir`. Se mantiene todo lo demás: nunca se sobrescribe (sufijo de hash; colisión doble =
  fallo por fichero), `copy` y `report_only`.
- `resolve_duplicates`/`deduplicate_streaming` solo pasan `mode`/`relative_to` a `move_group` (y este a
  `_move_to_duplicates`) cuando no tienen el valor por defecto: quien sustituya esos métodos con la firma anterior
  sigue funcionando.
- `doc_organize.utils.path_utils.ensure_no_symlinks(path) -> Path`: ruta absoluta normalizada sin resolver; `OSError`
  (`ELOOP`) si algún tramo existente es un enlace simbólico o una unión de Windows.
- `DeduplicationManager.check_duplicates_dir(duplicates_dir)`: `InvalidPathError` si es (o pasa por) un enlace.

### Security

- **L-11a (G26)**: `_move_to_duplicates` ya no sigue enlaces simbólicos. Antes resolvía el origen con `resolve()` y
  `safe_path_join` resolvía la base de `duplicates_dir`: un enlace cambiado justo antes de mover hacía que se moviera o
  copiara un fichero de fuera (p. ej. secretos). Ahora ninguna de las dos rutas se resuelve; si algún tramo del origen,
  de `duplicates_dir` o de la carpeta destino es un enlace, ese fichero falla (`OSError` → `failed_paths`) sin tocar el
  destino del enlace. En POSIX el origen y el destino se abren tramo a tramo con `O_NOFOLLOW` y se mueven con `rename`
  relativo a esos descriptores (o se copian con `O_NOFOLLOW`/`O_EXCL` si están en sistemas de ficheros distintos), así
  que un enlace puesto entre la comprobación y el movimiento tampoco se sigue; en Windows (sin `dir_fd`) queda la
  comprobación con `lstat` de cada tramo. `resolve_duplicates` y `deduplicate_streaming` rechazan de entrada un
  `duplicates_dir` enlazado (`InvalidPathError`) antes de escribir nada.
- Consecuencia: una ruta de origen o de duplicados que pase por un enlace del sistema (p. ej. `/tmp` → `/private/tmp`
  en macOS) falla. El llamador debe pasar rutas reales (resueltas una vez, en la configuración).

```python
# doc_organize.DeduplicationManager
async def resolve_duplicates(self, groups: list[DuplicateGroup], duplicates_dir: Path,
                             started_at: datetime | None = None, *, report_dir: Path | None = None,
                             mode: DedupMode = "move", relative_to: Path | None = None) -> DeduplicationReport
async def move_group(self, group: DuplicateGroup, duplicates_dir: Path, *, mode: DedupMode = "move",
                     relative_to: Path | None = None) -> tuple[int, int, list[str]]
async def _move_to_duplicates(self, source: Path, duplicates_dir: Path, sha256_hash: str, *, copy: bool = False,
                              relative_to: Path | None = None) -> None
@staticmethod
def check_duplicates_dir(duplicates_dir: Path) -> None        # InvalidPathError si hay un enlace

# doc_organize.utils.path_utils
def ensure_no_symlinks(path: str | Path) -> Path               # OSError (ELOOP) si hay un enlace

# doc_organize.ScanCommand
def deduplicate_streaming(self, paths: list[str], duplicates_dir: Path, folders_json: Path, *,
                          report_dir: Path | None = None, mode: DedupMode = "move",
                          relative_to: Path | None = None, on_progress: ProgressCallback | None = None,
                          cancel_token: CancelToken | None = None) -> AsyncIterator[DedupEvent]
```

## [0.12.0] - 2026-11-02

Robustez del escaneo y API de lectura para doc_organize_web (tareas L-10a…L-10e de su plan; cierra los huecos
G16–G23). Todo es aditivo salvo el valor por defecto de `source_path` en el JSON de cada documento (ver «Changed»).

> **Nota de versión**: el plan de doc_organize_web reservaba la 0.12.0 para L-10 (deprecación de la web integrada);
> esa tarea pasa a la siguiente MINOR.

### Added

- **L-10a (G16)**: `ScanCommand.run_streaming` guarda la caché durante la conversión cada
  `ScanOptions.cache_save_every` documentos (20) o `cache_save_seconds` segundos (30; 0 desactiva cada disparo), y
  también si el escaneo termina por una excepción, se cierra el generador o se cancela la tarea, antes de propagar el
  error. Un fallo o un `kill` a mitad solo pierde lo convertido desde el último guardado. En la fase de OCR los
  resultados llegan al final del lote: un corte en esa fase deja esos documentos en `ocr_pending`.
- **L-10b (G17)**: carpeta de modelos de Docling (`ScanOptions.artifacts_path`, `DocumentConverter(artifacts_path=)`,
  `OCRScheduler(artifacts_path=)`) y `allow_model_downloads=False` para prohibir descargas: hace falta una carpeta (la
  indicada o `DOCLING_ARTIFACTS_PATH`) y, si falta un modelo, `ModelsNotAvailableError` (subclase de
  `ConversionError`) en lugar de descargarlo o de marcar cada documento como error. Solo se comprueba con
  PDF/imagen, los únicos formatos que usan modelos.
- **L-10c (G18)**: `ScanOptions.root_name_in_output` (y `include_root_name=` en `resolve_output_paths`,
  `convert_document` y `process_with_ocr`) antepone el nombre de la carpeta escaneada a la ruta de salida:
  `2024/x/a.pdf` y `2025/x/a.pdf` van a `2024/x/a.md` y `2025/x/a.md`. Por defecto no cambia nada; con varias raíces y
  la opción desactivada, el evento `SCANNED` avisa (`warnings`) de los documentos que irían a la misma salida.
- **L-10d (G19)**: `ScanResult.unreadable_dirs` con las carpetas que no se pudieron listar (también en los `warnings`
  de `SCANNED`). Con `force`, los documentos de esas carpetas no se tratan como huérfanos: no se borran sus salidas y
  se conservan sus entradas de caché. Al cancelar un escaneo se escribe el `ScanErrorReport` de lo procesado en
  `error_log_path`.
- **L-10e (G20–G22)**: `resolve_output_paths`, `resolve_images_dir` y `relative_source_path` en
  `doc_organize.projects.layout` (no importa Docling); `DocumentConverter.resolve_output_paths`/`resolve_images_dir`
  quedan como alias. `CacheManager(db_path, read_only=True)` (URI `mode=ro`, sin `PRAGMA WAL`, `CREATE` ni `ALTER`;
  `CacheNotFoundError` si no existe; `CacheError` si el esquema no es el actual o si se intenta escribir).
  `count_entries`/`load_cache_page` con `relative_to=` (solo entradas bajo esa raíz y `search` sobre la ruta relativa)
  y `conversion_status=`.
- API pública: `resolve_output_paths`, `resolve_images_dir`, `relative_source_path`, `CacheNotFoundError`,
  `ModelsNotAvailableError`, `ConversionStatus` y `DocumentStatus`.

### Changed

- **L-10e (G23)**: el `source_path` del `.json` de cada documento convertido pasa a ser la ruta **relativa a la
  carpeta escaneada**, en formato POSIX (`Informes/a.pdf`; solo el nombre si no cuelga de ninguna raíz), en lugar de
  la ruta absoluta del servidor, que llegaba a quien abría el JSON o el ZIP del proyecto. `json_source_path="absolute"`
  (`ScanOptions`, `convert_document`, `process_with_ocr`) recupera lo anterior. Los JSON ya generados no cambian hasta
  reconvertirse.
- `ScanCommand` pasa los argumentos nuevos a `convert_document`/`process_with_ocr` solo cuando no tienen el valor por
  defecto (quien sustituya esos métodos con la firma anterior sigue funcionando).

### Firmas finales (para doc_organize_web)

```python
# doc_organize.projects.layout (y doc_organize.*)
def resolve_output_paths(full_path: str, output_dir: Path, scan_roots: Sequence[str] = (), *,
                         include_root_name: bool = False) -> tuple[Path, Path]
def resolve_images_dir(markdown_path: Path) -> Path
def relative_source_path(full_path: str, scan_roots: Sequence[str] = ()) -> str

# doc_organize.ScanOptions (campos nuevos)
cache_save_every: int = 20            # ge=0
cache_save_seconds: float = 30.0      # ge=0
artifacts_path: Path | None = None
allow_model_downloads: bool = True
root_name_in_output: bool = False
json_source_path: Literal["relative", "absolute"] = "relative"

# doc_organize.ScanResult (campo nuevo)
unreadable_dirs: list[str] = []

# doc_organize.DocumentConverter / OCRScheduler
DocumentConverter(*, artifacts_path: Path | str | None = None, allow_model_downloads: bool = True)
DocumentConverter.convert_document(source_doc, output_dir, use_ocr=False, use_gpu=False, extract_images=False,
                                   use_picture_description=False, scan_roots=(), *, include_root_name: bool = False,
                                   json_source_path: Literal["relative", "absolute"] = "relative") -> ConversionResult
OCRScheduler(*, artifacts_path: Path | str | None = None, allow_model_downloads: bool = True)
OCRScheduler.process_with_ocr(docs, output_dir, use_gpu=False, extract_images=False, use_picture_description=False,
                              scan_roots=(), progress_callback=None, *, include_root_name: bool = False,
                              json_source_path: Literal["relative", "absolute"] = "relative") -> list[ConversionResult]

# doc_organize.CacheManager
CacheManager(db_path: str | Path = "cache.db", *, read_only: bool = False)
async def count_entries(search: str | None = None, *, relative_to: str | Path | None = None,
                        conversion_status: ConversionStatus | str | None = None) -> int
async def load_cache_page(limit: int, offset: int, search: str | None = None, *,
                          relative_to: str | Path | None = None,
                          conversion_status: ConversionStatus | str | None = None) -> list[CacheEntry]

# doc_organize (errores)
class CacheNotFoundError(CacheError)
class ModelsNotAvailableError(ConversionError)
```

## [0.11.0] - 2026-11-01

Exportación de proyectos como API pública (tarea L-7 del plan de doc_organize_web; cierra el hueco G8). Cambios
aditivos: la web integrada y el CLI existente se comportan igual.

### Added

- `doc_organize.export`: `write_project_zip` (ZIP en *streaming* a una ruta o fichero binario, copia por bloques de
  1 MiB, sin temporales), `preview_project_zip` (ficheros y bytes, igual que el ZIP) y `ExportStats`;
  `write_cache_xlsx` y `write_scan_errors_xlsx` (`openpyxl` en modo `write_only`, fórmulas neutralizadas);
  `load_cache_entries` (varias `cache.db`) y `load_scan_error_history` (varios históricos). Rutas explícitas
  (`ProjectLayout` o `conversion_dir`/`dedup_report`), `on_progress` y `cancel_token`; al cancelar se borra el
  fichero parcial y se lanza `OperationCancelledError`. Nombres incluidos en `doc_organize.__all__`.
- CLI: `doc_organize export zip | cache-xlsx | errors-xlsx` con `--project` o `--output-root`/`--state-root`,
  `--cache-file` y `--errors-log` repetibles y `zip --preview`.
- Extra `export` (`openpyxl>=3.1`), importado al escribir un Excel; si falta, `MissingDependencyError` (nuevo en
  `core/exceptions.py` y en la API pública, con `package` y `extra`).
- `ProgressEvent.operation="export"` y fase `"export"`.
- Documentación: `docs/functional/export.md`, `docs/api/export.md`; `docs/api/publica.md` con el grupo «Exportación».

### Changed

- `web/routes/downloads.py` usa `doc_organize.export` (mismas rutas, nombres de fichero y contenido). Diferencias
  menores: `cache_export.json` lleva las entradas ordenadas por `file_path` y `export_timestamp` siempre con
  microsegundos; exportar un proyecto nunca escaneado ya no crea un `cache.db` vacío; la cabecera del Excel sigue en
  negrita pero sin borde; los ficheros enlace de `Conversión/` ya no entran en el ZIP; los caracteres de control de
  los mensajes de error se quitan en vez de hacer fallar el Excel.
- CI: `tests.yml` corre en los PR y en `develop`, no en cada push ni en `main`. PR fusionados con squash y release por
  fast-forward de `main` al commit de `develop` con el CI en verde (`SHARED_INSTRUCTIONS.md` § «Ramas y publicación»).
- `dev` incluye `openpyxl` y `types-openpyxl`; se retira el *override* de mypy para `pandas`, que ya no se importa en
  `src/`.

## [0.10.0] - 2026-10-31

API pública estable para consumidores externos (separación librería/web, tareas L-1…L-6 y L-13b del plan de
doc_organize_web; cierra los huecos G1–G7, G13 y G15 de ese repositorio). Todo cambio es aditivo o con
`DeprecationWarning`: el CLI y la web integrada se comportan igual que en la 0.9.3.

### Added

- `__init__.py`: API pública con importación diferida (PEP 562, `_EXPORTS` + `__getattr__`); `import doc_organize`
  ya no carga Docling (de ~49 s y ~4 300 módulos a ~0,5 s y ~300). Marcador `py.typed` y `docs/api/publica.md`
  (L-1, G1, G15).
- Extra `site` (`mkdocs`) para el sitio navegable del contexto de un proyecto, que antes dependía del extra
  `docs`.
- `ScanOptions` (`core/models.py`) y parámetro `options=` en `ScanCommand.run`/`run_streaming` como alternativa a
  los indicadores posicionales (G13).
- `ai/_secrets.py`: Protocol `SecretValueReader`; los clientes de IA ya no dependen de `auth` (L-3, G3).
- `projects/layout.py`: `ProjectLayout` con `output_root` (Markdown, duplicados, sitio) y `state_root` (caché,
  carpetas, logs, informes de deduplicación) separables; `report_dir=` en `finalize_report`, `resolve_duplicates` y
  `deduplicate_streaming`; `ScannedFoldersStore(registry_path=)` y `ProjectHistoryCleaner.clear(state_root=)`
  (L-4, L-5, G4, G5).
- `core/progress.py`: `CancelToken`, `ProgressEvent`, `ProgressCallback`; `OperationCancelledError`; tipo de evento
  `CANCELLED` en escaneo, deduplicación y contexto. La cancelación es cooperativa y conserva en caché lo ya
  convertido; `ContextBuilder.build` acepta `on_progress` y `cancel_token` (L-2, G2).
- Eventos con esquema versionado: base `VersionedEvent` (`schema_version`, `to_dict()`), `EVENT_SCHEMA_VERSION = 1`
  y test de contrato (L-6b, G7).
- Deduplicación en dos pasos: `group_id` estable entre ejecuciones (`DeduplicationManager.stable_group_id`) y
  `DedupMode` (`move` por defecto, `copy`, `report_only`) en `move_group`, `resolve_duplicates`,
  `finalize_report` y `deduplicate_streaming`; `DeduplicationReport.mode` (L-6, G6).
- `.github/workflows/release.yml`: al publicar un tag `v*` comprueba versión, construye wheel y sdist con `.sha256`,
  verifica que la importación no carga Docling y crea el GitHub Release (L-6d, G9).

### Changed

- Documentación con Zensical (`zensical.toml`, `zensical build --strict`) en lugar de mkdocs; extra `docs`:
  `zensical` + `mkdocstrings-python` (L-13b). El sitio de contexto de los proyectos (`MkDocsGenerator`) no cambia.
- `DuplicateGroup.group_id` deja de ser un UUID aleatorio: se deriva de la razón y de las rutas y hashes del grupo
  (sigue teniendo forma de UUID).

### Deprecated

- `tenant_id` en `ProjectRegistry` y `Project` (los tenants los gestiona el consumidor); se retira en 1.0.0 (L-6c).
- Las cinco funciones `*_from_store_or_env` de `ai/`: construir el `*Config` en el consumidor o usar
  `*_config_from_env()`; se retiran en 1.0.0 (L-3).

### Removed

- `mkdocs.yml` y la opción `--builder mkdocs` de `scripts/build_docs_zip.py`.

## [0.9.3] - 2026-10-31

Primera versión publicada en GitHub Releases con wheel y sdist, para que doc_organize_web pueda fijarla por URL y
hash. Recoge todo lo integrado en `develop` desde la 0.9.0.

> **Nota de versión**: por SemVer estricto, las novedades de `Added` pedirían una MINOR. Se publica como PATCH porque
> la 0.10.0 está reservada para la API pública de la separación librería/web (tareas L-1…L-6 del plan de
> doc_organize_web). El tag `v0.9.2` (2026-09-17) marcó un estado intermedio sin subir la versión del paquete, que
> seguía en 0.9.0; esta versión alinea `pyproject.toml`, `__version__` y el tag.

### Added

- `dedup/deduplication.py`: tercera pasada opcional de deduplicación por similitud aproximada de
  nombre (`find_duplicates(fuzzy_threshold=0-100)`), usando `rapidfuzz.process.cdist` con
  `fuzz.WRatio` sobre nombres normalizados (sin extensión, separadores unificados vía
  `rapidfuzz.utils.default_process`) y agrupación por componentes conexas sin exigir
  transitividad estricta. Los grupos resultantes (`DuplicateReason.FUZZY_NAME_MATCH`) nunca se
  auto-resuelven: quedan excluidos de "Buscar duplicados" y solo se resuelven desde el
  formulario interactivo de "Revisar Duplicados" (activación explícita por grupo).
- `web/routes/duplicates.py`, `web/templates/duplicates_resolver.html.j2`: control de umbral de
  similitud (`fuzzy_threshold`) y activación por grupo (`fuzzy_group_toggles`) en la pantalla de
  Duplicados.
- `context/taxonomy_templates_builtin/sgi-integrado.md`: plantilla de taxonomía «sgi-integrado» (7 dominios + 9
  tipos de material).
- `utils/office_detector.py`: detección de LibreOffice (mismo patrón que `av_detector.py`/`gpu_detector.py`);
  `web/templates/_status_banner_macros.html.j2` unifica los banners de GPU, audio/vídeo y LibreOffice en Escaneo.
- `web/`: edición de rol y restablecimiento de contraseña en los paneles de usuarios y tenants; edición de nombre,
  admin y proyectos de un rol; enlace «Proyectos» en el bloque Admin.
- `auth/migrations.py`: migraciones de esquema SQLite centralizadas (protocolo `SchemaMigration`);
  documentación del modelo de hilos (`web/STATE.md`, ADR-004) y pruebas de estrés concurrente de `ProjectRegistry` (estado `v0.9.2`).

### Changed

- `auth/`: `AuthStore` se descompone en `TenantStore`, `RoleStore`, `UserStore` y `SessionStore` (misma API pública
  como fachada); se elimina código de migración muerto.
- `ai/_http_client_base.py`: base HTTP compartida por los 5 clientes de IA, sin cambios de comportamiento.
- `web/routes/taxonomy_templates.py`: la administración de plantillas de taxonomía se separa de las rutas de contexto.
- `scan/scan_command.py`: la excepción capturada al reenviar fallos de OCR por la cola se acota a
  `(OSError, ValueError, RuntimeError, TypeError)`.
- `__version__` pasa de `"0.1.0"` a la versión real del paquete.
- CI: `ruff` fijado a `<0.16` (la 0.16 activa por defecto reglas DTZ/RUF/SIM y el CI estaba en rojo desde
  septiembre con 11 avisos nuevos, pendientes de revisar), `pandas` sin stubs ignorado por mypy y `cryptography`
  añadido al extra `dev` (lo importa `auth/secrets_cipher.py`; solo estaba en `web`).
- **Python mínimo 3.12** (`requires-python = ">=3.12"`, objetivo de ruff `py312`): la matriz del CI deja de incluir
  3.11 (prueba 3.12, 3.13 y 3.14).

### Fixed

- `src/doc_organize/main.py` (`_run_web`): `uvicorn.run(..., ws_ping_timeout=None)` evita que
  uvicorn cierre el WebSocket de escaneo/deduplicación por un pong tardío durante OCR largo
  (el hilo de `asyncio.to_thread` compite por el GIL con el event loop), que antes se veía
  como "Cliente desconectado durante el escaneo" en pleno progreso.
- `dedup/deduplication.py`: la similitud de nombres usa `fuzz.WRatio` sobre nombres normalizados (mejor precisión
  con sufijos de copia/versión).
- `converter/converter.py`: la conversión de `.xls` sin LibreOffice se corta con un mensaje claro en lugar de agotar
  reintentos; el error de conversión muestra la causa raíz encadenada por Docling (hasta 2 niveles).
- `web/`: el alta de usuario exige elegir rol de forma explícita (antes se preseleccionaba `admin`); el bloque Admin se
  muestra en modo local sin autenticación; desplegable de plantilla de taxonomía a todo el ancho.
- `auth/migrations.py`: `datetime.utcnow()` (obsoleto) sustituido por `datetime.now(UTC)` en las migraciones 004/005.
- `scanner/document_scanner.py`: un fichero que desaparece durante el escaneo ya no aborta el recorrido cuando
  `Path.is_symlink()` propaga el error de `lstat()` (Linux); se omite como el resto de casos TOCTOU.
- `projects/project_registry.py`: el doctest de `move_project_root` compara rutas resueltas (fallaba en Windows con
  nombres cortos de `tempfile`).
- `tests/unit/test_scan_command.py`: la duración de un escaneo fallido se comprueba sin exigir `> 0` (en Windows
  `time.monotonic()` tiene ~15,6 ms de resolución y el test fallaba de forma intermitente).

## [0.9.0] - 2026-09-11

### Added

- `src/doc_organize/context/taxonomy_manifest.py` (nuevo): `load_taxonomy_manifest()` lee
  `<project.root_path>/taxonomy_manifest.md` (front matter YAML, cuerpo Markdown libre para
  lectura humana) y lo valida como `TaxonomyManifest` (`core/models.py`, nuevo, junto con
  `TaxonomyCatalogEntry`) — catálogo cerrado de dominios + tipos de material de origen. Cada
  entrada puede llevar `keywords` opcionales que suman a la puntuación de ese candidato,
  además de las palabras derivadas de su propio `slug`.
- `src/doc_organize/context/domain_classifier.py`: nueva clase `MaterialTypeClassifier`
  (segundo eje de clasificación, solo por reglas) y función `score_catalog()` (extraída de
  `DomainClassifier._best_from_catalog` para reutilizar la misma puntuación en ambos ejes,
  sin cambiar su comportamiento), con soporte para `extra_keywords` por slug
  (`TaxonomyCatalogEntry.keywords`). `DomainClassifier` gana el método público `score_domain()`.
- `src/doc_organize/context/context_builder.py`: `ContextBuilder.build()` acepta
  `taxonomy_manifest: TaxonomyManifest | None` — con manifiesto, clasifica cada documento en
  2 ejes (dominio + tipo de material); un documento con los tres artefactos completos siempre
  se reorganiza, con el slug placeholder `sin-clasificar` en el eje que no alcance el umbral,
  en vez de excluirse (`unclassified_documents` sigue reservado a artefactos incompletos). Sin
  manifiesto, comportamiento idéntico al de antes de esta sesión. La Sub-fase B (IA) en modo
  manifiesto se añade en esta misma sesión (ver bullet siguiente) — ya no queda diferida.
- `src/doc_organize/ai/taxonomy_classification_client.py` (nuevo): `TaxonomyClassificationClient`
  — Sub-fase B para manifiesto de taxonomía, resuelve dominio + tipo de material en **una sola
  llamada combinada** al LiteLLM Proxy (en vez de dos llamadas independientes). Mismo patrón que
  `DomainClassificationClient`: `httpx.AsyncClient` con `transport` inyectable, config propia
  (`LiteLLMTaxonomyClassificationConfig`, nuevo en `core/models.py`, env vars propias
  `DOC_ORGANIZE_LITELLM_TAXONOMY_CLASSIFICATION_BASE_URL`/`_VIRTUAL_KEY`/`_MODEL` — no comparte
  credenciales con la config de 1 eje, ISP) y excepciones propias
  (`TaxonomyClassificationError`/`AuthError`/`ConnectionError`, nuevas en `core/exceptions.py`).
  El valor devuelto en cada eje se valida siempre contra su propio catálogo candidato, nunca
  inventa un dominio o tipo de material fuera de lista.
  `ContextBuilder.build()` gana el parámetro `taxonomy_classification_client`; en modo
  manifiesto, con `ai_classification_enabled=True` y un cliente dado,
  `_classify_with_manifest_ai()` reintenta por IA cada documento que las reglas dejaron con el
  placeholder `sin-clasificar` en el eje de dominio y/o en el de tipo de material — la sugerencia
  de la IA solo se aplica al eje que seguía en placeholder; un eje ya resuelto por reglas con
  confianza nunca se sobreescribe, aunque la IA sugiera algo distinto para ese eje en la misma
  respuesta. `DomainDocument.classified_by` pasa a `"ai"` si la IA cambió efectivamente algún eje,
  se queda en `"rules"` si no cambió nada (un único campo string sigue bastando).
- `src/doc_organize/context/reorganizer.py`/`mkdocs_generator.py`: la carpeta de tipo
  (`<dominio>/<tipo>/<stem>/` y el nav de `mkdocs.yml`) usa `DomainDocument.material_type`
  cuando está definido, o la extensión como hasta ahora.
- `src/doc_organize/web/routes/context.py`: `POST /api/projects/{name}/context` (REST y
  WebSocket) carga `taxonomy_manifest.md` automáticamente si existe; lo combina con
  `candidate_domains` en la misma petición devuelve `400` explícito. `ai_classification_enabled`
  ahora también tiene efecto en modo manifiesto: `_optional_ai_client()` construye
  `TaxonomyClassificationClient` (2 ejes) en vez de `DomainClassificationClient` (1 eje) cuando
  hay `taxonomy_manifest` — env vars de clasificación de 2 ejes sin definir se traduce en `400`
  explícito, igual criterio que ya existía para las de 1 eje. La página "Contexto"
  (`GET /projects/{name}/context`) consulta la config del proxy correspondiente al modo
  (manifiesto o no) para decidir si el checkbox de IA aparece habilitado.
- `src/doc_organize/web/templates/context.html.j2`: la página "Contexto" expone el modo
  manifiesto de taxonomía — aviso "Modo manifiesto de taxonomía activo" cuando
  `Context.taxonomy_manifest_used`, y cada fila de dominio se despliega para ver el tipo de
  material de cada documento (`DomainDocument.material_type_name`, o el slug derivado si el
  documento cayó en el placeholder `sin-clasificar`). Sin cambios en `web/routes/context.py`
  ni en el contrato REST/WebSocket — la plantilla ya recibía el `Context` completo.

- `src/doc_organize/context/taxonomy_template_registry.py` (nuevo): `TaxonomyTemplateRegistry` —
  biblioteca de plantillas de manifiesto de taxonomía reutilizables **entre proyectos**
  (`~/.doc_organize/taxonomy_templates/` por defecto, o ruta alternativa vía
  `doc_organize web --templates-path`), con fallback a plantillas empaquetadas de solo lectura
  (`sgi-iso27001`, `calidad`). Seleccionable por nombre al construir el contexto de un proyecto
  (`taxonomy_template_name`, selector en la página "Contexto"); el `taxonomy_manifest.md` local de
  un proyecto, si existe, sigue ganando siempre sobre cualquier plantilla.
- `src/doc_organize/ai/taxonomy_manifest_draft_client.py` (nuevo): `TaxonomyManifestDraftClient` +
  `POST /api/projects/{name}/context/taxonomy-manifest-draft` — a partir de una muestra de
  documentos ya convertidos (muestreo round-robin determinista por carpeta,
  `taxonomy_manifest_sampler.select_document_sample()`), pide a un LiteLLM Proxy que proponga un
  catálogo de dominios + tipos de material. Distinto de la Sub-fase B de clasificación (que elige
  DENTRO de un catálogo ya cerrado): aquí la IA propone el catálogo mismo. Endpoint de solo
  lectura — nunca persiste nada; el usuario revisa/edita el borrador antes de guardarlo.
- `src/doc_organize/auth/instance_secrets_store.py` (nuevo) + `web/routes/ai_settings.py`: panel
  `/admin/configuracion-ia` — ver/editar desde la web las 5 familias de credenciales de IA que
  antes solo eran configurables editando `.env` a mano. Cifradas en reposo con
  [Fernet](https://cryptography.io/en/latest/fernet/) (`DOC_ORGANIZE_SECRETS_KEY`, extra `[web]`);
  un secreto ya guardado nunca se reexpone (`GET` solo devuelve `masked_hint`, últimos 4
  caracteres). Precedencia store → `.env` → sin configurar. `PUT
  /api/projects/{name}/context/taxonomy-manifest` (nuevo) persiste por fin el borrador que
  "Proponer con IA" generaba pero nadie podía guardar hasta ahora. `/admin/plantillas-taxonomia`
  gana CRUD completo (crear/editar/borrar) sobre `TaxonomyTemplateRegistry`.

### Changed

- `src/doc_organize/core/exceptions.py`: `ProjectNotFoundError`/`ProjectAlreadyExistsError`
  construyen ahora su propio mensaje en `__init__(name: str)` a partir del nombre, en vez de que
  cada llamador repitiera el mismo f-string (cluster de literales duplicados, regla S1192) —
  cualquier código que las instanciara pasando un mensaje ya formateado debe pasar solo `name`.
- **Rediseño Tenant/Role/User** (breaking change en la API pública de `AuthStore`, ver
  `.ai/DECISIONS_LOG.md` Revisión 16 y `.ai/sessions/2026-09-11-tenant-role-user-redesign/`):
  `AuthStore` aprovisiona de fábrica, sin CLI previa, un tenant `"default"` + usuario `admin` al
  primer arranque (`must_change_password=True`, `is_instance_admin=True`); esa cuenta no puede
  completar `POST /login` en modo no-loopback mientras conserve la contraseña de fábrica.
  `create_tenant()` ya no aprovisiona ningún rol/usuario para tenants adicionales. `Role` deja de
  estar ligado a un tenant (`name` único **globalmente**): `create_role/get_role/update_role/
  delete_role/list_roles/can_access_project` pierden el parámetro `tenant_id`.
  `RoleNotFoundError`/`RoleAlreadyExistsError` pierden el parámetro `tenant_id` en su constructor.
  El acceso de escaneo de un rol no-admin pasa a ser implícito (`project.root_path` de cada
  proyecto en `project_names`); `GET /api/fs/browse` gana el parámetro opcional `project`. Nuevo
  `User.is_blocked` (bloquear invalida todas sus sesiones activas en la misma transacción) e
  `User.is_instance_admin` (nivel de instancia, independiente del `is_admin` de un rol; gestiona
  cualquier tenant desde la nueva pantalla `/admin/tenants` y es el único que puede tocar
  configuración de IA/plantillas de taxonomía, que pasan de `require_admin` a
  `require_instance_admin`). Nuevo subcomando CLI `user set-instance-admin`.

### Removed

- `src/doc_organize/core/models.py`: `Role.tenant_id` y `Role.allowed_scan_roots` (ver "Changed"
  arriba) — el acceso de escaneo de un rol restringido ya no se declara explícitamente, es
  implícito a la carpeta de sus proyectos permitidos.

### Fixed

- `src/doc_organize/context/context_builder.py`/`mkdocs_generator.py`: el `name`/`description`
  declarados por dominio y tipo de material en `taxonomy_manifest.md` ahora se reflejan en la
  tabla "Contexto", `context.json` y el nav de `mkdocs.yml` — antes se ignoraban y siempre se
  mostraba el slug derivado (p. ej. "Rrhh" en vez de "Recursos Humanos"), pese a que `name` es
  un campo obligatorio del manifiesto.
- `src/doc_organize/auth/auth_store.py`: las guardas de "último admin del tenant"
  (`delete_user`/`update_user`/`set_user_blocked`) bloqueaban también vaciar un tenant por
  completo eliminando/bloqueando/degradando a su único usuario restante, dejando `delete_tenant()`
  (que exige cero usuarios) inalcanzable para ese tenant. Ahora solo bloquean si dejarían a OTROS
  usuarios del tenant sin ningún admin.

## [0.8.0] - 2026-09-10

### Fixed

- `src/doc_organize/converter/converter.py`: dos fallos reales de conversión sin diagnóstico útil.
  Un `.docx`/`.html` cuyo `output_dir` vivía fuera del árbol escaneado terminaba con
  `[Errno 2] No such file or directory` al extraer imágenes (la ruta de salida arrastraba la
  jerarquía absoluta completa del disco de origen en vez de una relativa a la carpeta escaneada) y
  una excepción sin mensaje dejaba el documento en `ERROR` sin ninguna pista visible.
  `resolve_output_paths()` calcula ahora la ruta relativa a `scan_roots` (las carpetas indicadas al
  escanear), y `convert_document()` usa un mensaje de respaldo cuando `str(exc)` está vacío.
- `src/doc_organize/converter/converter.py`: dos causas adicionales del mismo tipo de fallo,
  encontradas al reprocesar los ficheros reales que motivaron el fix anterior. Un `MemoryError` (sin
  mensaje propio, por diseño de Python) al convertir un HTML muy grande (~60 MB, informe OWASP ZAP)
  seguía sin dar ninguna pista útil — ahora se reporta el tamaño del documento en el mensaje. Un
  fichero cuyo nombre termina en espacio antes de la extensión (p. ej. `"Anti SPAM correo Virtual
  Desk .docx"`) generaba una carpeta `img/<stem>/` sin ese espacio final (Windows lo normaliza al
  crearla, como último componente de la ruta) pero luego se referenciaba con el espacio al escribir
  una imagen dentro (ya como componente intermedio, sin normalizar), produciendo
  `[Errno 2] No such file or directory` — `resolve_output_paths()` ahora sanea con `rstrip(" .")`
  cada segmento de la ruta mirroreada (carpetas intermedias y nombre final).
- `src/doc_organize/web/templates/base.html.j2`: la tabla de la pestaña "Historial de ejecuciones"
  (Escanear) mostraba scroll horizontal — el contenedor `<main>` compartido por toda la app
  (`max-w-[720px]`) era más estrecho que las 7 columnas de la tabla. Ampliado a `max-w-[920px]`.
- `pyproject.toml`: el extra `ocr-gpu` instalaba `torch`/`torchvision`/`opencv-python` pero no
  `easyocr` en sí, el paquete que Docling realmente carga para el motor OCR acelerado por GPU —
  `pip install .[ocr-gpu]` seguido de `--use-ocr --use-gpu` fallaba con
  `EasyOCR is not installed`. Añadido `easyocr>=1.7` al extra (`docs/guides/installation.md` y
  `.ai/product.md` actualizados para reflejarlo).
- `src/doc_organize/web/templates/_shared_scripts.html.j2`: el explorador de carpetas del servidor
  ("Buscar…") no protegía contra respuestas de red desordenadas (navegar rápido por subcarpetas
  podía dejar la vista con datos de una carpeta distinta a la mostrada) ni contra doble clic en
  "Usar esta carpeta" durante una petición en curso. Añadido token de generación de petición y
  deshabilitado temporal del botón mientras se resuelve `onSelect`.
- `src/doc_organize/context/{domain_classifier,context_builder,reorganizer}.py`: `images_dir` de
  `ConversionResult` se perdía al construir `DomainDocument` y `Reorganizer._copy_document` nunca
  copiaba la carpeta `img/<stem>/` al destino reorganizado, así que MkDocs servía las imágenes de
  los documentos como rotas. Corregido en dos pasadas: propagar `images_dir` por `DomainDocument`/
  `Reorganizer`, y `web/routes/context.py::_gather_converted_documents` (que reconstruye
  `ConversionResult` desde `cache.db` recalculando `markdown_path`/`json_path`) recalculando también
  `images_dir` — no se persiste en `cache.db` ni en `document.json`, así que el primer fix por sí
  solo operaba sobre un `ConversionResult` que ya nacía sin él.

### Added

- `src/doc_organize/web/routes/downloads.py`: nuevo `GET /downloads/projects/{name}/export-preview`
  (`_compute_export_preview()`) — nº de ficheros y tamaño total en bytes que incluiría `export.zip`,
  sin generarlo; espeja las mismas tres fuentes que `_build_export_zip()` (`Conversión/`,
  `cache_export.json`, `DEDUP_REPORT.json`).
- `src/doc_organize/web/templates/_nav_macros.html.j2`: "Descargar export" muestra ahora esa
  estimación de tamaño/nº de archivos junto al botón (cargada vía `fetch` al `export-preview`) y,
  si el navegador soporta la File System Access API (`showDirectoryPicker`, Chrome/Edge en contexto
  seguro), permite elegir la carpeta de destino y escribe el ZIP ahí; en el resto de navegadores
  cae al comportamiento estándar (carpeta de descargas configurada del navegador).
- `src/doc_organize/core/models.py`: nuevos `ScanEventType.OCR_STARTED`/`OCR_FILE_STARTED`.
- `src/doc_organize/converter/ocr_scheduler.py`: `OCRScheduler.process_with_ocr()` gana un
  parámetro opcional `progress_callback` (no rompe compatibilidad — `None` por defecto), invocado
  justo antes de reconvertir cada documento con su índice/total.
- `src/doc_organize/scan/scan_command.py`: la segunda pasada de OCR informa ahora progreso en vivo
  en vez de todo de golpe al terminar el batch completo. Nuevo `_stream_ocr_batch()` lanza
  `OCRScheduler.process_with_ocr()` en una tarea paralela y retransmite `OCR_FILE_STARTED` por una
  cola según avanza cada documento; `_process_ocr()` emite `OCR_STARTED` (con el total de
  candidatos) antes de arrancar el batch.
- `src/doc_organize/web/templates/folder_selector.html.j2`: la pestaña "Escanear" muestra ahora una
  segunda barra de progreso (`#scan-ocr-progress`) dedicada a los ficheros en curso de OCR, análoga
  a la barra de conversión general ya existente — visible solo cuando hay candidatos a OCR en esta
  ejecución.
- `src/doc_organize/web/routes/admin.py`: la gestión de roles y usuarios pasa de una única página
  combinada (`GET /admin/users`) a dos páginas independientes — `GET /admin/roles` (nueva) y
  `GET /admin/users` — cada una con su propia entrada de menú, agrupadas bajo un apartado "Admin" en
  el sidebar (`base.html.j2`).
- `src/doc_organize/web/routes/admin.py`: `POST /api/users` acepta ahora
  `must_change_password: bool = False`; expuesto como checkbox "Debe cambiar contraseña" en
  `admin_users.html.j2` (antes solo alcanzable programáticamente, sin UI).
- `src/doc_organize/web/templates/admin_roles.html.j2`: "Raíces de escaneo permitidas" pasa de un
  `<textarea>` de texto libre a una lista gestionada con "Guardar carpeta" (ruta manual) y
  "Buscar…" (explorador de carpetas del servidor, reutilizando `GET /api/fs/browse`), con botón
  "Eliminar" por entrada.
- `src/doc_organize/ai/` (extra `ai`, nuevo — fase 2): monitorización de uso/coste de IA
  multi-fuente, sin funcionalidad de inferencia/proxying. `LiteLLMUsageClient.get_usage()` consulta
  el spend de una virtual key de un LiteLLM Proxy externo (`GET /key/info`);
  `GitHubCopilotUsageClient.get_usage()` consulta el consumo de "premium requests" de un plan
  Copilot Pro individual vía la API oficial de Billing Usage de GitHub
  (`GET /users/{username}/settings/billing/premium_request/usage`, sin tocar el endpoint interno de
  completions de Copilot). Ambos devuelven `UsageSnapshot`/`UsageLineItem`
  (`src/doc_organize/core/models.py`) y cumplen el protocolo estructural `UsageSource`
  (`src/doc_organize/ai/usage_source.py`) sin herencia compartida. Nuevas excepciones
  `UsageSourceError`/`UsageSourceAuthError`/`UsageSourceConnectionError`
  (`src/doc_organize/core/exceptions.py`).
- `src/doc_organize/context/` (paquete nuevo, extra `context`): organización documental por
  dominios. `ContextBuilder.build()` clasifica los documentos ya convertidos de un proyecto en dos
  sub-fases — `DomainClassifier` (Sub-fase A, reglas sobre `chunks`/`title` del `.json` de
  conversión, catálogo predefinido o descubrimiento por carpeta) y, opt-in vía
  `ai_classification_enabled`, un fallback por IA (Sub-fase B, `DomainClassificationClient` en
  `src/doc_organize/ai/`) que solo elige entre el catálogo ya confirmado por la Sub-fase A —
  ninguna de las dos inventa un dominio nuevo. `Reorganizer.reorganize()` copia original + `.md` +
  `.json` de cada documento clasificado a `<output_folder_name>/<dominio>/<tipo>/<stem>/` (nunca
  mueve, limpia copias huérfanas de dominios/documentos ya no vigentes en cada reconstrucción, y
  valida todos los artefactos antes de tocar disco para no destruir una reconstrucción anterior si
  falla a mitad). `MkDocsGenerator.generate()` escribe `mkdocs.yml` + `index.md` usando
  `organizado/` como `docs_dir` directamente. `ContextRegistry` persiste `context.json` +
  `domains/<slug>/{DOMAIN.md,index.json}` (mismo patrón que `ProjectRegistry`), preservando el
  texto editado a mano en `DOMAIN.md` entre reconstrucciones.
- `src/doc_organize/ai/domain_classification_client.py`: `DomainClassificationClient` (Sub-fase B)
  + `litellm_classification_config_from_env()` — habla `chat/completions` de un LiteLLM Proxy
  (config propia `LiteLLMClassificationConfig`, no comparte credenciales con `LiteLLMUsageConfig`);
  el dominio devuelto siempre se valida contra el catálogo antes de propagarlo. Nuevas excepciones
  `DomainClassificationError`/`AuthError`/`ConnectionError`.
- `src/doc_organize/web/routes/context.py`: `GET /projects/{name}/context` (página),
  `POST`/`GET /api/projects/{name}/context` (construir/ver) — rechaza con `409` si hay otra
  operación en curso para el proyecto, con `400` si se activa la IA sin
  `DOC_ORGANIZE_LITELLM_CLASSIFICATION_BASE_URL`/`_VIRTUAL_KEY` configuradas.
- `deploy/litellm/{docker-compose.yml,config.yaml.example,.env.example}` + guía
  [`docs/guides/litellm_proxy_setup.md`](docs/guides/litellm_proxy_setup.md): despliegue local del
  LiteLLM Proxy que requiere la Sub-fase B (proxy + Postgres, virtual key dedicada).
- `src/doc_organize/context/mkdocs_generator.py`: construir el contexto ejecuta ahora `mkdocs build`
  a disco (si `mkdocs` está instalado) en vez de dejar solo `mkdocs.yml` sin construir.
  `output_folder_name` es elegible en la primera construcción de un proyecto (validado contra path
  traversal y contra nombres ya reservados por otros subsistemas) y queda fijo hasta que se elimina
  el contexto por completo — nuevo `DELETE /api/projects/{name}/context`, con confirmación explícita
  en la UI — así se puede elegir otra carpeta sin dejar copias huérfanas. La página de Contexto avisa
  si LiteLLM Proxy está configurado antes de que el usuario intente activar la Sub-fase B.
- `src/doc_organize/web/routes/context.py`: nuevo `GET /projects/{name}/context/site[...]` para
  visualizar el sitio MkDocs ya construido de cualquier proyecto, independiente del flujo de
  build/reconstruir contexto, con el mismo control de acceso por tenant/rol que el resto de la app
  (`require_project_access`). Nunca se dispara automáticamente tras un build — el usuario lo abre
  desde el enlace "ver documentación generada", visible solo cuando `mkdocs_site_built` es `True`.
- `src/doc_organize/web/templates/context.html.j2`: "Reconstruir/Construir contexto" y "Eliminar
  contexto" muestran ahora el mismo semáforo de 3 luces que Escanear/Duplicados
  (Inicio/Ejecución/Finalización, rojo en error), con progreso real vía dos WebSocket nuevos
  (`/context/build`, `/context/delete`) que retransmiten cada paso de
  `ContextBuilder`/`Reorganizer`/`MkDocsGenerator` — incluida una barra numérica X/Y para la
  clasificación por IA y la copia de documentos. El checkbox de "Clasificación asistida por IA" se
  deshabilita (y se fuerza desmarcado) cuando LiteLLM Proxy no está configurado, incluso si un build
  anterior lo había dejado activo.

### Changed

- `src/doc_organize/web/templates/dashboard.html.j2`, `admin_roles.html.j2`, `admin_users.html.j2`,
  `project_selector.html.j2`: el helper `postJson`/`apiError` y el panel "explorador de carpetas
  del servidor" (antes duplicados inline en cada plantilla, incluyendo una implementación
  independiente en `project_selector.html.j2` con `createFolderBrowser()`) se extraen a
  `_shared_scripts.html.j2` (JS, `initFolderBrowser(idPrefix, onSelect)`) y
  `_folder_browser_macros.html.j2` (macros Jinja, `class_override` opcional para preservar las
  clases Tailwind propias de "Mover"/"ubicación al crear proyecto"); sin cambio de comportamiento
  observable — incluida la diferencia real de cerrar o no el panel tras seleccionar (resuelta con
  un segundo argumento `close()` que cada página invoca o ignora según su flujo).
- `src/doc_organize/web/dependencies.py`: la autenticación y el lock de los WebSocket de proyecto
  (antes duplicados entre `scan.py` y `context.py`, con textos ya divergentes entre sí) se
  centralizan aquí, reutilizados por los WS de escaneo, deduplicación y, ahora, construir/eliminar
  contexto.
- `src/doc_organize/web/templates/_semaforo_macros.html.j2` (nuevo): el HTML/JS del semáforo de 3
  luces (antes triplicado entre `folder_selector.html.j2`, `duplicates_resolver.html.j2` y
  `context.html.j2`) se extrae a esta macro común; sin cambio de comportamiento observable
  (verificado en navegador real con Playwright en las 3 páginas).

## [0.7.0] - 2026-09-03

### Added

- `src/doc_organize/core/models.py`: `ScanRunReport` gana `discovery_duration_seconds`/
  `total_conversion_seconds` (ambos opcionales — `None` en históricos previos a estos campos,
  para no romper la carga de líneas ya escritas en `SCAN_HISTORY.jsonl`). Nuevo `DedupEventType`
  (`started`/`duplicates_found`/`group_started`/`group_resolved`/`completed`) y `DedupEvent`,
  mismo patrón que `ScanEventType`/`ScanEvent`, emitidos por `ScanCommand.deduplicate_streaming()`.
- `src/doc_organize/scan/scan_command.py`: el payload de `FILE_CONVERTED`/`OCR_PROCESSED` gana
  `duration_seconds` (ya calculado por `ConversionResult`, antes descartado); el de `SCANNED` gana
  `discovery_duration_seconds` (ya calculado por `DocumentScanner.scan_folders()`, antes descartado).
  `ScanSummary` acumula ambos (`total_conversion_seconds`, `discovery_duration_seconds`) y los
  refleja en `render()` (CLI) y en el evento `COMPLETED`.
- `src/doc_organize/dedup/deduplication.py`: `DeduplicationManager` gana `move_group()` (mueve los
  descartados de un único grupo) y `finalize_report()` (persiste `DEDUP_REPORT.json`/
  `DEDUP_HISTORY.jsonl`), ambos públicos — `resolve_duplicates()` pasa a componerlos.
- `src/doc_organize/web/routes/scan.py`: nuevo WebSocket `WS /api/projects/{name}/scan/deduplicate`,
  retransmitiendo cada `DedupEvent` en vivo (progreso por grupo de duplicados detectado/movido) —
  mismo patrón que el WebSocket de escaneo.
- `src/doc_organize/web/templates/duplicates_resolver.html.j2`: la pestaña "Buscar duplicados"
  muestra ahora una barra de progreso en vivo por grupo ("Moviendo grupo X/Y…") y la duración de la
  ejecución, en vez de un semáforo que solo simulaba "en ejecución" sobre una única llamada bloqueante.
- `src/doc_organize/web/templates/folder_selector.html.j2`: la pantalla "Escanear" muestra ahora la
  duración de descubrimiento de ficheros y de conversión acumulada, tanto en la última ejecución
  (en vivo y tras recargar) como en cada fila del histórico de ejecuciones.
- `src/doc_organize/core/constants.py`: `DEDUP_REPORT_JSON_NAME` (`DEDUP_REPORT.json`),
  `DEDUP_HISTORY_JSONL_NAME` (`DEDUP_HISTORY.jsonl`) — nombres de fichero de deduplicación
  centralizados, mismo patrón que `SCAN_HISTORY_JSONL_NAME`/`SCAN_ERRORS_HISTORY_JSONL_NAME`.

### Changed

- `src/doc_organize/web/routes/scan.py`: `_authorize_scan_websocket` renombrado a
  `_authorize_project_websocket` — ahora compartido por los WebSocket de escaneo y de deduplicación.
- `src/doc_organize/dedup/deduplication.py`, `src/doc_organize/web/routes/downloads.py`,
  `src/doc_organize/web/routes/duplicates.py`, `src/doc_organize/main.py`: los literales
  `"DEDUP_REPORT.json"`/`"DEDUP_HISTORY.jsonl"`/`"duplicados"` pasan a usar las constantes
  centralizadas de `core/constants.py` (sin cambio de valor ni de comportamiento).

### Removed

- `src/doc_organize/scan/scan_command.py`: `ScanCommand.deduplicate()` eliminado — sustituido por
  `deduplicate_streaming()` (async generator con progreso, ver "Added"). Sin variante síncrona de
  resumen final: los llamadores que solo necesitan el resumen (CLI) consumen el generador y se
  quedan con su evento `COMPLETED`.
- `src/doc_organize/web/routes/scan.py`: `POST /api/projects/{name}/scan/deduplicate` eliminado —
  sustituido por el WebSocket `WS /api/projects/{name}/scan/deduplicate` (ver "Added").

## [0.6.0] - 2026-09-03

### Added

- `src/doc_organize/core/models.py`: `DeduplicationReport` gana `started_at`/`duration_seconds`
  (ambos opcionales — `None` en históricos previos a este campo, para no romper la carga de líneas ya
  escritas en `DEDUP_HISTORY.jsonl`).
- `src/doc_organize/dedup/deduplication.py`: `DeduplicationManager.resolve_duplicates()` acepta un
  nuevo parámetro opcional `started_at: datetime | None = None` — cuando se pasa, calcula
  `duration_seconds` cubriendo desde ahí hasta que termina la resolución.
- `src/doc_organize/scan/scan_command.py`: `DeduplicationSummary` gana `duration_seconds`;
  `ScanCommand.deduplicate()` captura `started_at` antes de re-escanear/detectar duplicados, para que
  la duración cubra la operación completa de "Buscar duplicados" (mismo criterio que
  `duration_seconds` en `ScanSummary`/`ScanRunReport` para "Escanear").
- `src/doc_organize/web/routes/scan.py`: `DeduplicateFoldersResponse` gana `duration_seconds`.
- `src/doc_organize/web/routes/duplicates.py`: el formulario interactivo de resolución
  (`POST /api/projects/{name}/duplicates/resolve`) también captura y persiste `started_at`/
  `duration_seconds`, mismo criterio que la acción masiva "Buscar duplicados".
- `src/doc_organize/web/templates/duplicates_resolver.html.j2`: la pantalla "Duplicados" muestra ahora
  la duración de la última ejecución de "Buscar duplicados" (banner) y de cada ejecución del histórico,
  reutilizando el filtro Jinja `format_duration` ya existente.
- `src/doc_organize/core/models.py`: nuevo `ScanEventType.FILE_STARTED`, emitido por
  `ScanCommand._convert_documents()` justo antes de convertir cada documento, con
  `{"path", "index", "total"}` (`total` = ficheros a convertir en esta ejecución).
- `src/doc_organize/scan/scan_command.py`: el payload del evento `SCANNED` gana `to_process` (total
  real de ficheros que se van a convertir, distinto de `scanned`/`new + modified`: también incluye
  reintentos de ficheros en `ERROR` sin cambios).
- `src/doc_organize/web/templates/folder_selector.html.j2`: la pantalla "Escanear" muestra ahora una
  barra de progreso en vivo con "Procesando X/Y: nombre_de_fichero" mientras el escaneo corre, y un
  mensaje final ("Completado: N fichero(s) procesado(s)." o "Sin ficheros nuevos que convertir."); el
  registro JSON detallado de eventos pasa a un `<details>` colapsado ("Resultado del escaneo") en vez
  de ser el elemento principal de la pantalla.

## [0.5.0] - 2026-09-03

### Added

- `src/doc_organize/utils/date_format.py`: nuevo módulo `format_datetime(value, pattern=None, tz_name=None)` /
  `format_duration(seconds)`, registrados como filtros Jinja (`web/templating.py`) — centraliza cómo se
  muestran al usuario los timestamps ISO 8601 UTC que genera el resto del proyecto. Parametrizable vía las
  variables de entorno `DOC_ORGANIZE_DATE_FORMAT` / `DOC_ORGANIZE_TIMEZONE` (mismo patrón que
  `utils/logging.py`); por defecto, formato español (`dd/mm/aaaa HH:MM:SS`) y zona horaria de España
  (`Europe/Madrid`, con cambio automático de horario de verano/invierno).
- `src/doc_organize/core/models.py`: nuevo modelo `ScanRunReport` (`scan_run_id`, `started_at`,
  `finished_at`, `duration_seconds`, `total_scanned`, `completed`) — histórico de duración de ejecuciones
  de escaneo.
- `src/doc_organize/scan/scan_history_store.py`: nuevo store JSONL append-only
  (`append_scan_run(history_path, report)` / `list_scan_runs(history_path)`), exportado desde
  `doc_organize.scan`. Mismo patrón que `SCAN_ERRORS_HISTORY.jsonl`/`DEDUP_HISTORY.jsonl`, pero registra
  **toda** ejecución (completada o no), no solo las que producen error.
- `src/doc_organize/core/constants.py`: `SCAN_HISTORY_FOLDER_NAME` (`historial_escaneo`),
  `SCAN_HISTORY_JSONL_NAME` (`SCAN_HISTORY.jsonl`).
- `src/doc_organize/scan/scan_command.py`: `ScanCommand.run()`/`run_streaming()` aceptan un nuevo
  parámetro opcional `history_log_path: Path | None = None`; `ScanSummary` incluye `duration_seconds`
  (también en el resumen impreso por el CLI, línea "Tiempo de ejecución: …"). Cada ejecución —completada
  o interrumpida por una excepción— se registra en el histórico con `completed=True`/`False`.
- `src/doc_organize/web/routes/scan.py` / `web/templates/folder_selector.html.j2`: la pantalla "Escanear"
  muestra ahora la duración de la última ejecución, y una nueva pestaña "Historial de ejecuciones" lista
  cada ejecución registrada (inicio, fin, duración, documentos escaneados, si terminó o se interrumpió).
- `pyproject.toml`: nueva dependencia `tzdata` (requerida por `zoneinfo` para resolver zonas horarias
  IANA como `Europe/Madrid` en Windows).
- `scripts/build_docs_zip.py`: nuevo script para empaquetar la documentación compilada como ZIP
  con checksums SHA256 para distribución offline. Genera:
  - `dist/doc_organize-docs-{version}.zip` (sitio MkDocs completo comprimido)
  - `dist/doc_organize-docs-{version}.zip.sha256` (checksum individual)
  - `dist/CHECKSUMS.txt` (histórico de todas las builds)
- `.github/workflows/docs-zip-release.yml`: nueva automatización que en cada push a `main`/`develop`
  que afecte `docs/`, `mkdocs.yml` o `pyproject.toml`:
  1. Construye documentación con `mkdocs build --strict`
  2. Genera ZIP con `scripts/build_docs_zip.py`
  3. Crea GitHub Release con tag `docs-v{version}` y adjunta ZIP + checksums
  4. Publica en [Releases](https://github.com/fmanza/doc_organize/releases)

**Features (documentación offline):**
- ✅ Descarga offline de documentación completa con búsqueda
- ✅ Verificación de integridad por SHA256 (portable, compatible con `sha256sum -c`)
- ✅ Histórico de builds en `CHECKSUMS.txt` para auditoría
- ✅ GitHub Artifacts (retención 30 días) para CI/CD
- ✅ Error handling + validaciones (cross-platform, Python 3.11+)

**Uso:**
```bash
# Manual (local)
python scripts/build_docs_zip.py
python scripts/build_docs_zip.py --no-build  # rezip site/ existente

# Automático (CI/CD)
# En cada push que toque docs/ → GitHub Release automático
```

### Changed

- `web/templates/dashboard.html.j2`, `project_selector.html.j2`, `duplicates_resolver.html.j2`,
  `scan_errors.html.j2`: los timestamps ISO 8601 UTC que antes se mostraban crudos ahora pasan por el
  filtro `format_datetime` (formato español/España por defecto, configurable — ver `date_format.py`
  arriba).

### Fixed

- `format_datetime()` degrada a mostrar el valor original (en vez de lanzar una excepción y tumbar la
  página) ante un timestamp no parseable o una zona horaria mal configurada — mismo criterio de
  tolerancia a datos corruptos que ya aplican `load_error_history`/`_load_dedup_history`.
- La persistencia del histórico de duración de ejecuciones se realiza ahora **antes** de emitir el evento
  `COMPLETED` (no después, en un `finally`): evita una carrera intermitente con la desconexión del cliente
  WebSocket, que cierra la conexión en cuanto recibe ese evento.
- Un fallo de E/S al escribir el histórico de tiempos de escaneo o el histórico de errores de escaneo
  (permiso denegado, disco lleno…) ya no aborta un escaneo que por lo demás terminó con éxito — ambas
  escrituras son ahora best-effort (se loguea un warning en vez de propagar la excepción).

---

## [0.4.0] - 2026-08-31

⚠️ **Rompe contratos públicos** (ver "Removed"/"Changed"): firma de `ScanCommand`, flags del CLI
`scan`, payload del WebSocket de escaneo y el enum `ScanEventType`. Sin release publicado de
`doc_organize` hasta la fecha — no se ofrece guía de migración formal, solo el detalle de cada
cambio abajo.

### Added

- `src/doc_organize/scan/scan_command.py`: nuevo método `ScanCommand.deduplicate(paths,
  duplicates_dir, folders_json) -> DeduplicationSummary` — busca y mueve duplicados de forma
  independiente al escaneo, a petición explícita del usuario. Nuevo dataclass
  `DeduplicationSummary` (`groups_found`, `moved`, `warnings`), exportado desde `doc_organize.scan`.
- `src/doc_organize/main.py`: nuevo subcomando CLI `deduplicate --paths ... [--project ...]
  [--duplicates-dir ...]`, con su propia resolución de rutas (`_resolve_dedup_paths`) — no exige
  `--output-dir`/`--cache-file` como `scan`, porque no convierte ni cachea nada.
- `src/doc_organize/web/routes/scan.py`: nuevo `POST /api/projects/{name}/scan/deduplicate` —
  equivalente web del subcomando CLI, sobre todas las carpetas guardadas del proyecto.
- `src/doc_organize/dedup/deduplication.py`: `DeduplicationManager.resolve_duplicates()` añade
  además una línea a `duplicados/DEDUP_HISTORY.jsonl` (JSON Lines, append-only) por cada ejecución
  — histórico incremental y consultable, a diferencia de `DEDUP_REPORT.json` (que solo refleja la
  última). Se registra toda ejecución, incluso sin duplicados encontrados.
- `src/doc_organize/web/templates/folder_selector.html.j2`: botón "Buscar duplicados" (menú
  Escaneo) — "Escanear" nace deshabilitado y solo se habilita tras una ejecución exitosa de
  "Buscar duplicados" en la misma visita a la página (gate de cliente, sin persistencia entre
  visitas; no sustituye ningún control de seguridad existente).
- `src/doc_organize/web/routes/duplicates.py` / `duplicates_resolver.html.j2`: sección "Histórico
  de deduplicaciones" — lista todas las ejecuciones registradas en `DEDUP_HISTORY.jsonl`, cada una
  con su propio detalle de archivos (conservado/movido), en un bloque colapsable
  (`<details>`/`<summary>` nativo, sin JavaScript de terceros). El buscador y el contador de la
  página cubren los grupos de todas las ejecuciones, no solo la más reciente.
- `src/doc_organize/core/constants.py`: `SCAN_FOLDERS_JSON_NAME` — nombre centralizado del fichero
  `folders.json`, usado por `main.py`, `web/routes/scan.py` y `web/routes/duplicates.py`.

### Changed

- `src/doc_organize/web/routes/scan.py`: el WebSocket `/api/projects/{name}/scan` ya no acepta
  `paths` del cliente — resuelve siempre todas las carpetas guardadas del proyecto
  (`ScannedFoldersStore`) del lado servidor. `mark_used()` ahora marca solo las rutas ya validadas
  por `FolderValidator`, no las carpetas guardadas sin validar (evita marcar como usada — y por
  tanto no eliminable — una carpeta que ya no existe en disco).
- `src/doc_organize/web/routes/duplicates.py`: la sección "Duplicados ya resueltos" desaparece
  como bloque independiente — su contenido pasa a ser, simplemente, el detalle de la ejecución más
  reciente dentro de "Histórico de deduplicaciones". "Última deduplicación" se deriva ahora de
  `DEDUP_HISTORY.jsonl` (primera entrada) en vez de leer `DEDUP_REPORT.json` aparte — elimina una
  posible inconsistencia entre ambas lecturas si un fallo interrumpe la escritura entre los dos
  ficheros. `DEDUP_REPORT.json` se sigue escribiendo en disco sin cambios (contrato externo).
- `src/doc_organize/web/templates/duplicates_resolver.html.j2`: al resolver un conflicto desde el
  formulario interactivo, la página se refresca (antes solo mostraba un texto de resultado sin
  actualizar el estado de pendientes/histórico).
- Lecturas de fichero en `web/routes/duplicates.py` (histórico, último reporte, re-escaneo de
  duplicados pendientes) pasan a ejecutarse en un hilo aparte (`asyncio.to_thread`) para no
  bloquear el bucle de eventos — relevante porque `DEDUP_HISTORY.jsonl` crece sin límite durante la
  vida del proyecto.

### Removed

- `src/doc_organize/scan/scan_command.py`: `ScanCommand.run()`/`run_streaming()` pierden los
  parámetros `deduplicate: bool` y `duplicates_dir: Path` — la deduplicación ya no forma parte del
  pipeline de escaneo (ver `deduplicate()` en "Added").
- `src/doc_organize/main.py`: `scan` pierde los flags `--deduplicate` y `--duplicates-dir`.
- `src/doc_organize/core/models.py`: `ScanEventType.DEDUPLICATED` eliminado del enum — el escaneo
  ya no emite ningún evento de deduplicación (`deduplicate()` no emite `ScanEvent`, devuelve un
  `DeduplicationSummary` de una sola vez).

## [0.3.0] - 2026-08-31

### Added

- `src/doc_organize/web/routes/duplicates.py` /
  `src/doc_organize/web/templates/duplicates_resolver.html.j2`: la página
  "Revisar Duplicados" ahora incluye un buscador de filtrado instantáneo en
  cliente (por nombre de archivo o carpeta, sin round-trip al servidor), muestra
  la carpeta contenedora y el tamaño legible (`1.5 MB`) de cada documento en una
  tabla en vez de una lista de radios en texto plano, añade una sección de
  solo lectura "Duplicados ya resueltos" con el detalle de los grupos que un
  escaneo previo con "Deduplicar" activado ya movió automáticamente (lee
  `duplicados/DEDUP_REPORT.json`), y un contador que se actualiza a
  "X de Y grupo(s)." mientras el filtro está activo (suma pendientes + ya
  resueltos). Sin cambios en los modelos Pydantic ni en las rutas JSON
  existentes (`GET`/`POST /api/projects/{name}/duplicates...`).
- `src/doc_organize/web/routes/cache.py` /
  `src/doc_organize/web/templates/cache_viewer.html.j2`: misma mejora de
  visualización aplicada a la página "Caché" — buscador de filtrado instantáneo
  en cliente (por nombre de archivo o carpeta) y columnas Archivo/Carpeta
  separadas en vez de la ruta completa en una sola celda; el contador de
  entradas se actualiza a "X de Y entradas." mientras el filtro está activo. Sin
  cambios en `CacheEntryResponse`/`CacheListResponse` ni en las rutas JSON.

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
