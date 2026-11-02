# API pública y compatibilidad

Desde la 0.10.0, la API pública de doc_organize son los nombres de `doc_organize.__all__`. Siguen
[SemVer](https://semver.org/lang/es/): una versión MINOR (0.x.0) puede añadir nombres o parámetros opcionales y marcar
cosas como obsoletas (`DeprecationWarning`), pero no romperlas; los cambios incompatibles se reservan para una MAJOR
(1.0.0). Lo que no está en `__all__` (módulos internos, `web/`, `auth/`) puede cambiar sin aviso.

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
| 0.12.0 | Nuevos `resolve_output_paths`, `resolve_images_dir`, `relative_source_path` (grupo «Rutas de salida»), `CacheNotFoundError` y `ModelsNotAvailableError`. Parámetros opcionales *keyword-only*: `CacheManager(read_only=)`, `count_entries`/`load_cache_page(relative_to=, conversion_status=)`, `DocumentConverter(artifacts_path=, allow_model_downloads=)`, `OCRScheduler(...)` ídem, `convert_document`/`process_with_ocr(include_root_name=, json_source_path=)`. Se exportan también `ConversionStatus` y `DocumentStatus`. Campos nuevos en `ScanOptions` y `ScanResult.unreadable_dirs`. **Cambio de comportamiento**: el `source_path` del JSON de cada documento pasa a ser relativo a la carpeta escaneada (`json_source_path="absolute"` recupera lo anterior) |
| 0.11.0 | Nuevo grupo «Exportación» y `MissingDependencyError`. `ProgressEvent.operation` admite `"export"` y `Phase` la fase `"export"`: un `match` exhaustivo sobre esos valores tiene un caso nuevo |
| 0.10.0 | Primera API pública estable |

## Grupos de nombres

| Grupo | Nombres |
|---|---|
| Escaneo y conversión | `ScanCommand`, `ScanOptions`, `ScanSummary`, `DocumentScanner`, `DocumentConverter`, `OCRScheduler`, `CacheManager`, `CancelToken`, `ProgressEvent` |
| Rutas de salida (0.12.0) | `resolve_output_paths`, `resolve_images_dir`, `relative_source_path` (también en `doc_organize.projects`; no cargan Docling) |
| Duplicados | `DeduplicationManager`, `DeduplicationSummary`, `DuplicateGroup`, `DuplicateReason`, `DeduplicationReport` |
| Contexto | `ContextBuilder`, `ContextRegistry`, `Reorganizer`, `MkDocsGenerator`, `TaxonomyTemplateRegistry`, `Context`, `TaxonomyManifest` |
| Exportación (0.11.0) | `write_project_zip`, `preview_project_zip`, `ExportStats`, `write_cache_xlsx`, `write_scan_errors_xlsx`, `load_cache_entries`, `load_scan_error_history` (también en `doc_organize.export`; ver [Exportación](export.md)) |
| Proyectos (CLI) | `ProjectRegistry`, `ProjectLayout`, `ProjectHistoryCleaner`, `ScannedFoldersStore`, `Project`, `ScannedFolder`, `FolderValidator`, `ProjectValidator` |
| Eventos de progreso | `ScanEvent`/`ScanEventType`, `DedupEvent`/`DedupEventType`, `ContextBuildEvent`/`ContextBuildEventType`, `ContextDeleteEvent`/`ContextDeleteEventType` |
| Modelos | `DocumentMetadata`, `ConversionResult`, `CacheEntry`, `ConversionStatus`, `DocumentStatus`, `ScanResult`, `ScanErrorEntry`, `ScanErrorReport`, `ScanRunReport` |
| Diagnóstico | `detect_gpu_status`, `detect_av_status`, `detect_office_status`, `GpuStatus`, `AvStatus`, `OfficeStatus` |
| Errores | `DocOrganizeError` (base), `OperationCancelledError`, `InvalidPathError`, `MissingDependencyError`, `ConversionError`, `ModelsNotAvailableError`, `CacheError`, `CacheNotFoundError`, `ProjectError`, `ProjectNotFoundError`, `ContextError` |

El paquete incluye `py.typed`: los tipos son utilizables por `mypy` en el código que lo consume.

## Consumidores conocidos

- [doc_organize_web](https://github.com/fmanza/doc_organize_web): la fija por versión (wheel de la GitHub Release con
  su hash) y solo la importa desde su capa anticorrupción. Antes de cambiar la API pública, revisa su
  `docs/plan/DOC_ORGANIZE_GAPS.md`.
