"""Deduplicación en dos pasos y modos (L-6, hueco G6 de doc_organize_web).

Paso 1: `find_duplicates` como vista previa con `group_id` estable. Paso 2: `resolve_duplicates` aplica **solo** los
grupos confirmados con `mode` = `move` (por defecto), `copy` o `report_only`.
"""

from pathlib import Path

import pytest

from doc_organize import DeduplicationManager, ProjectLayout
from doc_organize.core.models import DocumentMetadata, DuplicateReason


def _doc(path: Path, content: bytes, mtime: float) -> DocumentMetadata:
    path.write_bytes(content)
    return DocumentMetadata(
        full_path=str(path),
        display_name=path.name,
        extension=path.suffix.lstrip("."),
        size_bytes=len(content),
        modified_time=mtime,
        sha256_hash=f"hash-{content.decode()}",
    )


@pytest.fixture
def two_groups(tmp_path: Path) -> tuple[Path, list[DocumentMetadata]]:
    source = tmp_path / "origen"
    source.mkdir()
    docs = [
        _doc(source / "a.pdf", b"uno", 1.0),
        _doc(source / "a_copia.pdf", b"uno", 2.0),
        _doc(source / "b.pdf", b"dos", 1.0),
        _doc(source / "b_copia.pdf", b"dos", 2.0),
    ]
    return source, docs


def test_group_id_is_stable_across_runs(two_groups: tuple[Path, list[DocumentMetadata]]) -> None:
    _, docs = two_groups

    first = {g.group_id for g in DeduplicationManager().find_duplicates(docs)}
    second = {g.group_id for g in DeduplicationManager().find_duplicates(list(reversed(docs)))}

    assert first == second
    assert len(first) == 2


def test_group_id_changes_when_members_change(two_groups: tuple[Path, list[DocumentMetadata]]) -> None:
    _, docs = two_groups
    ids = DeduplicationManager.stable_group_id

    assert ids(docs[:2], DuplicateReason.EXACT_DUPLICATE) != ids(docs[:1] + docs[2:3], DuplicateReason.EXACT_DUPLICATE)
    assert ids(docs[:2], DuplicateReason.EXACT_DUPLICATE) != ids(docs[:2], DuplicateReason.FUZZY_NAME_MATCH)


@pytest.mark.asyncio
async def test_only_confirmed_groups_are_applied(tmp_path: Path, two_groups: tuple[Path, list[DocumentMetadata]]) -> None:
    source, docs = two_groups
    preview = DeduplicationManager().find_duplicates(docs)
    confirmed = [group for group in preview if group.canonical_doc.display_name == "a.pdf"]

    report = await DeduplicationManager().resolve_duplicates(confirmed, tmp_path / "duplicados")

    assert report.mode == "move"
    assert report.total_exact_duplicates == 1
    assert not (source / "a_copia.pdf").exists()
    assert (source / "b_copia.pdf").exists()  # grupo no confirmado: intacto


@pytest.mark.asyncio
async def test_copy_mode_leaves_source_untouched(tmp_path: Path, two_groups: tuple[Path, list[DocumentMetadata]]) -> None:
    source, docs = two_groups
    before = sorted(p.name for p in source.iterdir())

    report = await DeduplicationManager().resolve_duplicates(DeduplicationManager().find_duplicates(docs), tmp_path / "duplicados", mode="copy")

    assert report.mode == "copy"
    assert report.total_exact_duplicates == 2
    assert sorted(p.name for p in source.iterdir()) == before
    assert sorted(p.name for p in (tmp_path / "duplicados").rglob("*.pdf")) == ["a_copia.pdf", "b_copia.pdf"]


@pytest.mark.asyncio
async def test_report_only_writes_nothing_but_the_report(tmp_path: Path, two_groups: tuple[Path, list[DocumentMetadata]]) -> None:
    source, docs = two_groups
    layout = ProjectLayout(tmp_path / "salidas", state_root=tmp_path / "estado")
    before = sorted(p.name for p in source.iterdir())

    report = await DeduplicationManager().resolve_duplicates(
        DeduplicationManager().find_duplicates(docs), layout.duplicates_dir, mode="report_only", report_dir=layout.dedup_report_dir
    )

    assert report.mode == "report_only"
    assert report.total_exact_duplicates == 2  # señalados, no movidos
    assert sorted(p.name for p in source.iterdir()) == before
    assert not layout.duplicates_dir.exists()
    assert layout.dedup_report.exists()
