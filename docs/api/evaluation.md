# Evaluación contra una referencia (2.0.0)

Para saber si un cambio de reglas, prompt, perfil o modelo mejora la clasificación hay que medirlo contra una
**referencia**: unos documentos etiquetados a mano con el valor correcto de cada eje. `evaluate_classification` compara
un contexto con ella, eje a eje.

```python
from doc_organize import ContextRegistry, evaluate_classification, load_gold_xlsx

context = await ContextRegistry().load_context(project)
gold = load_gold_xlsx("referencia.xlsx", columns={"domains": "dominio_ok", "material_types": "tipo_ok"})
report = evaluate_classification(context, gold)
print(report.to_markdown())
```

## La referencia

`load_gold_xlsx(path, *, columns=None, sheet="Referencia", document_column="documento")` lee un Excel con una fila por
documento:

- `documento`: la **clave** del documento, su ruta relativa a la raíz de escaneo (`ENS/plan.pdf`). Un `'` inicial
  (fórmula neutralizada) se quita.
- Una columna por eje (`columns`: eje → columna; por defecto `dominio_ok` y `tipo_ok`, las de la línea base): el valor
  correcto, varios separados por `,` o `;`, o `ninguno` si ningún valor del catálogo encaja (dejar el eje vacío es lo
  correcto). Una celda vacía = documento sin etiquetar en ese eje.

Necesita el extra `export` (`openpyxl`). También se puede construir a mano: `GoldStandard(labels=[GoldLabel(document=...,
axes={"domains": ["calidad"]})])`.

## Las métricas

`EvaluationReport.axes` tiene un `AxisEvaluation` por eje etiquetado, sobre los documentos etiquetados que están en el
contexto (`matched`; los que no, en `missing_documents`):

| Métrica | Qué es |
|---|---|
| `accuracy` | Documentos con **exactamente** los valores de la referencia (en un eje de varios valores, el mismo conjunto) |
| `coverage` | Documentos con algún valor asignado |
| `precision` / `recall` | Por valores: asignados que son correctos / correctos que se asignaron |
| `accuracy_by_classified_by` | Exactitud según quién clasificó el eje (`rules`, `ai`, `human`, `semantic`; `unclassified` si quedó vacío), con `labelled_by_classified_by` |
| `confusions` | Los 10 errores más frecuentes: valor de la referencia → valor asignado (`ninguno` = vacío) |

Las claves del contexto se calculan con `roots` (raíces de escaneo) o, por defecto, con la carpeta común de todos los
originales, así que una referencia hecha con las rutas del contenedor de la web (`/mnt/...`) vale con un contexto del
equipo y al revés.

::: doc_organize.context.evaluation
    options:
      show_root_heading: false
      members:
        - evaluate_classification
        - load_gold_xlsx
        - GoldStandard
        - GoldLabel
        - EvaluationReport
        - AxisEvaluation
        - LabelConfusion
        - document_key
        - common_root
