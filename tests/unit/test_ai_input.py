"""Lo que recibe la IA en 2.0 (M5, G2): el `.json` completo, el extracto del documento y el perfil del proyecto."""

import json

import pytest

from doc_organize import parse_taxonomy_template, render_taxonomy_template
from doc_organize.ai.excerpt import MAX_EXCERPT_CHARS, build_document_excerpt
from doc_organize.context.conversion_document import ConversionChunk, ConversionDocument, parse_conversion_document, read_conversion_document
from doc_organize.context.project_profile import (
    PROJECT_PROFILE_FILE,
    compose_profile,
    parse_profile,
    profile_prompt_text,
    render_profile_sections,
)
from doc_organize.core.models import PROFILE_MAX_CHARS, PROFILE_MAX_EXAMPLES, ProjectProfile, TaxonomyEntry
from tests.unit.taxonomy_helpers import two_axis_manifest

LONG = "Este procedimiento describe cómo se gestionan los incidentes de seguridad de la información en la organización."

# --- .json de conversión ---------------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_conversion_document_keeps_headings_and_fingerprint(tmp_path) -> None:
    path = tmp_path / "d.json"
    path.write_text(
        json.dumps({"title": "Plan", "sha256_hash": "ab" * 32, "chunks": [{"text": "Uno", "headings": ["1. Objeto", ""]}, {"text": "Dos"}]}),
        encoding="utf-8",
    )

    document = await read_conversion_document(str(path))

    assert document is not None
    assert (document.title, document.source_sha256, document.text) == ("Plan", "ab" * 32, "Uno Dos")
    assert document.chunks[0].headings == ("1. Objeto",)
    assert await read_conversion_document(str(tmp_path / "no-existe.json")) is None
    assert parse_conversion_document([1, 2]) is None


# --- Extracto --------------------------------------------------------------------------------------------------------


def _document(*chunks: ConversionChunk, title: str = "Procedimiento de incidentes") -> ConversionDocument:
    return ConversionDocument(title=title, chunks=chunks)


def test_excerpt_puts_title_folder_outline_start_and_catalog_fragments_in_order() -> None:
    document = _document(
        ConversionChunk("Índice"),
        ConversionChunk("Página 2"),
        ConversionChunk(LONG, ("1. Objeto",)),
        ConversionChunk("Texto de relleno sin nada " * 3, ("2. Alcance",)),
        ConversionChunk("Se aplica el Esquema Nacional de Seguridad en categoría media.", ("2. Alcance", "2.1 Normas")),
    )

    excerpt = build_document_excerpt(
        document, folder="Clientes/ACME/SGSI/Procedimientos", metadata={"Tipo": "pdf", "Autor": None}, catalog_terms=["Esquema Nacional de Seguridad"]
    )

    lines = excerpt.splitlines()
    assert lines[:4] == ["Título: Procedimiento de incidentes", "Carpeta: SGSI/Procedimientos", "Tipo: pdf", "Esquema de títulos:"]
    assert "ACME" not in excerpt  # solo dos niveles de carpeta
    assert lines[4:7] == ["- 1. Objeto", "- 2. Alcance", "- 2.1 Normas"]
    assert "Índice" not in excerpt and "Página 2" not in excerpt  # sin texto de verdad
    assert excerpt.index("Comienzo:") < excerpt.index(LONG)
    # El fragmento del ENS es largo para el comienzo: ya entró en él, no se repite.
    assert excerpt.count("Esquema Nacional de Seguridad en categoría media") == 1


def test_excerpt_brings_catalog_fragments_from_the_end_of_long_documents() -> None:
    filler = [ConversionChunk(f"{LONG} Párrafo {index}.") for index in range(40)]
    document = _document(*filler, ConversionChunk("Anexo: declaración de aplicabilidad del SGSI conforme a ISO/IEC 27001."))

    excerpt = build_document_excerpt(document, catalog_terms=["ISO/IEC 27001", "inexistente"])

    assert "Fragmentos con términos del catálogo:" in excerpt
    assert "declaración de aplicabilidad del SGSI" in excerpt
    assert len(excerpt) <= MAX_EXCERPT_CHARS


