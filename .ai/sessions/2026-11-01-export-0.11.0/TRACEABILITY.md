# TRACEABILITY: Resumen de Sesión

## Sesión
- **Fecha**: 2026-11-01
- **Tipo**: `feature`
- **Rama**: `feature/export-0.11.0` → PR a `develop` (squash)
- **Estado**: ✅ COMPLETADA (pendiente de CI y publicación)

## Objetivo
Tarea L-7 del plan de doc_organize_web (hueco G8): exportación de un proyecto como API pública en
`doc_organize.export` (ZIP en *streaming* con vista previa exacta, Excel de caché y de errores), con rutas
explícitas, varias cachés, progreso y cancelación; la web integrada y un nuevo `doc_organize export` la usan.
Versión 0.11.0, solo L-7. Plan y auditoría del plan: [PLAN.md](PLAN.md).

## Cambios Ejecutados

### ✅ 1. Level 1 — `core/`
**Archivo(s)**: `core/progress.py`, `core/exceptions.py`
**Descripción**: `ProgressEvent.operation` admite `"export"` y `Phase` la fase `"export"`; `MissingDependencyError`
(`package`, `extra`) para dependencias opcionales ausentes.
**Status**: ✅

### ✅ 2. Level 3 — `export/`
**Archivo(s)**: `export/{__init__,sources,zip_export,xlsx_export,_progress}.py`
**Descripción**: `load_cache_entries` (varias `cache.db`, no crea las ausentes), `load_scan_error_history` (varios
JSONL, tolerante a líneas corruptas), `preview_project_zip`/`write_project_zip` (`ExportStats`), `write_cache_xlsx`,
`write_scan_errors_xlsx`. ZIP por bloques de 1 MiB, `cache_export.json` generado por trozos, sin temporales; Excel
con `openpyxl` `write_only` importado al escribir.
**Status**: ✅

### ✅ 3. Level 3 — consumidores
**Archivo(s)**: `web/routes/downloads.py`, `main.py`, `__init__.py`
**Descripción**: la web delega en `doc_organize.export` (mismas rutas, nombres y contenido; los 18 tests de
`test_web_downloads.py` pasan sin tocarlos). CLI `export zip | cache-xlsx | errors-xlsx`. Nombres en `__all__`.
**Status**: ✅

### ✅ 4. Empaquetado y documentación
**Archivo(s)**: `pyproject.toml`, `zensical.toml`, `docs/functional/export.md`, `docs/api/export.md`,
`docs/api/publica.md`, `docs/api/index.md`, `docs/guides/installation.md`, `README.md`, `CHANGELOG.md`,
`COMPATIBILITY.md`
**Descripción**: versión 0.11.0, extra `export` (`openpyxl>=3.1`), `openpyxl` y `types-openpyxl` en `dev`, fuera el
*override* de mypy de `pandas`.
**Status**: ✅

---

## AUDIT_CODE

| Aspecto | Hallazgo | Resolución |
|---|---|---|
| Bug potencial | `isoformat()` omite los microsegundos cuando valen 0: la vista previa y el ZIP podían diferir 7 bytes | `timespec="microseconds"`; test con marcas de tiempo de 0 y 123456 µs |
| Bug potencial | Destino dentro de `Conversión/`: el ZIP se incluiría a sí mismo mientras crece | `InvalidPathError` antes de abrir; test |
| Bug potencial | `ZipFile.write` rechaza ficheros con fecha anterior a 1980 (habitual en carpetas de red) | `ZipInfo.from_file(..., strict_timestamps=False)` |
| Bug potencial | Caracteres de control en mensajes de error hacían fallar el Excel (`IllegalCharacterError`), también antes | Se eliminan en `_excel_safe`; test |
| Edge case | `openpyxl` `write_only` deja `openpyxl.*.xml` en el temporal del sistema si no se llega a `save()` (hasta que acaba el proceso: en la web, nunca) | `_discard_temporary_sheets` los borra al cancelar o fallar; test con `tempfile.tempdir` aislado |
| Edge case | Flujo sin `seek` como destino | `zipfile` usa descriptores de datos; test con `RawIOBase` no posicionable |
| Edge case | Proyecto nunca escaneado / caché ausente | ZIP solo con instantánea vacía; no se crea `cache.db` |
| Edge case | Misma ruta en dos cachés | Gana la última caché (documentado y probado) |
| Performance | 100 000 entradas / 1 TB | Ficheros por bloques; JSON por trozos; la lista de entradas y de ficheros en memoria (~decenas de MB) |
| Seguridad | Inyección de fórmulas | `_excel_safe` en todas las columnas de texto (también `scan_run_id` y fecha); test sin celdas `data_type == "f"` |
| Seguridad | Enlaces simbólicos en `Conversión/` | `os.walk(followlinks=False)` y ficheros enlace omitidos; test (se salta en Windows sin privilegio) |
| Tipado | `openpyxl` sin tipos | `types-openpyxl` en `dev`; `mypy src` sin errores |
| Deuda técnica | `_discard_temporary_sheets` usa `ws._writer` (API privada de openpyxl 3.1) | Protegido con `getattr` y `suppress`; si cambia, vuelve al comportamiento de openpyxl |
| Deuda técnica | `pandas` sigue en `dependencies` sin usarse en `src/` | Retirarlo en una versión aparte (llega igualmente vía Docling) |
| Deuda técnica | `web/scan_errors_data.load_error_history` duplica el parseo de `load_scan_error_history` | Se retira con `web/` en 1.0.0 (L-11); no se toca por la política sin refactor |

