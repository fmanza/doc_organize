# Ejemplo: Evaluar la Clasificación contra una Referencia

**Objetivo**: Demostrar cómo sacar una referencia de las decisiones de las personas (`gold_from_decisions`), medir con
ella la clasificación (`evaluate_classification`) y probar un cambio sin guardar nada (`dry_run_classify`).

## 1. Contexto del Ejemplo

Antes de adoptar un cambio de reglas, prompt, perfil o modelo hay que saber si mejora la clasificación. Para eso hace
falta una **referencia**: documentos con el valor correcto de cada eje. Lo que ya decidieron las personas sirve como
referencia, y se puede completar a mano.

El ejemplo compara dos umbrales de las reglas (`threshold`) con `dry_run_classify`, que construye el contexto con
`persist=False`: no escribe `context.json` ni el histórico. Construye los documentos sin Docling (original, `.md` y
`.json` escritos a mano, como en [Construir el contexto](context-build.md)) y solo con reglas, sin IA.

### Requisitos

- Python 3.11+
- `doc_organize[context]` instalado (PyYAML, para leer el manifiesto)

Los ficheros se crean en un directorio temporal; no se llama a ningún servicio externo.

## 2. Implementación de Referencia

```python
import asyncio
import json
import tempfile
from pathlib import Path

from doc_organize import (
    ClassificationDecision,
    ClassificationDecisionStore,
    ContextBuilder,
    ConversionResult,
    GoldLabel,
    GoldStandard,
    Project,
    dry_run_classify,
    evaluate_classification,
    gold_from_decisions,
    parse_taxonomy_template,
)

MANIFEST = """\
---
schema: 2
title: Calidad mínima
axes:
- key: domains
  name: Dominios
  organizes: folder
  entries:
  - slug: gestion-proveedores
    name: Gestión de Proveedores
    keywords: [proveedor, homologacion]
  - slug: mejora-continua
    name: Mejora Continua
    keywords: [no conformidad, accion correctiva]
- key: material_types
  name: Tipos de material
  organizes: subfolder
  entries:
  - slug: procedimiento
    name: Procedimiento
  - slug: registro
    name: Registro
---
"""

DOCUMENTS = [  # (ruta, título, texto)
    ("compras/alta.txt", "Procedimiento de homologación de proveedores", "Alta de un proveedor y su homologacion anual."),
    ("compras/evaluacion.txt", "Registro de evaluación de proveedores", "Puntuación anual de cada proveedor."),
    ("calidad/nc-04.txt", "Registro de no conformidad 04", "No conformidad detectada y accion correctiva acordada."),
    ("calidad/auditoria.txt", "Registro de la auditoría interna", "Hallazgos de la auditoria interna y oportunidades de mejora."),
    ("varios/menu.txt", "Menú de la cafetería", "Lunes: lentejas. Martes: paella."),
    ("varios/aviso.txt", "Aviso a la cafetería", "Mañana viene el proveedor del café."),
]


def converted(root: Path, relative: str, title: str, text: str) -> ConversionResult:
    """El original en `origen/` y su `.md` + `.json` en `Conversión/`, como los deja `DocumentConverter`."""
    source = root / "origen" / relative
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text(text, encoding="utf-8")
    markdown, json_path = root / "Conversión" / f"{source.stem}.md", root / "Conversión" / f"{source.stem}.json"
    markdown.parent.mkdir(parents=True, exist_ok=True)
    markdown.write_text(f"# {title}\n\n{text}\n", encoding="utf-8")
    json_path.write_text(json.dumps({"title": title, "chunks": [{"text": text}]}, ensure_ascii=False), encoding="utf-8")
    return ConversionResult(source_path=str(source), markdown_path=str(markdown), json_path=str(json_path), success=True)


def show(title: str, report) -> None:
    print(f"{title}: {report.matched} de la referencia en el contexto, ausentes={report.missing_documents}")
    for axis in report.axes.values():
        print(f"  {axis.axis}: exactitud={axis.accuracy} cobertura={axis.coverage} precisión={axis.precision} recall={axis.recall}")
        print(f"    por quién: {axis.accuracy_by_classified_by} (documentos: {axis.labelled_by_classified_by})")
        for confusion in axis.confusions:
            print(f"    confusión: referencia={confusion.label!r} asignado={confusion.assigned!r} x{confusion.count}")


async def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp).resolve()
        roots = [str(root / "origen")]
        project = Project(name="Demo", root_path=str(root), created_at="2026-01-01T00:00:00+00:00")
        manifest = parse_taxonomy_template(MANIFEST)
        documents = [converted(root, *document) for document in DOCUMENTS]

        # 1) La referencia sale de lo que decidieron las personas (los `exclude` no cuentan)
        store = ClassificationDecisionStore(project.root_path)
        await store.add(ClassificationDecision(document_key="compras/alta.txt", action="confirm",
                                               axes={"domains": ["gestion-proveedores"], "material_types": ["procedimiento"]}))
        await store.add(ClassificationDecision(document_key="compras/evaluacion.txt", action="set_axis", axes={"domains": ["gestion-proveedores"]}))
        await store.add(ClassificationDecision(document_key="calidad/nc-04.txt", action="set_axis", axes={"domains": ["mejora-continua"]}))
        await store.add(ClassificationDecision(document_key="calidad/auditoria.txt", action="set_axis", axes={"domains": ["mejora-continua"]}))
        await store.add(ClassificationDecision(document_key="calidad/auditoria.txt", action="set_axis", axes={"material_types": ["registro"]}))
        await store.add(ClassificationDecision(document_key="varios/menu.txt", action="exclude"))
        gold = gold_from_decisions(await store.load())
        # ... y se puede completar a mano: una lista vacía es «ninguno» (dejar el eje vacío es lo correcto)
        gold = GoldStandard(labels=[*gold.labels, GoldLabel(document="varios/menu.txt", axes={"domains": []}),
                                    GoldLabel(document="varios/aviso.txt", axes={"domains": []}),
                                    GoldLabel(document="ventas/tarifas.txt", axes={"domains": []})])
        for label in gold.labels:
            print(f"Referencia {label.document}: {label.axes}")

        # 2) Prueba sin guardar, solo reglas y sin aplicar las decisiones (si no, se evaluarían a sí mismas)
        base = await dry_run_classify(project, documents, gold=gold, roots=roots, taxonomy_manifest=manifest, decisions=False)
        print(f"\nClasificados: {base.documents}; context.json guardado: {(root / 'context.json').exists()}")
        show("Reglas, umbral 0.5", base.evaluation)
        print(base.evaluation.to_markdown())

        # 3) Medir un cambio antes de adoptarlo: bajar el umbral de las reglas, comparado con el contexto guardado
        saved = await ContextBuilder().build(project, documents, taxonomy_manifest=manifest, scan_roots=roots, decisions=False)
        trial = await dry_run_classify(project, documents, gold=gold, roots=roots, baseline=saved,
                                       taxonomy_manifest=manifest, decisions=False, threshold=0.25)
        show("\nReglas, umbral 0.25", trial.evaluation)
        for change in trial.changes:
            print(f"  cambia {change.document_key} {change.axis}: {change.before} ({change.before_by}) → {change.after} ({change.after_by})")

        # 4) `evaluate_classification` también sirve con un contexto ya construido (p. ej. el guardado)
        report = evaluate_classification(saved, gold, roots=roots)
        print(f"\nContexto guardado: dominios exactitud={report.axes['domains'].accuracy}, documentos={report.documents}")


if __name__ == "__main__":
    asyncio.run(main())
```

