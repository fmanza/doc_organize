# PLAN + AUDIT_PLAN — doc_organize 0.12.0: robustez del escaneo y API de lectura (L-10a…L-10e, huecos G16–G23)

Origen: `doc_organize_web/docs/plan/DOC_ORGANIZE_GAPS.md` (G16–G23) y `TAREAS_DOC_ORGANIZE.md` («Peticiones de las
Fases 4 y 5»). Flujo `/new-feature`, rama `feature/lectura-robustez-0.12.0`, PR a `develop` con squash.

> Versión: 0.12.0 (MINOR: todo es aditivo salvo el valor por defecto de `source_path` en el JSON, pedido por el
> consumidor y documentado). El plan de la web reservaba 0.12.0 para L-10 (deprecación de la web integrada); esa
> tarea pasa a la siguiente MINOR.

## Estado de partida (verificado en `develop`, 0.11.0)

| Punto | Estado real |
|---|---|
| G16 | `_run_pipeline` guarda `entries` solo tras convertir todo o al cancelar (`OperationCancelledError`); cualquier otra excepción, un `aclose()` o un `kill` pierden la caché del escaneo |
| G17 | `DocumentConverter()` sin parámetros; `PdfPipelineOptions` sin `artifacts_path`; Docling descarga modelos al vuelo la primera vez |
| G18 | `resolve_output_paths` usa la ruta relativa a la raíz más profunda, sin su nombre: `2024/x/a.pdf` y `2025/x/a.pdf` → `x/a.md` |
| G19 | `DocumentScanner._list_dir_entries` traga el `OSError` y devuelve `[]`; con `force`, los documentos de esa carpeta pasan a huérfanos y se borran sus salidas. Al cancelar no se escribe `ScanErrorReport` |
| G20 | `resolve_output_paths`/`resolve_images_dir` son `staticmethod` de `converter/converter.py` (importa Docling) |
| G21 | `CacheManager.__aenter__` pone WAL, crea la tabla y migra columnas siempre |
| G22 | `count_entries`/`load_cache_page` filtran solo con `LIKE` sobre la ruta absoluta |
| G23 | `_write_outputs` escribe `"source_path": source_doc.full_path` (absoluta) |

## PLAN

**Objetivo**: que un escaneo interrumpido no pierda la caché ni borre salidas por un listado fallido, que la
conversión pueda funcionar sin red con una carpeta de modelos, que varias raíces no colisionen en la salida, y dar a
la web una API de lectura sin Docling (rutas de salida, caché de solo lectura con filtros, JSON sin rutas del
servidor).

**Rutas afectadas**

- Level 1: `core/models.py` (`ScanOptions`, `ScanResult`), `core/exceptions.py`.
- Level 2: `projects/layout.py` (funciones de ruta), `converter/converter.py`, `converter/ocr_scheduler.py`,
  `scanner/document_scanner.py`, `cache/cache_manager.py`.
- Level 3: `scan/scan_command.py`, `__init__.py`, `projects/__init__.py`.
- Tests: `tests/unit/test_scan_robustness.py` (nuevo: L-10a, L-10c, L-10d), `test_cache_manager.py`,
  `test_converter.py`, `test_document_scanner.py`, `test_project_layout.py`, `test_public_api.py`.
- Docs: `docs/api/publica.md`, `docs/api/projects.md`, `docs/api/cache.md`, `CHANGELOG.md`, `COMPATIBILITY.md`,
  `pyproject.toml` (versión).

**API (firmas finales)**

| Punto | Nombre | Firma / cambio |
|---|---|---|
| L-10a | `ScanOptions.cache_save_every` | `int = 20` (`ge=0`; 0 desactiva el disparo por número) |
| L-10a | `ScanOptions.cache_save_seconds` | `float = 30.0` (`ge=0`; 0 desactiva el disparo por tiempo) |
| L-10b | `ScanOptions.artifacts_path` | `Path \| None = None` |
| L-10b | `ScanOptions.allow_model_downloads` | `bool = True` |
| L-10b | `DocumentConverter.__init__` | `(*, artifacts_path: Path \| str \| None = None, allow_model_downloads: bool = True)` |
| L-10b | `OCRScheduler.__init__` | `(*, artifacts_path=None, allow_model_downloads=True)` |
| L-10b | `ModelsNotAvailableError` | `ConversionError`; se **propaga** (no es un fallo de un documento) |
| L-10c | `ScanOptions.root_name_in_output` | `bool = False` |
| L-10c | `resolve_output_paths` | `(full_path, output_dir, scan_roots=(), *, include_root_name=False) -> tuple[Path, Path]` |
| L-10d | `ScanResult.unreadable_dirs` | `list[str] = []` |
| L-10e | `relative_source_path` | `(full_path, scan_roots=()) -> str` (POSIX; nombre del fichero si no cuelga de ninguna raíz) |
| L-10e | `ScanOptions.json_source_path` | `Literal["relative", "absolute"] = "relative"` |
| L-10e | `DocumentConverter.convert_document` / `OCRScheduler.process_with_ocr` | `*, include_root_name=False, json_source_path="relative"` |
| L-10e | `resolve_output_paths`, `resolve_images_dir` | En `doc_organize.projects.layout`; `DocumentConverter.*` quedan como alias |
| L-10e | `CacheManager.__init__` | `(db_path=..., *, read_only: bool = False)` |
| L-10e | `CacheNotFoundError` | `CacheError`; `read_only=True` y la caché no existe |
| L-10e | `count_entries` | `(search=None, *, relative_to: str \| Path \| None = None, conversion_status: ConversionStatus \| str \| None = None) -> int` |
| L-10e | `load_cache_page` | `(limit, offset, search=None, *, relative_to=None, conversion_status=None) -> list[CacheEntry]` |

