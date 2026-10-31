# TRACEABILITY: doc_organize 0.10.0 — API pública para doc_organize_web

## Sesión
- **Fecha**: 2026-10-31
- **Tipo**: `feature`
- **Rama**: `feature/api-publica-0.10.0` (desde `develop` `2a893a4`)
- **Estado**: ✅ COMPLETADA (pendiente de PR, CI y release `v0.10.0`)

## Objetivo
Dar a doc_organize_web una API pública estable sin romper el CLI ni la web integrada: tareas L-1…L-6d y L-13b de
`doc_organize_web/docs/plan/TAREAS_DOC_ORGANIZE.md`, que cierran los huecos G1–G7, G9, G13 y G15. Plan y condiciones
del mantenedor en [`PLAN.md`](PLAN.md).

## Cambios Ejecutados

### ✅ 1. L-1 + G15 — API pública con importación diferida (`42a5e8d`)
**Archivo(s)**: `src/doc_organize/__init__.py`, `py.typed`, `MANIFEST.in`, `docs/api/publica.md`, `tests/unit/test_public_api.py`
**Descripción**: `_EXPORTS` + `__getattr__` (PEP 562); `__version__` desde `importlib.metadata`. `import doc_organize`
pasa de ~49 s / ~4 300 módulos a ~0,5 s / ~300 (medido).

### ✅ 2. G13 — `ScanOptions` (`a0fe0a6`)
**Archivo(s)**: `core/models.py`, `scan/scan_command.py`, `tests/unit/test_scan_options.py`
**Descripción**: `options=` en `run`/`run_streaming`; los indicadores posicionales siguen funcionando.

### ✅ 3. L-3 — clientes de IA sin `auth` (`1dde83b`)
**Archivo(s)**: `ai/_secrets.py`, los cinco clientes, `tests/unit/test_ai_architecture.py`
**Descripción**: Protocol `SecretValueReader`; `*_from_store_or_env` emiten `DeprecationWarning` (se retiran en 1.0.0).

### ✅ 4. L-6c — `tenant_id` obsoleto (`a28a008`)
**Archivo(s)**: `projects/project_registry.py`, `tests/unit/test_project_registry.py`

### ✅ 5. L-6d — workflow de release (`99fc73f`)
**Archivo(s)**: `.github/workflows/release.yml`
**Descripción**: tag `v*` → comprueba versión, wheel + sdist + `.sha256`, importación sin Docling, GitHub Release.

### ✅ 6. L-4 / L-5 — `ProjectLayout` (`6248c8d`)
**Archivo(s)**: `projects/layout.py`, `dedup/deduplication.py`, `scan/scan_command.py`, `main.py`, `tests/unit/test_project_layout.py`
**Descripción**: `output_root` y `state_root` separables; `report_dir=`; test que impide derivar rutas a mano fuera de `web/`.

### ✅ 7. L-2 — progreso y cancelación (`7ec21f5`)
**Archivo(s)**: `core/progress.py`, `core/exceptions.py`, `scan/scan_command.py`, `context/context_builder.py`, `tests/unit/test_progress_and_cancel.py`
**Descripción**: `CancelToken`, `ProgressEvent`, `CANCELLED`; al cancelar se conserva lo ya convertido en caché.

### ✅ 8. L-6b — eventos versionados (`0ae8615`)
**Archivo(s)**: `core/models.py`, `tests/unit/test_event_contract.py`, `tests/unit/data/event_contract.json`

### ✅ 9. L-6 — deduplicación en dos pasos (`65b166c`)
**Archivo(s)**: `dedup/deduplication.py`, `core/models.py`, `scan/scan_command.py`, `tests/unit/test_dedup_modes.py`
**Descripción**: `group_id` estable; `DedupMode` `move` (por defecto) / `copy` / `report_only`.

### ✅ 10. L-13b — Zensical (`b64110f` + cierre)
**Archivo(s)**: `zensical.toml` (sustituye a `mkdocs.yml`), `pyproject.toml`, workflows, `scripts/build_docs_zip.py`, documentación operativa e instrucciones IA
**Descripción**: extra `docs` = zensical + mkdocstrings-python. El sitio de contexto (`MkDocsGenerator`) sigue con
mkdocs, ahora en el extra nuevo `site` (antes lo traía `docs`; detectado en el cierre).

