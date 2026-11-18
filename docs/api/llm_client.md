# Cliente único de IA (2.0)

`LlmClient` es, desde 2.0.0, el único camino por el que doc_organize envía algo a un modelo. Sustituye a los cuatro
clientes de 1.x (clasificación, clasificación por manifiesto, enriquecimiento y borrador de taxonomía); ver
[De 1.x a 2.0](../guides/migracion_2_0.md).

```python
from doc_organize.ai import LlmClient, PromptRegistry, settings_from_env

settings = settings_from_env()  # None si la IA no está configurada
async with LlmClient(settings) as client:
    messages = PromptRegistry(project.root_path).get("enrich").render(max_keywords=8, title=title, content=text)
    result = await client.complete_json("enrich", messages, schema=esquema, parse=validar)
```

## Configuración

`AiSettings`: un LiteLLM Proxy, una clave general y un modelo (y si se quiere una clave propia, D12) por **tarea**:
`classify`, `enrich`, `taxonomy_design`, `agent`, `embed`. Una tarea sin configurar usa el alias recomendado
`doc-organize-<tarea>`; los alias se recomiendan pero no se exigen.

| Variable de entorno | Para qué |
|---|---|
| `DOC_ORGANIZE_LITELLM_BASE_URL` | URL del proxy |
| `DOC_ORGANIZE_LITELLM_VIRTUAL_KEY` | Clave general |
| `DOC_ORGANIZE_LITELLM_MODEL_<TAREA>` | Modelo de la tarea (`CLASSIFY`, `ENRICH`, `TAXONOMY_DESIGN`, `AGENT`, `EMBED`) |
| `DOC_ORGANIZE_LITELLM_VIRTUAL_KEY_<TAREA>` | Clave propia de la tarea (opcional) |

Las variables de 1.x (`DOC_ORGANIZE_LITELLM_CLASSIFICATION_*`, `_TAXONOMY_CLASSIFICATION_*`, `_ENRICHMENT_*`,
`_TAXONOMY_MANIFEST_DRAFT_*`) **ya no se leen**: si alguna está definida, `settings_from_env` lanza
`AiConfigurationError` con la equivalente de cada una (D15). Así una actualización sin reconfigurar no deja la IA
desactivada en silencio.

## Qué hace en cada llamada

- **Redacta** las credenciales de cada mensaje antes de enviarlo (`AiSettings.redact_credentials`, por defecto
  activado) y devuelve el recuento por regla en `LlmResult.redacted`.
- Pide **`json_schema` estricto** con el esquema de la tarea. Si el proxy lo rechaza (HTTP 400), cae **una vez** a
  `json_object` y lo recuerda para ese modelo. La respuesta se **valida siempre** con `parse`; si no vale,
  `AiResponseError`.
- Reintentos de transporte y ante 429/503 con `Retry-After` (D5); `metadata.tags` con `doc_organize`, `task:<tarea>` y
  las de `AiSettings.tags`.
- Errores: `AiAuthError` (clave rechazada), `AiConnectionError` (red o timeout), `AiResponseError` (respuesta no válida)
  y `AiError` (cualquier otro).

`complete_with_tools` (una vuelta de conversación con herramientas, para los agentes) y `embed` (embeddings) siguen las
mismas reglas.

## Servicios por tarea

| Servicio | Tarea | Devuelve |
|---|---|---|
| `classify_document(llm, prompts, *, axes, title, content)` | `classify` | `ClassificationAnswer`: por eje pedido (`AxisRequest(key, slugs)`), `AxisAnswer(slug \| None, confidence)`, y `reasoning`. El esquema lleva un `enum` con los slugs de cada eje; un valor fuera del catálogo no pasa la validación |
| `enrich_document(llm, prompts, *, title, content)` | `enrich` | `DocumentEnrichmentResult` (descripción y hasta 8 palabras clave, limpias) |
| `draft_taxonomy(llm, prompts, documents)` | `taxonomy_design` | `TaxonomyManifestDraftResult` sin slugs repetidos; `.to_manifest()` y `render_taxonomy_manifest_markdown` para revisarlo |

Todos devuelven `LlmResult` (`value`, `model`, `response_format`, `usage`, `redacted`) y aceptan `on_redacted` para
anotar lo redactado por documento. `ContextBuilder.build(llm=..., ai_scope="unclassified", enrich=True)` los usa por
dentro. En este paso envían lo mismo que 1.x (slugs y los primeros 4000 caracteres); en M5 se añaden descripciones,
perfil del proyecto y extracto.

## Caché de resultados

`AiResultCache(project_root)` guarda cada respuesta en `<raíz>/.doc_organize/ai_cache/`, bajo la huella de **lo que se
enviaría**: tarea, modelo, mensajes ya redactados (prompt, catálogo y documento), esquema y si se redactó. Con
`complete_json(..., cache=cache)` (o `classify_document(..., cache=)`/`enrich_document(..., cache=)`), una petición
idéntica a una ya hecha no llama al modelo: el resultado se vuelve a validar y sale con `LlmResult.cached=True`. Cambiar
el documento, el prompt (o su versión), el modelo, el catálogo o la redacción cambia la huella y se vuelve a preguntar.
Una entrada ilegible o que ya no pasa la validación se ignora.

`ContextBuilder.build(ai_cache=True)` (por defecto) la usa: **reconstruir un contexto sin cambios no hace ninguna
llamada**. Los documentos resueltos con la caché cuentan en `AiPhaseStats.cached`, no en `sent`, y no consumen
`ai_max_documents`. `ai_cache=False` la desactiva. `prune_ai_cache(project_root, max_age_days=90)` borra las entradas
que llevan ese tiempo sin usarse (leer una entrada renueva su fecha).

La caché guarda respuestas derivadas del contenido (justificaciones, descripciones), del texto ya redactado, nunca las
claves: trátala como `Conversión/`.

## Prompts

`PromptRegistry` da el prompt de cada tarea: un `.md` empaquetado con front matter (`id`, `version`) y las secciones
`## system` y `## user`, con marcadores `$nombre`. Un proyecto puede sustituirlo con
`<raíz>/.doc_organize/prompts/<tarea>.md`. `PromptTemplate.provenance(modelo)` da el `PromptProvenance` (id, versión,
origen, SHA-256 y modelo) que se guardará en el contexto. Las instrucciones y el catálogo van en `system` y el documento
en `user`: el prefijo es el mismo entre documentos y el proveedor puede cachearlo.

::: doc_organize.ai.llm_client
    options:
      show_root_heading: false
      members:
        - LlmClient
        - LlmResult

::: doc_organize.ai.settings
    options:
      show_root_heading: false
      members:
        - settings_from_env
        - legacy_variables