## 3. Explicación del Código

1. **Referencia desde decisiones**: `gold_from_decisions` convierte cada `confirm` y `set_axis` en los valores
   correctos de sus ejes (los dos `set_axis` de `auditoria.txt` se juntan en una etiqueta); los `exclude` no cuentan,
   por eso `menu.txt` no sale de las decisiones
2. **Completar a mano**: un `GoldLabel` con lista vacía significa «ninguno» (dejar el eje vacío es lo correcto).
   `ventas/tarifas.txt` no está en el corpus: la evaluación lo lista en `missing_documents`
3. **`decisions=False`**: `dry_run_classify` pasa a `build` el resto de opciones y, por defecto, `build` aplica las
   decisiones del proyecto. Si la referencia sale de esas mismas decisiones, se aplicarían y la evaluación mediría a las
   personas contra sí mismas (ejes `human`, todos acertados). Para medir las reglas o la IA, sin decisiones
4. **Métricas del eje `domains`** (umbral 0,5): acierta 5 de 6 (exactitud 0,8333: `menu.txt` y `aviso.txt` aciertan
   al quedar vacíos); asigna algo a 3 de 6 (cobertura 0,5); los 3 valores asignados son correctos (precisión 1,0) y
   encuentra 3 de los 4 valores de la referencia (*recall* 0,75). `accuracy_by_classified_by` separa lo de las reglas
   (`rules`) de los ejes que quedaron vacíos (`unclassified`); la confusión dice que `auditoria.txt` debía ser
   `mejora-continua` y quedó en «ninguno». En `material_types` solo hay 2 documentos etiquetados