def test_excerpt_is_bounded_deterministic_and_single_line_per_fragment() -> None:
    document = _document(ConversionChunk(LONG + "\x00\x1b[31m rojo\n\nsegunda línea" + "x" * 9000))

    first = build_document_excerpt(document, max_chars=1000)

    assert first == build_document_excerpt(document, max_chars=1000)
    assert len(first) <= 1000
    assert "\x00" not in first and "\x1b" not in first
    assert "segunda línea" in first.splitlines()[2]


def test_excerpt_of_an_empty_document() -> None:
    assert build_document_excerpt(ConversionDocument(title=None, chunks=())) == "Título: (sin título)"


# --- Perfil del proyecto ---------------------------------------------------------------------------------------------

BODY = """# Taxonomía de normas

Texto que no es perfil.

## Contexto del proyecto

Documentación del SGSI y de calidad de una consultora.

## Reglas de desempate

- Una norma publicada es referencial normativo aunque hable de procedimientos.

## glosario

SoA: declaración de aplicabilidad.

## Ejemplos

- Política de seguridad → gobernanza
1. Acta del comité → registro

## Diagramas

Esto no va al modelo.
"""


def test_profile_is_read_from_the_body_sections_regardless_of_case_and_accents() -> None:
    profile = parse_profile(BODY.replace("Contexto del proyecto", "CONTEXTO DEL PROYECTO"))

    assert profile is not None
    assert profile.context == "Documentación del SGSI y de calidad de una consultora."
    assert profile.tie_breakers.startswith("- Una norma publicada")
    assert profile.glossary == "SoA: declaración de aplicabilidad."
    assert profile.examples == ["Política de seguridad → gobernanza", "Acta del comité → registro"]
    assert "Esto no va al modelo" not in profile_prompt_text(profile)
    assert parse_profile("# Sin secciones\n\nNada.") is None


def test_project_profile_adds_to_the_template_one(tmp_path) -> None:
    template = ProjectProfile(context="Plantilla.", examples=[f"e{index}" for index in range(15)])
    (tmp_path / PROJECT_PROFILE_FILE).parent.mkdir(parents=True)
    (tmp_path / PROJECT_PROFILE_FILE).write_text(
        "## Contexto del proyecto\nProyecto VD.\n\n## Ejemplos\n" + "".join(f"- p{i}\n" for i in range(10)), encoding="utf-8"
    )

    profile = compose_profile(template, tmp_path)

    assert profile is not None
    assert profile.context == "Plantilla.\n\nProyecto VD."
    assert len(profile.examples) == PROFILE_MAX_EXAMPLES and profile.examples[-1] == "p4"
    assert compose_profile(None, tmp_path).context == "Proyecto VD."
    assert compose_profile(template, None) is template


def test_profile_prompt_text_is_bounded_and_clean() -> None:
    profile = ProjectProfile(context="a\x07" + "b" * (PROFILE_MAX_CHARS + 100))

    text = profile_prompt_text(profile)

    assert len(text) <= PROFILE_MAX_CHARS and "\x07" not in text
    assert profile_prompt_text(None) == "" and profile_prompt_text(ProjectProfile()) == ""
    assert parse_profile(render_profile_sections(ProjectProfile(context="C", examples=["x"]))) == ProjectProfile(context="C", examples=["x"])


def test_manifest_reading_keeps_the_profile_and_writing_round_trips() -> None:
    manifest = two_axis_manifest([TaxonomyEntry(slug="calidad", name="Calidad")], [TaxonomyEntry(slug="politica", name="Política")])
    text = render_taxonomy_template(manifest, BODY)

    parsed = parse_taxonomy_template(text)

    assert parsed.profile is not None and parsed.profile.glossary == "SoA: declaración de aplicabilidad."
    assert parse_taxonomy_template(render_taxonomy_template(parsed)) == parsed  # sin cuerpo, se escriben sus secciones
    assert parse_taxonomy_template(render_taxonomy_template(manifest)).profile is None
