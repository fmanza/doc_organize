# Medir la clasificación (2.6)

Cómo decidir con datos si un cambio de reglas, plantilla, prompt, perfil o modelo mejora la organización documental, y no
confundir una mejora con ruido. Es el protocolo que siguen las mejoras de precisión de doc_organize a partir de 2.6.0, y
cualquiera puede aplicarlo a su propio proyecto.

## Por qué hace falta un protocolo

Con 150 documentos etiquetados y una exactitud del 25 %, el error típico es √(0,25 · 0,75 / 150) ≈ 0,035: el intervalo
al 95 % es de **±7 puntos**. Una mejora de 1 o 2 puntos entre dos evaluaciones sueltas no significa nada. Además:

- Si se calibra y se mide con los mismos documentos, el resultado es optimista (se ajusta a la referencia).
- Si la referencia la propuso un modelo de lenguaje, favorece a lo que se le parece.
- Las respuestas de un modelo cambian entre ejecuciones aunque la temperatura sea 0.

## Las piezas

| Pieza | Para qué |
|---|---|
| `load_gold_xlsx`, `GoldStandard` | La referencia: el valor correcto de cada eje para unos documentos |
| `dry_run_classify` | Clasificar con una configuración sin guardar nada |
| `evaluate_classification` | Exactitud, cobertura, F1 por valor, F1 macro, exactitud sobre lo asignado, matriz de confusión y exactitud por tramo de confianza ([Evaluación](../api/evaluation.md)) |
| `compare_classifications` | Diferencia pareada entre dos configuraciones, con intervalo de confianza y McNemar |
| `scripts/benchmark/run.py` (repositorio) | Todo lo anterior en un comando, con partición, ablaciones, repeticiones e informe |

## El protocolo

1. **Referencia fiable.** Que una persona que conoce el corpus etiquete a ciegas al menos 50 documentos (sin ver lo que
   asignó doc_organize) y medir el acuerdo con la referencia (kappa de Cohen por eje). Con kappa < 0,6 la referencia no
   sirve para decidir. Dar los resultados en tres vistas: toda la referencia, solo filas revisadas por personas y,
   si la muestra está estratificada, reponderada por estratos.
2. **Partición.** Un tramo **bloqueado** (~1/3, estratificado por valor, semilla fija, lista guardada) que solo se usa
   para aceptar un cambio; el resto, para probar y calibrar. Con pocos documentos el tramo bloqueado es pequeño:
   para cambiar un valor por defecto hace falta un segundo corpus.
3. **Métricas.** Por eje: exactitud, F1 macro, exactitud sobre lo asignado y cobertura (una abstención no es un
   error: va a la cola de revisión), y confusiones por pareja.
4. **Comparación.** Siempre pareada sobre los mismos documentos (`compare_classifications`): **no inferioridad** = el
   límite inferior del intervalo de la diferencia de exactitud no baja de −3 puntos en ningún eje y el F1 macro no baja
   más de 3 puntos; **mejora** = el intervalo de la exactitud excluye el 0 y la candidata supera la línea base de
   «asignar siempre el valor más frecuente» (2.7.0). Mirar siempre esa línea base: con clases desequilibradas, una
   exactitud alta puede no aportar nada.
5. **Ablación.** Un cambio por ejecución; las combinaciones, solo para confirmar.
6. **IA sobre toda la referencia.** Para medir un cambio de prompt o de modelo, mandar a la IA todos los documentos, no
   solo los que las reglas dejan sin clasificar.
7. **Ruido de la IA.** Repetir 2-3 veces la configuración base sin caché; si la variación es comparable al efecto, no
   se decide.
8. **Ejemplos y decisiones por pliegues.** Si una configuración usa decisiones o ejemplos, en cada pliegue sirven de
   decisiones las etiquetas de los otros pliegues, nunca las del propio.
9. **Modelo.** Si la referencia la propuso un modelo, no medir con modelos de la misma familia, o dar esos resultados
   aparte.
10. **Presupuesto y registro.** Con IA local cada prueba en seco tarda del orden de una hora: planificar cuántas
    ejecuciones hay y registrar modelo, prompt, catálogo, perfil y semilla de cada una.

## Con la API

```python
from doc_organize import compare_classifications, dry_run_classify, load_gold_xlsx

gold = load_gold_xlsx("referencia.xlsx")  # fuera del repositorio
base = await dry_run_classify(project, documents, gold=gold, taxonomy_manifest=actual, decisions=False)
nuevo = await dry_run_classify(project, documents, gold=gold, taxonomy_manifest=propuesto, decisions=False)

print(base.evaluation.to_markdown(detail=True))
comparacion = compare_classifications(base.context, nuevo.context, gold, margin=0.03)
print(comparacion.to_markdown())
adoptar = comparacion.non_inferior and comparacion.improved
```

`decisions=False`: si se aplican las decisiones de las personas, lo que decidieron siempre «acierta» y la exactitud se
infla.

## Con el benchmark del repositorio

`scripts/benchmark/run.py` aplica el protocolo de punta a punta: hoja para etiquetar a ciegas y kappa (`blind-sheet`,
`agreement`), partición guardada, configuraciones en `.toml`, ablaciones del puntuador, IA sobre toda la referencia,
repeticiones e informe Markdown. Ver `scripts/benchmark/README.md`.

## Privacidad

La referencia y los informes contienen nombres de documentos reales: guárdalos fuera de cualquier repositorio. El
benchmark rechaza una carpeta de salida dentro del repositorio.