5. **Probar un cambio**: con `threshold=0.25`, `auditoria.txt` entra en `mejora-continua` (1 de sus 4 palabras clave,
   «mejora») pero `aviso.txt` entra por error en `gestion-proveedores` («proveedor»): el *recall* sube a 1,0 y la
   precisión baja a 0,8, con la misma exactitud. Con `baseline` (el contexto guardado), `changes` dice exactamente qué
   documentos y ejes cambian
6. **Solo la referencia**: con `only_gold=True` (por defecto) solo se clasifican los documentos de la referencia; aquí
   son los 6 del corpus. `roots` da las claves y también se pasa a `build` como `scan_roots`
7. **Contexto ya construido**: `evaluate_classification(context, gold, roots=...)` mide cualquier `Context`, por
   ejemplo el guardado (`ContextRegistry.load_context`)

## 4. Ejecución y Pruebas

```bash
$ python evaluation_example.py
Referencia compras/alta.txt: {'domains': ['gestion-proveedores'], 'material_types': ['procedimiento']}
Referencia compras/evaluacion.txt: {'domains': ['gestion-proveedores']}
Referencia calidad/nc-04.txt: {'domains': ['mejora-continua']}
Referencia calidad/auditoria.txt: {'domains': ['mejora-continua'], 'material_types': ['registro']}
Referencia varios/menu.txt: {'domains': []}
Referencia varios/aviso.txt: {'domains': []}
Referencia ventas/tarifas.txt: {'domains': []}

Clasificados: 6; context.json guardado: False
Reglas, umbral 0.5: 6 de la referencia en el contexto, ausentes=['ventas/tarifas.txt']
  domains: exactitud=0.8333 cobertura=0.5 precisión=1.0 recall=0.75
    por quién: {'rules': 1.0, 'unclassified': 0.6667} (documentos: {'rules': 3, 'unclassified': 3})
    confusión: referencia='mejora-continua' asignado='ninguno' x1
  material_types: exactitud=1.0 cobertura=1.0 precisión=1.0 recall=1.0
    por quién: {'rules': 1.0} (documentos: {'rules': 2})
| Eje | Etiquetados | Exactitud | Cobertura | Precisión | Recall |
|---|---|---|---|---|---|
| domains | 6 | 0.8333 | 0.5 | 1.0 | 0.75 |
| material_types | 2 | 1.0 | 1.0 | 1.0 | 1.0 |

Reglas, umbral 0.25: 6 de la referencia en el contexto, ausentes=['ventas/tarifas.txt']
  domains: exactitud=0.8333 cobertura=0.8333 precisión=0.8 recall=1.0
    por quién: {'rules': 0.8, 'unclassified': 1.0} (documentos: {'rules': 5, 'unclassified': 1})
    confusión: referencia='ninguno' asignado='gestion-proveedores' x1
  material_types: exactitud=1.0 cobertura=1.0 precisión=1.0 recall=1.0
    por quién: {'rules': 1.0} (documentos: {'rules': 2})
  cambia calidad/auditoria.txt domains: [] (None) → ['mejora-continua'] (rules)
  cambia varios/aviso.txt domains: [] (None) → ['gestion-proveedores'] (rules)

Contexto guardado: dominios exactitud=0.8333, documentos=6
```

La salida es determinista. Validación sintáctica: `python -m py_compile evaluation_example.py`.

## 5. Referencias Relacionadas

- [Referencia técnica: Evaluación contra una referencia](../api/evaluation.md)
- [Documentación funcional: Revisión y calidad de la clasificación](../functional/revision_clasificacion.md)
- [Ejemplo: Decisiones de personas y cola de revisión](decisions-review.md)
- [Ejemplo: Construir el contexto](context-build.md)
