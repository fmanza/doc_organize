"""Giro del historial del contexto (1.6.0, fase L3)."""

import asyncio
import json
import logging
import os
import subprocess
import sys

from datetime import UTC, datetime
from pathlib import Path

import pytest

from doc_organize.context import ContextBuilder, ContextHistoryPolicy, ContextRegistry, context_history as context_history_module
from doc_organize.context.context_history import append_context_build, history_file_set, list_context_builds
from doc_organize.core.models import ContextBuildRecord, ContextChange, ConversionResult, Project
from doc_organize.export import load_context_history
from doc_organize.projects import ProjectLayout
from doc_organize.projects.layout import context_history_files, rotated_context_history_path


def _record(index: int, changes: int = 20) -> ContextBuildRecord:
    return ContextBuildRecord(
        built_at=f"2026-11-16T00:{index // 60:02d}:{index % 60:02d}+00:00",
        project_name="Demo",
        classified=changes,
        unclassified=0,
        changes=[ContextChange(source_path=f"/origen/{index}/{n}.pdf", change="added", domain="calidad") for n in range(changes)],
    )


def _line_size() -> int:
    return len(_record(0).model_dump_json()) + 1


def _append(history: Path, indexes: range, policy: ContextHistoryPolicy) -> None:
    async def _run() -> None:
        for index in indexes:
            await append_context_build(history, _record(index), policy)

    asyncio.run(_run())


@pytest.fixture
def history(tmp_path: Path) -> Path:
    return tmp_path / "historial_contexto" / "CONTEXT_HISTORY.jsonl"


def test_default_policy() -> None:
    assert ContextHistoryPolicy() == ContextHistoryPolicy(max_bytes=5_000_000, backups=4)


@pytest.mark.parametrize(("max_bytes", "backups"), [(0, 4), (-1, 4), (100, -1)])
def test_invalid_policy(max_bytes: int, backups: int) -> None:
    with pytest.raises(ValueError):
        ContextHistoryPolicy(max_bytes=max_bytes, backups=backups)


def test_rotates_when_the_next_line_would_pass_the_limit(history: Path) -> None:
    policy = ContextHistoryPolicy(max_bytes=3 * _line_size(), backups=4)

    _append(history, range(4), policy)  # caben 3 líneas: la cuarta gira

    assert [len(path.read_text(encoding="utf-8").splitlines()) for path in context_history_files(history)] == [3, 1]
    assert context_history_files(history) == [rotated_context_history_path(history, 1), history]


def test_keeps_only_the_configured_backups_and_reads_them_in_order(history: Path) -> None:
    policy = ContextHistoryPolicy(max_bytes=2 * _line_size(), backups=2)

    _append(history, range(10), policy)  # 2 líneas por fichero: .2 = [4,5], .1 = [6,7], actual = [8,9]

    assert [path.name for path in context_history_files(history)] == [
        "CONTEXT_HISTORY.2.jsonl",
        "CONTEXT_HISTORY.1.jsonl",
        "CONTEXT_HISTORY.jsonl",
    ]
    assert [record.built_at for record in list_context_builds(history)] == [_record(i).built_at for i in range(9, 3, -1)]
    assert [record.built_at for record in list_context_builds(history, include_rotated=False)] == [_record(9).built_at, _record(8).built_at]


def test_without_backups_the_file_grows_as_in_1_5_0(history: Path) -> None:
    _append(history, range(5), ContextHistoryPolicy(max_bytes=1, backups=0))

    assert context_history_files(history) == [history]
    assert len(list_context_builds(history)) == 5


def test_a_line_larger_than_the_limit_is_written_to_a_new_file(history: Path) -> None:
    policy = ContextHistoryPolicy(max_bytes=10, backups=3)

    _append(history, range(2), policy)

    assert [len(path.read_text(encoding="utf-8").splitlines()) for path in context_history_files(history)] == [1, 1]


def test_lowering_backups_removes_the_extra_copies(history: Path) -> None:
    size = _line_size()
    _append(history, range(6), ContextHistoryPolicy(max_bytes=size, backups=5))
    assert len(context_history_files(history)) == 6

    _append(history, range(6, 7), ContextHistoryPolicy(max_bytes=size, backups=2))

    assert [path.name for path in context_history_files(history)] == [
        "CONTEXT_HISTORY.2.jsonl",
        "CONTEXT_HISTORY.1.jsonl",
        "CONTEXT_HISTORY.jsonl",
    ]


