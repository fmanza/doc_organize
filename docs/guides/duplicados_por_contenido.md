# Duplicados por contenido (2.2.0)

`DeduplicationManager.find_duplicates` encuentra duplicados por el **fichero**: el mismo hash, versiones del mismo
nombre o nombres parecidos. `ContentDuplicateFinder` los busca por lo que **dicen** los documentos, sobre el Markdown
que generó la conversión (`Conversión/`). Así aparecen:

- el mismo documento en dos formatos (un `.docx` y el `.pdf` que se exportó de él);
- versiones reescritas, borradores o la misma plantilla con otros datos;
- un documento contenido en otro (un anexo que también está dentro del informe completo).

Todo se hace en local: el texto va al modelo de embeddings de **tu** LiteLLM Proxy, que puede ser un modelo de Ollama en
la misma máquina.

## Cuándo usarlo

Necesita los documentos **ya convertidos**: en un proyecto, después de escanear y convertir. Es una segunda vuelta de la
búsqueda de duplicados, con la misma revisión y la misma forma de resolver.

| Vuelta | Cuándo | Qué encuentra |
|---|---|---|
| 1.ª `find_duplicates` | Antes de convertir | Mismo hash, versiones, nombre parecido |
| 2.ª `ContentDuplicateFinder` | Después de convertir | Mismo contenido, contenido parecido (IA) |

## Las dos pasadas

1. **Mismo contenido** (`DuplicateReason.SAME_CONTENT`, sin IA). Se quitan del Markdown el formato, las imágenes, los
   enlaces, las mayúsculas y la puntuación; si el texto que queda es el mismo, es el mismo contenido.
2. **Contenido parecido** (`DuplicateReason.SEMANTIC_CONTENT_MATCH`, opcional, con IA). Cada documento se parte en
   bloques de 800 palabras (con 100 de solape) y cada bloque se convierte en un vector:
    - un vector medio por documento elige sus 10 vecinos más cercanos;
    - con cada vecino se comparan bloque a bloque, en los dos sentidos (cuánto de A está en B y al revés). La
      similitud del par es la mayor de las dos; si solo una llega al umbral, el grupo queda marcado como `contained`
      (un documento contenido en otro).

De cada grupo parecido se dan dos números:

| Campo | Qué mide | Cómo leerlo |
|---|---|---|
| `similarity` | Parecido del significado (0-1), el menor entre los miembros | Por encima de 0,95, casi el mismo documento |
| `lexical_similarity` | Parecido del texto (Jaccard de trozos de 5 palabras) | Alto: casi el mismo texto. Bajo con `similarity` alta: reescrito o la misma plantilla con otros datos |

Un documento entra en un grupo solo si se parece a **todos** sus miembros: si A se parece a B y B a C pero A no a C, no
se juntan los tres.

## Configurar el modelo

La búsqueda por contenido parecido usa la tarea de IA **`dedup`**, independiente de los embeddings del contexto
(`embed`): tiene su modelo, su clave y su gasto aparte en LiteLLM. Sin un modelo propio para `dedup` no se ejecuta
(`AiConfigurationError`); no usa el de `embed`.

```bash
DOC_ORGANIZE_LITELLM_MODEL_DEDUP=doc-organize-dedup
DOC_ORGANIZE_LITELLM_VIRTUAL_KEY_DEDUP=sk-...   # opcional: clave y presupuesto aparte
```

En el proxy, `bge-m3` con Ollama (multilingüe, buen rendimiento en español, hasta 8.192 tokens). Ver
`deploy/litellm/config.yaml.example`:

```yaml
- model_name: doc-organize-dedup
  litellm_params:
    model: ollama/bge-m3
    api_base: http://host.docker.internal:11434
    num_ctx: 8192   # sin esto, Ollama corta a 4096 tokens
```

`check_environment(check_ai=True)` prueba el modelo de `dedup`, dice qué modelo contesta detrás del alias
(`served_model`) y la dimensión de los vectores, y **avisa si corta el texto** antes de unas 1.500 palabras. En ese
caso, sube `num_ctx` o usa bloques más pequeños (`chunk_words`).

## Uso

```python
from doc_organize import ContentDocument, ContentDuplicateFinder, DeduplicationManager, LlmClient
from doc_organize.ai import settings_from_env

documents = [ContentDocument(metadata=metadata, conversion=conversion) for metadata, conversion in converted]

async with LlmClient(settings_from_env()) as llm:
    finder = ContentDuplicateFinder(project_root, llm, semantic_threshold=0.90)
    report = await finder.find(documents, semantic=True)

for group in report.groups:
    print(group.reason.value, group.similarity, group.lexical_similarity, group.contained)
print("Sin comparar:", report.not_compared)  # sin conversión, ilegibles o con menos de 30 palabras
```

Sin `llm` (o con `semantic=False`) solo se hace la pasada de «mismo contenido», que no necesita IA.

Los duplicados exactos (mismo hash) cuentan una sola vez: esos los agrupa `find_duplicates`. Los vectores se guardan en
el índice de embeddings del proyecto (`.doc_organize/embeddings/`): repetir la búsqueda no los vuelve a pedir.

## Calibrar el umbral

| Similitud | Interpretación habitual |
|---|---|
| > 0,95 | El mismo documento con cambios mínimos (fechas, nombres, erratas) |
| 0,85 – 0,95 | Versiones reescritas, borradores o plantillas rellenadas con información muy parecida |
| < 0,85 | Documentos del mismo tema con contenido distinto |

El valor por defecto es **0,90**: los modelos de embeddings dan valores altos incluso a documentos distintos del mismo
tema. Empieza ahí y baja solo si echas en falta grupos.

## Resolver

Igual que los grupos por nombre parecido, **nunca se resuelven solos**: una persona elige qué conservar
(`DuplicateGroup.user_choice`). Se aplican con las mismas herramientas, pasando la conversión de cada original:

```python
conversions = {doc.metadata.full_path: doc.conversion for doc in documents}
report = await DeduplicationManager().resolve_duplicates(
    confirmed_groups, duplicates_dir, relative_to=source_root,
    conversions=conversions, conversion_dir=conversion_root,
)
```

| Modo | El original descartado | Su conversión |
|---|---|---|
| `move` (por defecto) | Se mueve a la carpeta de duplicados | **Se mueve con él**, a `duplicados/Conversión/`: deja de entrar en el contexto y se puede devolver a su sitio sin volver a convertir |
| `copy` (origen de solo lectura) | Se copia; el original se queda | No se toca: exclúyelo del contexto con `exclude_from_context` |
| `report_only` | No se toca | No se toca |

Nunca se borra nada. Después de resolver, **reconstruye el contexto**.

`exclude_from_context(project_root, groups, roots=scan_roots)` guarda una decisión `exclude` por cada descartado (con
la huella del original, revocable como cualquier otra). Como todas las decisiones, solo se aplica al construir con un
manifiesto de taxonomía; sin él queda en `Context.stale_decisions`.

## Privacidad

A la tarea `dedup` va el texto **completo** de cada documento (al contexto semántico solo va un extracto), con las
credenciales redactadas antes de enviar. Usa un modelo local. El índice de vectores deriva del contenido de los
documentos: trátalo como `Conversión/` (se borra con `clear_embedding_index`).
