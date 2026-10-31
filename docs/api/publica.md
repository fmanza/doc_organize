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

## Grupos de nombres

| Grupo | Nombres |
|---|---|
| Escaneo y conversión | `ScanCommand`, `ScanSummary`, `DocumentScanner`, `DocumentConverter`, `OCRScheduler`, `CacheManager` |
| Duplicados | `DeduplicationManager`, `DeduplicationSummary`, `DuplicateGroup`, `DuplicateReason`, `DeduplicationReport` |
| Contexto | `ContextBuilder`, `ContextRegistry`, `Reorganizer`, `MkDocsGenerator`, `TaxonomyTemplateRegistry`, `Context`, `TaxonomyManifest` |
| Proyectos (CLI) | `ProjectRegistry`, `ProjectHistoryCleaner`, `ScannedFoldersStore`, `Project`, `ScannedFolder`, `FolderValidator`, `ProjectValidator` |
| Eventos de progreso | `ScanEvent`/`ScanEventType`, `DedupEvent`/`DedupEventType`, `ContextBuildEvent`/`ContextBuildEventType`, `ContextDeleteEvent`/`ContextDeleteEventType` |
| Modelos | `DocumentMetadata`, `ConversionResult`, `CacheEntry`, `ScanResult`, `ScanErrorEntry`, `ScanErrorReport`, `ScanRunReport` |
| Diagnóstico | `detect_gpu_status`, `detect_av_status`, `detect_office_status`, `GpuStatus`, `AvStatus`, `OfficeStatus` |
| Errores | `DocOrganizeError` (base), `InvalidPathError`, `ConversionError`, `CacheError`, `ProjectError`, `ProjectNotFoundError`, `ContextError` |

El paquete incluye `py.typed`: los tipos son utilizables por `mypy` en el código que lo consume.

## Consumidores conocidos

- [doc_organize_web](https://github.com/fmanza/doc_organize_web): la fija por versión (wheel de la GitHub Release con
  su hash) y solo la importa desde su capa anticorrupción. Antes de cambiar la API pública, revisa su
  `docs/plan/DOC_ORGANIZE_GAPS.md`.
