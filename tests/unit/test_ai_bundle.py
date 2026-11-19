"""Paquete del contexto para IA (M9, F7): `write_ai_context_bundle`, `llms.txt` y su versión en el sitio."""

import hashlib
import io
import json
import zipfile

from datetime import UTC, datetime
from pathlib import Path

import pytest
import yaml

from doc_organize.context.context_builder import ContextBuilder
from doc_organize.context.reorganizer import Reorganizer
from doc_organize.context.site_generator import SiteGenerator
from doc_organize.core.exceptions import OperationCancelledError
from doc_organize.core.models import Context, ConversionResult, Project
from doc_organize.core.progress import CancelToken
from doc_organize.export.ai_bundle import write_ai_context_bundle
from tests.unit.test_taxonomy_check import base_manifest

SECRET = "Xq7#Secreto-9931"
DOCUMENTS = {
    "Calidad/Manual_v1.pdf": ("Manual de calidad", "Manual del sistema de gestión de calidad ISO 9001, versión antigua."),
    "Calidad/Manual_v2.pdf": ("Manual de calidad", "Manual del sistema de gestión de calidad ISO 9001, versión nueva."),
    "Seguridad/accesos.pdf": (f"Accesos password: {SECRET}", f"Política de seguridad del ENS. Acceso: password: {SECRET}"),
}


async def _context(tmp_path: Path) -> tuple[Project, Context]:
    project = Project(name="Demo", root_path=str(tmp_path), created_at=datetime.now(UTC).isoformat())
    documents = []
    for index, (relative, (title, text)) in enumerate(DOCUMENTS.items()):
        source = tmp_path / "entrada" / relative
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_bytes(b"%PDF")
        (tmp_path / f"doc{index}.json").write_text(json.dumps({"title": title, "chunks": [{"text": text}]}), encoding="utf-8")
        (tmp_path / f"doc{index}.md").write_text(f"# {title}\n\n{text}\n", encoding="utf-8")
        documents.append(
            ConversionResult(
                source_path=str(source), markdown_path=str(tmp_path / f"doc{index}.md"), json_path=str(tmp_path / f"doc{index}.json"), success=True
            )
        )
    context = await ContextBuilder().build(project, documents, taxonomy_manifest=base_manifest(), versions="mark", persist=False)
    return project, context


def _members(data: bytes) -> dict[str, str]:
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        return {name: archive.read(name).decode("utf-8") for name in archive.namelist()}


def _front_matter(text: str) -> dict:
    return yaml.safe_load(text.split("---\n")[1])


@pytest.mark.asyncio
async def test_bundle_contents(tmp_path) -> None:
    project, context = await _context(tmp_path)
    buffer = io.BytesIO()

    stats = write_ai_context_bundle(buffer, project, context)

    members = _members(buffer.getvalue())
    documents = sorted(name for name in members if name.startswith("documentos/"))
    assert stats.documents == 2 and stats.superseded_skipped == 1 and stats.file_count == 4 and len(documents) == 2
    assert stats.sha256 == hashlib.sha256(buffer.getvalue()).hexdigest()
    llms = members["llms.txt"]
    assert llms.startswith("# Demo\n\n> Documentación organizada del proyecto Demo: 2 documentos en 2 dominios.")
    for name in documents:
        assert f"]({name})" in llms
    manual = next(name for name in documents if "calidad/" in name)
    front = _front_matter(members[manual])
    assert front["title"] == "Manual de calidad" and front["domain"] == "calidad" and front["source"] == "Calidad/Manual_v2.pdf"
    assert front["version"] == "2" and front["is_current"] is True and front["axes"]["domains"] == ["calidad"]
    assert "versión nueva" in members[manual] and "versión antigua" not in "".join(members.values())
    reduced = json.loads(members["context.json"])
    assert sorted(document["path"] for document in reduced["documents"]) == documents
    assert {axis["key"] for axis in reduced["taxonomy_axes"]} == {"domains", "material_types", "frameworks"}
    assert all(str(tmp_path) not in text and str(tmp_path).replace("\\", "/") not in text for text in members.values())  # sin rutas absolutas


@pytest.mark.asyncio
async def test_redacted_values_never_reach_the_bundle(tmp_path) -> None:
    """Puerta de M9 (F7): el valor redactado no aparece en ningún fichero del paquete (títulos, texto, índice, JSON)."""
    project, context = await _context(tmp_path)
    redacted, plain = io.BytesIO(), io.BytesIO()

    stats = write_ai_context_bundle(redacted, project, context, max_full_chars=100_000)
    write_ai_context_bundle(plain, project, context, redact=False)

    assert SECRET.encode() not in redacted.getvalue()  # ni comprimido ni sin comprimir
    assert all(SECRET not in text for text in _members(redacted.getvalue()).values()) and stats.redacted_documents == 1
    assert any(SECRET in text for text in _members(plain.getvalue()).values())  # sin redactar sí sale (opción explícita)


@pytest.mark.asyncio
async def test_options(tmp_path) -> None:
    project, context = await _context(tmp_path)

    everything = _members(_bytes(project, context, current_only=False))
    without_text = _members(_bytes(project, context, include_text=False))
    short = _members(_bytes(project, context, max_file_chars=10, max_full_chars=60))

    assert len([name for name in everything if name.startswith("documentos/")]) == 3
    assert all(text.endswith("---\n\n") for name, text in without_text.items() if name.startswith("documentos/"))
    assert all("texto cortado" in text for name, text in short.items() if name.startswith("documentos/"))
    assert "se alcanzó el tope de llms-full.txt" in short["llms-full.txt"]


def _bytes(project: Project, context: Context, **options: object) -> bytes:
    buffer = io.BytesIO()
    write_ai_context_bundle(buffer, project, context, **options)  # type: ignore[arg-type]
    return buffer.getvalue()


@pytest.mark.asyncio
async def test_reproducible_and_cancellable(tmp_path) -> None:
    project, context = await _context(tmp_path)

    first = write_ai_context_bundle(tmp_path / "a.zip", project, context)
    second = write_ai_context_bundle(tmp_path / "b.zip", project, context)

    assert first.sha256 == second.sha256 == hashlib.sha256((tmp_path / "a.zip").read_bytes()).hexdigest()
    token = CancelToken()
    token.cancel()
    with pytest.raises(OperationCancelledError):
        write_ai_context_bundle(tmp_path / "c.zip", project, context, cancel_token=token)
    assert not (tmp_path / "c.zip").exists()


@pytest.mark.asyncio
async def test_site_llms_txt(tmp_path) -> None:
    project, context = await _context(tmp_path)
    await Reorganizer().reorganize(project, context)
    output = tmp_path / "organizado"

    await SiteGenerator().generate(project, context, build=False, llms_txt=True)
    normal = (output / "llms.txt").read_text(encoding="utf-8")
    await SiteGenerator().generate(project, context, build=False, llms_txt=True, offline=True)
    offline = (output / "llms.txt").read_text(encoding="utf-8")
    await SiteGenerator().generate(project, context, build=False)

    assert "](calidad/" in normal and ".html)" not in normal and "/)" in normal
    assert ".html)" in offline and SECRET not in normal + offline
    assert not (output / "llms.txt").exists()
