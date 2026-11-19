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
`doc-organize-<tarea>`; los alias se recomiendan pero no se exigen. Cada respuesta tiene un tope de tokens
(`TaskSettings.max_tokens`; por defecto `DEFAULT_MAX_TOKENS`: 1024 en `classify`, 512 en `enrich`, 4096 en
`taxonomy_design`) que corta las respuestas que se desbocan; una respuesta cortada no pasa la validación y cuenta como
fallo.

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
| `classify_document(llm, prompts, *, axes, title, content, profile="")` | `classify` | `ClassificationAnswer`: por eje pedido (`AxisRequest.from_axis(eje)` o `AxisRequest.from_slugs(clave, slugs)`), un `AxisAnswer` con sus `choices` (`AxisChoice`: `slug`, `confidence`, `evidence`, `evidence_verified`; uno como mucho, o 5 si el eje es múltiple) y `reasoning`. El esquema lleva un `enum` con los slugs de cada eje; un valor fuera del catálogo se descarta |
| `enrich_document(llm, prompts, *, title, content, profile="")` | `enrich` | `DocumentEnrichmentResult` (descripción y hasta 8 palabras clave, limpias), a partir del extracto (hasta `MAX_CONTENT_CHARS`) entre delimitadores |
| `draft_taxonomy(llm, prompts, documents)` | `taxonomy_design` | `TaxonomyManifestDraftResult` sin slugs repetidos, con descripciones y un perfil inicial (`profile`: contexto, reglas de desempate y glosario); `.to_manifest()` y `render_taxonomy_manifest_markdown` para revisarlo (el perfil va en las secciones del cuerpo) |

Todos devuelven `LlmResult` (`value`, `model`, `response_format`, `usage`, `redacted`) y aceptan `on_redacted` para
anotar lo redactado por documento. `ContextBuilder.build(llm=..., ai_scope="unclassified", enrich=True)` los usa por
dentro. La clasificación envía el catálogo con nombres y descripciones, el perfil del proyecto y el extracto (ver
abajo); el enriquecimiento, el perfil y un extracto más corto (4000 caracteres, como en 1.x).

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

## Lo que recibe el modelo (2.0.0, M5)

Para que el modelo clasifique como lo haría alguien del proyecto, M5 cambia lo que se le envía en la tarea `classify`
(prompt versión 2):

- **`.json` completo** (`read_conversion_document`): título, fragmentos con su ruta de títulos de sección y huella del
  original (hasta 1.7 se descartaban los títulos).
- **Extracto** (`doc_organize.ai.excerpt.build_document_excerpt`, hasta 4500 caracteres): título, carpeta (dos niveles
  como mucho), metadatos, esquema de títulos, el comienzo con texto de verdad (sin portadas ni índices) y los fragmentos
  que mencionan términos del catálogo, aunque estén al final. Determinista; `EXCERPT_VERSION` identifica su forma.
- **Perfil del proyecto** (`ProjectProfile`, `TaxonomyManifest.profile`): las secciones `## Contexto del proyecto`,
  `## Reglas de desempate`, `## Glosario` y `## Ejemplos` del cuerpo del manifiesto o la plantilla, más las de
  `<raíz>/.doc_organize/profile.md`, que se añaden detrás (D11). Como mucho 8000 caracteres y 20 ejemplos, sin
  caracteres de control.
- **Catálogo con nombres y descripciones** (`render_catalog`): por eje, su nombre, si admite varios valores y qué
  clasifica, y cada valor con su nombre y descripción, una línea cada uno. El modelo solo puede responder slugs (`enum`).

El mensaje `system` lleva las instrucciones, el perfil y el catálogo (el mismo prefijo en todo el proyecto); el `user`,
solo el extracto entre `<<<DOCUMENTO` y `DOCUMENTO>>>` (el texto del documento no puede cerrar el bloque). El modelo
responde, por eje, `values`: una lista de `{value, confidence, evidence}`, donde `evidence` es un fragmento del
documento copiado tal cual (de 3 a 15 palabras). La cita se comprueba contra lo enviado, sin distinguir mayúsculas,
acentos ni espacios, sin las comillas que la rodeen y, si lleva puntos suspensivos, trozo a trozo
(`AxisChoice.evidence_verified`); **si no aparece, la confianza del valor queda justo por debajo del umbral del eje**
(D10): el valor se conserva en el contexto, con su cita, para revisarlo. En los ejes que solo etiquetan, los valores
por debajo del umbral del eje se descartan.

`render_prompt_preview(manifest)` devuelve los mensajes que recibiría el modelo con ese manifiesto, sin llamar a nadie:
para revisar el catálogo y el perfil antes de gastar llamadas.

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
