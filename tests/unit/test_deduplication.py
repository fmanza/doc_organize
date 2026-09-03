"""Tests unitarios de DeduplicationManager (REQ-005)."""

import json

from datetime import datetime, timedelta, timezone

import pytest

from doc_organize.core.models import DocumentMetadata, DuplicateReason
from doc_organize.dedup import DeduplicationManager


def _doc(full_path: str, sha256_hash: str, modified_time: float, extension: str = "pdf") -> DocumentMetadata:
    return DocumentMetadata(
        full_path=full_path,
        display_name=full_path.rsplit("/", 1)[-1],
        extension=extension,
        size_bytes=100,
        modified_time=modified_time,
        sha256_hash=sha256_hash,
    )


@pytest.fixture
def manager() -> DeduplicationManager:
    return DeduplicationManager()


def test_no_duplicates_returns_empty(manager: DeduplicationManager) -> None:
    docs = [_doc("/repo/a.pdf", "hash-a", 1.0), _doc("/repo/b.pdf", "hash-b", 2.0)]
    assert manager.find_duplicates(docs) == []


def test_exact_duplicate_keeps_oldest_as_canonical(manager: DeduplicationManager) -> None:
    older = _doc("/repo/original.pdf", "same-hash", modified_time=1.0)
    newer = _doc("/repo/copy.pdf", "same-hash", modified_time=2.0)

    groups = manager.find_duplicates([newer, older])

    assert len(groups) == 1
    group = groups[0]
    assert group.reason == DuplicateReason.EXACT_DUPLICATE
    assert group.canonical_doc.full_path == older.full_path
    assert [d.full_path for d in group.duplicates] == [newer.full_path]


def test_version_conflict_detected_by_suffix(manager: DeduplicationManager) -> None:
    v1 = _doc("/repo/report_v1.pdf", "hash-v1", modified_time=1.0)
    v2 = _doc("/repo/report_v2.pdf", "hash-v2", modified_time=2.0)

    groups = manager.find_duplicates([v2, v1])

    assert len(groups) == 1
    group = groups[0]
    assert group.reason == DuplicateReason.VERSION_CONFLICT
    assert group.canonical_doc.full_path == v1.full_path


def test_different_base_names_are_not_grouped(manager: DeduplicationManager) -> None:
    a = _doc("/repo/alpha.pdf", "hash-a", modified_time=1.0)
    b = _doc("/repo/beta.pdf", "hash-b", modified_time=2.0)
    assert manager.find_duplicates([a, b]) == []


@pytest.mark.asyncio
async def test_resolve_duplicates_moves_files_and_writes_report(tmp_path) -> None:
    source_dir = tmp_path / "docs"
    source_dir.mkdir()
    older = source_dir / "original.pdf"
    newer = source_dir / "copy.pdf"
    older.write_bytes(b"same-content")
    newer.write_bytes(b"same-content")

    older_doc = _doc(str(older), "same-hash", modified_time=1.0)
    newer_doc = _doc(str(newer), "same-hash", modified_time=2.0)

    manager = DeduplicationManager()
    groups = manager.find_duplicates([newer_doc, older_doc])
    duplicates_dir = tmp_path / "duplicados"

    report = await manager.resolve_duplicates(groups, duplicates_dir)

    assert older.exists()  # el canonico se queda en su sitio
    assert not newer.exists()  # el duplicado se movio
    assert report.total_exact_duplicates == 1
    assert report.total_version_conflicts == 0

    audit_path = duplicates_dir / "DEDUP_REPORT.json"
    assert audit_path.exists()
    payload = json.loads(audit_path.read_text(encoding="utf-8"))
    assert payload["total_exact_duplicates"] == 1
    # Sin `started_at`, la duracion queda sin dato -- no un `0.0` enganoso que
    # sugiera una operacion instantanea.
    assert report.duration_seconds is None
    assert report.started_at is None