def test_a_failed_rotation_still_records_the_build(history: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
    policy = ContextHistoryPolicy(max_bytes=_line_size(), backups=2)
    _append(history, range(1), policy)

    def _locked_by_a_reader(source: Path, target: Path) -> None:
        raise PermissionError("El proceso no tiene acceso al archivo porque está siendo utilizado por otro proceso")

    monkeypatch.setattr(context_history_module, "_replace_with_retry", _locked_by_a_reader)
    with caplog.at_level(logging.WARNING):
        _append(history, range(1, 2), policy)

    assert "No se pudo girar" in caplog.text
    assert context_history_files(history) == [history]
    assert len(list_context_builds(history)) == 2


def test_replace_retries_while_a_reader_holds_the_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source, target = tmp_path / "a", tmp_path / "b"
    source.write_text("x", encoding="utf-8")
    calls: list[int] = []
    real_replace = os.replace

    def _flaky_replace(src: Path, dst: Path) -> None:
        calls.append(1)
        if len(calls) < 3:
            raise PermissionError("en uso")
        real_replace(src, dst)

    monkeypatch.setattr(context_history_module.os, "replace", _flaky_replace)
    monkeypatch.setattr(context_history_module, "_REPLACE_BACKOFF_S", 0)

    context_history_module._replace_with_retry(source, target)

    assert len(calls) == 3
    assert target.read_text(encoding="utf-8") == "x"


def test_a_1_5_0_history_is_read_unchanged(history: Path) -> None:
    history.parent.mkdir(parents=True)
    history.write_text("".join(_record(i).model_dump_json() + "\r\n" for i in range(3)), encoding="utf-8")  # 1.5.0 en Windows

    assert [record.built_at for record in list_context_builds(history)] == [_record(i).built_at for i in (2, 1, 0)]


def test_gaps_in_the_numbering_are_listed(history: Path) -> None:
    history.parent.mkdir(parents=True)
    for index in (1, 3):
        rotated_context_history_path(history, index).write_text(_record(index).model_dump_json() + "\n", encoding="utf-8")
    (history.parent / "CONTEXT_HISTORY.x.jsonl").write_text("no es una copia", encoding="utf-8")

    assert [path.name for path in context_history_files(history)] == ["CONTEXT_HISTORY.3.jsonl", "CONTEXT_HISTORY.1.jsonl"]


def test_load_context_history_does_not_repeat_explicit_copies(history: Path) -> None:
    _append(history, range(4), ContextHistoryPolicy(max_bytes=_line_size(), backups=4))

    explicit = load_context_history([history, *context_history_files(history)])

    assert [record.built_at for record in explicit] == [_record(i).built_at for i in (3, 2, 1, 0)]
    assert history_file_set([history, rotated_context_history_path(history, 1)]) == context_history_files(history)


def _converted(tmp_path: Path, name: str) -> ConversionResult:
    source = tmp_path / "origen" / "Calidad" / name
    source.parent.mkdir(parents=True, exist_ok=True)
    json_path = tmp_path / f"{source.stem}.json"
    json_path.write_text(json.dumps({"title": source.stem, "chunks": []}), encoding="utf-8")
    return ConversionResult(source_path=str(source), markdown_path=str(tmp_path / f"{source.stem}.md"), json_path=str(json_path), success=True)


@pytest.mark.asyncio
async def test_context_builder_uses_its_history_policy(tmp_path: Path) -> None:
    project = Project(name="Demo", root_path=str(tmp_path), created_at=datetime.now(UTC).isoformat())
    builder = ContextBuilder(ContextRegistry(), history_policy=ContextHistoryPolicy(max_bytes=1, backups=2))
    documents = [_converted(tmp_path, "informe.pdf")]

    for _ in range(4):
        await builder.build(project, documents)

    layout = ProjectLayout.for_project(project)
    assert [path.name for path in layout.context_history_files()] == [
        "CONTEXT_HISTORY.2.jsonl",
        "CONTEXT_HISTORY.1.jsonl",
        "CONTEXT_HISTORY.jsonl",
    ]
    assert len(list_context_builds(layout.context_history)) == 3  # la primera construcción ya se descartó


_ROTATING_WRITER = """
import asyncio, sys
from pathlib import Path
from doc_organize.context.context_history import ContextHistoryPolicy, append_context_build
from doc_organize.core.models import ContextBuildRecord, ContextChange

history, writer, count = Path(sys.argv[1]), int(sys.argv[2]), int(sys.argv[3])
policy = ContextHistoryPolicy(max_bytes=60_000, backups=1000)

async def main():
    for index in range(count):
        changes = [ContextChange(source_path=f"/origen/{writer}/{index}/{n}.pdf", change="added") for n in range(150)]
        record = ContextBuildRecord(built_at=f"{writer}-{index}", project_name="Demo", classified=150, unclassified=0,
                                    changes=changes)
        await append_context_build(history, record, policy)

asyncio.run(main())
"""


def test_concurrent_processes_rotating_lose_no_build(history: Path) -> None:
    """Cuatro procesos × 40 líneas de ~15 KB con giro cada ~4 líneas: ninguna se pierde ni se mezcla."""
    writers, count = 4, 40
    processes = [
        subprocess.Popen([sys.executable, "-c", _ROTATING_WRITER, str(history), str(writer), str(count)], stderr=subprocess.PIPE)
        for writer in range(writers)
    ]
    for process in processes:
        _, stderr = process.communicate(timeout=180)
        assert process.returncode == 0, stderr.decode(errors="replace")

    files = context_history_files(history)
    assert len(files) > 10
    lines = [line for path in files for line in path.read_text(encoding="utf-8").splitlines()]
    records = [ContextBuildRecord.model_validate_json(line) for line in lines]
    assert sorted(record.built_at for record in records) == sorted(f"{w}-{i}" for w in range(writers) for i in range(count))


def test_symlinked_copies_are_neither_listed_nor_read(tmp_path: Path) -> None:
    history = tmp_path / "CONTEXT_HISTORY.jsonl"
    history.write_text("", encoding="utf-8")
    elsewhere = tmp_path / "ajeno.jsonl"
    elsewhere.write_text("", encoding="utf-8")
    try:
        rotated_context_history_path(history, 1).symlink_to(elsewhere)
    except OSError as exc:
        pytest.skip(f"no se pueden crear enlaces simbólicos aquí: {exc}")

    assert context_history_files(history) == [history]
