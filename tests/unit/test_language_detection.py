"""Idioma de un documento con py3langid (1.5.0): solo se acepta con texto suficiente y confianza alta."""

import pytest

from doc_organize.context.language_detection import detect_language

SPANISH = "Este procedimiento describe cómo se planifican y realizan las auditorías internas del sistema de gestión de calidad."
ENGLISH = "This procedure describes how internal audits of the quality management system are planned and carried out."
CATALAN = "Aquest procediment descriu com es planifiquen i es fan les auditories internes del sistema de gestió de la qualitat."


@pytest.mark.parametrize(("text", "language"), [(SPANISH, "es"), (ENGLISH, "en"), (CATALAN, "ca")])
def test_detects_the_language_of_a_paragraph(text: str, language: str) -> None:
    assert detect_language(text) == language


@pytest.mark.parametrize(
    "text",
    [
        "",
        "Política de calidad",  # py3langid la da como gallego con confianza baja
        "ISO 9001 | 2024-01-15 | 1234 | 5678 | ---- | ---- | 9999 | 8888 | 7777 | 6666 | 5555",
    ],
)
def test_short_or_non_linguistic_text_has_no_language(text: str) -> None:
    assert detect_language(text) is None


def test_only_the_first_4000_characters_are_analysed() -> None:
    assert detect_language(SPANISH * 40 + ENGLISH * 200) == "es"
