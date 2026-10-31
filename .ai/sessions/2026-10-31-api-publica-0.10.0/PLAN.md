# PLAN + AUDIT_PLAN — doc_organize 0.10.0: API pública para doc_organize_web (sin romper nada)

Origen: plan de separación librería/web (`doc_organize_web/docs/plan/TAREAS_DOC_ORGANIZE.md`, tareas L-1…L-6d) y
huecos G1–G7, G9, G13 y G15 de `doc_organize_web/docs/plan/DOC_ORGANIZE_GAPS.md`. Flujo: `/new-feature` por ola,
una sola release **0.10.0** al final. Ningún cambio incompatible: lo que se retira se marca *deprecated* (se elimina en
1.0.0).

## Estado de partida (verificado en `develop`, 2026-10-31, 0.9.3)

| Punto | Estado real |
|---|---|
| `__init__.py` | Importa `CacheManager`, `DocumentConverter` (Docling), `DeduplicationManager`… al importar el paquete: cualquier `import doc_organize.<x>` carga Docling y torch (~4 300 módulos, 49 s en frío medido) — **G15** |
| `__all__` | 8 nombres; faltan `ScanCommand`, `ContextBuilder`, `Reorganizer`, eventos y modelos — G1 |
| `ScanCommand.run_streaming` | 12 parámetros posicionales (G13); sin `on_progress`/`cancel_token` (G2); `cache_db`, `folders_json`, `error_log_path`, `history_log_path` ya son explícitos |
| Deduplicación | Ya separada del escaneo (`deduplicate_streaming`); `resolve_duplicates(groups, duplicates_dir)` **mueve** siempre; `DuplicateGroup.group_id` es un UUID aleatorio (no estable entre ejecuciones) — G6 |
| Eventos | `ScanEvent(event, data: dict)` sin versión de esquema — G7 |
| `ai/` | Los 5 clientes importan `doc_organize.auth.InstanceSecretsStore` — G3 |
| Rutas | `cache.db`, `folders.json`, `duplicados/`, `DEDUP_REPORT.json`, historial y errores se derivan en `main.py` y en `web/routes/*` a partir de constantes de `core/constants.py` — G4, G5 |
| Proyectos | `Project.tenant_id` y `ProjectRegistry(..., tenant_id=)` — G4 |
| Release | Publicada a mano (0.9.3); sin workflow de release — G9 |

## Olas (una rama `feature/api-publica-0.10.0`, un commit por tarea, PR al final)

### Ola A — bases (L-1, G15, L-3, L-6c, L-6d)

- **L-1 + G15**: `__init__` **ligero** con importación diferida (PEP 562 `__getattr__`): los mismos nombres públicos,
  pero `import doc_organize` y `import doc_organize.utils.*` ya no cargan Docling. `__version__` desde
  `importlib.metadata`. `__all__` con los puntos de entrada reales (`ScanCommand`, `ScanOptions`,
  `DeduplicationManager`, `CacheManager`, `ContextBuilder`, `Reorganizer`, `MkDocsGenerator`,
  `TaxonomyTemplateRegistry`, `ProjectLayout`, `CancelToken`, `OperationCancelledError`, eventos y modelos). `py.typed`
  (verificar si ya existe). Página «API pública y compatibilidad» en `docs/`.
- **G13**: `ScanOptions` (modelo Pydantic con los flags) y `run_streaming(..., *, options=...)`; la firma posicional
  actual sigue funcionando con `DeprecationWarning`.
- **L-3**: los clientes de `ai/` reciben solo su `*Config`; `*_config_from_env()` se mantiene; la vía que lee
  `InstanceSecretsStore` se mueve a `web/` (o se marca *deprecated* allí). Test de arquitectura: `ai/` no importa
  `auth/` ni `web/`.
- **L-6c**: `tenant_id` de `Project` y `ProjectRegistry` → `DeprecationWarning` si se pasa distinto de `"default"`.
- **L-6d**: `.github/workflows/release.yml` en tags `v*`: `python -m build`, wheel + sdist + `.sha256` en la GitHub
  Release (lo que hoy se hace a mano).

### Ola B — rutas (L-4, L-5)

