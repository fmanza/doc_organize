"""Demuestra los defectos de score_catalog (ejes organizadores) frente a AxisRuleScorer, con la plantilla sgi-integrado."""

import asyncio

from doc_organize.context.axis_rules import AxisRuleScorer, FoldedText
from doc_organize.context.domain_classifier import DomainClassifier, catalog_scores, fold_accents
from doc_organize.context.taxonomy_template_registry import TaxonomyTemplateRegistry

manifest = asyncio.run(TaxonomyTemplateRegistry().load_template("sgi-integrado"))
dom, mat = manifest.folder_axis, manifest.subfolder_axis
slug = DomainClassifier._slugify


def show(label: str, title: str, body: str) -> None:
    haystack = f"{title} {body}".lower()
    for axis in (dom, mat):
        kw = {slug(e.slug): e.keywords for e in axis.entries if e.keywords}
        scores = catalog_scores([slug(e.slug) for e in axis.entries], haystack, "", extra_keywords=kw)
        top = sorted(scores, key=lambda s: -s[1])[:4]
        best = max(scores, key=lambda s: s[1])  # el primero del catálogo en empate (como score_catalog)
        print(f"  [{axis.key}] score_catalog top: {[(s, round(v, 2)) for s, v in top]} -> elegido {best[0] if best[1] >= 0.5 else 'sin-clasificar'}")
        alt = AxisRuleScorer(axis.model_copy(update={"multiple": True}), 0.5).scores(FoldedText.of(title, body))
        print(f"  [{axis.key}] AxisRuleScorer      : {[(v.slug, v.confidence) for v in alt[:4]]}")
    print()


print("1) Procedimiento de gestión de incidentes (documento interno corto)")
show(
    "proc",
    "PR-SGSI-05 Procedimiento de gestión de incidentes",
    "Objeto: este procedimiento describe cómo se registran y resuelven los incidentes de seguridad. "
    "Alcance: todos los sistemas. Responsabilidades: el responsable de seguridad coordina la respuesta a incidentes. "
    "Se aplica conforme a la política de seguridad y la normativa vigente. Ver artículo 5.",
)

print("2) Mismo procedimiento, largo (menciona de pasada riesgos, proveedores, continuidad, infraestructura)")
show(
    "proc-largo",
    "PR-SGSI-05 Procedimiento de gestión de incidentes",
    "Objeto: este procedimiento describe cómo se registran y resuelven los incidentes de seguridad. "
    "Se evalúa la amenaza y la vulnerabilidad asociada y el análisis de riesgo. Si afecta a la continuidad de negocio "
    "se activa el plan de continuidad y la contingencia; si afecta a la infraestructura o a la arquitectura de red se "
    "avisa al centro de datos. Si el incidente lo causa un proveedor se revisa el contrato con proveedores y la "
    "evaluación de proveedores. Tras el cierre se abre una no conformidad y una acción correctiva. Conforme a la "
    "política, la norma ISO 27001 y la ley aplicable.",
)

print("3) Falsos positivos por subcadena")
for word in ("ley", "norma", "soa", "politica"):
    samples = {"ley": "leyenda del gráfico", "norma": "funcionamiento normal", "soa": "persona asociada", "politica": "geopolitica"}
    text = fold_accents(samples[word])
    print(f"  '{word}' in '{samples[word]}' -> {word in text}")
print()

print("4) Añadir palabras clave baja la puntuación (fracción de aciertos)")
for extra in ([], ["incidente"], ["incidente", "brecha de seguridad", "respuesta a incidentes", "ciberincidente", "csirt"]):
    keywords = ["incidente", *extra[1:]] if extra else []
    score = dict(catalog_scores(["incidencia"], "gestion del incidente de seguridad", "", {"incidencia": keywords}))["incidencia"]
    print(f"  keywords={keywords!r:70} -> {score:.2f}")