### ✅ 11. Cierre de versión
**Archivo(s)**: `pyproject.toml` (0.10.0), `CHANGELOG.md`, `COMPATIBILITY.md`, `.ai/{runtime,standards,DECISIONS_LOG}.md` (revisión 17), plantilla de sesión

---

## Impacto

### Código
- **Archivos modificados/creados**: ~70 (21 en `src/`, +925/−113 en `src/`)
- **Cambios funcionales**: sí, todos aditivos (ver CHANGELOG `[0.10.0]`)

### Compatibilidad
- **BREAKING**: ninguno en la API Python. `DuplicateGroup.group_id` deja de ser aleatorio (sigue con forma de UUID).
  Quien instalase `[docs]` para el sitio de contexto debe instalar `[site]`.
- **NO BREAKING**: `tenant_id` y `*_from_store_or_env` avisan con `DeprecationWarning` y se retiran en 1.0.0.

---

## Verificación
```
python -m ruff check src tests      → All checks passed (ruff 0.15.22, la cota del CI es <0.16)
python -m mypy src                  → Success: no issues found in 87 source files
python -m pytest                    → 929 passed, 96 % cobertura (build/logs/pytest-0.10.0.txt)
zensical build --strict             → No issues found
python -c "import doc_organize; print(doc_organize.__version__)"  → 0.10.0
```

---

## Riesgos Residuales

| Riesgo | Mitigación | Status |
|--------|-----------|--------|
| `release.yml` no se ha ejecutado nunca | Primera ejecución con `v0.10.0`; si falla, se publica a mano como la 0.9.3 | Abierto |
| `ruff format --check` marca `ocr_scheduler.py` y `test_main.py` | Previo a esta rama; el CI no comprueba formato | Aceptado |
| ruff 0.16 en el venv local da 11 errores nuevos | Cota `<0.16` en `dev`; subir de versión es tarea aparte | Aceptado |

---

## Siguientes Pasos (Recomendado)
1. PR a `develop`, CI verde, PR `develop` → `main`, tag `v0.10.0` sobre el merge (después de verificarlo).
2. doc_organize_web: G1–G7, G9, G13 y G15 a «Resueltos» en `DOC_ORGANIZE_GAPS.md`; Fase 3 contra 0.10.0.
3. L-8 (sitio de contexto con Zensical) en la 0.11.0.

---

## Directrices para Futuras IAs

- **[api]**: los nombres públicos se declaran en `_EXPORTS` de `src/doc_organize/__init__.py`; añadir uno ahí es lo que lo publica, y `tests/unit/test_public_api.py` comprueba que la importación no carga Docling.
- **[rutas]**: toda ruta de proyecto (caché, carpetas, logs, duplicados, informes) sale de `ProjectLayout`; `test_project_layout.py` falla si un módulo fuera de `web/` la construye a mano.
- **[dedup]**: con `mode="move"` las llamadas internas a `move_group`/`_move_to_duplicates` deben quedar idénticas a antes, porque hay tests que las sustituyen con monkeypatch sin los parámetros nuevos.
- **[eventos]**: cambiar un evento exige subir `EVENT_SCHEMA_VERSION` y regenerar `tests/unit/data/event_contract.json`.
- **[docs]**: el sitio de la librería se construye con `zensical build --strict` (`zensical.toml`); el sitio de contexto de un proyecto sigue con mkdocs (extra `site`), son cosas distintas.
- **[herramientas]**: el venv local puede tener ruff ≥ 0.16; valida con `pip install "ruff<0.16"` antes de fiarte del resultado, que es la versión del CI.

---

## Veredicto

### 🟢 COMPLETADA

**Criterios**:
- Todas las tareas del PLAN implementadas con tests; suite, mypy, ruff y docs en verde.

**Evidencia**:
- Branch: `feature/api-publica-0.10.0`
- Commits: `42a5e8d` … `b64110f` + commit de cierre
- Tests: 929 passed

**Sesión cerrada**: 2026-10-31
