# PLAN + AUDIT_PLAN — doc_organize 0.11.0: módulo `doc_organize.export` (L-7, hueco G8)

Origen: `doc_organize_web/docs/plan/TAREAS_DOC_ORGANIZE.md` (L-7) y requisitos de la Fase 5 de doc_organize_web.
Alcance: **solo L-7**; L-8, L-9 y L-9b quedan para otra versión. Flujo `/new-feature`, rama
`feature/export-0.11.0`, PR a `develop` con squash.

## Estado de partida (verificado en `develop`, 2026-11-01, 0.10.0)

| Punto | Estado real |
|---|---|
| `web/routes/downloads.py` | Única implementación de ZIP, vista previa, Excel de caché y Excel de errores. Deriva todo de `project.root_path` (registro JSON) y de **un** `cache.db` |
| ZIP | `zipfile.ZipFile` sobre un `tempfile.mkstemp` del sistema; `rglob` + `zip_file.write` (sin cancelación ni progreso); `cache_export.json` se construye entero en memoria con `model_dump_json(indent=2)` |
| Vista previa | Recorre `Conversión/` por separado y vuelve a serializar el snapshot: el tamaño del JSON depende de `datetime.now().isoformat()`, que omite los microsegundos cuando valen 0 (desajuste posible de 7 bytes) |
| Excel | `pandas.DataFrame.to_excel` (no `write_only`); `_excel_safe` antepone `'` a los valores que empiezan por `= + - @ \t \r` |
| Errores de escaneo | `web/scan_errors_data.py` (`load_current_errors`, `load_error_history`) a partir de `Project` |
| `ProgressEvent.operation` | `Literal["scan", "deduplicate", "context_build"]`; `Phase` sin fase de exportación |
| openpyxl | Solo en el extra `web` (y transitivamente vía Docling); no hay extra `export` |
| CLI | Sin subcomando `export` |

## PLAN

**Objetivo**: exponer la exportación de un proyecto como API pública sin web ni registro: ZIP en *streaming* con
vista previa exacta, Excel de caché y Excel de errores, con progreso y cancelación; la web y el CLI la usan.

**Rutas afectadas**

- Nuevas: `src/doc_organize/export/{__init__,sources,zip_export,xlsx_export,_progress}.py`,
  `tests/unit/test_export_*.py`, `docs/functional/export.md`, `docs/api/export.md`.
- Modificadas: `core/progress.py` (operación `export`, fase `export`), `core/exceptions.py`
  (`MissingDependencyError`), `__init__.py` (`_EXPORTS`), `web/routes/downloads.py`, `main.py`, `pyproject.toml`
  (versión, extra `export`, override mypy de `openpyxl`), `zensical.toml`, `docs/api/publica.md`, `README.md`,
  `docs/guides/installation.md`, `CHANGELOG.md`, `COMPATIBILITY.md`.

**Componentes y API** (`doc_organize.export`)

| Nombre | Firma | Notas |
|---|---|---|
| `load_cache_entries` | `async (cache_dbs: Iterable[Path]) -> list[CacheEntry]` | Varias cachés; omite las que no existen (no crea `cache.db`); si una ruta se repite en dos cachés gana la última |
| `load_scan_error_history` | `(history_logs: Iterable[Path]) -> list[ScanErrorReport]` | Varios JSONL; tolera líneas corruptas; más recientes primero |
| `ExportStats` | modelo Pydantic congelado `file_count`, `total_size_bytes` | Lo que devuelve la vista previa y lo que escribe el ZIP |
| `preview_project_zip` | `(entries, *, layout=None, conversion_dir=None, dedup_report=None) -> ExportStats` | Mismo recorrido y mismo JSON que el ZIP |
| `write_project_zip` | `(destination: Path \| BinaryIO, entries, *, layout=None, conversion_dir=None, dedup_report=None, on_progress=None, cancel_token=None) -> ExportStats` | *Streaming*, copia por bloques de 1 MiB |
| `write_cache_xlsx` | `(destination, entries, *, on_progress=None, cancel_token=None) -> int` | Hoja «Cache», filas ordenadas por `file_path` |
| `write_scan_errors_xlsx` | `(destination, entries, history, *, on_progress=None, cancel_token=None) -> int` | Hojas «Estado actual» e «Histórico» |
| `MissingDependencyError` | `DocOrganizeError` con `extra` | Error tipado si falta `openpyxl` (reutilizable por L-8) |

Contrato de entrada: entradas ya cargadas (iterable de `CacheEntry`, de una o varias cachés) y rutas explícitas
(`ProjectLayout` **o** `conversion_dir`/`dedup_report`, mutuamente excluyentes). Funciones síncronas: el consumidor
async las llama con `asyncio.to_thread`; `CancelToken` es seguro entre hilos.

Contrato de salida:

- ZIP: `Conversión/<ruta relativa>` (orden alfabético estable), `cache_export.json` (instantánea con todas las
  entradas ordenadas por `file_path`), `duplicados/DEDUP_REPORT.json` si existe.
- `preview_project_zip(...) == write_project_zip(...)` y ambos coinciden con `infolist()` del ZIP
  (nº de entradas y suma de `file_size`), salvo que el disco cambie entre las dos llamadas.
- Cancelación o error: si `destination` es una ruta, se borra el fichero parcial; se relanza
  (`OperationCancelledError` al cancelar). Si es un fichero abierto, su limpieza es del llamador.
- `on_progress`: `ProgressEvent(operation="export", phase="started"|"export"|"done", processed, total, current)`; un
  fallo del callback se registra y no para la exportación (igual que `ScanCommand`).

**Reglas de negocio**: no inventar datos (el JSON y las hojas solo contienen lo que hay en caché/historial); orden
determinista; escapado de fórmulas igual que hoy; sin `project_root` implícito ni registro JSON en `export/`.

**Restricciones técnicas**: `export/` depende solo de Nivel 1 (`core`, `utils`), `cache/` y `projects/layout`; no
importa `web/` ni `auth/` ni Docling; `openpyxl` se importa dentro de las funciones Excel. Sin temporales fuera del
destino.

**CLI**: `doc_organize export {zip,cache-xlsx,errors-xlsx}` con `--project` (registro del CLI) o
`--output-root`/`--state-root`; `--cache-file` y `--errors-log` repetibles; `-o/--output`; `zip --preview`.

**Riesgos**

- Funcional: la web cambia de implementación; los 18 tests de `test_web_downloads.py` deben seguir verdes sin tocarlos.
- Técnico: ampliar los `Literal` de `ProgressEvent` (aditivo); `openpyxl` sin tipos (override de mypy).
- Seguridad: inyección de fórmulas (se conserva `_excel_safe`), enlaces simbólicos en `Conversión/` que apunten fuera,
  destino dentro de `Conversión/` (el ZIP se incluiría a sí mismo).

## AUDIT_PLAN

**Riesgos funcionales**

- Orden de `cache_export.json`: hoy es el de `load_cache()`; pasa a ordenarse por `file_path` (determinista con
  varias cachés). Estructura y claves iguales; ningún test depende del orden.
- `export_timestamp` con `timespec="microseconds"` (longitud fija) para que la vista previa no pueda desviarse.
- La web dejaba creado un `cache.db` vacío al exportar un proyecto nunca escaneado; `load_cache_entries` no lo crea
  (efecto lateral eliminado, sin impacto visible).
- Cabecera del Excel: pandas la escribía en negrita con borde; con `write_only` se mantiene en negrita, sin borde.

**Riesgos técnicos (LSP/ISP)**

- Contratos síncronos homogéneos (todas las escrituras son `def`, solo la carga de cachés es `async` porque
  `CacheManager` lo es): no se mezclan sync/async en una misma función.
- Interfaces pequeñas: cuatro funciones de escritura con los mismos parámetros de progreso/cancelación; sin clase
  «Exporter» con estado (no lo necesita).
- `ProgressEvent.operation`/`Phase` crecen: un `match` exhaustivo del consumidor verá un caso nuevo (MINOR, documentado).
- ZIP64: `force_zip64` cuando el fichero supera ~2 GiB (mismo criterio que `ZipFile.write`).

**Riesgos de seguridad**

- Fórmulas: `_excel_safe` en todas las columnas de texto procedentes de rutas y mensajes (igual que hoy).
- Caracteres de control en mensajes de error: openpyxl lanza `IllegalCharacterError`; se eliminan antes de escribir.
- Enlaces simbólicos: `os.walk(followlinks=False)` y se omiten ficheros enlace; un symlink en `Conversión/` no puede
  colar ficheros de fuera en el ZIP.
- Destino dentro de `conversion_dir`: `InvalidPathError` antes de abrir nada.

**Simplificaciones posibles**

- Sin `ZipSources`/`ExportRequest` adicionales: `layout` o rutas sueltas como argumentos con nombre.
- `ExportStats` sirve para vista previa y resultado del ZIP (un solo tipo).
- `web/scan_errors_data.py` no se toca (política sin refactor): `downloads.py` sigue usando su `load_error_history`
  y pasa las entradas de caché a `write_scan_errors_xlsx`.
- `pandas` deja de usarse en `src/`; su retirada de `dependencies` queda como deuda (cambio de dependencias aparte).

**Veredicto: GO_CONDICIONAL**

1. `tests/unit/test_web_downloads.py` pasa sin modificaciones.
2. Test de importación ligera ampliado a `doc_organize.export` (sin Docling ni openpyxl al importar).
3. `zensical build --strict` sin avisos con las páginas nuevas.