**Contratos**

- L-10a: durante la conversión se guardan en `cache.db` las entradas nuevas cada `cache_save_every` documentos o
  cuando pasan `cache_save_seconds` desde el último guardado; ante cualquier excepción (o `aclose()` del generador)
  se guarda lo convertido antes de propagarla (sin enmascararla si el guardado falla). Upsert idempotente.
- L-10b: `artifacts_path` se pasa a `PdfPipelineOptions.artifacts_path` (Docling carga los modelos solo de ahí, sin
  red). Con `allow_model_downloads=False` hace falta una carpeta (la indicada o `DOCLING_ARTIFACTS_PATH`) y el
  pipeline PDF/imagen se inicializa antes del primer documento (`initialize_pipeline`): si falla, se lanza
  `ModelsNotAvailableError` en lugar de marcar cada documento como error. Con `True` (por defecto) todo sigue igual.
- L-10c: `include_root_name=True` antepone el nombre de la raíz (`2024/x/a.md`). Por defecto nada cambia. Con varias
  raíces y la opción desactivada, si dos documentos van a la misma salida se añade un aviso al evento `SCANNED`.
- L-10d: las carpetas que no se pueden listar (o una raíz inaccesible) quedan en `ScanResult.unreadable_dirs` y en
  los avisos de `SCANNED`; con `force` sus documentos no se tratan como huérfanos (no se borran sus salidas y se
  conservan sus entradas de caché). Al cancelar se escribe el `ScanErrorReport` de lo procesado.
- L-10e: `source_path` del JSON relativo a la raíz escaneada (POSIX) por defecto; `"absolute"` recupera lo de antes.
  `read_only=True`: URI `mode=ro`, sin `PRAGMA WAL`/`CREATE`/`ALTER`; `CacheNotFoundError` si el fichero no existe,
  `CacheError` si la tabla o columnas no están (caché sin migrar) o si se intenta escribir. `relative_to=` limita a
  las entradas bajo esa raíz y aplica `search` a la ruta relativa; `conversion_status=` filtra por estado.

**Reglas de negocio**: no borrar salidas sin evidencia de que el origen desapareció; orden y resultados
deterministas; no inventar rutas (la relativa sale de las raíces del propio escaneo).

**Restricciones técnicas**: sin dependencias nuevas; `projects/layout.py` no importa Docling (test en subproceso);
API pública solo crece (parámetros opcionales, *keyword-only*); `ScanOptions` sigue `frozen`/`extra="forbid"`.

**Riesgos**

- Funcional: cambiar el valor por defecto de `source_path` afecta a quien lea ese campo (en la librería nadie lo lee;
  la web lo reescribía ya). Activar `root_name_in_output` en un proyecto existente mueve las salidas (requiere
  `force`).
- Técnico: guardado en el camino de `GeneratorExit`/`CancelledError` dentro de un generador async; el modo `ro`
  sobre una base en WAL; la inicialización anticipada de Docling.
- Seguridad: `source_path` absoluto filtraba rutas del servidor al ZIP (se corrige por defecto).

## AUDIT_PLAN

**Riesgos funcionales**

- Auto-incluir la raíz con varias raíces (lo que sugiere la petición) cambiaría la salida de proyectos existentes
  multi-raíz sin reconvertirlos (la caché dice «convertido» y la salida nueva no existiría). Por eso es **opción**
  (`root_name_in_output`), más el aviso de colisión. Dos raíces con el mismo nombre (`a/2024`, `b/2024`) siguen
  colisionando incluso con la opción: se documenta.
- Propagar el `OSError` de listado abortaría escaneos enteros por una subcarpeta sin permisos (`System Volume
  Information`, carpetas de otros usuarios): se elige la alternativa «mínima» de la petición, más exposición tipada
  (`unreadable_dirs`).
- Durante el OCR, los resultados llegan al final del lote: un `kill` en esa fase deja los documentos en
  `ocr_pending` (se repite el OCR, no la conversión). Se documenta.

**Riesgos técnicos (LSP/ISP)**

- Contratos async sin cambios; todos los parámetros nuevos son opcionales y *keyword-only* (sin desplazar
  posicionales). Los alias de `DocumentConverter` mantienen la firma (más el *keyword* nuevo).
- `ScanCommand` usa internamente `ScanOptions` para lo nuevo; los métodos privados reciben `options` con valor por
  defecto para no romper los tests que los llaman.
- `mode=ro` con WAL: SQLite necesita `-shm`; en el caso de la web (directorio con permisos) funciona; test con una
  conexión escritora abierta a la vez.

**Riesgos de seguridad**: `relative_to` y `search` van como parámetros ligados (sin SQL dinámico con datos del
usuario); `relative_source_path` nunca devuelve rutas absolutas.

**Simplificaciones**: sin error tipado de listado (no se propaga); sin migración de esquema en solo lectura (error
claro); sin guardado incremental dentro del lote de OCR.

**Veredicto: GO_CONDICIONAL** — condiciones: (1) `root_name_in_output` opcional, por defecto sin cambios; (2) tests de
regresión de rutas de salida y de `DocumentConverter.resolve_*` sin tocar; (3) `zensical build --strict` limpio.