@pytest.mark.asyncio
async def test_resolve_duplicates_computes_duration_from_started_at(tmp_path) -> None:
    source_dir = tmp_path / "docs"
    source_dir.mkdir()
    older = source_dir / "original.pdf"
    newer = source_dir / "copy.pdf"
    older.write_bytes(b"same-content")
    newer.write_bytes(b"same-content")

    older_doc = _doc(str(older), "same-hash", modified_time=1.0)
    newer_doc = _doc(str(newer), "same-hash", modified_time=2.0)

    manager = DeduplicationManager()
    groups = manager.find_duplicates([newer_doc, older_doc])
    duplicates_dir = tmp_path / "duplicados"
    started_at = datetime.now(timezone.utc) - timedelta(seconds=5)

    report = await manager.resolve_duplicates(groups, duplicates_dir, started_at=started_at)

    assert report.started_at == started_at.isoformat()
    assert report.duration_seconds is not None
    assert report.duration_seconds >= 5.0


@pytest.mark.asyncio
async def test_resolve_duplicates_appends_to_history_across_runs(tmp_path) -> None:
    # "los duplicados generan una lista incremental que permita su consulta":
    # DEDUP_REPORT.json solo guarda el ultimo run, pero DEDUP_HISTORY.jsonl debe
    # acumular todas las ejecuciones -- una linea por resolve_duplicates(), sin
    # sobrescribir las anteriores.
    source_dir = tmp_path / "docs"
    source_dir.mkdir()
    duplicates_dir = tmp_path / "duplicados"
    manager = DeduplicationManager()

    first_older = source_dir / "first_original.pdf"
    first_newer = source_dir / "first_copy.pdf"
    first_older.write_bytes(b"first-content")
    first_newer.write_bytes(b"first-content")
    first_groups = manager.find_duplicates(
        [
            _doc(str(first_newer), "first-hash", modified_time=2.0),
            _doc(str(first_older), "first-hash", modified_time=1.0),
        ]
    )
    await manager.resolve_duplicates(first_groups, duplicates_dir)

    second_older = source_dir / "second_original.pdf"
    second_newer = source_dir / "second_copy.pdf"
    second_older.write_bytes(b"second-content")
    second_newer.write_bytes(b"second-content")
    second_groups = manager.find_duplicates(
        [
            _doc(str(second_newer), "second-hash", modified_time=2.0),
            _doc(str(second_older), "second-hash", modified_time=1.0),
        ]
    )
    await manager.resolve_duplicates(second_groups, duplicates_dir)

    history_path = duplicates_dir / "DEDUP_HISTORY.jsonl"
    lines = [line for line in history_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(lines) == 2
    reports = [json.loads(line) for line in lines]
    assert [report["total_exact_duplicates"] for report in reports] == [1, 1]
    # DEDUP_REPORT.json (solo lectura del ultimo run) no se ve afectado por el
    # historico: sigue reflejando unicamente la segunda ejecucion.
    last_report = json.loads((duplicates_dir / "DEDUP_REPORT.json").read_text(encoding="utf-8"))
    assert last_report["total_exact_duplicates"] == 1


@pytest.mark.asyncio
async def test_resolve_duplicates_avoids_overwrite_on_name_collision(tmp_path) -> None:
    source_dir = tmp_path / "a"
    source_dir.mkdir()
    source_file = source_dir / "report.pdf"
    source_file.write_bytes(b"content-a")

    duplicates_dir = tmp_path / "duplicados"
    # Archivo preexistente en la ruta destino reflejada, para forzar una colision.
    mirrored_parts = source_file.resolve().parts[1:]
    pre_existing = duplicates_dir.joinpath(*mirrored_parts)
    pre_existing.parent.mkdir(parents=True, exist_ok=True)
    pre_existing.write_bytes(b"already-there")

    manager = DeduplicationManager()
    await manager._move_to_duplicates(source_file, duplicates_dir, "hash-a-collision")

    assert not source_file.exists()
    assert pre_existing.exists()  # el archivo preexistente no se sobrescribio
    suffixed = pre_existing.with_name(f"{pre_existing.stem}_{'hash-a-collision'[:8]}{pre_existing.suffix}")
    assert suffixed.exists()
