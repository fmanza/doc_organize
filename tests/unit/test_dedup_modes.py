"""Deduplicación en dos pasos y modos (L-6, hueco G6 de doc_organize_web).

Paso 1: `find_duplicates` como vista previa con `group_id` estable. Paso 2: `resolve_duplicates` aplica **solo** los
grupos confirmados con `mode` = `move` (por defecto), `copy` o `report_only`.
"""

import os

from pathlib import Path

import pytest

from doc_organize import DeduplicationManager, ProjectLayout
from doc_organize.core.exceptions import InvalidPathError
from doc_organize.core.models import DocumentMetadata, DuplicateReason
from doc_organize.dedup import deduplication


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


# --- L-11a (G24): ruta relativa en duplicados/ ---


@pytest.fixture
def nested_group(tmp_path: Path) -> tuple[Path, list[DocumentMetadata]]:
    source = tmp_path / "origen"
    (source / "2024").mkdir(parents=True)
    docs = [_doc(source / "2024" / "a.pdf", b"uno", 1.0), _doc(source / "2024" / "a_copia.pdf", b"uno", 2.0)]
    return source, docs


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["move", "copy"])
async def test_relative_to_replicates_only_the_relative_path(tmp_path: Path, nested_group: tuple[Path, list[DocumentMetadata]], mode: str) -> None:
    source, docs = nested_group
    duplicates_dir = tmp_path / "duplicados"

    report = await DeduplicationManager().resolve_duplicates(
        DeduplicationManager().find_duplicates(docs),
        duplicates_dir,
        mode=mode,
        relative_to=source,  # type: ignore[arg-type]
    )

    assert report.failed_paths == []
    assert [p.relative_to(duplicates_dir).as_posix() for p in duplicates_dir.rglob("*.pdf")] == ["2024/a_copia.pdf"]
    assert (source / "2024" / "a_copia.pdf").exists() is (mode == "copy")


@pytest.mark.asyncio
async def test_relative_to_keeps_hash_suffix_on_collision(tmp_path: Path, nested_group: tuple[Path, list[DocumentMetadata]]) -> None:
    source, docs = nested_group
    duplicates_dir = tmp_path / "duplicados"
    (duplicates_dir / "2024").mkdir(parents=True)
    (duplicates_dir / "2024" / "a_copia.pdf").write_bytes(b"previo")

    report = await DeduplicationManager().resolve_duplicates(DeduplicationManager().find_duplicates(docs), duplicates_dir, relative_to=source)

    assert report.failed_paths == []
    assert (duplicates_dir / "2024" / "a_copia.pdf").read_bytes() == b"previo"
    assert (duplicates_dir / "2024" / "a_copia_hash-uno.pdf").read_bytes() == b"uno"


@pytest.mark.asyncio
async def test_document_outside_relative_to_fails_per_file(tmp_path: Path, nested_group: tuple[Path, list[DocumentMetadata]]) -> None:
    _, docs = nested_group
    duplicates_dir = tmp_path / "duplicados"
    other_root = tmp_path / "otra"
    other_root.mkdir()

    report = await DeduplicationManager().resolve_duplicates(DeduplicationManager().find_duplicates(docs), duplicates_dir, relative_to=other_root)

    assert report.failed_paths == [docs[1].full_path]
    assert report.total_exact_duplicates == 0
    assert Path(docs[1].full_path).exists()
    assert list(duplicates_dir.rglob("*.pdf")) == []


@pytest.mark.asyncio
async def test_without_relative_to_replicates_absolute_path(tmp_path: Path, nested_group: tuple[Path, list[DocumentMetadata]]) -> None:
    _, docs = nested_group
    duplicates_dir = tmp_path / "duplicados"

    await DeduplicationManager().resolve_duplicates(DeduplicationManager().find_duplicates(docs), duplicates_dir)

    expected = duplicates_dir.resolve().joinpath(*Path(docs[1].full_path).resolve().parts[1:])
    assert [p.resolve() for p in duplicates_dir.rglob("*.pdf")] == [expected]


# --- L-11a (G26): sin seguir enlaces simbólicos ---


def _symlink(link: Path, target: Path, *, is_dir: bool = False) -> None:
    try:
        link.symlink_to(target, target_is_directory=is_dir)
    except OSError:
        pytest.skip("El entorno no permite crear symlinks (privilegios insuficientes en Windows).")


