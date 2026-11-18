"""Frescura del contexto (M2, F4): huella del original en el contexto y `check_context_freshness`."""

import json
import os
import time

from datetime import UTC, datetime, timedelta

import pytest

from doc_organize import ContextBuilder, check_context_freshness
from doc_organize.core.models import (
    CacheEntry,
    Context,
    ConversionResult,
    ConversionStatus,
    DocumentStatus,
    Domain,
    DomainDocument,
    Project,
    TaxonomyEntry,
    UnclassifiedDocument,
)
from tests.unit.taxonomy_helpers import two_axis_manifest

SHA_A, SHA_B, SHA_C = "a" * 64, "b" * 64, "c" * 64


def _project(root) -> Project:
    return Project(name="Demo", root_path=str(root), created_at=datetime.now(UTC).isoformat())


def _entry(
    path: str, sha: str, *, status: DocumentStatus = DocumentStatus.UNCHANGED, conversion: ConversionStatus = ConversionStatus.SUCCESS
) -> CacheEntry:
    return CacheEntry(file_path=path, sha256_hash=sha, timestamp=0.0, status=status, conversion_status=conversion)


def _document(path: str, sha: str | None) -> DomainDocument:
    return DomainDocument(
        source_path=path, markdown_path=f"{path}.md", json_path=f"{path}.json", title="T", document_type="pdf", confidence=0.9, source_sha256=sha
    )


def _context(updated_at: str = "2026-11-18T10:00:00+00:00", **kwargs: object) -> Context:
    return Context(project_name="Demo", created_at=updated_at, updated_at=updated_at, **kwargs)  # type: ignore[arg-type]


# --- Huella en el contexto -------------------------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("with_manifest", [True, False])
async def test_builder_keeps_the_source_fingerprint(tmp_path, with_manifest) -> None:
    (tmp_path / "calidad").mkdir()
    documents = []
    for index, text in enumerate(["procedimiento de calidad", "sin nada que ver"]):
        json_path = tmp_path / f"d{index}.json"
        json_path.write_text(json.dumps({"title": f"D{index}", "chunks": [{"text": text}]}), encoding="utf-8")
        documents.append(
            ConversionResult(
                source_path=str(tmp_path / "calidad" / f"d{index}.pdf"),
                markdown_path=str(tmp_path / f"d{index}.md"),
                json_path=str(json_path),
                success=True,
                source_sha256=(SHA_A, SHA_B)[index],
            )
        )
    documents.append(ConversionResult(source_path=str(tmp_path / "roto.pdf"), success=False, source_sha256=SHA_C))
    manifest = two_axis_manifest([TaxonomyEntry(slug="calidad", name="Calidad")], [TaxonomyEntry(slug="procedimiento", name="Procedimiento")])

    if with_manifest:
        context = await ContextBuilder().build(_project(tmp_path), documents, taxonomy_manifest=manifest)
    else:
        context = await ContextBuilder().build(_project(tmp_path), documents, candidate_domains=["calidad"])

    fingerprints = {document.source_path: document.source_sha256 for domain in context.domains for document in domain.documents}
    fingerprints |= {detail.source_path: detail.source_sha256 for detail in context.unclassified_details}
    assert fingerprints == {document.source_path: document.source_sha256 for document in documents}


# --- Informe ---------------------------------------------------------------------------------------------------------


def test_report_lists_changed_added_removed_and_unknown(tmp_path) -> None:
    context = _context(
        domains=[
            Domain(
                slug="calidad",
                name="Calidad",
                documents=[_document("/p/igual.pdf", SHA_A), _document("/p/cambia.pdf", SHA_A), _document("/p/viejo.pdf", None)],
            )
        ],
        unclassified_details=[
            UnclassifiedDocument(source_path="/p/borrado.pdf", document_type="pdf", reason="below_threshold", source_sha256=SHA_A),
            UnclassifiedDocument(source_path="/p/ahora-falla.pdf", document_type="pdf", reason="below_threshold", source_sha256=SHA_A),
        ],
        unclassified_documents=["/p/borrado.pdf", "/p/ahora-falla.pdf"],
    )
    entries = [
        _entry("/p/igual.pdf", SHA_A),
        _entry("/p/cambia.pdf", SHA_B),
        _entry("/p/viejo.pdf", SHA_A),
        _entry("/p/nuevo.pdf", SHA_C),
        _entry("/p/borrado.pdf", SHA_A, status=DocumentStatus.DELETED),
        _entry("/p/ahora-falla.pdf", SHA_A, conversion=ConversionStatus.ERROR),
        _entry("/p/sin-convertir.pdf", SHA_C, conversion=ConversionStatus.PENDING),
    ]

    report = check_context_freshness(_project(tmp_path), context, entries, scanned_at="2026-11-18T12:00:00+00:00")

    assert report.changed == ["/p/cambia.pdf"]
    assert report.added == ["/p/nuevo.pdf"]
    assert report.removed == ["/p/ahora-falla.pdf", "/p/borrado.pdf"]
    assert report.unknown == ["/p/viejo.pdf"]
    assert report.scanned_at == "2026-11-18T12:00:00+00:00"
    assert report.up_to_date is False


def test_a_context_in_step_with_the_cache_is_up_to_date(tmp_path) -> None:
    context = _context(domains=[Domain(slug="calidad", name="Calidad", documents=[_document("/p/a.pdf", SHA_A)])])

    report = check_context_freshness(_project(tmp_path), context, [_entry("/p/a.pdf", SHA_A)])

    assert report.up_to_date and report.stale_site is False


def test_old_contexts_are_unknown_not_changed(tmp_path) -> None:
    context = _context(domains=[Domain(slug="calidad", name="Calidad", documents=[_document("/p/a.pdf", None)])])

    report = check_context_freshness(_project(tmp_path), context, [_entry("/p/a.pdf", SHA_A)])

    assert (report.unknown, report.changed, report.up_to_date) == (["/p/a.pdf"], [], True)


@pytest.mark.parametrize(("site_age", "stale"), [(timedelta(hours=-1), True), (timedelta(hours=1), False)])
def test_site_built_before_the_last_build_is_stale(tmp_path, site_age, stale) -> None:
    updated = datetime(2026, 11, 18, 10, tzinfo=UTC)
    index = tmp_path / "site" / "index.html"
    index.parent.mkdir()
    index.write_text("<html></html>", encoding="utf-8")
    moment = (updated + site_age).timestamp()
    os.utime(index, (moment, moment))

    report = check_context_freshness(_project(tmp_path), _context(updated.isoformat()), [])

    assert report.stale_site is stale


def test_cost_with_thousands_of_documents_is_small(tmp_path) -> None:
    documents = [_document(f"/p/d{index}.pdf", SHA_A) for index in range(2600)]
    context = _context(domains=[Domain(slug="calidad", name="Calidad", documents=documents)])
    entries = [_entry(f"/p/d{index}.pdf", SHA_A if index % 10 else SHA_B) for index in range(2700)]

    start = time.perf_counter()
    report = check_context_freshness(_project(tmp_path), context, entries)
    elapsed = time.perf_counter() - start

    assert (len(report.changed), len(report.added)) == (260, 100)
    assert elapsed < 0.5
