"""Regresión del puntuador de los ejes organizadores v1 (`score_catalog`), 2.6.0 (E6 del PLAN de F0).

Cada test fija un defecto **conocido** de v1 (`.ai/sessions/2026-11-27-precision-contexto/ANALISIS_MEJORAS.md` §4.1
y §A.1) con el resultado que da hoy. No son el comportamiento deseado: son el de v1, que no debe cambiar por accidente
(«nada cambia el comportamiento por defecto antes de F5»). Cuando exista `rules_version="2"` (F2), cada caso añadirá
al lado la expectativa de v2. Catálogos sintéticos a propósito: P8.3 cambiará las plantillas empaquetadas y estos
tests son del puntuador, no de su contenido.
"""

import pytest

from doc_organize.context.domain_classifier import catalog_scores, score_catalog


def test_v1_matches_substrings_not_whole_words() -> None:
    """Defecto «subcadena»: «ley» encaja en «leyenda», «norma» en «normal», «politica» en «geopolitica»."""
    catalog = ["legal"]
    keywords = {"legal": ["ley", "norma", "politica"]}

    score = score_catalog(catalog, "leyenda del mapa en funcionamiento normal; contexto geopolitico y geopolitica", "", keywords)

    assert score == ("legal", 0.75)  # 3 de 4 términos («legal» no sale) sin que el texto hable de leyes


def test_v1_divides_by_the_number_of_keywords() -> None:
    """Defecto «fracción»: describir mejor una entrada baja su nota (0,50 → 0,17 en §A.1)."""
    text = "gestión del incidente de seguridad"

    assert score_catalog(["incidencia"], text, "") == (None, 0.0)  # el slug no encaja con «incidente»
    assert score_catalog(["incidencia"], text, "", {"incidencia": ["incidente"]}) == ("incidencia", 0.5)
    more = {"incidencia": ["incidente", "brecha", "notificacion", "csirt", "evidencia"]}
    slug, score = score_catalog(["incidencia"], text, "", more)
    assert slug == "incidencia" and score == pytest.approx(1 / 6)


def test_v1_tie_goes_to_the_first_catalog_entry() -> None:
    """Defecto «empate → orden del catálogo»: no se abstiene, gana la primera entrada."""
    text = "riesgos y continuidad"

    assert score_catalog(["riesgos", "continuidad"], text, "") == ("riesgos", 1.0)
    assert score_catalog(["continuidad", "riesgos"], text, "") == ("continuidad", 1.0)


def test_v1_shared_terms_score_in_every_entry() -> None:
    """Defecto «términos compartidos»: un término de varias entradas puntúa en todas (empates y conflictos)."""
    keywords = {"riesgos": ["seguridad"], "tecnologia": ["seguridad"], "cumplimiento": ["seguridad"]}

    scores = catalog_scores(["riesgos", "tecnologia", "cumplimiento"], "politica de seguridad", "", keywords)

    assert scores == [("riesgos", 0.5), ("tecnologia", 0.5), ("cumplimiento", 0.5)]


def test_v1_passing_mentions_weigh_like_the_title() -> None:
    """Defecto «texto entero sin pesos»: una mención de pasada en un anexo vale lo mismo que el título, y la frecuencia
    no cuenta (1 mención = 50)."""
    title = "procedimiento de gestion de incidencias. " + "incidencias " * 50
    annex = " anexo: continuidad mencionada una vez."

    scores = dict(catalog_scores(["incidencias", "continuidad"], title + annex, ""))

    assert scores == {"incidencias": 1.0, "continuidad": 1.0}
    assert score_catalog(["continuidad", "incidencias"], title + annex, "") == ("continuidad", 1.0)  # y gana por orden


def test_v1_folder_bonus_needs_the_exact_slug() -> None:
    """Defecto «bonus de carpeta exacto»: «01 Politicas» no suma; solo una carpeta llamada igual que el slug."""
    exact = dict(catalog_scores(["politicas"], "texto sin pistas", "politicas"))
    numbered = dict(catalog_scores(["politicas"], "texto sin pistas", "01-politicas"))

    assert exact == {"politicas": 0.25}
    assert numbered == {"politicas": 0.0}
