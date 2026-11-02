# TRACEABILITY: Resumen de Sesión

## Sesión
- **Fecha**: 2026-11-02
- **Tipo**: `feature`
- **Rama**: `feature/lectura-robustez-0.12.0` → PR a `develop` (squash)
- **Estado**: ✅ COMPLETADA (pendiente de CI y publicación)

## Objetivo
Tareas L-10a…L-10e del plan de doc_organize_web (huecos G16–G23): caché incremental, carpeta de modelos sin
descargas, nombre de la raíz en la salida, listado fallido sin borrar salidas y errores al cancelar, y API de lectura
sin Docling (rutas de salida, caché de solo lectura con filtros, `source_path` relativo). Versión 0.12.0. Plan y
auditoría del plan: [PLAN.md](PLAN.md).

## Cambios Ejecutados

### ✅ 1. Level 1 — `core/`
**Archivo(s)**: `core/models.py`, `core/exceptions.py`
**Descripción**: `ScanOptions` con `cache_save_every`, `cache_save_seconds`, `artifacts_path`,
`allow_model_downloads`, `root_name_in_output`, `json_source_path`; `ScanResult.unreadable_dirs`;
`CacheNotFoundError(CacheError)` y `ModelsNotAvailableError(ConversionError)`.
**Status**: ✅

### ✅ 2. Level 2 — rutas, conversión, escáner y caché
**Archivo(s)**: `projects/layout.py`, `converter/converter.py`, `converter/ocr_scheduler.py`,
`scanner/document_scanner.py`, `cache/cache_manager.py`
**Descripción**: `resolve_output_paths` (con `include_root_name`), `resolve_images_dir` y `relative_source_path` en
`projects/layout.py` (sin Docling), alias en `DocumentConverter`; `artifacts_path`/`allow_model_downloads` con
inicialización anticipada del pipeline PDF/imagen; `source_path` relativo; carpetas ilegibles anotadas;
`CacheManager(read_only=True)` y filtros `relative_to=`/`conversion_status=`.
**Status**: ✅

### ✅ 3. Level 3 — orquestación y API pública
**Archivo(s)**: `scan/scan_command.py`, `__init__.py`, `projects/__init__.py`
**Descripción**: `_CacheCheckpoint` (guardado cada N documentos o X segundos) y guardado en el camino de excepción /
`aclose()`; `ScanErrorReport` al cancelar; huérfanos protegidos bajo carpetas ilegibles; aviso de salidas compartidas
entre raíces; opciones nuevas pasadas a la conversión solo si no son las de por defecto. Nombres nuevos en `__all__`
(más `ConversionStatus` y `DocumentStatus`).
**Status**: ✅

### ✅ 4. Tests, documentación y versión
**Archivo(s)**: `tests/unit/test_scan_robustness.py` (nuevo), `test_cache_manager.py`, `test_converter.py`,
`test_project_layout.py`, `test_public_api.py`; `docs/api/{publica,cache,converter,projects,scanner}.md`,
`docs/functional/converter.md`, `CHANGELOG.md` (con firmas finales), `COMPATIBILITY.md`, `pyproject.toml` (0.12.0)
**Status**: ✅

---

## AUDIT_CODE

| Aspecto | Hallazgo | Resolución |
|---|---|---|
| Bug potencial | Un guardado intermedio que falla (`database is locked`) abortaría un escaneo que antes terminaba | Best-effort con aviso y reintento en el siguiente; el guardado final sigue propagando. Test |
| Bug potencial | `ModelsNotAvailableError` dentro del lote de OCR: la tarea solo reenviaba `OSError/ValueError/RuntimeError/TypeError` a la cola; cualquier otro error dejaba el generador esperando | Se reenvía también `DocOrganizeError` |
| Bug potencial | Comprobar modelos con un `.docx` fallaría sin necesidad (no usa modelos) | Solo se comprueba con extensiones del pipeline PDF/imagen (`FormatToExtensions`). Test con HTML |
| Edge case | `a.pdf` y `a.docx` de una misma raíz ya compartían salida; el aviso sugeriría una opción que no lo resuelve | El aviso solo cubre colisiones entre raíces distintas; máximo 20 avisos. Test |
| Edge case | Fichero que no es SQLite abierto en solo lectura | `CacheError` tipado. Test |
| Edge case | Ruta de caché con espacios y no ASCII en la URI `mode=ro` | `Path.as_uri()`; test con «Conversión ñ» |
| Edge case | Caché con escritor abierto (WAL) leída en solo lectura | Test: el lector ve lo que el escritor confirma |
| Edge case | `force` con carpeta ilegible | No se borran salidas y se conservan entradas de caché; un fichero borrado de verdad sí se limpia. Test |
| Edge case | Dos raíces con el mismo nombre | Siguen colisionando con `root_name_in_output`: documentado |
| Edge case | Corte durante el OCR | Los resultados llegan al final del lote: quedan en `ocr_pending` (se repite el OCR, no la conversión). Documentado |
| Performance | Aviso de colisiones: dos `resolve()` por documento, solo con varias raíces y la opción desactivada | Aceptado (la conversión ya resuelve cada ruta) |
| Seguridad | `source_path` absoluto llegaba al ZIP | Relativo por defecto; `relative_source_path` nunca devuelve rutas absolutas |
| Seguridad | Filtros SQL | Parámetros ligados; la ruta relativa se calcula en una función SQL registrada (`py_relpath`) |
| Tipado | `mypy src` sin errores; `Literal["relative", "absolute"]` en las firmas | — |
| Deuda técnica | Sin migración en solo lectura (error claro); sin guardado incremental dentro del lote de OCR | Aceptado y documentado |

## VERSION

- **Commit (squash)**: `feat: robustez del escaneo y API de lectura (L-10a…L-10e) y versión 0.12.0`
- **Impacto en API pública**: aditivo (parámetros *keyword-only* opcionales, campos con valor por defecto, nombres
  nuevos). Cambio de comportamiento documentado: `source_path` del JSON relativo por defecto.
- **Rollback**: revertir el commit de squash en `develop` (no hay migraciones de datos; las cachés no cambian de
  esquema). Los JSON generados con 0.12.0 llevan `source_path` relativo hasta reconvertirse.
- **Verificación**: `ruff check`, `ruff format --check src`, `mypy src`, `pytest` (suite completa) y
  `zensical build --strict` en verde.
