# Medición de M8.2: diseñador de la taxonomía sobre CALIDAD_VD

Fecha: 2026-11-19. Puerta de M8: «la propuesta del diseñador mejora cobertura y conflictos de la plantilla original en
`dry_run`». Medido en memoria (solo lectura del proyecto), contra el LiteLLM Proxy local con Ollama.

**Estado: puerta pendiente.** La infraestructura funciona (el agente explora, edita, deshace y termina), pero con el
modelo local de 9B la propuesta final no mejora de forma fiable la plantilla. Se vuelve a medir con un modelo más capaz
antes del rc (M10).

## Plantilla de partida (por reglas, 213 documentos legibles)

| Eje | Cobertura | Conflictos | Entradas vacías |
|---|---|---|---|
| domains | 91,5 % (195) | 62 | 1 |
| material_types | 93,0 % (198) | 48 | 0 |

Criterio (`TaxonomyRulesReport.improves_on`): en ningún eje baja la cobertura ni suben los conflictos, y en alguno
mejora.

## Hallazgos del entorno

- **Ollama recorta la entrada a 4096 tokens por defecto, sin error**: el agente perdía el prompt de sistema y
  respondía describiendo el JSON. Con `num_ctx` 32768 en la petición (inyectado desde el script de medición, sin
  cambiar la configuración del proxy) entra entera. La clasificación de una llamada (M5) cabía en 4096: sus medidas son
  válidas. Documentado en `docs/api/agents.md`.
- `qwen2.5-coder:14b` (alias `DOC_ORGANIZE_LITELLM_ENRICHMENT_MODEL`): con 32k sigue en bucle (24 `overview`
  seguidos); escribe a veces la llamada como JSON en el texto (el runner ya la reconoce).
- `qwen3.5:9b`: trabaja como agente con 32k.

## Iteraciones (todas con `qwen3.5:9b`, 32k)

| Cambio | Resultado |
|---|---|
| Manifiesto completo en `finish` | No termina (`invalid_answer`): no escribe el manifiesto |
| Borrador editable (`edit_draft`, `undo_edit`) y `finish` solo con la justificación | Explora y edita; se queda sin pasos |
| Informe con el resumen primero (antes se cortaba a 8000 caracteres y el modelo no veía si mejoraba), términos de cada conflicto, casi aciertos y palabras clave sin uso | Termina con `finish` |
| Mejor borrador guardado y `restore_best` (si termina con uno peor habiendo tenido uno mejor) | Ver tabla |

## Resultados (propuesta final)

| Ejecución | domains | material_types | Mejora |
|---|---|---|---|
| 1 | 93,4 % / 79 | 94,4 % / 31 | No; un borrador intermedio sí (197 cubiertos / 50 conflictos en domains, igual en material_types), que hoy recuperaría `restore_best` |
| 2 | 97,2 % / 61 | 93,0 % / 51 | No (+3 conflictos en material_types) |
| 3 | 94,4 % / 81 | 93,0 % / 48 | No |
| 4 | 94,8 % / 117 | 93,0 % / 48 | No |

Cada ejecución: ~29 pasos, 260 000-330 000 tokens de entrada, 10-15 minutos.

El patrón: el modelo sube la cobertura con palabras clave genéricas que crean empates. Las mejoras sin empates las
encuentra a veces, pero no las mantiene.

## Siguiente

- Volver a medir con un modelo más capaz (decisión del mantenedor: no se cambia la configuración del proxy desde aquí).
- Si sigue sin cumplir, valorar una herramienta que sugiera palabras clave a partir de los documentos (opción 2).

## M8.3: revisor y auditor sobre CALIDAD_VD (contexto guardado, solo lectura)

Plantilla: el manifiesto del proyecto (2 ejes). Cola de revisión: 7 documentos (4 sin clasificar, 3 con desacuerdo
reglas/IA).

- **Auditor** (sin IA): dominios con valor en el 98,1 %, tipos de material en el 99,5 %, sin confianza baja ni citas
  sin verificar; 3 propuestas `rules_ai_confusion` (pares de dominios que la IA corrige a menudo).
- **Revisor** (`qwen3.5:9b`, 32k): 3 propuestas `set_axis` válidas, todas con cita, de 7 documentos; 21 pasos,
  ~85 000 tokens de entrada, 9 minutos. Terminó en `invalid_answer` porque el modelo escribió las llamadas como texto
  con `function_name` en lugar de `name`: el runner ya reconoce esa forma. Sin referencia etiquetada disponible, la
  calidad de las propuestas no se ha medido (la revisa una persona: D14).

## Nota sobre la plantilla de la puerta

La medición del diseñador de arriba usa el **manifiesto del proyecto** (2 ejes). La plantilla de las mediciones M0/M5
(5 ejes: dominios, tipos de material, sistema de gestión, marcos normativos y evidencias) es la «plantilla original»
del plan: hay que repetir la medición del diseñador con ella cuando se vuelva a medir con un modelo más capaz.
