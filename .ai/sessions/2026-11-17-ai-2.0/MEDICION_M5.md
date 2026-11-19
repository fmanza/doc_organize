# Medición de M5 contra la línea base (M0)

Fecha: 2026-11-19. Corpus CALIDAD_VD (213 documentos), catálogo y umbral de la plantilla de M0, referencia de M0
(150 documentos etiquetados en dominio y tipo de material). IA en memoria (sin reconstruir el contexto del proyecto),
`ai_scope="unclassified"`: 38 documentos a la IA, como en M0. Proxy local, modelo `qwen2.5-coder:14b` en Ollama
(alias `DOC_ORGANIZE_LITELLM_ENRICHMENT_MODEL`), `json_schema` estricto en todas las llamadas. Sin nombres de
documentos aquí; las citas sin verificar se analizaron solo en local.

## Resultados

| | M0 (1.7.1) | M5 primera versión | **M5 ajustado** |
|---|---|---|---|
| Exactitud dominio | 0,2333 | 0,2467 | **0,2533** (+2,0 pts) |
| Dominio en los documentos de la IA | 0,333 | 0,391 | **0,435** |
| Exactitud tipo de material | 0,22 | 0,2267 | **0,2267** (+0,7 pts) |
| Tipo de material en los documentos de la IA | 0,333 | 0,348 | **0,348** |
| Cobertura (dominio / tipo) | 0,98 / 1,0 | 1,0 / 1,0 | 1,0 / 1,0 |
| Fallos de IA | 0 | 0 | 0 |
| Tokens de entrada por documento (media) | 1226 | 2082 (1,70×) | **1985 (1,62×)** |
| Tokens de salida por documento (media / máx.) | 112 / 152 | 519 / 4964 | **284 / 693** |
| Total por documento | 1338 | 2601 (1,94×) | **2269 (1,70×)** |
| Segundos por llamada (media / p95) | 50 / 69 | 53 / 145 | **27 / 48** |
| Citas verificadas | — | 24 de 53 | **42 de 53** |

Los tiempos no son comparables entre sí: M0 y la primera versión corrieron con el modelo en CPU (al menos en parte) y
el ajustado con 57 % en GPU.

## Ajustes entre la primera versión y la ajustada

1. `TaskSettings.max_tokens` (por defecto 1024 en `classify`): corta las respuestas que se desbocaban.
2. Prompt `classify` versión 3: cita de 3 a 15 palabras copiadas tal cual y justificación de 25 palabras como mucho.
3. Verificación de la cita sin las comillas que la rodeen y trozo a trozo si lleva puntos suspensivos.
4. Extracto de 6000 a 4500 caracteres (`EXCERPT_VERSION = "2"`).

## Lectura

- Ningún eje empeora; la IA acierta bastante más donde interviene. La exactitud total sube poco porque las confusiones
  grandes vienen de las reglas (las mismas que en M0: cumplimiento legal → riesgos y amenazas; referencial normativo →
  procedimiento y control), y la IA solo ve los 38 documentos que las reglas no resuelven.
- **Coste: 1,62× en entrada (referencia 1,5×), 1,70× en total.** La mitad del prompt es fija (instrucciones y catálogo
  con descripciones, unos 3400 caracteres); con un proveedor con caché de prefijo esa parte se paga una vez. Recortar
  el extracto apenas ayuda (pocos documentos llegan al tope). Se vuelve a medir en M10 (criterio de salida).
- Citas sin verificar (11): 8 son títulos de sección del esquema unidos con comas (cada uno está, no seguidos) y 3 son
  citas reales de más de 50 palabras que se salen del fragmento enviado. Quedan bajo el umbral y van a la cola de
  revisión, que es lo conservador.

## Siguiente

- `2.0.0a1` con M5 completo.
- Para M10: probar con un modelo con caché de prefijo y, si hace falta, un catálogo más corto en el prompt (solo las
  descripciones de las entradas candidatas).
