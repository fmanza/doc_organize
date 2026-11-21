"""Bloqueo entre procesos del historial del contexto (1.6.0, fase L2)."""

import asyncio
import functools
import logging
import os
import subprocess
import sys
import textwrap
import threading
import time

from pathlib import Path

import pytest

from doc_organize.context import context_history as context_history_module
from doc_organize.context.context_history import append_context_build, list_context_builds
from doc_organize.core.models import ContextBuildRecord, ContextChange
from doc_organize.utils import file_lock as file_lock_module
from doc_organize.utils.file_lock import exclusive_lock, lock_path_for


def _record(index: int, changes: int = 1) -> ContextBuildRecord:
    return ContextBuildRecord(
        built_at=f"2026-11-16T00:00:{index:02d}+00:00",
        project_name="Demo",
        classified=changes,
        unclassified=0,
        changes=[ContextChange(source_path=f"/origen/{index}/{n}.pdf", change="added", domain="calidad") for n in range(changes)],
    )


def test_lock_exists_only_inside_the_block(tmp_path: Path) -> None:
    target = tmp_path / "CONTEXT_HISTORY.jsonl"
    with exclusive_lock(target):
        assert lock_path_for(target).is_file()
    assert not lock_path_for(target).exists()


def test_lock_is_released_when_the_block_fails(tmp_path: Path) -> None:
    target = tmp_path / "CONTEXT_HISTORY.jsonl"
    with pytest.raises(RuntimeError), exclusive_lock(target):
        raise RuntimeError("fallo dentro del bloque")
    assert not lock_path_for(target).exists()


def test_a_live_lock_times_out(tmp_path: Path) -> None:
    target = tmp_path / "CONTEXT_HISTORY.jsonl"
    lock_path_for(target).write_text("otro proceso", encoding="utf-8")

    started = time.monotonic()
    with pytest.raises(TimeoutError), exclusive_lock(target, timeout=0.3):
        pass

    assert time.monotonic() - started >= 0.3
    assert lock_path_for(target).read_text(encoding="utf-8") == "otro proceso"  # no se rompe un bloqueo vivo