@pytest.fixture
def secret(tmp_path: Path) -> Path:
    outside = tmp_path / "fuera"
    outside.mkdir()
    secret_file = outside / "secreto.pdf"
    secret_file.write_bytes(b"secreto")
    return secret_file


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["move", "copy"])
async def test_source_replaced_by_symlink_fails_per_file(
    tmp_path: Path, nested_group: tuple[Path, list[DocumentMetadata]], secret: Path, mode: str
) -> None:
    source, docs = nested_group
    groups = DeduplicationManager().find_duplicates(docs)
    swapped = source / "2024" / "a_copia.pdf"
    swapped.unlink()
    _symlink(swapped, secret)  # cambiado entre la vista previa y la resolución
    duplicates_dir = tmp_path / "duplicados"

    report = await DeduplicationManager().resolve_duplicates(groups, duplicates_dir, mode=mode, relative_to=source)  # type: ignore[arg-type]

    assert report.failed_paths == [docs[1].full_path]
    assert secret.read_bytes() == b"secreto"
    assert swapped.is_symlink()
    assert list(duplicates_dir.rglob("*.pdf")) == []  # el informe (DEDUP_REPORT.json) sí se escribe


@pytest.mark.asyncio
async def test_source_directory_replaced_by_symlink_fails_per_file(
    tmp_path: Path, nested_group: tuple[Path, list[DocumentMetadata]], secret: Path
) -> None:
    source, docs = nested_group
    groups = DeduplicationManager().find_duplicates(docs)
    (source / "2024").rename(tmp_path / "2024_movida")
    (secret.parent / "a_copia.pdf").write_bytes(b"secreto")
    _symlink(source / "2024", secret.parent, is_dir=True)
    duplicates_dir = tmp_path / "duplicados"

    report = await DeduplicationManager().resolve_duplicates(groups, duplicates_dir, relative_to=source)

    assert sorted(report.failed_paths) == sorted(d.full_path for d in docs if d.display_name == "a_copia.pdf")
    assert (secret.parent / "a_copia.pdf").read_bytes() == b"secreto"
    assert list(duplicates_dir.rglob("*.pdf")) == []  # el informe (DEDUP_REPORT.json) sí se escribe


@pytest.mark.asyncio
async def test_duplicates_dir_symlink_is_rejected(tmp_path: Path, nested_group: tuple[Path, list[DocumentMetadata]]) -> None:
    source, docs = nested_group
    real_dir = tmp_path / "real"
    real_dir.mkdir()
    duplicates_dir = tmp_path / "duplicados"
    _symlink(duplicates_dir, real_dir, is_dir=True)
    groups = DeduplicationManager().find_duplicates(docs)

    with pytest.raises(InvalidPathError):
        await DeduplicationManager().resolve_duplicates(groups, duplicates_dir, relative_to=source)
    with pytest.raises(OSError):
        await DeduplicationManager()._move_to_duplicates(Path(docs[1].full_path), duplicates_dir, docs[1].sha256_hash)

    assert list(real_dir.iterdir()) == []
    assert Path(docs[1].full_path).exists()


@pytest.mark.skipif(not deduplication._NOFOLLOW_DIR_FD, reason="Solo POSIX: dir_fd + O_NOFOLLOW")
@pytest.mark.asyncio
async def test_symlink_swapped_after_check_is_not_followed(
    tmp_path: Path, nested_group: tuple[Path, list[DocumentMetadata]], secret: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Simula la carrera: el enlace aparece después de la comprobación con `lstat`."""
    source, docs = nested_group
    (source / "2024").rename(tmp_path / "2024_movida")
    (secret.parent / "a_copia.pdf").write_bytes(b"secreto")
    _symlink(source / "2024", secret.parent, is_dir=True)
    monkeypatch.setattr(deduplication, "ensure_no_symlinks", lambda path: Path(os.path.abspath(path)))

    for copy in (True, False):
        with pytest.raises(OSError):
            await DeduplicationManager()._move_to_duplicates(
                source / "2024" / "a_copia.pdf", tmp_path / "duplicados", "hash-uno", copy=copy, relative_to=source
            )

    assert (secret.parent / "a_copia.pdf").read_bytes() == b"secreto"
    assert not any(p.is_file() for p in (tmp_path / "duplicados").rglob("*"))


@pytest.mark.asyncio
async def test_copy_preserves_content_and_mtime(tmp_path: Path, nested_group: tuple[Path, list[DocumentMetadata]]) -> None:
    source, docs = nested_group
    os.utime(docs[1].full_path, (1_000_000, 1_000_000))
    duplicates_dir = tmp_path / "duplicados"

    await DeduplicationManager().resolve_duplicates(DeduplicationManager().find_duplicates(docs), duplicates_dir, mode="copy", relative_to=source)

    copied = duplicates_dir / "2024" / "a_copia.pdf"
    assert copied.read_bytes() == b"uno"
    assert int(copied.stat().st_mtime) == 1_000_000
