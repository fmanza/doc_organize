# API pública y compatibilidad

Desde la 0.10.0, la API pública de doc_organize son los nombres de `doc_organize.__all__`. Siguen
[SemVer](https://semver.org/lang/es/): una versión MINOR (0.x.0) puede añadir nombres o parámetros opcionales y marcar
cosas como obsoletas (`DeprecationWarning`), pero no romperlas; los cambios incompatibles se reservan para una MAJOR
(1.0.0). Lo que no está en `__all__` (módulos internos) puede cambiar sin aviso.

```python
import doc_organize

doc_organize.__version__          # versión del paquete instalado (metadatos)
from doc_organize import ScanCommand, DeduplicationManager, ContextBuilder, ScanEvent
```

## Importación ligera

`import doc_organize` **no** carga Docling ni torch: cada nombre público se importa la primera vez que se usa
(PEP 562). Así un consumidor puede leer la versión, los modelos (`ScanEvent`, `Project`…), los errores o el diagnóstico
de la instancia sin el coste de Docling:

```python
from doc_organize import detect_gpu_status, detect_av_status, detect_office_status

detect_office_status().libreoffice_installed   # no carga Docling
```

`ScanCommand`, `DocumentConverter` y el resto de lo que convierte documentos sí cargan Docling al usarlos.
`doc_organize.export` no carga Docling, y `openpyxl` (extra `export`) solo se importa al escribir un Excel.
Tampoco lo cargan `resolve_output_paths`, `resolve_images_dir`, `relative_source_path` ni `CacheManager` (también en
solo lectura).

## Cambios por versión

| Versión | Cambio |
|---|---|
| 1.0.0 | **Incompatible (MAJOR)**. Se retiran la web integrada y `auth/` (L-11): `doc_organize.web`, `doc_organize.auth`, los subcomandos `web`, `tenant` y `user` del CLI y el extra `[web]`. Se retira lo obsoleto de la web (L-12): `Project.tenant_id`, `Context.tenant_id` y el parámetro `tenant_id` de `ProjectRegistry` (un `projects.json`/`context.json` antiguo con el campo se sigue leyendo; se ignora), las cinco `*_config_from_store_or_env` de `doc_organize.ai` (quedan las `*_config_from_env`), y de `core` los modelos `Tenant`, `Role`, `User`, `Session`, `SecurityConfig` y `DirectoryListing`, `AuthError` y sus subclases, `SecretsCipherError`/`SecretsEncryptionNotConfiguredError` y las constantes de autenticación. Ninguno de estos nombres estaba en `doc_organize.__all__`; de los que sí están, solo `Project` y `Context` cambian (pierden `tenant_id`). Se retira también lo obsoleto desde 0.13.0: `MkDocsGenerator` (sale de `doc_organize.__all__`; usa `SiteGenerator`) y las propiedades `Context.mkdocs_generated`/`mkdocs_site_built` (usa `site_generated`/`site_built`; un `context.json` antiguo con esas claves se sigue leyendo) |
| 0.14.0 | Parámetros opcionales *keyword-only* `ContextBuilder.build(ai_max_failures=, ai_max_documents=)` y `select_document_sample(roots=)`; campos nuevos `Context.ai_classification_stopped`/`ai_documents_sent`/`ai_documents_classified`/`ai_documents_failed` y `retries`/`retry_backoff_s` en las `*Config` de `doc_organize.ai`; alias de tipo `AiClassificationStopReason` en `core.models`. **Cambios de comportamiento**: un 401/403 detiene la Sub-fase B en el acto (antes se intentaba cada documento); `LiteLLMUsageClient.get_usage()` ya no envía `?key=` con la clave propia (seguridad). **L-8d…L-8f**: nueva `resolve_organized_paths` y campo `DomainDocument.organized_path`; dos documentos con el mismo nombre (sin distinguir mayúsculas) en el mismo dominio y tipo van a `<stem>-<8 hex>/` en vez de sobrescribirse; los ficheros del contexto se escriben con temporales que no siguen enlaces; `Context` valida `output_folder_name` (un `Context(output_folder_name="..")` o un `context.json` así dan `ValidationError`/`ContextError`). **Obsoletos (L-10, se retiran en 1.0.0)**: `doc_organize.web`, `doc_organize.auth` (`DeprecationWarning` al importarlos) y los subcomandos `web`, `tenant` y `user` del CLI (aviso por stderr; sustituidos por doc_organize_web) |
| 0.13.0 | Nuevos `SiteGenerator`, `SiteResult` y `SiteBuildError` (sitio de contexto con Zensical); `parse_taxonomy_template`, `render_taxonomy_template`, `list_builtin_templates` y `load_builtin_template`; `RESERVED_OUTPUT_FOLDER_NAMES` y `validate_output_folder_name`. Propiedades nuevas de `ProjectLayout` (contexto y sitio), `Context.site_generated`/`site_built`/`reorganize_failed_documents`, `Reorganizer.reorganize(on_document_failed=)` y `ContextBuildEventType.DOCUMENT_FAILED` (un `match` exhaustivo tiene un caso nuevo). **Obsoletos** (se retiran en 1.0.0): `MkDocsGenerator` (alias de `SiteGenerator`) y `Context.mkdocs_generated`/`mkdocs_site_built`. **Cambios de comportamiento**: el extra `site` instala `zensical` en lugar de `mkdocs`; `MkDocsGenerator.generate` devuelve `SiteResult` y lanza `SiteBuildError` en lugar de devolver `(ruta, False)`; `Reorganizer` ya no sigue enlaces simbólicos |
| 0.12.0 | Nuevos `resolve_output_paths`, `resolve_images_dir`, `relative_source_path` (grupo «Rutas de salida»), `CacheNotFoundError` y `ModelsNotAvailableError`. Parámetros opcionales *keyword-only*: `CacheManager(read_only=)`, `count_entries`/`load_cache_page(relative_to=, conversion_status=)`, `DocumentConverter(artifacts_path=, allow_model_downloads=)`, `OCRScheduler(...)` ídem, `convert_document`/`process_with_ocr(include_root_name=, json_source_path=)`. Se exportan también `ConversionStatus` y `DocumentStatus`. Campos nuevos en `ScanOptions` y `ScanResult.unreadable_dirs`. **Cambio de comportamiento**: el `source_path` del JSON de cada documento pasa a ser relativo a la carpeta escaneada (`json_source_path="absolute"` recupera lo anterior) |
| 0.11.0 | Nuevo grupo «Exportación» y `MissingDependencyError`. `ProgressEvent.operation` admite `"export"` y `Phase` la fase `"export"`: un `match` exhaustivo sobre esos valores tiene un caso nuevo |
| 0.10.0 | Primera API pública estable |

## Grupos de nombres

| Grupo | Nombres |
|---|---|
| Escaneo y conversión | `ScanCommand`, `ScanOptions`, `ScanSummary`, `DocumentScanner`, `DocumentConverter`, `OCRScheduler`, `CacheManager`, `CancelToken`, `ProgressEvent` |
| Rutas de salida (0.12.0) | `resolve_output_paths`, `resolve_images_dir`, `relative_source_path` (también en `doc_organize.projects`; no cargan Docling) |
| Carpeta reorganizada (0.13.0) | `RESERVED_OUTPUT_FOLDER_NAMES`, `validate_output_folder_name` (también en `doc_organize.projects.layout`) |
| Duplicados | `DeduplicationManager`, `DeduplicationSummary`, `DuplicateGroup`, `DuplicateReason`, `DeduplicationReport` |
| Contexto | `ContextBuilder`, `ContextRegistry`, `Reorganizer`, `SiteGenerator`, `SiteResult`, `TaxonomyTemplateRegistry`, `Context`, `TaxonomyManifest` |
| Plantillas de taxonomía como texto (0.13.0) | `parse_taxonomy_template`, `render_taxonomy_template`, `list_builtin_templates`, `load_builtin_template` (también en `doc_organize.context`) |
| Exportación (0.11.0) | `write_project_zip`, `preview_project_zip`, `ExportStats`, `write_cache_xlsx`, `write_scan_errors_xlsx`, `load_cache_entries`, `load_scan_error_history` (también en `doc_organize.export`; ver [Exportación](export.md)) |
| Proyectos (CLI) | `ProjectRegistry`, `ProjectLayout`, `ProjectHistoryCleaner`, `ScannedFoldersStore`, `Project`, `ScannedFolder`, `FolderValidator`, `ProjectValidator` |
| Eventos de progreso | `ScanEvent`/`ScanEventType`, `DedupEvent`/`DedupEventType`, `ContextBuildEvent`/`ContextBuildEventType`, `ContextDeleteEvent`/`ContextDeleteEventType` |
| Modelos | `DocumentMetadata`, `ConversionResult`, `CacheEntry`, `ConversionStatus`, `DocumentStatus`, `ScanResult`, `ScanErrorEntry`, `ScanErrorReport`, `ScanRunReport` |
| Diagnóstico | `detect_gpu_status`, `detect_av_status`, `detect_office_status`, `GpuStatus`, `AvStatus`, `OfficeStatus` |
| Errores | `DocOrganizeError` (base), `OperationCancelledError`, `InvalidPathError`, `MissingDependencyError`, `ConversionError`, `ModelsNotAvailableError`, `CacheError`, `CacheNotFoundError`, `ProjectError`, `ProjectNotFoundError`, `ContextError`, `SiteBuildError` |

El paquete incluye `py.typed`: los tipos son utilizables por `mypy` en el código que lo consume.

## Consumidores conocidos

- [doc_organize_web](https://github.com/fmanza/doc_organize_web): la fija por versión (wheel de la GitHub Release con
  su hash) y solo la importa desde su capa anticorrupción. Antes de cambiar la API pública, revisa su
  `docs/plan/DOC_ORGANIZE_GAPS.md`.
