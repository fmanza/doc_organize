# Cliente único de IA (2.0)

`LlmClient` es, desde 2.0.0, el único camino por el que doc_organize envía algo a un modelo. Sustituye a los cuatro
clientes de 1.x (clasificación, clasificación por manifiesto, enriquecimiento y borrador de taxonomía), que se retiran en
el mismo ciclo de 2.0 (la guía de migración llega con ese paso).

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
