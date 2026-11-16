# TRACEABILITY: Resumen de Sesión

## Sesión
- **Fecha**: 2026-11-15
- **Tipo**: `feature`
- **Rama**: `feat/metadata-enhancement-fase1` (PR #34) y `feat/document-properties` (PR #36, sustituye al #35 cerrado)
- **Estado**: ✅ COMPLETADA (pendiente la release 1.5.0)

## Objetivo
Saber si el escaneo guarda metadatos de los ficheros (solo guardaba ruta, nombre, extensión, tamaño, fecha de
modificación y SHA-256) y ampliarlos para organizar mejor la información. Plan en cuatro fases en
[PLAN_METADATA_ENHANCEMENT.md](PLAN_METADATA_ENHANCEMENT.md). Una primera implementación de las fases 1 y 2 no superó
`/audit-code` (veredicto RECHAZADO); esta sesión corrige la Fase 1, rehace la Fase 2 y añade el idioma de cada
documento.

## Cambios Ejecutados

### ✅ 1. Metadatos de fichero sin datos aproximados

**Archivo(s)**: `src/doc_organize/utils/metadata_detector.py`, `src/doc_organize/scanner/document_scanner.py`
**Descripción**: `created_time` = `st_birthtime` (`None` en Linux); `mime_type` por la extensión (`mimetypes`, sin
leer el fichero); `file_permissions` en octal POSIX (`None` en Windows); `owner_name` con `ctypes`
(`GetNamedSecurityInfoW` + `LookupAccountSidW`, en caché por SID) en Windows y `pwd` (en caché por UID) en POSIX. Se
usa el `stat` con reintentos que el escáner ya hacía. Se quitó `detected_language`, que nada rellenaba.
**Status**: ✅

### ✅ 2. Propietario solo si se pide

**Archivo(s)**: `src/doc_organize/core/models.py`, `src/doc_organize/scan/scan_command.py`
**Descripción**: `ScanOptions.capture_owner` y `DocumentScanner(capture_owner=)`, `False` por defecto: es un dato
personal y llega a `ScanResult`, a la caché y a `DEDUP_REPORT.json`.
**Status**: ✅

### ✅ 3. Persistencia en `cache.db`

**Archivo(s)**: `src/doc_organize/cache/cache_manager.py`, `src/doc_organize/core/models.py`,
`src/doc_organize/scan/scan_command.py`
**Descripción**: cuatro columnas nuevas con la migración aditiva de `size_bytes`, generalizada en `_OPTIONAL_COLUMNS`
(en solo lectura, las que faltan se leen como `NULL`). `_build_entry` y `from_cache_entry` llevan los campos.
`ScanCommand._refresh_file_metadata` actualiza, sin reconvertir, los metadatos de fichero y `size_bytes` de los
documentos sin cambios de contenido; un fallo al guardarlos no para el escaneo.
**Status**: ✅

### ✅ 4. Tests y documentación

**Archivo(s)**: `tests/unit/test_file_metadata.py` (sustituye a `test_scanner_metadata_phase1.py`),
`docs/guides/metadata-schema.md` (reescrita, con nota de corrección), `docs/api/scanner.md`, `docs/api/scan.md`,
`docs/api/cache.md`, `zensical.toml` (nav), `CHANGELOG.md` (`[Unreleased]`)
**Status**: ✅

### ✅ 5. Autor, descripción y palabras clave en el contexto (PR #36)

**Archivo(s)**: `src/doc_organize/context/document_properties.py`, `src/doc_organize/context/context_builder.py`,
`src/doc_organize/utils/text_clean.py`
**Descripción**: `DomainDocument.author/description/keywords` salen de lo que declara el documento: PDF `/Author`,
`/Subject`, `/Keywords` con pypdfium2 (ya la instalaba Docling) y Office OOXML `docProps/core.xml` con `zipfile` y
`ElementTree` (máx. 1 MB). `/Creator` y `/Producer` no cuentan como autor.
**Status**: ✅

### ✅ 6. Enriquecimiento por IA opcional (PR #36)

**Archivo(s)**: `src/doc_organize/ai/document_enrichment_client.py`, `context_builder.py`, `core/models.py`,
`core/exceptions.py`, `core/progress.py`
**Descripción**: `DocumentEnrichmentClient` sobre `AiHttpClientBase` (`/chat/completions`, config Pydantic
`LiteLLMEnrichmentConfig`). Con `ai_enrichment_enabled`, rellena solo la descripción y las palabras clave que faltan
(`DomainDocument.ai_filled`); el autor nunca. Reutiliza `_AiRun` (mismos límites y paradas que la Sub-fase B) con
recuento propio (`Context.ai_enrichment_*`) y fase de progreso `"enrichment"`.
**Status**: ✅

### ✅ 7. Idioma de cada documento (PR #36)

**Archivo(s)**: `src/doc_organize/context/language_detection.py`, `context_builder.py`
**Descripción**: `DomainDocument.language` (ISO 639-1) con py3langid (4,6 MB, BSD, solo numpy; lingua ocupaba 170 MB y
langdetect no publica wheel) sobre el título y los primeros 4000 caracteres del texto convertido. Solo con ≥ 40 letras
y probabilidad ≥ 0,7; si no, `None`. El modelo se carga una vez, de forma diferida (~0,4 s).
**Status**: ✅

### ⚠️ 8. Incidente: el PR #34 se fusionó en `main`

**Descripción**: el PR #34 se abrió sin `--base` y apuntaba a `main` (rama por defecto); se fusionó sin comprobarlo.
`main` no exige revisión para el administrador y aceptó el squash (`5a98ca2`). Como `develop` solo admite PR con squash
y `main` prohíbe los push que no son fast-forward, la única salida que conserva el flujo fue: lanzar `tests.yml` en
`main` para que `5a98ca2` tuviera los checks exigidos, desactivar un momento el ruleset «PR en develop», hacer
`git push origin 5a98ca2:develop` (fast-forward) y reactivarlo. Decisión del usuario.
**Status**: ✅

### ✅ 9. Fase 3: trazabilidad de la clasificación

**Archivo(s)**: `src/doc_organize/context/context_builder.py`, `context/domain_classifier.py`, `core/models.py`
**Descripción**: `DomainDocument.rules_domain/rules_confidence` (propuesta de las reglas, recalculada con
`DomainClassifier.score_domain` en los documentos que decide la IA), `ai_confidence`, `ai_reasoning` (antes se
descartaba) y `material_type_confidence`; `Context.ai_classification_model` (ya existía, nadie lo rellenaba),
`ai_enrichment_model` y `built_with_version`. Cambios respecto al plan: sin fecha por documento (es
`Context.updated_at`), sin `rules_version.txt` manual (las reglas son código: basta la versión de doc_organize) y con
campos tipados en lugar del diccionario `domain_confidence_breakdown`.
**Status**: ✅

### ✅ 10. Fase 4: historial del contexto y su exportación

**Archivo(s)**: `src/doc_organize/context/context_history.py`, `context_builder.py`, `core/models.py`,
`core/constants.py`, `projects/layout.py`, `export/sources.py`, `export/xlsx_export.py`, `main.py`
**Descripción**: `ContextBuilder._save_and_record` lee el contexto anterior, guarda el nuevo y añade un
`ContextBuildRecord` a `historial_contexto/CONTEXT_HISTORY.jsonl` con `diff_contexts` (entra, sale o cambia de
dominio/tipo de material). Exportación con `write_context_history_xlsx` y `export context-xlsx`. Decisión del usuario:
de la Fase 4 del plan, solo historial e informe; se descartaron el origen «importado/creado/migrado» y el evento
«accedido» (la librería no puede saberlos) y la retención por tipo de material.
**Status**: ✅

### ✅ 11. `/audit-code` de las Fases 3 y 4: dos regresiones corregidas

**Archivo(s)**: `context/context_registry.py`, `context/domain_classifier.py`, `context/context_builder.py`,
`core/models.py`, `docs/api/context.md`, `docs/api/export.md`
**Descripción**:
- **Reconstruir sobre un contexto dañado fallaba** (desde el #38): `ContextRegistry._load` dejaba escapar
  `UnicodeDecodeError`/`TypeError` con un `context.json` no UTF-8 o JSON que no era un objeto, y `build()` ahora lee el
  contexto anterior. Ahora `_read_json_object` lo convierte todo en `ContextError`.
- **`fold_accents` multiplicaba por ~150 el coste de clasificar** (desde el #37): `unicodedata.normalize("NFKD")` sobre
  10 MB tardaba 5,8 s. Ahora es una tabla de `str.translate` (0,19 s; mismo resultado en las letras latinas).
- `DomainDocument.ai_domain`: la propuesta de la IA, que se perdía cuando en modo manifiesto solo se aplicaba al tipo de
  material. Corregida la documentación que decía que `confidence` era siempre la de `classified_by`.
**Status**: ✅

---

## Impacto

### Código
- **Archivos modificados/creados**: 5 de `src/`, 1 de tests, 6 de documentación/configuración.
- **Cambios funcionales**: sí. Campos nuevos en `DocumentMetadata`/`CacheEntry`, columnas nuevas en `cache.db` y un
  guardado extra (solo si algo cambió) en cada escaneo para los documentos sin cambios.

### Compatibilidad
- **BREAKING**: ninguno. Una caché de 1.4.0 se migra al abrirse en escritura y se lee en solo lectura.
- **NO BREAKING**: campos opcionales (`None` por defecto); `capture_owner` *keyword-only*; `CacheEntry` serializado sin
  los campos se sigue leyendo.

---

## Verificación
```
python -m ruff check src tests      # All checks passed!
python -m ruff format --check       # 129 files already formatted
python -m mypy src                  # Success: no issues found in 63 source files
python -m mypy --platform linux src/doc_organize/utils/metadata_detector.py   # Success
python -m pytest                    # Fase 1: 841 passed, 8 skipped; Fase 2 + idioma: 869 passed, 7 skipped
zensical build --strict             # No issues found
```
`test_owner_is_the_current_account` ejecuta la ruta `ctypes` real en Windows. La ruta POSIX de permisos solo se
prueba en Linux/macOS (CI). El PR #34 pasó el CI completo (Linux y Windows, 3.12-3.14, tests lentos con Docling). El
cliente de IA solo se ha probado con `httpx.MockTransport`, no contra un LiteLLM Proxy real.

---

## Riesgos Residuales

| Riesgo | Mitigación | Status |
|--------|-----------|--------|
| En Windows, `capture_owner=True` añade una llamada al sistema por fichero; en carpetas de red puede notarse | Opt-in; cuentas resueltas en caché por SID | Aceptado (sin medir) |
| `mime_type` por extensión no detecta ficheros renombrados | Documentado en la guía | Aceptado |
| Un escaneo sin `capture_owner` borra el propietario guardado por otro anterior | Documentado; es coherente con el opt-in | Aceptado |
| Versión: el código y la doc dicen 1.5.0 pero `pyproject.toml` seguía en 1.4.0 | Subida en `release/1.5.0` (CHANGELOG, `COMPATIBILITY.md`, `publica.md`) | Cerrado |
| El historial del contexto no rota, se reescribe `created_at` en cada construcción y dos construcciones simultáneas pueden cruzar sus líneas | Anotados en `/audit-code`; para una versión posterior | Abierto |
| `main` publicó la documentación de la Fase 1 antes de la release (workflows `Docs` al fusionar el #34) | Se corrige sola con la release 1.5.0 | Aceptado |
| Cada fase de IA (clasificación y enriquecimiento) puede enviar hasta `ai_max_documents`: el total puede duplicarse | Documentado en `docs/api/context.md` | Aceptado |
| El sitio de contexto no muestra autor, descripción, palabras clave ni idioma | Pendiente en `SiteGenerator` | Abierto |

---

## Siguientes Pasos (Recomendado)
1. Release 1.5.0 (versión, `COMPATIBILITY.md`, `docs/api/publica.md`, fast-forward de `main` y tag).
2. Mostrar los campos nuevos en el sitio de contexto (`SiteGenerator`) y, si interesa, en la exportación XLSX.
3. doc_organize_web: exponer `capture_owner`, `ai_enrichment_enabled` y los campos nuevos.

---

## Directrices para Futuras IAs

- **[cache.db]**: una columna nueva de `cache_entries` se añade a `_OPTIONAL_COLUMNS` (`cache_manager.py`), al
  `_SCHEMA`, al `_UPSERT`, a `_row_to_entry` y a `save_entries`; la migración y la lectura en solo lectura salen solas.
- **[ScanCommand]**: los documentos sin cambios de hash no se vuelven a guardar al convertir; un dato que deba
  refrescarse sin reconvertir va en `_FILE_METADATA_FIELDS` (`scan_command.py`).
- **[tests]**: hay tests que cuentan las llamadas a `CacheManager.save_entries` (p. ej.
  `test_failed_intermediate_save_does_not_stop_the_scan`): no llamarla con una lista vacía.
- **[mypy]**: el código por plataforma va en `if sys.platform == "win32": ... else: ...`; con un `return` temprano en
  lugar de `else`, mypy analiza la rama de la otra plataforma y falla por nombres que no existen.
- **[proceso]**: no escribir "mypy OK", "migración automática" ni cifras de rendimiento sin haber ejecutado o medido;
  la primera versión de esta sesión lo hizo y el resumen resultó falso.
- **[git/GitHub]**: la rama por defecto del repositorio es `main`, no `develop`: `gh pr create` sin `--base develop`
  abre el PR contra `main`. Comprobar `gh pr view N --json baseRefName` antes de fusionar. `develop` solo admite squash y
  `main` prohíbe push que no sean fast-forward (rulesets «PR en develop» y «CI en verde»).
- **[imports]**: `ai/` no puede importar de `context/` (`context/__init__` importa `ContextBuilder`, que importa `ai`):
  lo compartido va en `utils/` (p. ej. `utils/text_clean.py`).
- **[historial del contexto]**: se escribe en `ContextBuilder`, no en `ContextRegistry.save_context`, porque el
  registro también guarda al reorganizar o generar el sitio y eso no son construcciones. Cualquier carpeta nueva en la
  raíz del proyecto debe ir a `RESERVED_OUTPUT_FOLDER_NAMES` (`projects/layout.py`): la carpeta reorganizada se borra
  entera al reconstruir.
- **[rendimiento]**: el texto de los documentos convertidos puede ocupar varios MB (hojas de cálculo grandes). Antes de
  aplicarle una transformación por documento, medirla con ~10 MB: `unicodedata.normalize` tardó 5,8 s.
- **[ContextRegistry]**: todo fallo de lectura de `context.json`/`index.json` debe salir como `ContextError`
  (`_read_json_object`); `ContextBuilder` depende de ello para reconstruir sobre un contexto dañado.
- **[tests de contexto]**: los dobles de los clientes de IA necesitan `config = SimpleNamespace(model=...)`, porque
  `ContextBuilder` anota `client.config.model` en el `Context`.
- **[reglas]**: `score_catalog` compara con `fold_accents` (sin tildes ni diéresis; «ñ» → «n») desde esta sesión; antes
  «gestión» no contaba para la palabra clave «gestion». `_slugify` no se tocó a propósito: cambiaría los slugs y las
  carpetas reorganizadas de contextos existentes.
- **[idioma]**: py3langid falla con textos cortos con confianza baja; por eso `MIN_LETTERS` y `MIN_CONFIDENCE` en
  `context/language_detection.py`. El idioma declarado por Word/PDF no se usa: suele ser el del ordenador del autor.

---

## Veredicto

### 🟢 COMPLETADA

**Criterios**:
- Fases 1 y 2 e idioma implementados; lint, tipos, tests y documentación estricta en verde.
- Fusionados en `develop` (PR #34 vía fast-forward tras el incidente de `main`; PR #36 por squash).

**Evidencia**:
- PR #34 (`5a98ca2`), PR #36
- Tests: 869 passed, 7 skipped en local
