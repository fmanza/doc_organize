# 📦 Product Context — doc_organize

## Descripción Ejecutiva

**doc_organize** es una **librería Python con CLI** que escanea carpetas de documentos heterogéneos (PDF, Word,
Excel, PowerPoint, imágenes; audio/vídeo con el extra `av`), los convierte a Markdown + JSON con
[Docling](https://github.com/docling-project/docling), detecta y resuelve duplicados, mantiene un caché incremental
(SHA-256) para no reconvertir lo que no ha cambiado y organiza los documentos de un proyecto en un **contexto
documental** (taxonomía por ejes, clasificación por reglas y, opcionalmente, semántica e IA vía LiteLLM).

Desde 1.0.0 es una **librería pura**: no incluye interfaz web, autenticación, usuarios, tenants, plantillas Jinja ni
WebSocket. La web es el proyecto aparte [doc_organize_web](https://github.com/fmanza/doc_organize_web), un consumidor
más de la API pública (`docs/guides/migracion_web.md`); `tests/unit/test_library_architecture.py` falla si `src/`
vuelve a importar FastAPI/Starlette/uvicorn/Jinja2/`python-multipart` o si reaparecen `doc_organize.web` o
`doc_organize.auth`.

**Propósito primario**: normalizar repositorios heterogéneos de documentos en Markdown versionado, sin perder la
estructura de carpetas original ni duplicar trabajo entre ejecuciones, y dejarlos organizados y listos para personas
y asistentes de IA.

**Versión**: 2.4.2 (`pyproject.toml`) | **Python**: ≥3.12 (`requires-python`; classifiers 3.12–3.14) |
**API pública (SemVer)**: los nombres de `doc_organize.__all__` (= claves de `_EXPORTS` en
`src/doc_organize/__init__.py`, importadas bajo demanda, PEP 562); ver `docs/api/publica.md`.

> Historial de este documento: la versión de 2026-08-28 sustituyó contenido fabricado por una sesión previa de
> GitHub Copilot (MVP "PRE-IMPLEMENT" con `workflow/`, SSE y comandos `doclink`). La revisión de 2026-09-11 describía
> la interfaz web, `auth/` y el rediseño Tenant/Role/User, que se retiraron en 1.0.0 (ver «Histórico» al final).
> Este documento describe **solo lo que existe en el código** a 2.2.0, verificado contra `src/doc_organize/`.

---

## Capacidades reales (verificadas contra el código)

### Escaneo y conversión
- `scanner/DocumentScanner` (REQ-002): recorrido recursivo + hash SHA-256 concurrente (único punto de hashing:
  `utils/hash_utils.hash_file()`).
- `converter/DocumentConverter` + `OCRScheduler` (REQ-003/REQ-004): conversión con Docling, estructura de carpetas
  replicada bajo `Conversión/`; dos fases (sin OCR → con OCR bajo demanda, CPU por defecto vía `docling[rapidocr]`,
  GPU opcional vía extra `ocr-gpu`).
- `scan/ScanCommand`: orquestación escaneo + caché + conversión + OCR; la deduplicación es una acción aparte, a
  petición del usuario. Progreso por eventos (`ScanEvent`, `DedupEvent`, `ProgressEvent`) y cancelación con
  `CancelToken`; la librería no sabe si detrás hay un terminal o una web.

### Caché y deduplicación
- `cache/CacheManager` (REQ-006): SQLite + WAL, clasifica new/modified/unchanged.
- `dedup/DeduplicationManager` (REQ-005): duplicados exactos (SHA-256), conflictos de versión y similitud aproximada
  de nombre; el llamante puede elegir el documento canónico por grupo (`user_choice`).
- `dedup/content.ContentDuplicateFinder` (2.2.0): duplicados **por contenido** sobre el Markdown ya convertido —
  mismo texto normalizado (`DuplicateReason.SAME_CONTENT`, sin IA) y contenido parecido por embeddings por bloques
  (`SEMANTIC_CONTENT_MATCH`, opcional, tarea de IA `dedup`). Nunca se resuelven solos; `exclude_from_context()`
  guarda decisiones `exclude` para el modo `copy`. Guía: `docs/guides/duplicados_por_contenido.md`.

### Proyectos
- `projects/ProjectRegistry` (REQ-008): registro local (`~/.doc_organize/projects.json`); cada proyecto agrupa su
  `Conversión/`, `cache.db` y `duplicados/`. Sin tenants desde 1.0.0 (un `projects.json` antiguo con `tenant_id` se
  sigue leyendo y el campo se ignora).
- `ProjectLayout` y funciones sin Docling (`resolve_output_paths`, `resolve_images_dir`…) para las rutas de salida;
  `ScannedFoldersStore`, `ProjectHistoryCleaner`.

### Contexto documental (`context/`, 2.0)
- `ContextBuilder` / `ContextRegistry`: taxonomía por **ejes** (`taxonomy_manifest.md` v2: ejes que organizan carpetas
  y ejes que solo etiquetan; `migrate_manifest_v1`), clasificación por reglas y, opcionalmente, semántica
  (embeddings) e IA.
- Decisiones humanas (`ClassificationDecisionStore`), cola de revisión (`review_queue`), evaluación contra una
  referencia (`evaluate_classification`, `load_gold_xlsx`), `dry_run_classify`, versiones de un documento
  (`detect_document_versions`), frescura (`check_context_freshness`) e historial.
- Agentes con topes que **solo proponen**: diseñador de taxonomía (`TaxonomyDesignAgent`) y revisor (`ReviewAgent`,
  `audit_taxonomy`).
- `Reorganizer` (copia a una carpeta reorganizada) y `SiteGenerator` (sitio navegable con **Zensical**, extra `site`);
  sitio sin conexión (`check_site_offline`, `write_site_zip`) y `llms.txt` (`render_llms_txt`).
- Plantillas de taxonomía: `TaxonomyTemplateRegistry` y plantillas integradas (`list_builtin_templates`…).

### IA (`ai/`, opcional, siempre vía LiteLLM Proxy)
- Un solo cliente, `LlmClient`, configurado con `AiSettings` (proxy + clave general) y `TaskSettings` por tarea.
  Tareas (`AI_TASKS`): `classify`, `enrich`, `taxonomy_design`, `agent`, `embed` y, desde 2.2.0, `dedup`.
  `settings_from_env()` lee `DOC_ORGANIZE_LITELLM_BASE_URL`, `..._VIRTUAL_KEY`, `..._MODEL_<TAREA>` y
  `..._VIRTUAL_KEY_<TAREA>`; las variables de 1.x provocan `AiConfigurationError` con la equivalencia.
- Prompts versionados (`PromptRegistry`), caché de resultados (`AiResultCache`), respuestas con `json_schema` y cita
  verificada, índice de embeddings, `AgentRunner`. Las credenciales se redactan antes de enviar nada
  (`security/`).
- Uso y coste: `LiteLLMUsageClient`. `GitHubCopilotUsageClient` y compañía están **obsoletos desde 2.1.0**
  (`DeprecationWarning`, se retiran en 3.0; `docs/guides/migracion_3_0.md`).

### Seguridad, exportación y diagnóstico
- `security/`: `redact_credentials`, `scan_credentials`, `neutralize_untrusted_markdown`.
- `export/`: ZIP en streaming (`write_project_zip`, `preview_project_zip`), Excel de caché, errores y documentos del
  contexto (extra `export`) y paquete para IA (`write_ai_context_bundle`).
- `diagnostics.check_environment`: dependencias, modelos de Docling e IA (sin enviar documentos); detectores ligeros
  `detect_gpu_status`, `detect_av_status`, `detect_office_status`.

### CLI (`python -m doc_organize ...`)
- `project create --location ...` / `project list` (opción común `--registry-path`)
- `scan --paths ... [--project ...] [--output-dir ...] [--cache-file ...] [--use-ocr] [--use-gpu] [--force]`
  (no deduplica)
- `deduplicate --paths ... [--project ...] [--duplicates-dir ...]` (acción aparte, a petición del usuario)
- `export zip|cache-xlsx|errors-xlsx|context-xlsx` (ZIP con `--preview` o `-o`; los Excel exigen `-o`)
- No hay subcomandos `web`, `tenant` ni `user` desde 1.0.0.

---

## Arquitectura (3 niveles, regla #6)

```
src/doc_organize/
├── __init__.py   # API pública bajo demanda (PEP 562)
├── core/         # Nivel 1 — modelos Pydantic, excepciones, constantes, progreso
├── utils/        # Nivel 1 — hash_file, safe_path_join, logging, detectores, formato de fechas
├── validators/   # Nivel 2 — FolderValidator, ProjectValidator
├── scanner/      # Nivel 2 — DocumentScanner
├── converter/    # Nivel 2 — DocumentConverter, OCRScheduler
├── dedup/        # Nivel 2 — DeduplicationManager, ContentDuplicateFinder
├── cache/        # Nivel 2 — CacheManager (SQLite+WAL)
├── projects/     # Nivel 2 — ProjectRegistry, ProjectLayout, ScannedFoldersStore, ProjectHistoryCleaner
├── security/     # Nivel 2 — redacción de credenciales, Markdown no confiable
├── ai/           # Nivel 2 — LlmClient, ajustes, prompts, caché, embeddings, agentes, uso (LiteLLM)
├── context/      # Nivel 3 — ContextBuilder/Registry/Reorganizer/SiteGenerator, decisiones, evaluación, agentes
├── scan/         # Nivel 3 — ScanCommand (compartido por el CLI y los consumidores)
├── export/       # Nivel 3 — ZIP, Excel y paquete para IA
├── diagnostics.py
└── main.py       # Nivel 3 — CLI
```

Detalle: `.ai/architecture.md`, `.github/SHARED_INSTRUCTIONS.md` («Arquitectura real») y `docs/api/`.

---

## Stack tecnológico real

| Componente | Rol |
|---|---|
| **Docling** (`docling[rapidocr]`) | Extracción de documentos + OCR en CPU, dependencia obligatoria |
| **Pydantic v2** | Modelos y validación |
| **aiosqlite** | Backend de `CacheManager` |
| **aiofiles** | I/O async (p. ej. `hash_file()`) |
| **pandas, numpy, rapidfuzz** | Tablas/Excel, matrices de embeddings (numpy directo desde 2.2.0), similitud de nombres |
| **pillow, pypdfium2, py3langid, python-magic(-bin), tzdata** | Imágenes, metadatos PDF, idioma, tipo MIME, zonas horarias |
| **httpx** (extra `ai`) | `LlmClient` y clientes de uso contra el LiteLLM Proxy |
| **pyyaml** (extra `context`) | Front matter de `taxonomy_manifest.md` y plantillas |
| **openpyxl** (extra `export`) | Excel de `doc_organize.export` |
| **zensical** (extra `site`) | Sitio navegable del contexto (`SiteGenerator`) |
| **zensical + mkdocstrings-python** (extra `docs`) | Documentación del propio proyecto |
| **torch/torchvision/opencv-python/easyocr** (extra `ocr-gpu`) | OCR GPU |
| **docling[asr]** (extra `av`) | Audio y vídeo |

No hay extra `web` ni dependencias de FastAPI/Uvicorn/Jinja2/`cryptography` (lo comprueba
`test_pyproject_declares_no_web_dependencies`).

---

## Requisitos funcionales — estado real

| REQ | Descripción | Estado |
|---|---|---|
| REQ-001 | Selección + validación de carpetas | ✅ Implementado |
| REQ-002 | Escaneo recursivo | ✅ Implementado |
| REQ-003 | Conversión Markdown + JSON | ✅ Implementado |
| REQ-004 | Detección y reprocesado OCR | ✅ Implementado |
| REQ-005 | Deduplicación | ✅ Implementado (exacta/versión/nombre; por contenido desde 2.2.0) |
| REQ-006 | Caché incremental | ✅ Implementado |
| REQ-007 | Interfaz web | ↗️ Fuera de la librería desde 1.0.0: doc_organize_web |
| REQ-008 | Gestión de proyectos | ✅ Implementado (sin tenants desde 1.0.0) |

Especificación original: `.github/prompts/doclink_extractor_plan.md` (documento histórico de la Fase 1; puede no
reflejar 2.x).

## Hitos de versión

- **0.11.0 / 0.13.0**: exportación como API pública (L-7); `SiteGenerator` con Zensical (L-8).
- **1.0.0**: librería pura (L-11/L-12): fuera `web/`, `auth/`, extra `[web]`, tenants y `MkDocsGenerator`.
- **1.7.0**: `doc_organize.security` (redacción y detección de credenciales).
- **2.0.0**: taxonomía por ejes, cliente único `LlmClient` con `AiSettings`/`TaskSettings` por tarea, decisiones,
  cola de revisión, evaluación, versiones, semántica, agentes, sitio offline con `llms.txt`, paquete para IA
  (`docs/guides/migracion_2_0.md`).
- **2.0.1**: corrección de `detect_gpu_status` (exige `torch` con CUDA).
- **2.1.0**: GitHub Copilot obsoleto; uso y coste de IA en LiteLLM.
- **2.2.0**: duplicados por contenido y tarea de IA `dedup`.
- **2.3.0**: API pública completa y tipada; jerarquía de capas comprobada por test.
- **2.4.0**: API pública para lo que doc_organize_web importaba de submódulos.
- **2.4.1**: progreso final del escaneo con unidades; canónico de la deduplicación estable ante empates de fecha.
- **2.4.2**: claves fuera de `repr()`; decisiones huérfanas en la cola de revisión; bloqueo del historial con más margen.

Detalle: `CHANGELOG.md`.

## Pendiente

- Retirada de `GitHubCopilotUsageClient`, `GitHubCopilotUsageConfig`, `github_copilot_usage_config_from_env()` y
  `UsageSourceName.GITHUB_COPILOT` en 3.0.
- Sin verificar en esta revisión: si `.github/prompts/doclink_extractor_plan.md` sigue siendo la fuente de verdad de
  algo vigente o es solo histórico.

---

## Histórico (ya no existe en la librería)

Hasta 0.x la librería incluía `web/` (FastAPI, Jinja2, WebSocket de progreso, panel `/admin/*`, Duplicates Resolver,
Export ZIP vía web), `auth/` (`AuthStore`, sesiones por cookie, scrypt, rediseño Tenant/Role/User de 2026-09-11,
`InstanceSecretsStore` con Fernet) y los subcomandos `web`, `tenant create`, `user create` y `user set-instance-admin`.
Todo eso vive ahora en doc_organize_web. Los clientes IA por tarea de 1.x (`DomainClassificationClient`,
`TaxonomyClassificationClient`, `TaxonomyManifestDraftClient`) y `MkDocsGenerator` (sustituido por `SiteGenerator`)
también se retiraron.

---

## Referencias

- Instrucciones compartidas: `.github/SHARED_INSTRUCTIONS.md`
- API pública: `docs/api/publica.md`; cambios: `CHANGELOG.md`
- Migraciones: `docs/guides/migracion_web.md`, `docs/guides/migracion_2_0.md`, `docs/guides/migracion_3_0.md`
- Registro de decisiones: `.ai/DECISIONS_LOG.md`
- Docling: https://github.com/docling-project/docling

---

**Documento regenerado**: 2026-08-28 (sustituye contenido fabricado de una sesión de Copilot previa)
**Última revisión de contenido**: 2026-11-23 (2.2.0: librería pura, IA 2.0, duplicados por contenido)
**Clasificación**: contexto persistente IA — leer antes de planificar
