# Exportación — Referencia Técnica

`doc_organize.export` (desde la 0.11.0, tarea L-7). Nivel 3: usa `cache/` y `projects/layout` y no importa Docling. Funcionalidad: [Exportación](../functional/export.md).

## API pública

| Nombre | Firma | Devuelve |
|---|---|---|
| `load_cache_entries` | `async (cache_dbs: Iterable[str \| Path])` | `list[CacheEntry]` |
| `load_scan_error_history` | `(history_logs: Iterable[str \| Path])` | `list[ScanErrorReport]`, más recientes primero |
| `preview_project_zip` | `(entries, *, layout=None, conversion_dir=None, dedup_report=None)` | `ExportStats` |
| `write_project_zip` | `(destination, entries, *, layout=None, conversion_dir=None, dedup_report=None, on_progress=None, cancel_token=None)` | `ExportStats` |
| `write_cache_xlsx` | `(destination, entries, *, on_progress=None, cancel_token=None)` | filas escritas |
| `write_scan_errors_xlsx` | `(destination, entries, history, *, on_progress=None, cancel_token=None)` | filas escritas |
| `ExportStats` | `file_count`, `total_size_bytes` (modelo Pydantic congelado) | — |
| `MissingDependencyError` | `package`, `extra` (en `doc_organize.core.exceptions`) | — |

- `destination`: ruta (se crea o sobrescribe) o fichero binario abierto para escritura. El ZIP admite flujos sin
  `seek`. Si la escritura se cancela o falla, una ruta se borra; un fichero abierto lo descarta el llamador.
- `layout` y `conversion_dir`/`dedup_report` son excluyentes (`ValueError` si se combinan).
- Las escrituras son síncronas. Desde código async: `await asyncio.to_thread(write_project_zip, ...)`; el
  `CancelToken` es seguro entre hilos.
- `on_progress` recibe `ProgressEvent(operation="export")` con fase `started`, `export` (una por fichero del ZIP o
  fila del Excel; en el ZIP `current` es el nombre dentro del archivo) y `done`. Un fallo del callback se registra y no
  para la exportación. El callback corre en el hilo que escribe: con `asyncio.to_thread`, para tocar el event loop
  hay que usar `loop.call_soon_threadsafe`.

## Uso desde un consumidor async

```python
import asyncio
from pathlib import Path

from doc_organize import CancelToken, ProjectLayout
from doc_organize.export import load_cache_entries, preview_project_zip, write_project_zip

layout = ProjectLayout(Path("/red/Proyecto"), state_root=Path("/local/estado/7"))
cache_dbs = [layout.state_dir / carpeta / "cache.db" for carpeta in ("origen_a", "origen_b")]


async def exportar(destino: Path, token: CancelToken) -> None:
    entries = await load_cache_entries(cache_dbs)
    preview = await asyncio.to_thread(preview_project_zip, entries, layout=layout)
    print(f"{preview.file_count} ficheros, {preview.total_size_bytes} bytes")
    await asyncio.to_thread(write_project_zip, destino, entries, layout=layout, cancel_token=token)
```

## Formato del ZIP

| Nombre en el ZIP | Origen |
|---|---|
| `Conversión/<ruta relativa>` | `conversion_dir` (o `layout.conversion_dir`), recorrido alfabético, sin enlaces simbólicos |
| `cache_export.json` | `CacheExportSnapshot` con sangría de 2; `export_timestamp` ISO 8601 con microsegundos; entradas ordenadas por `file_path` |
| `duplicados/DEDUP_REPORT.json` | `dedup_report` (o `layout.dedup_report`), si existe |

Compresión `ZIP_DEFLATED`; ZIP64 automático para ficheros de más de 2 GiB.

## Excel

`openpyxl` en modo `write_only`, importado al escribir. Ese modo guarda el XML de cada hoja en un temporal del
sistema hasta `save()`; si la escritura se cancela o falla, se borran en el momento. Cabeceras exportadas como
constantes: `CACHE_COLUMNS`, `SCAN_ERRORS_CURRENT_COLUMNS`, `SCAN_ERRORS_HISTORY_COLUMNS` (en
`doc_organize.export.xlsx_export`).

## Referencia generada

::: doc_organize.export.sources

::: doc_organize.export.zip_export

::: doc_organize.export.xlsx_export