def test_a_stale_lock_is_broken(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    target = tmp_path / "CONTEXT_HISTORY.jsonl"
    lock = lock_path_for(target)
    lock.write_text("proceso muerto", encoding="utf-8")
    old = time.time() - 3600
    os.utime(lock, (old, old))

    with caplog.at_level(logging.WARNING), exclusive_lock(target, timeout=0.3, stale_after=60):
        assert lock.read_text(encoding="utf-8") != "proceso muerto"

    assert "huérfano" in caplog.text
    assert not lock.exists()
    assert list(tmp_path.iterdir()) == []  # ni la lápida ni el fichero de sondeo se quedan


def test_append_writes_one_line_per_record(tmp_path: Path) -> None:
    history = tmp_path / "historial_contexto" / "CONTEXT_HISTORY.jsonl"

    asyncio.run(append_context_build(history, _record(1)))
    asyncio.run(append_context_build(history, _record(2)))

    assert [record.built_at for record in list_context_builds(history)] == [_record(2).built_at, _record(1).built_at]
    assert history.read_bytes().count(b"\r\n") == 0
    assert not lock_path_for(history).exists()


def test_append_fails_with_os_error_while_another_process_holds_the_lock(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    history = tmp_path / "CONTEXT_HISTORY.jsonl"
    lock_path_for(history).write_text("otro proceso", encoding="utf-8")
    monkeypatch.setattr(context_history_module, "exclusive_lock", functools.partial(exclusive_lock, timeout=0.2))

    with pytest.raises(OSError):  # TimeoutError es un OSError: ContextBuilder lo trata como aviso
        asyncio.run(append_context_build(history, _record(1)))

    assert not history.exists()


def _symlink_or_skip(link: Path, target: Path) -> None:
    """Crea el enlace o salta el test (en Windows hace falta el modo desarrollador o privilegios)."""
    try:
        link.symlink_to(target)
    except OSError as exc:
        pytest.skip(f"no se pueden crear enlaces simbólicos aquí: {exc}")


def test_append_does_not_follow_a_symlink(tmp_path: Path) -> None:
    elsewhere = tmp_path / "fuera.txt"
    elsewhere.write_text("", encoding="utf-8")
    history = tmp_path / "historial_contexto" / "CONTEXT_HISTORY.jsonl"
    history.parent.mkdir()
    _symlink_or_skip(history, elsewhere)

    with pytest.raises(OSError):
        asyncio.run(append_context_build(history, _record(1)))

    assert elsewhere.read_text(encoding="utf-8") == ""
    assert not (tmp_path / "historial_contexto" / "CONTEXT_HISTORY.1.jsonl").exists()  # tampoco gira el enlace


def _acquire_in_thread(target: Path, timeout: float) -> dict[str, object]:
    """Intenta tomar el bloqueo en un hilo y espera como mucho 5 s: un bucle sin fin no cuelga la suite."""
    result: dict[str, object] = {}

    def run() -> None:
        try:
            with exclusive_lock(target, timeout=timeout):
                result["outcome"] = "acquired"
        except OSError as exc:
            result["outcome"] = type(exc).__name__

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    thread.join(5)
    result["alive"] = thread.is_alive()
    return result


def test_a_dangling_symlink_lock_is_a_busy_lock_not_a_loop(tmp_path: Path) -> None:
    target = tmp_path / "CONTEXT_HISTORY.jsonl"
    nowhere = tmp_path / "no-existe"
    _symlink_or_skip(lock_path_for(target), nowhere)

    result = _acquire_in_thread(target, timeout=0.3)

    assert result == {"outcome": "TimeoutError", "alive": False}  # reciente: se espera; antes, bucle sin fin
    assert not nowhere.exists()  # en Windows, O_EXCL creaba el destino del enlace


def test_an_old_symlink_lock_is_broken_without_touching_its_target(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    target = tmp_path / "CONTEXT_HISTORY.jsonl"
    elsewhere = tmp_path / "fuera.txt"
    elsewhere.write_text("no tocar", encoding="utf-8")
    lock = lock_path_for(target)
    _symlink_or_skip(lock, elsewhere)
    real_now = file_lock_module._server_now
    monkeypatch.setattr(file_lock_module, "_server_now", lambda folder: real_now(folder) + 3600)  # el enlace parece de hace 1 h

    result = _acquire_in_thread(target, timeout=2.0)

    assert result == {"outcome": "acquired", "alive": False}
    assert elsewhere.read_text(encoding="utf-8") == "no tocar"
    assert not os.path.lexists(lock)


_WRITER = textwrap.dedent(
    """
    import asyncio, sys
    from pathlib import Path
    import functools
    from doc_organize.context import context_history
    from doc_organize.context.context_history import append_context_build
    from doc_organize.core.models import ContextBuildRecord, ContextChange
    from doc_organize.utils.file_lock import exclusive_lock

    # La prueba es de que no se intercalen líneas, no del plazo: con cuatro procesos en un runner de Windows cargado,
    # uno puede pasar más de los 5 s por defecto sin conseguir el bloqueo (se sondea, no hay cola).
    context_history.exclusive_lock = functools.partial(exclusive_lock, timeout=120)

    history, writer, count = Path(sys.argv[1]), int(sys.argv[2]), int(sys.argv[3])

    async def main():
        for index in range(count):
            changes = [ContextChange(source_path=f"/origen/{writer}/{index}/{n}.pdf", change="added") for n in range(150)]
            record = ContextBuildRecord(built_at=f"{writer}-{index}", project_name="Demo", classified=150, unclassified=0,
                                        changes=changes)
            await append_context_build(history, record)

    asyncio.run(main())
    """
)


def test_concurrent_processes_never_interleave_lines(tmp_path: Path) -> None:
    """Cuatro procesos añaden 40 construcciones grandes (~15 KB por línea) cada uno al mismo historial."""
    history = tmp_path / "historial_contexto" / "CONTEXT_HISTORY.jsonl"
    writers, count = 4, 40
    processes = [
        subprocess.Popen([sys.executable, "-c", _WRITER, str(history), str(writer), str(count)], stderr=subprocess.PIPE) for writer in range(writers)
    ]
    for process in processes:
        _, stderr = process.communicate(timeout=120)
        assert process.returncode == 0, stderr.decode(errors="replace")

    lines = history.read_text(encoding="utf-8").splitlines()
    records = [ContextBuildRecord.model_validate_json(line) for line in lines]  # una línea intercalada no validaría
    assert len(records) == writers * count
    assert {record.built_at for record in records} == {f"{w}-{i}" for w in range(writers) for i in range(count)}
    assert not lock_path_for(history).exists()
