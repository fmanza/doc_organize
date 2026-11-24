# 📚 Glossary — doc_organize

> Reemplaza una versión anterior con términos de otra librería (motores de base de datos, `_drivers/`, `connection/`,
> `metadata/`) — la encarnación previa de este mismo repositorio. Revisado contra el código de 2.2.0.

## Niveles de arquitectura (regla #6, `.github/instructions/architecture.instructions.md`)

- **Nivel 1 (Fundacional)**: `core/`, `utils/` — sin dependencias del resto del paquete.
- **Nivel 2 (Servicios)**: `validators/`, `scanner/`, `converter/`, `dedup/`, `cache/`, `projects/`, `ai/` (y
  `security/` según `.github/SHARED_INSTRUCTIONS.md`) — cada uno resuelve una responsabilidad, solo depende de Nivel 1
  salvo excepciones documentadas en `.ai/architecture.md`.
- **Nivel 3 (Orquestación)**: `scan/`, `context/`, `export/`, `main.py` — coordinan Nivel 2 sin cambiar sus contratos.

## Entidades de dominio

- **Project**: carpeta de trabajo con nombre, registrada en `~/.doc_organize/projects.json`, con su `Conversión/`,
  `cache.db` y `duplicados/`. Sin `tenant_id` desde 1.0.0 (un registro antiguo que lo traiga se lee y el campo se
  ignora).
- **ProjectLayout**: rutas derivadas de un proyecto (`conversion_dir`, `cache_db`, `folders_json`…).
- **DocumentMetadata**: metadatos de un documento descubierto por el escaneo (ruta, nombre, tamaño, hash SHA-256).
- **CacheEntry**: entrada persistida en `cache.db` — hash, estado (new/modified/unchanged), estado de conversión.
- **DuplicateGroup**: grupo de documentos duplicados con un documento canónico y una elección opcional del usuario
  (`user_choice`). Motivo (`DuplicateReason`): `exact_duplicate`, `version_conflict`, `fuzzy_name_match` y, desde
  2.2.0, `same_content` y `semantic_content_match` (con `similarity`, `lexical_similarity` y `contained`).
- **Context**: resultado de construir el contexto documental de un proyecto (clasificación, carpeta reorganizada,
  sitio).
- **TaxonomyManifest / TaxonomyAxis**: `taxonomy_manifest.md` v2 con **ejes**: los que organizan carpetas y los que
  solo etiquetan.
- **ClassificationDecision**: decisión de una persona sobre un documento (p. ej. `exclude`), guardada por
  `ClassificationDecisionStore` en `.doc_organize/decisions.json`; solo se aplica al construir con manifiesto.
- **AiSettings / TaskSettings**: configuración de `LlmClient`: proxy LiteLLM + clave general, y modelo/clave por tarea.
- **AiTask**: `classify`, `enrich`, `taxonomy_design`, `agent`, `embed`, `dedup` (2.2.0).

## Eventos y progreso

- **ScanEvent**: progreso de `ScanCommand.run_streaming()` (`started`, `scanned`, `file_started`, `file_converted`,
  `ocr_started`, `ocr_file_started`, `ocr_processed`, `completed` o, si se cancela, `cancelled` como último evento).
- **DedupEvent**: progreso de `ScanCommand.deduplicate_streaming()`, acción aparte a petición del usuario
  (`started`/`duplicates_found`/`group_started`/`group_resolved`/`completed`); su `COMPLETED` se colapsa en un
  `DeduplicationSummary` para quien solo necesita el resumen (CLI).
- **ContextBuildEvent / ContextDeleteEvent**: progreso de construir o borrar el contexto.
- **ProgressEvent**: progreso con unidades, común a `scan`, `deduplicate`, `context_build` y `export`.
- **CancelToken**: petición de parada compartida, segura entre hilos; las operaciones lanzan
  `OperationCancelledError`.

## Conceptos técnicos

- **`safe_path_join()`**: única forma permitida de construir una ruta a partir de un segmento elegido por el usuario —
  previene path traversal.
- **`hash_file()`**: única fuente de verdad de SHA-256 en todo el proyecto.
- **`ScanCommand`**: orquestación compartida de escaneo + caché + conversión + OCR (y deduplicación bajo demanda),
  usada por el CLI y por consumidores como doc_organize_web — vive en `scan/`.
- **`LlmClient`**: cliente único de IA (2.0), siempre vía LiteLLM Proxy; alias recomendado de modelo
  `doc-organize-<tarea>`.
- **`ContentDuplicateFinder`**: búsqueda de duplicados por contenido sobre el Markdown convertido (2.2.0).
- **`AgentRunner`**: bucle de agente con topes (`AgentLimits`); los agentes **solo proponen**.
- **`redact_credentials()`**: redacción de credenciales antes de enviar a la IA o publicar.
- **API pública**: claves de `_EXPORTS` en `src/doc_organize/__init__.py` (= `doc_organize.__all__`), importadas bajo
  demanda (PEP 562).
- **REQ-00X**: identificador de requisito funcional, definido en `.github/prompts/doclink_extractor_plan.md` §2
  (REQ-007, interfaz web, salió de la librería en 1.0.0).

## Siglas y convenciones del proyecto

- **`L-N`**, **`G-N`**, **`F-N`**, **`D-N`**: identificadores de tareas y decisiones de los planes de versión (p. ej.
  L-11 librería pura, L-12 sin tenants, L-7 exportación, G1 cliente único de IA) citados en docstrings y `CHANGELOG.md`.
  (Significado exacto de cada prefijo: **pendiente** de confirmar.)
- **`§N`**: referencia a una sección del PLAN original (`.github/prompts/doclink_extractor_plan.md`).
- **`.ai/doc_old/`**: historial de sesiones de la encarnación anterior de este repositorio — gitignored, no forma
  parte de este proyecto.

## Términos históricos (ya no existen en la librería)

- **Tenant, User, Role, Session, `AuthMiddleware`, `AuthStore`**: autenticación y multi-tenant de la web integrada;
  retirados en 1.0.0, viven en doc_organize_web.
- **`_group_key`**: clave del antiguo Duplicates Resolver web (`web/routes/duplicates.py`).
- **Fase D-2a/b/c**: sub-fases de la antigua interfaz web integrada.
- **`MkDocsGenerator`**: sustituido por `SiteGenerator` (Zensical); retirado en 1.0.0.
