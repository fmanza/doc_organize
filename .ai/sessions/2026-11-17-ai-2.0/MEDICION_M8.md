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
