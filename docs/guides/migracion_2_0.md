# De doc_organize 1.x a 2.0

doc_organize 2.0 cambia la taxonomía (ejes en vez de dos listas) y la IA (un cliente único en vez de cuatro). Esta guía
recoge **lo que se rompe** y qué usar en su lugar. Se completa a medida que avanza 2.0; lo que ya está en esta versión
de desarrollo está marcado con su hito.

Si solo usas el CLI de escaneo, conversión, deduplicación y exportación, no tienes que hacer nada.

## Variables de entorno de la IA (M4)

Las variables de 1.x **ya no se leen**. Si alguna sigue definida, `settings_from_env()` lanza `AiConfigurationError`
con la lista de las antiguas y su equivalente, y `check_environment(check_ai=True)` lo informa como error. Así una
actualización sin reconfigurar no deja la IA desactivada en silencio.

| 1.x | 2.0 |
|---|---|
| `DOC_ORGANIZE_LITELLM_CLASSIFICATION_BASE_URL`, `_TAXONOMY_CLASSIFICATION_BASE_URL`, `_ENRICHMENT_BASE_URL`, `_TAXONOMY_MANIFEST_DRAFT_BASE_URL` | `DOC_ORGANIZE_LITELLM_BASE_URL` (una para todas; es la misma que ya usaba `LiteLLMUsageClient`) |
| `DOC_ORGANIZE_LITELLM_CLASSIFICATION_VIRTUAL_KEY`, `_TAXONOMY_CLASSIFICATION_VIRTUAL_KEY` | `DOC_ORGANIZE_LITELLM_VIRTUAL_KEY` o, si quieres una clave propia, `DOC_ORGANIZE_LITELLM_VIRTUAL_KEY_CLASSIFY` |
| `DOC_ORGANIZE_LITELLM_ENRICHMENT_VIRTUAL_KEY` | `DOC_ORGANIZE_LITELLM_VIRTUAL_KEY` o `DOC_ORGANIZE_LITELLM_VIRTUAL_KEY_ENRICH` |
| `DOC_ORGANIZE_LITELLM_TAXONOMY_MANIFEST_DRAFT_VIRTUAL_KEY` | `DOC_ORGANIZE_LITELLM_VIRTUAL_KEY` o `DOC_ORGANIZE_LITELLM_VIRTUAL_KEY_TAXONOMY_DESIGN` |
| `DOC_ORGANIZE_LITELLM_CLASSIFICATION_MODEL`, `_TAXONOMY_CLASSIFICATION_MODEL` | `DOC_ORGANIZE_LITELLM_MODEL_CLASSIFY` |
| `DOC_ORGANIZE_LITELLM_ENRICHMENT_MODEL` | `DOC_ORGANIZE_LITELLM_MODEL_ENRICH` |
| `DOC_ORGANIZE_LITELLM_TAXONOMY_MANIFEST_DRAFT_MODEL` | `DOC_ORGANIZE_LITELLM_MODEL_TAXONOMY_DESIGN` |

Sin `MODEL_<TAREA>`, la tarea usa el alias recomendado `doc-organize-<tarea>` (`doc-organize-classify`,
`doc-organize-enrich`, `doc-organize-taxonomy-design`): o lo creas en el proxy o das el modelo real en la variable.

## Clientes de IA (M4)

| Se retira | Sustituto |
|---|---|
| `DomainClassificationClient`, `TaxonomyClassificationClient`, `DocumentEnrichmentClient`, `TaxonomyManifestDraftClient` | `LlmClient(AiSettings)` y los servicios `classify_document`, `enrich_document`, `draft_taxonomy` (`doc_organize.ai`) |
| `LiteLLMClassificationConfig`, `LiteLLMTaxonomyClassificationConfig`, `LiteLLMEnrichmentConfig`, `LiteLLMTaxonomyManifestDraftConfig` | `AiSettings` (con `TaskSettings` por tarea) |
| `litellm_classification_config_from_env()` y las otras tres | `settings_from_env()` |
| `DomainClassificationResult`, `TaxonomyClassificationResult` | `ClassificationAnswer` (`axes: dict[clave, AxisAnswer]`) |
| `DomainClassificationError`, `TaxonomyClassificationError`, `DocumentEnrichmentError`, `TaxonomyManifestDraftError` y sus `*AuthError`/`*ConnectionError` | `AiError`, `AiAuthError`, `AiConnectionError`, `AiResponseError` |
| `SampledDocument` en `doc_organize.ai.taxonomy_manifest_draft_client` | `doc_organize.ai.SampledDocument` |
| `ContextBuilder(ai_redact_credentials=)`, `LiteLLMTaxonomyManifestDraftConfig.redact_credentials` | `AiSettings.redact_credentials` (la redacción la hace `LlmClient` con todo lo que sale) |

`LiteLLMUsageClient` y `GitHubCopilotUsageClient` no cambian.

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

## `ContextBuilder.build` (M4)

Todos los parámetros tras `documents` pasan a ser **solo por nombre**.

| 1.x | 2.0 |
|---|---|
| `ai_classification_enabled=True, ai_classification_client=c` / `taxonomy_classification_client=c` | `llm=LlmClient(...), ai_scope="unclassified"` |
| `ai_enrichment_enabled=True, ai_enrichment_client=c` | `llm=..., enrich=True` |
| `on_ai_progress=callback(index, total, ruta)` | `on_progress=callback(ProgressEvent)` (fase `classification` o `enrichment`) |
| — | `prompts=PromptRegistry(...)` (por defecto, los del proyecto o los empaquetados) |

`ai_scope` o `enrich` sin `llm` lanza `ValueError`.

## `Context` (M1 y M4)

| 1.x | 2.0 |
|---|---|
| `ai_classification_enabled`, `ai_enrichment_enabled` | `ai_stats.scope`, `ai_stats.enrich` |
| `ai_documents_sent`, `ai_documents_classified`, `ai_documents_failed`, `ai_classification_stopped` | `ai_stats.classification.sent`, `.assigned`, `.failed`, `.stopped` (y `prompt_tokens`, `completion_tokens`, `response_format`) |
| `ai_enrichment_sent`, `ai_enrichment_applied`, `ai_enrichment_failed`, `ai_enrichment_stopped` | `ai_stats.enrichment.*` |
| `ai_classification_model`, `ai_enrichment_model` | `ai_provenance` (prompt y modelo por tarea) o `context.model_for_task("classify")` |
| — | `schema_version`, `taxonomy_axes`, `DomainDocument.classification` (ejes, M1) |

Un `context.json` de 1.x **se sigue leyendo**: se migra en memoria (los recuentos van a `ai_stats`, los modelos a
`ai_provenance` con el prompt marcado como `1.x`, y la clasificación de los ejes organizadores sale del dominio y el
tipo de material de cada documento). Se escribe en el formato de 2.0 al reconstruir.

## Taxonomía (M1)

| 1.x | 2.0 |
|---|---|
| `TaxonomyManifest.domains`, `.material_types` | `TaxonomyManifest.axes`; `manifest.folder_axis.entries`, `manifest.subfolder_axis.entries` |
| `TaxonomyCatalogEntry` | `TaxonomyEntry` |
| Front matter con `domains:`/`material_types:` (y `facets:` o ejes implícitos) | `schema: 2` y `axes:`; los de 1.x se leen y se migran en memoria, `migrate_manifest_v1(text)` los reescribe |
