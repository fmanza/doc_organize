# De doc_organize 1.x a 2.0

doc_organize 2.0 cambia la taxonomía (ejes en vez de dos listas) y la IA (un cliente único en vez de cuatro). Esta guía
recoge **lo que se rompe**, qué usar en su lugar y **lo que cambia de comportamiento** aunque el código siga
funcionando. Lo nuevo es opcional y está al final.

Si solo usas el CLI de escaneo, conversión, deduplicación y exportación, no tienes que hacer nada.

## Pasos para actualizar

1. **Variables de entorno de la IA**: sustituye las de 1.x por las de 2.0 ([tabla](#variables-de-entorno-de-la-ia)).
   Si te dejas alguna, `settings_from_env()` lo dice con un error en lugar de dejar la IA desactivada en silencio.
2. **Código que crea clientes de IA**: pasa a `LlmClient(AiSettings)` ([clientes](#clientes-de-ia)).
3. **Llamadas a `ContextBuilder.build`**: `llm=`, `ai_scope=` y `enrich=`, todo por nombre
   ([`build`](#contextbuilderbuild)).
4. **Código que lee `Context`**: los recuentos de la IA están en `ai_stats` y los modelos en `ai_provenance`
   ([`Context`](#context)).
5. **Código que lee el manifiesto**: `manifest.folder_axis` y `manifest.subfolder_axis` en vez de `domains` y
   `material_types` ([taxonomía](#taxonomia)). Los manifiestos y `context.json` de 1.x se siguen leyendo.
6. Repasa [lo que cambia de comportamiento](#lo-que-cambia-de-comportamiento) y reconstruye el contexto.

## Variables de entorno de la IA

Las variables de 1.x **ya no se leen**. Si alguna sigue definida, `settings_from_env()` lanza `AiConfigurationError`
con la lista de las antiguas y su equivalente, y `check_environment(check_ai=True)` lo informa como error.

| 1.x | 2.0 |
|---|---|
| `DOC_ORGANIZE_LITELLM_CLASSIFICATION_BASE_URL`, `_TAXONOMY_CLASSIFICATION_BASE_URL`, `_ENRICHMENT_BASE_URL`, `_TAXONOMY_MANIFEST_DRAFT_BASE_URL` | `DOC_ORGANIZE_LITELLM_BASE_URL` (una para todas; es la misma que ya usaba `LiteLLMUsageClient`) |
| `DOC_ORGANIZE_LITELLM_CLASSIFICATION_VIRTUAL_KEY`, `_TAXONOMY_CLASSIFICATION_VIRTUAL_KEY` | `DOC_ORGANIZE_LITELLM_VIRTUAL_KEY` o, si quieres una clave propia, `DOC_ORGANIZE_LITELLM_VIRTUAL_KEY_CLASSIFY` |
| `DOC_ORGANIZE_LITELLM_ENRICHMENT_VIRTUAL_KEY` | `DOC_ORGANIZE_LITELLM_VIRTUAL_KEY` o `DOC_ORGANIZE_LITELLM_VIRTUAL_KEY_ENRICH` |
| `DOC_ORGANIZE_LITELLM_TAXONOMY_MANIFEST_DRAFT_VIRTUAL_KEY` | `DOC_ORGANIZE_LITELLM_VIRTUAL_KEY` o `DOC_ORGANIZE_LITELLM_VIRTUAL_KEY_TAXONOMY_DESIGN` |
| `DOC_ORGANIZE_LITELLM_CLASSIFICATION_MODEL`, `_TAXONOMY_CLASSIFICATION_MODEL` | `DOC_ORGANIZE_LITELLM_MODEL_CLASSIFY` |
| `DOC_ORGANIZE_LITELLM_ENRICHMENT_MODEL` | `DOC_ORGANIZE_LITELLM_MODEL_ENRICH` |
| `DOC_ORGANIZE_LITELLM_TAXONOMY_MANIFEST_DRAFT_MODEL` | `DOC_ORGANIZE_LITELLM_MODEL_TAXONOMY_DESIGN` |
| — | `DOC_ORGANIZE_LITELLM_MODEL_AGENT`, `_MODEL_EMBED` (agentes y embeddings, nuevos) |

Sin `MODEL_<TAREA>`, la tarea usa el alias recomendado `doc-organize-<tarea>` (`default_model_alias`): o lo creas en el
proxy o das el modelo real en la variable. Timeout, reintentos, tope de tokens y presupuesto se pueden ajustar por
tarea en `TaskSettings` ([ajustes por tarea](../api/llm_client.md#ajustes-por-tarea)).

## Clientes de IA

| Se retira | Sustituto |
|---|---|
| `DomainClassificationClient`, `TaxonomyClassificationClient`, `DocumentEnrichmentClient`, `TaxonomyManifestDraftClient` | `LlmClient(AiSettings)` y los servicios `classify_document`, `enrich_document`, `draft_taxonomy` (`doc_organize.ai`) |
| `LiteLLMClassificationConfig`, `LiteLLMTaxonomyClassificationConfig`, `LiteLLMEnrichmentConfig`, `LiteLLMTaxonomyManifestDraftConfig` | `AiSettings` (con `TaskSettings` por tarea) |
| `litellm_classification_config_from_env()` y las otras tres | `settings_from_env()` |
| `DomainClassificationResult`, `TaxonomyClassificationResult` | `ClassificationAnswer` (`axes: dict[clave, AxisAnswer]`, cada valor con confianza y cita) |
| `DomainClassificationError`, `TaxonomyClassificationError`, `DocumentEnrichmentError`, `TaxonomyManifestDraftError` y sus `*AuthError`/`*ConnectionError` | `AiError`, `AiAuthError`, `AiConnectionError`, `AiResponseError` |
| `SampledDocument` en `doc_organize.ai.taxonomy_manifest_draft_client` | `doc_organize.ai.SampledDocument` |
| `ContextBuilder(ai_redact_credentials=)`, `LiteLLMTaxonomyManifestDraftConfig.redact_credentials` | `AiSettings.redact_credentials` (la redacción la hace `LlmClient` con todo lo que sale) |

`LiteLLMUsageClient` y `GitHubCopilotUsageClient` no cambian en 2.0. GitHub Copilot quedó obsoleto en 2.1.0 y se
retira en 3.0: ver [Hacia 3.0](migracion_3_0.md).

Borrador de taxonomía, antes y ahora:

```python
# 1.x
async with TaxonomyManifestDraftClient(litellm_taxonomy_manifest_draft_config_from_env()) as client:
    draft = await client.propose_manifest(documents=sample)

# 2.0
async with LlmClient(settings_from_env()) as llm:
    draft = (await draft_taxonomy(llm, PromptRegistry(project.root_path), sample)).value
text = render_taxonomy_manifest_markdown(draft.to_manifest(), reasoning=draft.reasoning, ...)
```

## `ContextBuilder.build`

Todos los parámetros tras `documents` pasan a ser **solo por nombre**.

| 1.x | 2.0 |
|---|---|
| `ai_classification_enabled=True, ai_classification_client=c` / `taxonomy_classification_client=c` | `llm=LlmClient(...), ai_scope="unclassified"` |
| — | `ai_scope="missing_axes"`: además, los ejes vacíos de documentos ya clasificados (con manifiesto) |
| `ai_enrichment_enabled=True, ai_enrichment_client=c` | `llm=..., enrich=True` |
| `on_ai_progress=callback(index, total, ruta)` | `on_progress=callback(ProgressEvent)` (fase `classification` o `enrichment`) |
| — | `prompts=PromptRegistry(...)` (por defecto, los del proyecto o los empaquetados) |

`ai_scope` o `enrich` sin `llm` lanza `ValueError`.

## `Context`

| 1.x | 2.0 |
|---|---|
| `ai_classification_enabled`, `ai_enrichment_enabled` | `ai_stats.scope`, `ai_stats.enrich` |
| `ai_documents_sent`, `ai_documents_classified`, `ai_documents_failed`, `ai_classification_stopped` | `ai_stats.classification.sent`, `.assigned`, `.failed`, `.stopped` (y `prompt_tokens`, `completion_tokens`, `response_format`) |
| `ai_enrichment_sent`, `ai_enrichment_applied`, `ai_enrichment_failed`, `ai_enrichment_stopped` | `ai_stats.enrichment.*` |
| `ai_classification_model`, `ai_enrichment_model` | `ai_provenance` (prompt y modelo por tarea) o `context.model_for_task("classify")` |
| — | `schema_version`, `taxonomy_axes`, `DomainDocument.classification` (valores por eje, con quién los asignó, confianza y cita) |

Un `context.json` de 1.x **se sigue leyendo**: se migra en memoria (los recuentos van a `ai_stats`, los modelos a
`ai_provenance` con el prompt marcado como `1.x`, y la clasificación de los ejes organizadores sale del dominio y el
tipo de material de cada documento). Se escribe en el formato de 2.0 al reconstruir. `material_type`, `classified_by`
y el dominio de cada documento se siguen guardando como en 1.x.

## Taxonomía

| 1.x | 2.0 |
|---|---|
| `TaxonomyManifest.domains`, `.material_types` | `TaxonomyManifest.axes`; `manifest.folder_axis.entries`, `manifest.subfolder_axis.entries` |
| `TaxonomyCatalogEntry` | `TaxonomyEntry` (con `description` y `examples`) |
| Front matter con `domains:`/`material_types:` (y `facets:` o ejes implícitos) | `schema: 2` y `axes:`; los de 1.x se leen y se migran en memoria, `migrate_manifest_v1(text)` los reescribe |

Límites con mensaje claro: 10 ejes, 150 entradas por eje, descripciones de 500 caracteres y claves
`^[a-z][a-z0-9_]{0,40}$`. `inspect_taxonomy_front_matter` dice qué ejes se leerán y qué claves se ignoran.

## Lo que cambia de comportamiento

Sin cambiar de API, estas cosas funcionan distinto que en 1.x:

| Qué | 1.x | 2.0 |
|---|---|---|
| Sin IA ni decisiones | — | **Igual que 1.7**: dominio y tipo de material idénticos (comprobado con el corpus de los tests y CALIDAD_VD) |
| Respuesta de la IA al clasificar | Un valor por eje | Varios valores en los ejes que lo admiten, cada uno con **cita literal** del documento; si la cita no aparece, la confianza se limita por debajo del umbral y el valor va a la cola de revisión (D10) |
| Lo que ve la IA | El comienzo del texto | Un extracto (título, carpeta, metadatos, títulos, primeros bloques y bloques con términos del catálogo) y el **perfil del proyecto** si lo hay |
| Reconstruir sin cambios | Volvía a llamar al modelo | **No llama**: caché de resultados en `.doc_organize/ai_cache/` (`build(ai_cache=False)` para desactivarla) |
| Credenciales hacia la IA | Opcional | **Redactadas por defecto** (D7), también en las herramientas de los agentes y en los embeddings |
| Decisiones de personas | — | Si existe `.doc_organize/decisions.json`, `build` las aplica antes que las reglas y la IA (`decisions=False` para no hacerlo) |
| Historial del contexto | `added`, `removed`, `reclassified` | Además `superseded` (versión antigua) y `excluded` (excluido por una persona), que antes salían como `removed` |

## Lo nuevo (opcional)

Nada de esto se activa solo:

| Qué | Dónde |
|---|---|
| Perfil del proyecto (contexto, reglas de desempate, glosario, ejemplos) y prompts propios por proyecto | [Contexto](../api/context.md) y [Cliente único de IA](../api/llm_client.md) |
| Evaluación contra una referencia y clasificación de prueba sin guardar (`dry_run_classify`) | [Evaluación](../api/evaluation.md) |
| Decisiones de personas y cola de revisión | [Decisiones](../api/decisions.md) |
| Versiones de un mismo documento (`build(versions="mark" \| "current_only")`) | [Versiones](../api/versions.md) |
| Clasificación semántica con embeddings (`build(semantic=True)`) | [Clasificación semántica](../api/semantic.md) |
| Agentes: diseñador de la taxonomía, revisor y auditor | [Agentes](../api/agents.md) |
| Sitio sin conexión y ZIP reproducible para entregarlo | [Sitio sin conexión](../api/offline_site.md) |
| Paquete del contexto para IA (`llms.txt`) | [Paquete para IA](../api/ai_bundle.md) |
| Diagnóstico del entorno (`check_environment`) | [Diagnóstico](../api/diagnostics.md) |
| Frescura del contexto respecto a la caché del escaneo (`check_context_freshness`) | [Contexto](../api/context.md) |