- **L-4**: `ProjectLayout(output_root, state_root=None)` público: deriva salida, imágenes, `duplicados/`, sitio y
  contexto desde `output_root`, y `cache.db`, `folders.json`, carpetas guardadas, historial, errores,
  `DEDUP_REPORT.json`/`DEDUP_HISTORY.jsonl` desde `state_root` (por defecto, el mismo `output_root`: comportamiento
  actual). `main.py` y las rutas de `web/` lo usan en lugar de construir rutas con las constantes.
- **L-5**: toda operación que hoy deduce una ruta de estado la acepta explícita (`resolve_duplicates`/`finalize_report`
  con `report_dir`, `ScannedFoldersStore`, `ProjectHistoryCleaner`, contexto). Test: escaneo + dedup con salida en A y
  estado en B sin ficheros cruzados.

### Ola C — operaciones (L-2, L-6b, L-6)

- **L-2**: `CancelToken` (hilo-seguro) y `OperationCancelledError`; `on_progress: Callable[[ProgressEvent], None]` en
  `run_streaming`, `deduplicate_streaming` y `ContextBuilder.build`; `ProgressEvent(phase, processed, total, current)`;
  parada **entre documentos**, `cache.db` coherente, evento final `cancelled`. Los generadores actuales se mantienen.
- **L-6b**: `schema_version` y `to_dict()` estable en `ScanEvent`, `DedupEvent`, `ContextBuildEvent` y
  `ContextDeleteEvent`; test de contrato con JSON de referencia (sin cambiar `str(Enum)`, decisión UP042).
- **L-6**: `DuplicateGroup.group_id` **estable** (hash de las rutas y hashes de los miembros);
  `find_duplicates` ya es la vista previa; `resolve_duplicates(groups, *, mode="move"|"copy"|"report_only",
  keep_policy=…)` aplica **solo** los grupos recibidos (por defecto `move`, como hoy). Con origen de solo lectura,
  `copy`/`report_only` no escriben en el origen.

### Cierre (VERSION)

0.10.0 en `pyproject.toml`/`__version__`/CHANGELOG/COMPATIBILITY; PR a `develop` y a `main`; tag `v0.10.0`; el workflow
L-6d publica el wheel. En doc_organize_web: huecos G1–G7, G13, G15 a «Resueltos».

## Riesgos

| # | Riesgo | Mitigación |
|---|---|---|
| K1 | La importación diferida rompe a quien hacía `from doc_organize import X` | Mismos nombres en `__all__`; test que importa todos; `mypy` ve los tipos vía `TYPE_CHECKING` |
| K2 | La web integrada (congelada) depende de rutas y firmas que cambian | Todo compatible hacia atrás; los 15 `test_web_*` deben seguir en verde |
| K3 | Cancelación a mitad de un lote de OCR | Parada entre documentos; el documento en curso termina (documentado) |
| K4 | `group_id` estable cambia el formato de `DEDUP_REPORT.json` | Solo el valor del id; mismo campo |
| K5 | Tamaño: 11 tareas en una release | Tres olas con commits por tarea; PR único revisable por commits |

## AUDIT_PLAN

- Sin *breaking changes* (SemVer MINOR): firmas antiguas con `DeprecationWarning`.
- Arquitectura: `ai/` sin `auth/`; `ProjectLayout` como único derivador de rutas fuera de los tests.
- Tests: los existentes (863) en verde + los nuevos de cada tarea; CI en Ubuntu/Windows 3.12–3.14.
- Fuera de alcance: L-7…L-9b (0.11.0), L-13b (Zensical; se puede adelantar si se pide).

**Veredicto: `GO_CONDICIONAL`** — condiciones en el resumen al mantenedor.

## Resolución de condiciones (mantenedor, 2026-10-31)

1. G15 (`__init__` ligero con importación diferida) dentro de L-1: aprobado.
2. Una sola release 0.10.0 con las olas: aprobado.
3. **L-13b (documentación a Zensical) se adelanta a la 0.10.0** como **Ola D**: `mkdocs.yml` → `zensical.toml`,
   workflows `docs.yml`/`docs-zip-release.yml`, `scripts/build_docs_zip.py`, extra `docs`, `CLAUDE.md` y SHARED con
   `zensical build --strict`; se retiran `mkdocs`, `mkdocs-material` y `mkdocstrings` (referencia de API desde
   *docstrings*: PENDIENTE DE VERIFICAR el equivalente en Zensical).
4. `resolve_duplicates(mode=...)` con `move` por defecto: aprobado.

Veredicto tras condiciones: **GO** — IMPLEMENT autorizado (olas A → B → C → D).