## Impacto

### Código
- **Archivos creados**: 5 en `src/doc_organize/export/`, 3 de tests, 2 páginas de docs, artefactos de sesión.
- **Cambios funcionales**: sí — API nueva y subcomando CLI nuevo; la web se comporta igual (ver CHANGELOG para las
  diferencias menores: orden de `cache_export.json`, cabecera sin borde, symlinks fuera del ZIP).

### Compatibilidad
- **BREAKING**: ninguno.
- **NO BREAKING**: `ProgressEvent.operation`/`Phase` admiten un valor más (un `match` exhaustivo ve un caso nuevo).

---

## Verificación
```
.venv/Scripts/python.exe -m ruff check src tests            # All checks passed!
.venv/Scripts/python.exe -m mypy src                        # Success: no issues found in 92 source files
.venv/Scripts/python.exe -m pytest --doctest-modules src --no-cov   # 56 passed, 6 skipped
.venv/Scripts/python.exe -m pytest tests/ -m "not slow"     # 948 passed, 3 skipped, 21 deselected
cobertura export/: __init__ 100 %, _progress 100 %, sources 100 %, xlsx_export 99 %, zip_export 99 %; downloads.py 100 %
zensical build --strict                                     # No issues found
```

---

## Riesgos Residuales

| Riesgo | Mitigación | Status |
|--------|-----------|--------|
| El disco cambia entre vista previa y ZIP | Documentado: la vista previa es una instantánea | Aceptado |
| `cache_export.json` > 2 GiB (≈ 5 M entradas) no usa ZIP64 | Muy por encima de la escala objetivo (100 000) | Aceptado |
| Test de symlinks no corre en Windows local | Corre en el CI Linux | Aceptado |

---

## Siguientes Pasos (Recomendado)
1. doc_organize_web (Fase 5): fijar 0.11.0 y sustituir su copia de la exportación por `doc_organize.export`.
2. L-8, L-9 y L-9b en la siguiente versión; L-8 puede reutilizar `MissingDependencyError`.
3. Retirar `pandas` de `dependencies`.

---

## Directrices para Futuras IAs

- **[export]**: `src/doc_organize/export/` es el único sitio de ZIP/Excel de proyecto; `web/routes/downloads.py` solo resuelve el proyecto y sirve un temporal.
- **[export]**: la vista previa y el ZIP comparten `_conversion_members`, `_report_member` y `_snapshot_chunks`; cualquier fuente nueva del ZIP debe añadirse a los dos o el test `test_preview_matches_zip_contents_exactly` fallará.
- **[export]**: `cache_export.json` se genera a mano por trozos; `test_snapshot_json_matches_pydantic_serialization` garantiza que es idéntico a `CacheExportSnapshot.model_dump_json(indent=2)` — si cambia el modelo, ese test lo detecta.
- **[export]**: las escrituras son síncronas a propósito (zipfile/openpyxl); los consumidores async usan `asyncio.to_thread` y `on_progress` corre en ese hilo.
- **[dependencias opcionales]**: `MissingDependencyError(package, extra)` en `core/exceptions.py` es el error tipado para extras ausentes; importar la dependencia dentro de la función que la usa y comprobar con `test_importing_export_does_not_load_docling_nor_openpyxl`.
- **[openpyxl]**: `write_only` escribe cada hoja en `openpyxl.*.xml` del temporal del sistema y solo lo borra en `save()` o `atexit`; si se aborta antes, hay que limpiar (`_discard_temporary_sheets`).
- **[herramientas]**: no hay `.venv` versionado; `pip install -e ".[dev,docs]"` en `.venv` (ruta que espera el workspace). El ruff global puede ser de otra versión y reformatear ficheros ajenos: usar el de `.venv` y revisar `git status` antes del commit.

---

## Veredicto

### 🟢 COMPLETADA

**Criterios**:
- Condiciones del AUDIT_PLAN: `test_web_downloads.py` sin cambios y en verde; test de importación ligera de `export`; `zensical build --strict` sin avisos.

**Evidencia**:
- Branch: `feature/export-0.11.0`
- Commits: un commit `feat:` (squash en `develop`)
- Tests: 948 passed, 3 skipped (sin `slow`)

**Sesión cerrada**: 2026-11-01
