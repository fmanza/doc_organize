"""Prototipo de puntuador para ejes organizadores: palabra completa + raíz, campos con peso, saturación y margen."""

import asyncio
import re

from doc_organize.context.domain_classifier import fold_accents
from doc_organize.context.taxonomy_template_registry import TaxonomyTemplateRegistry

WORD = re.compile(r"[a-z0-9]+")
STOP = {"de", "del", "la", "el", "los", "las", "y", "a", "en", "con", "por", "para", "un", "una"}
FIELD_WEIGHTS = {"title": 3.0, "start": 1.5, "body": 1.0}  # título/nombre de fichero > comienzo > resto
K = 1.2  # saturación tipo BM25: la 5.ª mención apenas suma


def stem(word: str) -> str:
    """Raíz por truncado (en producción: Snowball español)."""
    return word[:6] if len(word) > 6 else word


def terms_of(text: str) -> tuple[str, ...]:
    return tuple(stem(w) for w in WORD.findall(fold_accents(text)) if w not in STOP)


def count(haystack: tuple[str, ...], phrase: tuple[str, ...]) -> int:
    n = len(phrase)
    return sum(1 for i in range(len(haystack) - n + 1) if haystack[i : i + n] == phrase) if n else 0


def entry_phrases(entry) -> set[tuple[str, ...]]:
    raw = [entry.slug.replace("-", " "), entry.name, *entry.keywords]
    return {terms_of(p) for p in raw if terms_of(p)}


def score_axis(axis, title: str, body: str):
    fields = {"title": terms_of(title), "start": terms_of(body[:1500]), "body": terms_of(body[1500:])}
    phrases = {e.slug: entry_phrases(e) for e in axis.entries}
    owners: dict = {}
    for ps in phrases.values():
        for p in ps:
            owners[p] = owners.get(p, 0) + 1
    scores = {}
    for slug, ps in phrases.items():
        total = 0.0
        for p in ps:
            if owners[p] > 1:
                continue  # término compartido: no discrimina
            for field, toks in fields.items():
                tf = count(toks, p)
                total += FIELD_WEIGHTS[field] * tf / (tf + K) * len(p)  # frases largas valen más
        scores[slug] = total
    ranked = sorted(scores.items(), key=lambda s: -s[1])
    (s1, v1), (_, v2) = ranked[0], ranked[1]
    confidence = v1 / (v1 + v2) if v1 else 0.0  # margen relativo frente al segundo
    return ranked[:3], (s1 if v1 >= 1.0 and confidence >= 0.6 else "sin-clasificar"), round(confidence, 2)


manifest = asyncio.run(TaxonomyTemplateRegistry().load_template("sgi-integrado"))
TITLE = "PR-SGSI-05 Procedimiento de gestión de incidentes"
OBJECT = "Objeto: este procedimiento describe cómo se registran y resuelven los incidentes de seguridad. "
MENTIONS = (
    "Se evalúa la amenaza y la vulnerabilidad asociada y el análisis de riesgo. Si afecta a la continuidad de negocio "
    "se activa el plan de continuidad y la contingencia; si afecta a la infraestructura o a la arquitectura de red se "
    "avisa al centro de datos. Si el incidente lo causa un proveedor se revisa el contrato con proveedores y la "
    "evaluación de proveedores. Tras el cierre se abre una no conformidad y una acción correctiva. Conforme a la "
    "política, la norma ISO 27001 y la ley aplicable."
)
CASES = {
    "corto": (
        TITLE,
        OBJECT + "Alcance: todos los sistemas. Responsabilidades: el responsable de seguridad coordina la respuesta a "
        "incidentes. Se aplica conforme a la política de seguridad y la normativa vigente. Ver artículo 5.",
    ),
    # Mismo texto que el caso 2 de demo_scoring.py: las menciones de pasada caen dentro de la ventana inicial.
    "largo (texto de demo_scoring.py)": (TITLE, OBJECT + MENTIONS),
    # Con relleno artificial: las menciones de pasada quedan fuera de los primeros 1500 caracteres (ventana "start").
    "largo con relleno (menciones fuera de la ventana inicial)": (TITLE, OBJECT * 2 + "x " * 700 + MENTIONS),
}
for name, (title, body) in CASES.items():
    print(name)
    for axis in (manifest.folder_axis, manifest.subfolder_axis):
        top, chosen, conf = score_axis(axis, title, body)
        print(f"  [{axis.key}] top={[(s, round(v, 2)) for s, v in top]} -> {chosen} (margen {conf})")
