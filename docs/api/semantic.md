# Clasificación semántica (2.0.0)

Entre las reglas (que buscan palabras) y la IA (que lee el documento y cuesta una llamada por documento), la
**sub-fase semántica** compara significados con embeddings: un vector por documento y uno por valor del catálogo. Es
opcional (D13) y barata: con el índice guardado, reconstruir no vuelve a pedir nada.

```python
context = await ContextBuilder().build(
    project, documents, taxonomy_manifest=manifest, llm=llm,
    semantic=True,                # tras reglas y decisiones, antes de la IA
    semantic_threshold=0.75,      # similitud mínima (coseno)
    ai_scope="unclassified",      # la IA solo ve lo que siga vacío
)
print(context.ai_stats.semantic_classification)  # textos embebidos, sacados del índice, documentos asignados
```

## Qué hace

- Solo rellena **ejes vacíos**: los que organizan que las reglas dejaron sin clasificar y los que etiquetan sin valor.
  Nunca cambia lo que decidieron las reglas o una persona.
- Compara el extracto del documento (hasta 4000 caracteres) con el texto de cada valor del catálogo:
  `«Eje: Nombre. Descripción. palabras clave»`. Cuanto mejor sea la descripción, mejor funciona.
- En un eje de **un valor**, asigna el más parecido si llega al umbral **y** le saca al segundo al menos
  `SEMANTIC_MARGIN` (0,03): ante un empate no decide.
- En un eje de **varios valores**, todos los que llegan al umbral, hasta 5.
- Lo asignado queda con `classified_by="semantic"` y la similitud como confianza.
- Un fallo del modelo de embeddings no para la construcción: queda en `semantic_classification.failed`.

Necesita la tarea `embed` en `AiSettings` (un modelo de embeddings en el proxy) y un manifiesto de taxonomía.

## El índice

`EmbeddingIndex(project_root, model=, redacted=)` guarda los vectores en `<raíz>/.doc_organize/embeddings/<modelo>/`
(`vectors.bin`, números `float32` del módulo `array`, sin numpy, e `index.json`). La clave de cada texto es la huella
del modelo, de si se redactó y del texto: cambiar de modelo o de texto da vectores nuevos. Los textos se redactan antes
de enviarlos (`LlmClient.embed`); aun así, el índice deriva del contenido de los documentos: trátalo como `Conversión/`.

::: doc_organize.ai.embeddings
    options:
      show_root_heading: false
      members:
        - EmbeddingIndex
        - cosine

::: doc_organize.context.semantic
    options:
      show_root_heading: false
      members:
        - classify_semantic
        - best_values
        - entry_text
