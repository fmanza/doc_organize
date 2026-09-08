# TRACEABILITY: Resumen de Sesión

## Sesión
- **Fecha**: 2026-09-08 (prompt/PLAN) → 2026-09-09 (IMPLEMENT/AUDIT_CODE/VERSION)
- **Tipo**: `feature`
- **Rama**: `develop`
- **Estado**: ✅ COMPLETADA

## Objetivo
Añadir a doc_organize la capacidad de organizar los documentos ya convertidos de un proyecto por
**dominios** (Sub-fase A, reglas; Sub-fase B opcional, IA vía LiteLLM Proxy), copiarlos a una
carpeta reorganizada y generar la configuración de un sitio MkDocs — ver
[`00_REQUEST.md`](00_REQUEST.md) para el diseño completo y las decisiones tomadas con el usuario.

## Cambios Ejecutados

### ✅ 1. Modelos y excepciones base (`core/`)

**Archivo(s)**: `src/doc_organize/core/models.py`, `src/doc_organize/core/exceptions.py`
**Descripción**: `DomainStatus`, `Domain`, `DomainDocument` (`confidence` acotada `ge=0.0,le=1.0`),
`Context` (con `reorganized`/`mkdocs_generated: bool`, estado honesto ante fallo parcial),
`DomainClassificationResult`, `LiteLLMClassificationConfig`. Excepciones: `ContextError` y
subclases (`ContextNotFoundError`, `DomainNotFoundError`, `IncompleteConversionArtifactsError`),
`DomainClassificationError` y subclases (`AuthError`, `ConnectionError`).
**Status**: ✅ Completo

### ✅ 2. Sub-fase A — clasificación por reglas (`context/`)

**Archivo(s)**: `src/doc_organize/context/{__init__,domain_classifier,context_registry,context_builder}.py`
**Descripción**: `DomainClassifier` lee `chunks`/`title` del `.json` de conversión (nunca el `.md`,
§2.4 del `00_REQUEST.md`); modo catálogo (nunca inventa dominio fuera de él, cada candidato saneado
con `_slugify()` contra path traversal) o descubrimiento (carpeta contenedora). `ContextRegistry`
persiste `context.json` + `domains/<slug>/{DOMAIN.md,index.json}` (patrón `ProjectRegistry`:
`asyncio.Lock` + escritura atómica), preservando el texto editado a mano de `DOMAIN.md` y limpiando
dominios huérfanos en cada reconstrucción. `ContextBuilder` orquesta clasificación + persistencia.
**Status**: ✅ Completo

### ✅ 3. Reorganización física + MkDocs (`context/`, web)

**Archivo(s)**: `src/doc_organize/context/{reorganizer,mkdocs_generator}.py`, `src/doc_organize/web/routes/context.py`,
`src/doc_organize/web/templates/context.html.j2`, `_nav_macros.html.j2`, `web/app.py`
**Descripción**: `Reorganizer.reorganize()` copia original+`.md`+`.json` a
`<output_folder_name>/<dominio>/<tipo>/<stem>/` (copia, nunca mueve; valida todos los artefactos
antes de tocar disco). `MkDocsGenerator.generate()` escribe `mkdocs.yml`+`index.md` usando
`organizado/` como `docs_dir` directamente (sin cuarta copia). Rutas `GET/POST /api/projects/{name}/context`
+ página HTML, con lock de operación (`409` si hay otra en curso) y persistencia honesta de
`reorganized`/`mkdocs_generated` ante fallo parcial.
**Status**: ✅ Completo

### ✅ 4. Sub-fase B — clasificación por IA (`ai/`, Docker)

**Archivo(s)**: `src/doc_organize/ai/domain_classification_client.py`, `context_builder.py` (fallback),
`web/routes/context.py` (toggle), `deploy/litellm/*`, `.env.example`, `.gitignore`
**Descripción**: `DomainClassificationClient` habla `chat/completions` de un LiteLLM Proxy; el
dominio devuelto se valida contra el catálogo antes de propagarlo (nunca inventa uno), `confidence`
recortada a `[0,1]`. Solo se invoca para lo que la Sub-fase A deja sin clasificar, opt-in explícito.
`deploy/litellm/{docker-compose.yml,config.yaml.example,.env.example}` (proxy + Postgres) +
`.gitignore` corregido (no ignoraba ningún `.env` del repo — gap de seguridad cerrado).
**Status**: ✅ Completo

### ✅ 5. Documentación

**Archivo(s)**: `docs/functional/context.md`, `docs/api/context.md`, `docs/guides/litellm_proxy_setup.md`,
`docs/functional/ai_usage_monitoring.md` (cross-referencia actualizada), `mkdocs.yml`, `CHANGELOG.md`
**Descripción**: Arquetipos funcional/API/guía completos; `mkdocs build --strict` sin warnings.
**Status**: ✅ Completo

---

## Impacto

### Código
- **Archivos nuevos**: paquete `context/` completo (6 módulos), `ai/domain_classification_client.py`,
  `web/routes/context.py`, `web/templates/context.html.j2`, `deploy/litellm/*` (3 ficheros), 3
  páginas de documentación, 7 ficheros de test nuevos (54 tests).
- **Archivos modificados**: `core/models.py`, `core/exceptions.py`, `ai/__init__.py`, `web/app.py`
  (router + mapeo de excepciones), `_nav_macros.html.j2`, `pyproject.toml` (extra `context`, dep dev
  `types-PyYAML`), `.env.example`, `.gitignore`, `mkdocs.yml`, `docs/functional/ai_usage_monitoring.md`.
