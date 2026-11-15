"""Propiedades declaradas en PDF y Office (1.5.0): autor, descripción y palabras clave."""

import zipfile

from pathlib import Path

import pytest

from doc_organize.context.document_properties import DocumentProperties, read_document_properties
from doc_organize.utils.text_clean import clean_keywords, clean_text


def make_pdf(info: str | None) -> bytes:
    """PDF de una página con el diccionario `Info` dado (sintaxis PDF), con tabla xref válida para PDFium."""
    objects = ["<</Type/Catalog/Pages 2 0 R>>", "<</Type/Pages/Kids[3 0 R]/Count 1>>", "<</Type/Page/Parent 2 0 R/MediaBox[0 0 10 10]>>"]
    if info is not None:
        objects.append(info)
    out = b"%PDF-1.4\n"
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{number} 0 obj\n{body}\nendobj\n".encode("latin-1")
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    out += b"".join(f"{offset:010d} 00000 n \n".encode() for offset in offsets)
    info_ref = f"/Info {len(objects)} 0 R" if info is not None else ""
    out += f"trailer\n<</Size {len(objects) + 1}/Root 1 0 R{info_ref}>>\nstartxref\n{xref}\n%%EOF\n".encode()
    return out


def make_ooxml(path: Path, core_xml: str | None) -> Path:
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        if core_xml is not None:
            archive.writestr("docProps/core.xml", core_xml)
    return path


def core_xml(*, creator: str = "", description: str = "", subject: str = "", keywords: str = "") -> str:
    return (
        '<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
        'xmlns:dc="http://purl.org/dc/elements/1.1/">'
        f"<dc:creator>{creator}</dc:creator><dc:description>{description}</dc:description>"
        f"<dc:subject>{subject}</dc:subject><cp:keywords>{keywords}</cp:keywords></cp:coreProperties>"
    )


def test_pdf_properties_come_from_the_info_dictionary(tmp_path: Path) -> None:
    path = tmp_path / "a.pdf"
    path.write_bytes(make_pdf("<</Author(Ana Ruiz)/Subject(Informe anual)/Keywords(calidad; ISO 9001)>>"))
    assert read_document_properties(path) == DocumentProperties(author="Ana Ruiz", description="Informe anual", keywords=["calidad", "ISO 9001"])


def test_pdf_producer_and_creator_are_not_the_author(tmp_path: Path) -> None:
    path = tmp_path / "a.pdf"
    path.write_bytes(make_pdf("<</Creator(Microsoft Word)/Producer(Microsoft: Print To PDF)>>"))
    assert read_document_properties(path).author is None


def test_pdf_without_info_has_no_properties(tmp_path: Path) -> None:
    path = tmp_path / "a.pdf"
    path.write_bytes(make_pdf(None))
    assert read_document_properties(path) == DocumentProperties()


@pytest.mark.parametrize("extension", ["docx", "xlsx", "pptx"])
def test_ooxml_properties_come_from_core_xml(tmp_path: Path, extension: str) -> None:
    path = make_ooxml(tmp_path / f"a.{extension}", core_xml(creator="Luis Gil", description="Plan de auditoría", keywords="auditoría, ISO 19011"))
    assert read_document_properties(path) == DocumentProperties(
        author="Luis Gil", description="Plan de auditoría", keywords=["auditoría", "ISO 19011"]
    )


def test_ooxml_subject_is_the_description_when_there_is_none(tmp_path: Path) -> None:
    path = make_ooxml(tmp_path / "a.docx", core_xml(subject="Procedimiento PR-07"))
    assert read_document_properties(path).description == "Procedimiento PR-07"


def test_ooxml_without_core_xml_has_no_properties(tmp_path: Path) -> None:
    assert read_document_properties(make_ooxml(tmp_path / "a.docx", None)) == DocumentProperties()


def test_oversized_core_xml_is_not_read(tmp_path: Path) -> None:
    path = make_ooxml(tmp_path / "a.docx", core_xml(creator="x" * 1_100_000))
    assert read_document_properties(path) == DocumentProperties()


@pytest.mark.parametrize(
    ("name", "content"),
    [("roto.pdf", b"no es un pdf"), ("roto.docx", b"no es un zip"), ("roto.xlsx", None), ("nota.txt", b"texto")],
)
def test_unreadable_or_unsupported_files_have_no_properties(tmp_path: Path, name: str, content: bytes | None) -> None:
    path = tmp_path / name
    if content is not None:
        path.write_bytes(content)
    if name == "roto.xlsx":
        make_ooxml(path, "<cp:coreProperties")  # XML mal formado
    assert read_document_properties(path) == DocumentProperties()


def test_missing_file_has_no_properties(tmp_path: Path) -> None:
    assert read_document_properties(tmp_path / "no-existe.pdf") == DocumentProperties()


def test_text_and_keywords_are_cleaned() -> None:
    assert clean_text("  dos\n  líneas ") == "dos líneas"
    assert clean_text(42) is None
    assert clean_text("x" * 600) == "x" * 500
    assert clean_keywords("a, B; b ,, c") == ["a", "B", "c"]
    assert clean_keywords(["uno", 2, " ", "dos"]) == ["uno", "dos"]
    assert clean_keywords(None) == []
    assert len(clean_keywords(",".join(f"k{i}" for i in range(50)))) == 20