- **Cambios funcionales**: sí — nueva capacidad opcional (extra `context`), sin tocar scan/dedup/convert.

### Compatibilidad
- **BREAKING**: Ninguno.
- **NO BREAKING**: Todo aditivo — nuevo paquete, nuevas rutas, nuevo extra opcional, nuevas
  variables de entorno (todas opcionales, con mensaje explícito si faltan al activarlas).

---

## Verificación

```
python -m ruff check src tests        → All checks passed!
python -m mypy src                    → Success: no issues found in 65 source files
python -m pytest                      → 587 passed
mkdocs build --strict                 → Documentation built in ~2.5s, sin warnings
```

---

## Riesgos Residuales

| Riesgo | Mitigación | Status |
|--------|-----------|--------|
| `cache.db` puede tener entradas `SUCCESS` para documentos ya movidos por deduplicación (`dedup/` no toca `cache.db`) | `_gather_converted_documents` omite entradas cuyo original ya no existe en disco | Mitigado |
| Dos documentos con el mismo `stem` en el mismo dominio/tipo se pisan en `organizado/` | Documentado como limitación conocida en `Reorganizer`; sin desambiguación todavía | Abierto |
| Sin test de integración real contra un LiteLLM Proxy vía Docker (no había Docker disponible en este entorno) | YAML de `deploy/litellm/` validado sintácticamente; `DomainClassificationClient` probado con `httpx.MockTransport` | Abierto — validar manualmente contra un proxy real antes de depender de la Sub-fase B en producción |
| `chunks_text` truncado a 4000 caracteres antes de enviarlo a la IA | Documentado en `domain_classification_client.py`; aceptable para MVP | Aceptado |

---

## Siguientes Pasos (Recomendado)
1. Validar manualmente la Sub-fase B contra un LiteLLM Proxy real (`deploy/litellm/`) antes de
   activarla en un entorno con usuarios reales.
2. Si se detecta colisión real de `stem` duplicados en `organizado/`, añadir desambiguación
   (p. ej. sufijo corto del hash del documento).
3. Considerar paralelizar la lectura de `.json` en `DomainClassifier.classify()`
   (`asyncio.gather`, ya usado en `scanner/document_scanner.py`) si el volumen de documentos por
   proyecto se vuelve un cuello de botella — no era necesario para el alcance de esta sesión.

---

## Directrices para Futuras IAs

- **[patrón]**: Cualquier operación que reconstruya un árbol de ficheros derivado (como
  `Reorganizer.reorganize()`) debe **validar todo lo necesario antes de borrar nada** — borrar y
  reconstruir sobre la marcha, descubriendo un fallo a mitad, destruye estado válido previo sin
  posibilidad de recuperarlo. Este bug real se introdujo en un primer AUDIT_CODE (arreglando
  "carpetas huérfanas") y se corrigió en un segundo pase — ver `reorganizer.py::reorganize()`.
- **[patrón]**: `resolve_document_slug_parts()` (`reorganizer.py`) es la única fuente de verdad de
  `<tipo>/<stem>/` para un documento clasificado — la usan tanto `Reorganizer` (ruta real en disco)
  como `MkDocsGenerator` (ruta del `.md` en el `nav`, siempre con `/` literales, nunca `Path` — en
  Windows uniría con `\`). No reimplementar esta fórmula en un tercer sitio.
- **[patrón]**: `doc_organize.ai` es el paquete de **cualquier** cliente que llame a un proveedor de
  IA o LiteLLM Proxy — `UsageSource`/`LiteLLMUsageClient`/`GitHubCopilotUsageClient` (monitorización,
  sesión 2026-09-07) y `DomainClassificationClient` (inferencia, esta sesión) conviven ahí con el
  mismo patrón (Protocol/config-from-env explícita/excepciones propias/`httpx.AsyncClient` con
  `transport` inyectable) pero **configs separadas, nunca comparten credenciales** (ISP) aunque
  apunten al mismo proxy en despliegue.
- **[decisión]**: La Sub-fase B nunca es la primera pasada de clasificación ni puede crear un
  dominio fuera del catálogo ya confirmado por la Sub-fase A — validado en dos sitios
  (`DomainClassificationClient._parse_result` y, por diseño, el catálogo que `ContextBuilder` le
  pasa) para que un fallo en cualquiera de los dos no rompa la regla de negocio.
- **[gap conocido]**: `dedup/deduplication.py` no actualiza `cache.db` al mover un duplicado — ver
  Riesgos Residuales. Cualquier feature futura que lea `cache.db` como fuente de "documentos
  vigentes" debe repetir el filtro de existencia real en disco que aplica
  `web/routes/context.py::_gather_converted_documents`, no asumir que `conversion_status=success`
  implica que el fichero sigue ahí.

---

## Veredicto

### 🟢 COMPLETADA

**Criterios**:
- Las tres sub-fases del PLAN (Level 1/2/3) implementadas y con AUDIT_CODE aplicado (3 rondas +
  1 revisión holística final, todos los hallazgos corregidos con test de regresión).
- ruff/mypy/pytest/mkdocs build --strict en verde.
- Documentación funcional, API y guía de despliegue completas, con nav en `mkdocs.yml`.
- Sin cambios breaking.

**Evidencia**:
- Branch: `develop`
- Commits: ver commit de cierre inmediatamente después de este fichero.
- Tests: `pytest` → 587 passed (54 específicos de esta feature).

**Sesión cerrada**: 2026-09-09
