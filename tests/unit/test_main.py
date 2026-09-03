"""Tests de main.py (CLI, Fase D-1): resolucion de rutas y orquestacion de `scan`."""

import json

from pathlib import Path
from typing import Self

import pytest

from doc_organize.converter import DocumentConverter
from doc_organize.core.constants import SCAN_HISTORY_FOLDER_NAME, SCAN_HISTORY_JSONL_NAME
from doc_organize.core.exceptions import DocOrganizeError
from doc_organize.core.models import AvStatus, ConversionStatus, ScanEventType
from doc_organize.main import ScanCommand, _resolve_dedup_paths, _resolve_scan_paths, build_parser, main
from doc_organize.projects import ProjectRegistry

_SAMPLE_TEXT = "Informe de prueba doc_organize.\nDocumento de fixture para tests del CLI."


def _make_native_pdf(path: Path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig = plt.figure(figsize=(8.27, 11.69))
    fig.text(0.1, 0.7, _SAMPLE_TEXT, fontsize=14, family="sans-serif")
    fig.savefig(path, format="pdf")
    plt.close(fig)


def _make_scanned_pdf(path: Path) -> None:
    from PIL import Image, ImageDraw, ImageFont

    img = Image.new("RGB", (1240, 1754), color="white")
    draw = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype("arial.ttf", 36)
    except OSError:
        font = ImageFont.load_default()
    draw.multiline_text((80, 200), _SAMPLE_TEXT, fill="black", font=font, spacing=12)
    img.save(path, "PDF", resolution=150.0)


# ===== _resolve_scan_paths =====


class _Args:
    def __init__(self, **kwargs: object) -> None:
        self.project = kwargs.get("project")
        self.output_dir = kwargs.get("output_dir")
        self.cache_file = kwargs.get("cache_file")
        self.duplicates_dir = kwargs.get("duplicates_dir")


@pytest.mark.asyncio
async def test_resolve_scan_paths_from_project(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("doc_organize.main.ProjectRegistry", lambda: _FakeRegistry(tmp_path / "proj"))
    args = _Args(project="Mi Proyecto")

    output_dir, cache_db, folders_json = await _resolve_scan_paths(args)

    root = tmp_path / "proj"
    assert output_dir == root / "Conversión"
    assert cache_db == root / "cache.db"
    assert folders_json == root / "folders.json"


@pytest.mark.asyncio
async def test_resolve_scan_paths_explicit_flags_without_project() -> None:
    args = _Args(output_dir="/tmp/out", cache_file="/tmp/cache.db")

    output_dir, cache_db, _folders_json = await _resolve_scan_paths(args)

    assert output_dir == Path("/tmp/out")
    assert cache_db == Path("/tmp/cache.db")


@pytest.mark.asyncio
async def test_resolve_scan_paths_requires_project_or_explicit_flags() -> None:
    args = _Args()
    with pytest.raises(DocOrganizeError):
        await _resolve_scan_paths(args)


@pytest.mark.asyncio
async def test_resolve_scan_paths_explicit_overrides_project(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("doc_organize.main.ProjectRegistry", lambda: _FakeRegistry(tmp_path / "proj"))
    args = _Args(project="Mi Proyecto", cache_file=str(tmp_path / "custom_cache.db"))

    output_dir, cache_db, _folders_json = await _resolve_scan_paths(args)

    root = tmp_path / "proj"
    assert cache_db == tmp_path / "custom_cache.db"  # el flag explicito gana
    assert output_dir == root / "Conversión"  # el resto sigue derivado del proyecto


# ===== _resolve_dedup_paths =====


@pytest.mark.asyncio
async def test_resolve_dedup_paths_from_project(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("doc_organize.main.ProjectRegistry", lambda: _FakeRegistry(tmp_path / "proj"))
    args = _Args(project="Mi Proyecto")

    duplicates_dir, folders_json = await _resolve_dedup_paths(args)

    root = tmp_path / "proj"
    assert duplicates_dir == root / "duplicados"
    assert folders_json == root / "folders.json"


@pytest.mark.asyncio
async def test_resolve_dedup_paths_explicit_without_project() -> None:
    args = _Args(duplicates_dir="/tmp/duplicados")

    duplicates_dir, folders_json = await _resolve_dedup_paths(args)

    assert duplicates_dir == Path("/tmp/duplicados")
    assert folders_json == Path("/tmp/folders.json")


@pytest.mark.asyncio
async def test_resolve_dedup_paths_requires_project_or_explicit_flag() -> None:
    args = _Args()
    with pytest.raises(DocOrganizeError):
        await _resolve_dedup_paths(args)


class _FakeProject:
    def __init__(self, root_path: Path) -> None:
        self.root_path = str(root_path)


class _FakeRegistry:
    def __init__(self, root_path: Path) -> None:
        self._root_path = root_path

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        return None

    async def get_project(self, name: str) -> _FakeProject:
        return _FakeProject(self._root_path)


# ===== build_parser =====


def test_build_parser_scan_requires_paths() -> None:
    parser = build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["scan"])


def test_build_parser_scan_parses_flags() -> None:
    parser = build_parser()
    args = parser.parse_args(["scan", "--paths", "/a", "/b", "--project", "Foo", "--use-ocr"])
    assert args.paths == ["/a", "/b"]
    assert args.project == "Foo"
    assert args.use_ocr is True
    assert args.use_gpu is False
    assert args.force is False


def test_build_parser_scan_parses_force_flag() -> None:
    parser = build_parser()
    args = parser.parse_args(["scan", "--paths", "/a", "--force"])
    assert args.force is True


def test_build_parser_deduplicate_requires_paths() -> None:
    parser = build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["deduplicate"])


def test_build_parser_deduplicate_parses_flags() -> None:
    parser = build_parser()
    args = parser.parse_args(["deduplicate", "--paths", "/a", "/b", "--project", "Foo"])
    assert args.paths == ["/a", "/b"]
    assert args.project == "Foo"
    assert args.duplicates_dir is None


def test_build_parser_project_create() -> None:
    parser = build_parser()
    args = parser.parse_args(["project", "create", "Mi Proyecto", "--location", "/repo"])
    assert args.command == "project"
    assert args.project_command == "create"
    assert args.name == "Mi Proyecto"
    assert args.location == "/repo"


# ===== ScanCommand end-to-end (Docling real, sin mocks) =====


@pytest.mark.slow
@pytest.mark.asyncio
async def test_scan_command_converts_new_documents(tmp_path) -> None:
    base = tmp_path / "workspaces"
    base.mkdir()
    async with ProjectRegistry(tmp_path / "projects.json") as registry:
        project = await registry.create_project("Proyecto Scan", base)
    root = Path(project.root_path)

    input_dir = tmp_path / "input"
    input_dir.mkdir()
    _make_native_pdf(input_dir / "native.pdf")

    summary = await ScanCommand().run(
        paths=[str(input_dir)],
        output_dir=root / "Conversión",
        cache_db=root / "cache.db",
        folders_json=root / "folders.json",
        use_ocr=False,
        use_gpu=False,
    )

    assert summary.scanned == 1
    assert summary.new == 1
    assert summary.converted == 1
    assert summary.conversion_errors == 0
    assert summary.ocr_required == 0
    # DocumentConverter replica la ruta de origen completa bajo output_dir (REQ-003),
    # asi que se busca el .md generado en vez de asumir una ubicacion plana.
    generated = list((root / "Conversión").rglob("native.md"))
    assert len(generated) == 1
    assert (root / "folders.json").exists()


@pytest.mark.slow
@pytest.mark.asyncio
async def test_scan_command_run_streaming_emits_expected_event_sequence(tmp_path) -> None:
    # Fase D-2b (SS2.7.3): run_streaming() es la orquestacion real; run() (probado arriba)
    # es ahora un envoltorio delgado sobre ella. Este test cubre la secuencia de eventos
    # que web/routes/scan.py retransmitira por WebSocket.
    base = tmp_path / "workspaces"
    base.mkdir()
    async with ProjectRegistry(tmp_path / "projects.json") as registry:
        project = await registry.create_project("Proyecto Streaming", base)
    root = Path(project.root_path)

    input_dir = tmp_path / "input"
    input_dir.mkdir()
    _make_native_pdf(input_dir / "native.pdf")

    events = [
        event
        async for event in ScanCommand().run_streaming(
            paths=[str(input_dir)],
            output_dir=root / "Conversión",
            cache_db=root / "cache.db",
            folders_json=root / "folders.json",
            use_ocr=False,
            use_gpu=False,
        )
    ]

    event_types = [event.event for event in events]
    assert event_types == [
        ScanEventType.STARTED,
        ScanEventType.SCANNED,
        ScanEventType.FILE_STARTED,
        ScanEventType.FILE_CONVERTED,
        ScanEventType.COMPLETED,
    ]
    assert events[1].data["to_process"] == 1
    assert events[-1].data["scanned"] == 1
    assert events[-1].data["converted"] == 1
    assert events[-1].data["duration_seconds"] > 0
    file_started = events[2]
    assert file_started.data == {"path": file_started.data["path"], "index": 1, "total": 1}
    assert file_started.data["path"].endswith("native.pdf")
    file_converted = events[3]
    assert file_converted.data["success"] is True
    assert file_converted.data["path"].endswith("native.pdf")


@pytest.mark.slow
@pytest.mark.asyncio
async def test_scan_command_run_streaming_no_file_started_when_nothing_to_convert(tmp_path) -> None:
    # `to_process=0` (todo ya en cache, sin cambios): no debe emitirse ningun
    # FILE_STARTED/FILE_CONVERTED -- la UI depende de esto para mostrar "Sin
    # ficheros nuevos que convertir" en vez de una barra de progreso vacia.
    base = tmp_path / "workspaces"
    base.mkdir()
    async with ProjectRegistry(tmp_path / "projects.json") as registry:
        project = await registry.create_project("Proyecto Sin Cambios", base)
    root = Path(project.root_path)

    input_dir = tmp_path / "input"
    input_dir.mkdir()
    _make_native_pdf(input_dir / "native.pdf")

    run_kwargs = {
        "paths": [str(input_dir)],
        "output_dir": root / "Conversión",
        "cache_db": root / "cache.db",
        "folders_json": root / "folders.json",
        "use_ocr": False,
        "use_gpu": False,
    }
    await ScanCommand().run(**run_kwargs)

    events = [event async for event in ScanCommand().run_streaming(**run_kwargs)]

    event_types = [event.event for event in events]
    assert ScanEventType.FILE_STARTED not in event_types
    assert ScanEventType.FILE_CONVERTED not in event_types
    scanned_event = next(event for event in events if event.event == ScanEventType.SCANNED)
    assert scanned_event.data["to_process"] == 0


@pytest.mark.slow
@pytest.mark.asyncio
async def test_scan_command_second_run_skips_unchanged(tmp_path) -> None:
    base = tmp_path / "workspaces"
    base.mkdir()
    async with ProjectRegistry(tmp_path / "projects.json") as registry:
        project = await registry.create_project("Proyecto Cache", base)
    root = Path(project.root_path)

    input_dir = tmp_path / "input"
    input_dir.mkdir()
    _make_native_pdf(input_dir / "native.pdf")

    run_kwargs = {
        "paths": [str(input_dir)],
        "output_dir": root / "Conversión",
        "cache_db": root / "cache.db",
        "folders_json": root / "folders.json",
        "use_ocr": False,
        "use_gpu": False,
    }

    first = await ScanCommand().run(**run_kwargs)
    second = await ScanCommand().run(**run_kwargs)

    assert first.new == 1
    assert second.new == 0
    assert second.unchanged == 1
    assert second.converted == 0  # no se reconvierte lo que no cambio


@pytest.mark.slow
@pytest.mark.asyncio
async def test_scan_command_force_reconverts_unchanged(tmp_path) -> None:
    """`force=True` vacía la caché antes de comparar: un documento sin cambios
    (que normalmente se saltaría, ver test anterior) se reconvierte igualmente."""
    base = tmp_path / "workspaces"
    base.mkdir()
    async with ProjectRegistry(tmp_path / "projects.json") as registry:
        project = await registry.create_project("Proyecto Force", base)
    root = Path(project.root_path)

    input_dir = tmp_path / "input"
    input_dir.mkdir()
    _make_native_pdf(input_dir / "native.pdf")

    run_kwargs = {
        "paths": [str(input_dir)],
        "output_dir": root / "Conversión",
        "cache_db": root / "cache.db",
        "folders_json": root / "folders.json",
        "use_ocr": False,
        "use_gpu": False,
    }

    first = await ScanCommand().run(**run_kwargs)
    second = await ScanCommand().run(**run_kwargs)
    third = await ScanCommand().run(force=True, **run_kwargs)

    assert first.new == 1
    assert second.converted == 0
    assert third.new == 1  # cache vaciada: el documento vuelve a contar como nuevo
    assert third.converted == 1  # y se reconvierte de verdad, no solo se recuenta


@pytest.mark.slow
@pytest.mark.asyncio
async def test_scan_command_force_removes_output_of_removed_file(tmp_path) -> None:
    """Un fichero presente en la cache anterior pero eliminado antes del rescan
    forzado deja de generar output huerfano en `output_dir` (REQ nuevo: reset completo)."""
    base = tmp_path / "workspaces"
    base.mkdir()
    async with ProjectRegistry(tmp_path / "projects.json") as registry:
        project = await registry.create_project("Proyecto Force Orphan", base)
    root = Path(project.root_path)

    input_dir = tmp_path / "input"
    input_dir.mkdir()
    stale_path = input_dir / "stale.pdf"
    _make_native_pdf(stale_path)

    run_kwargs = {
        "paths": [str(input_dir)],
        "output_dir": root / "Conversión",
        "cache_db": root / "cache.db",
        "folders_json": root / "folders.json",
        "use_ocr": False,
        "use_gpu": False,
    }
    await ScanCommand().run(**run_kwargs)

    generated = list((root / "Conversión").rglob("stale.md"))
    assert len(generated) == 1

    stale_path.unlink()  # el fichero fuente desaparece antes del rescan forzado

    summary = await ScanCommand().run(force=True, **run_kwargs)

    assert summary.scanned == 0
    assert not generated[0].exists()  # el output huerfano se borro


@pytest.mark.asyncio
async def test_delete_orphaned_outputs_removes_stale_artifacts_and_ignores_missing(tmp_path) -> None:
    """Cubre `ScanCommand._delete_orphaned_outputs` sin pasar por Docling: los
    artefactos se crean a mano en la ubicacion que `resolve_output_paths` calcularia."""
    output_dir = tmp_path / "Conversión"
    orphaned_path = str(tmp_path / "input" / "old.pdf")
    kept_path = str(tmp_path / "input" / "kept.pdf")
    never_existed_path = str(tmp_path / "input" / "never-existed.pdf")

    orphaned_md, orphaned_json = DocumentConverter.resolve_output_paths(orphaned_path, output_dir)
    orphaned_md.parent.mkdir(parents=True, exist_ok=True)
    orphaned_md.write_text("stale markdown", encoding="utf-8")
    orphaned_json.write_text("{}", encoding="utf-8")

    kept_md, kept_json = DocumentConverter.resolve_output_paths(kept_path, output_dir)
    kept_md.parent.mkdir(parents=True, exist_ok=True)
    kept_md.write_text("kept markdown", encoding="utf-8")
    kept_json.write_text("{}", encoding="utf-8")

    await ScanCommand._delete_orphaned_outputs({orphaned_path, never_existed_path}, output_dir)

    assert not orphaned_md.exists()
    assert not orphaned_json.exists()
    assert kept_md.exists()
    assert kept_json.exists()


@pytest.mark.slow
@pytest.mark.asyncio
async def test_scan_command_ocr_pending_then_processed_on_next_run(tmp_path) -> None:
    base = tmp_path / "workspaces"
    base.mkdir()
    async with ProjectRegistry(tmp_path / "projects.json") as registry:
        project = await registry.create_project("Proyecto OCR", base)
    root = Path(project.root_path)

    input_dir = tmp_path / "input"
    input_dir.mkdir()
    _make_scanned_pdf(input_dir / "scanned.pdf")

    base_kwargs = {
        "paths": [str(input_dir)],
        "output_dir": root / "Conversión",
        "cache_db": root / "cache.db",
        "folders_json": root / "folders.json",
        "use_gpu": False,
    }

    first = await ScanCommand().run(use_ocr=False, **base_kwargs)
    assert first.new == 1
    assert first.ocr_required == 1
    assert first.ocr_processed == 0

    from doc_organize.cache import CacheManager

    async with CacheManager(root / "cache.db") as cache:
        entries = await cache.load_cache()
    file_path = str((input_dir / "scanned.pdf").resolve())
    assert entries[file_path].conversion_status == ConversionStatus.OCR_PENDING

    # Segunda pasada: el documento no cambio (mismo hash), pero --use-ocr debe
    # recogerlo igualmente porque seguia OCR_PENDING en cache.
    second = await ScanCommand().run(use_ocr=True, **base_kwargs)
    assert second.new == 0
    assert second.unchanged == 1
    assert second.ocr_processed == 1

    async with CacheManager(root / "cache.db") as cache:
        entries = await cache.load_cache()
    assert entries[file_path].conversion_status == ConversionStatus.SUCCESS


@pytest.mark.slow
@pytest.mark.asyncio
async def test_scan_command_deduplicate_moves_exact_duplicate(tmp_path) -> None:
    base = tmp_path / "workspaces"
    base.mkdir()
    async with ProjectRegistry(tmp_path / "projects.json") as registry:
        project = await registry.create_project("Proyecto Dedup", base)
    root = Path(project.root_path)

    input_dir = tmp_path / "input"
    input_dir.mkdir()
    _make_native_pdf(input_dir / "original.pdf")
    # Copia exacta (mismo contenido) con otro nombre -> duplicado exacto.
    (input_dir / "copia.pdf").write_bytes((input_dir / "original.pdf").read_bytes())

    summary = await ScanCommand().deduplicate(
        paths=[str(input_dir)],
        duplicates_dir=root / "duplicados",
        folders_json=root / "folders.json",
    )

    assert summary.groups_found == 1
    assert summary.moved == 1
    assert summary.duration_seconds >= 0.0
    assert (root / "duplicados" / "DEDUP_REPORT.json").exists()
    assert (root / "folders.json").exists()  # para que web/routes/duplicates.py funcione sin haber escaneado

    # `run()` ya no deduplica: la copia se movió por `deduplicate()`, así que
    # el escaneo posterior ya solo encuentra el canónico.
    scan_summary = await ScanCommand().run(
        paths=[str(input_dir)],
        output_dir=root / "Conversión",
        cache_db=root / "cache.db",
        folders_json=root / "folders.json",
        use_ocr=False,
        use_gpu=False,
    )
    assert scan_summary.scanned == 1
    assert scan_summary.converted == 1


@pytest.mark.asyncio
async def test_scan_command_deduplicate_no_duplicates_returns_zero(tmp_path) -> None:
    base = tmp_path / "workspaces"
    base.mkdir()
    async with ProjectRegistry(tmp_path / "projects.json") as registry:
        project = await registry.create_project("Proyecto Sin Dedup", base)
    root = Path(project.root_path)

    input_dir = tmp_path / "input"
    input_dir.mkdir()
    (input_dir / "unico.pdf").write_bytes(b"contenido-unico")

    summary = await ScanCommand().deduplicate(
        paths=[str(input_dir)],
        duplicates_dir=root / "duplicados",
        folders_json=root / "folders.json",
    )

    assert summary.groups_found == 0
    assert summary.moved == 0
    assert summary.warnings == []
    # Se registra igual en el historico (histórico completo de cada ejecución de
    # "Buscar duplicados", no solo de las que movieron algo).
    assert (root / "duplicados" / "DEDUP_REPORT.json").exists()
    history_lines = (root / "duplicados" / "DEDUP_HISTORY.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(history_lines) == 1


# ===== main() end-to-end (usa --registry-path para no tocar ~/.doc_organize/) =====


def test_main_project_create_and_list(tmp_path, capsys) -> None:
    registry_path = str(tmp_path / "projects.json")
    base = tmp_path / "workspaces"
    base.mkdir()

    exit_code = main(["project", "create", "Mi Proyecto", "--location", str(base), "--registry-path", registry_path])
    assert exit_code == 0
    assert "Mi Proyecto" in capsys.readouterr().out
    assert (base / "Mi Proyecto").is_dir()

    exit_code = main(["project", "list", "--registry-path", registry_path])
    assert exit_code == 0
    assert "Mi Proyecto" in capsys.readouterr().out


def test_main_project_list_empty(tmp_path, capsys) -> None:
    exit_code = main(["project", "list", "--registry-path", str(tmp_path / "projects.json")])
    assert exit_code == 0
    assert "No hay proyectos registrados" in capsys.readouterr().out


def test_main_project_create_invalid_name_reports_error(tmp_path, capsys) -> None:
    base = tmp_path / "workspaces"
    base.mkdir()

    exit_code = main(["project", "create", "CON", "--location", str(base), "--registry-path", str(tmp_path / "projects.json")])

    assert exit_code == 1
    assert "Error" in capsys.readouterr().err
    assert list(base.iterdir()) == []


@pytest.mark.slow
def test_main_scan_end_to_end(tmp_path, capsys) -> None:
    registry_path = str(tmp_path / "projects.json")
    base = tmp_path / "workspaces"
    base.mkdir()
    main(["project", "create", "Proyecto CLI", "--location", str(base), "--registry-path", registry_path])
    capsys.readouterr()

    input_dir = tmp_path / "input"
    input_dir.mkdir()
    _make_native_pdf(input_dir / "native.pdf")

    exit_code = main(
        [
            "scan",
            "--paths",
            str(input_dir),
            "--project",
            "Proyecto CLI",
            "--registry-path",
            registry_path,
        ]
    )

    assert exit_code == 0
    output = capsys.readouterr().out
    assert "Documentos escaneados: 1" in output
    assert "Convertidos: 1" in output
    assert "Tiempo de ejecución:" in output
    assert list((base / "Proyecto CLI" / "Conversión").rglob("native.md"))

    # El histórico de duración de ejecuciones (nueva funcionalidad) registra
    # esta ejecución completa, con la misma cuenta de documentos que el resumen.
    history_path = base / "Proyecto CLI" / SCAN_HISTORY_FOLDER_NAME / SCAN_HISTORY_JSONL_NAME
    assert history_path.is_file()
    history_entry = json.loads(history_path.read_text(encoding="utf-8").strip())
    assert history_entry["completed"] is True
    assert history_entry["total_scanned"] == 1
    assert history_entry["duration_seconds"] > 0


def test_main_scan_rejects_include_audio_video_without_av_support(tmp_path, capsys, monkeypatch) -> None:
    """Pre-check bloqueante (sesion 'soporte de formatos docling'): sin el extra
    `av`/`ffmpeg`, `--include-audio-video` falla ANTES de tocar `cache.db`, con
    un mensaje de qué falta — en vez de fallar tarde, archivo por archivo, dentro
    del pipeline de conversion."""
    not_ready = AvStatus(asr_installed=False, ffmpeg_installed=False, ready=False, instructions="Falta instalar cosas específicas.")
    monkeypatch.setattr("doc_organize.main.detect_av_status", lambda: not_ready)

    registry_path = str(tmp_path / "projects.json")
    base = tmp_path / "workspaces"
    base.mkdir()
    main(["project", "create", "Proyecto CLI AV", "--location", str(base), "--registry-path", registry_path])
    capsys.readouterr()

    input_dir = tmp_path / "input"
    input_dir.mkdir()

    exit_code = main(
        [
            "scan",
            "--paths",
            str(input_dir),
            "--project",
            "Proyecto CLI AV",
            "--registry-path",
            registry_path,
            "--include-audio-video",
        ]
    )

    assert exit_code == 1
    assert "Falta instalar cosas específicas." in capsys.readouterr().err
    assert not (base / "Proyecto CLI AV" / "cache.db").exists()


@pytest.mark.slow
def test_main_scan_force_end_to_end(tmp_path, capsys) -> None:
    registry_path = str(tmp_path / "projects.json")
    base = tmp_path / "workspaces"
    base.mkdir()
    main(["project", "create", "Proyecto CLI Force", "--location", str(base), "--registry-path", registry_path])
    capsys.readouterr()

    input_dir = tmp_path / "input"
    input_dir.mkdir()
    _make_native_pdf(input_dir / "native.pdf")

    scan_args = ["scan", "--paths", str(input_dir), "--project", "Proyecto CLI Force", "--registry-path", registry_path]
    main(scan_args)
    capsys.readouterr()

    main(scan_args)  # sin --force: documento sin cambios, no se reconvierte
    assert "Convertidos: 0" in capsys.readouterr().out

    exit_code = main([*scan_args, "--force"])
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "Convertidos: 1" in output


def test_main_deduplicate_end_to_end(tmp_path, capsys) -> None:
    """El CLI también puede deduplicar (independiente de `scan`, ver PLAN de la
    sesión que separó ambas acciones)."""
    registry_path = str(tmp_path / "projects.json")
    base = tmp_path / "workspaces"
    base.mkdir()
    main(["project", "create", "Proyecto CLI Dedup", "--location", str(base), "--registry-path", registry_path])
    capsys.readouterr()

    input_dir = tmp_path / "input"
    input_dir.mkdir()
    original = input_dir / "original.pdf"
    original.write_bytes(b"contenido-duplicado")
    (input_dir / "copia.pdf").write_bytes(original.read_bytes())

    exit_code = main(
        [
            "deduplicate",
            "--paths",
            str(input_dir),
            "--project",
            "Proyecto CLI Dedup",
            "--registry-path",
            registry_path,
        ]
    )

    assert exit_code == 0
    output = capsys.readouterr().out
    assert "Grupos de duplicados detectados: 1" in output
    assert "Archivos movidos a duplicados/: 1" in output
    assert (base / "Proyecto CLI Dedup" / "duplicados" / "DEDUP_REPORT.json").exists()


# ===== `web` subcommand =====
# Revision 8 (SS2.7.2): ya no hay un DOC_ORGANIZE_API_TOKEN compartido que exigir al
# arrancar -- la autenticacion es multi-usuario (login via /login), asi que el
# proceso arranca igual en loopback y en no-loopback; sin usuarios provisionados,
# el host no-loopback simplemente queda inaccesible (nadie puede autenticarse).


def test_main_web_starts_on_non_loopback_without_any_provisioned_user(tmp_path, monkeypatch) -> None:
    calls: list[dict] = []
    monkeypatch.setattr("uvicorn.run", lambda app, host, port: calls.append({"app": app, "host": host, "port": port}))

    exit_code = main(
        [
            "web",
            "--host",
            "0.0.0.0",
            "--port",
            "9000",
            "--registry-path",
            str(tmp_path / "p.json"),
            "--auth-db-path",
            str(tmp_path / "auth.db"),
        ]
    )

    assert exit_code == 0
    assert len(calls) == 1
    assert calls[0]["host"] == "0.0.0.0"
    assert calls[0]["port"] == 9000


def test_main_web_starts_on_loopback(tmp_path, monkeypatch) -> None:
    calls: list[dict] = []
    monkeypatch.setattr("uvicorn.run", lambda app, host, port: calls.append({"app": app, "host": host, "port": port}))

    exit_code = main(
        ["web", "--registry-path", str(tmp_path / "p.json"), "--auth-db-path", str(tmp_path / "auth.db")]
    )

    assert exit_code == 0
    assert len(calls) == 1
    assert calls[0]["host"] == "127.0.0.1"


# ===== `tenant create` / `user create` subcommands (revision 8, SS2.7.2, sub-paso 4/4) =====


def test_build_parser_tenant_create_requires_name() -> None:
    parser = build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["tenant", "create"])


def test_build_parser_user_create_requires_tenant_and_username() -> None:
    parser = build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["user", "create", "alice"])  # falta --tenant


def test_main_tenant_create(tmp_path, capsys) -> None:
    exit_code = main(["tenant", "create", "Acme Corp", "--auth-db-path", str(tmp_path / "auth.db")])

    assert exit_code == 0
    output = capsys.readouterr().out
    assert "acme-corp" in output
    assert "Acme Corp" in output


def test_main_tenant_create_duplicate_reports_error(tmp_path, capsys) -> None:
    auth_db_path = str(tmp_path / "auth.db")
    main(["tenant", "create", "Acme Corp", "--auth-db-path", auth_db_path])

    exit_code = main(["tenant", "create", "Acme Corp", "--auth-db-path", auth_db_path])

    assert exit_code == 1
    assert "Error" in capsys.readouterr().err


def test_main_user_create_prompts_password_via_getpass_not_cli_arg(tmp_path, monkeypatch, capsys) -> None:
    auth_db_path = str(tmp_path / "auth.db")
    main(["tenant", "create", "Acme Corp", "--auth-db-path", auth_db_path])

    prompts: list[str] = []
    monkeypatch.setattr("doc_organize.main.getpass.getpass", lambda prompt="": (prompts.append(prompt), "s3cr3t-password")[1])

    exit_code = main(["user", "create", "alice", "--tenant", "acme-corp", "--auth-db-path", auth_db_path])

    assert exit_code == 0
    assert len(prompts) == 1  # la contraseña se pidio interactivamente, no vino de sys.argv
    output = capsys.readouterr().out
    assert "alice" in output
    assert "acme-corp" in output


def test_main_user_create_unknown_tenant_reports_error(tmp_path, monkeypatch, capsys) -> None:
    monkeypatch.setattr("doc_organize.main.getpass.getpass", lambda prompt="": "s3cr3t-password")

    exit_code = main(["user", "create", "alice", "--tenant", "no-existe", "--auth-db-path", str(tmp_path / "auth.db")])

    assert exit_code == 1
    assert "Error" in capsys.readouterr().err


def test_main_user_create_then_authenticate_succeeds(tmp_path, monkeypatch) -> None:
    from doc_organize.auth import AuthStore

    auth_db_path = tmp_path / "auth.db"
    monkeypatch.setattr("doc_organize.main.getpass.getpass", lambda prompt="": "s3cr3t-password")

    main(["tenant", "create", "Acme Corp", "--auth-db-path", str(auth_db_path)])
    main(["user", "create", "alice", "--tenant", "acme-corp", "--auth-db-path", str(auth_db_path)])

    import asyncio

    async def _authenticate() -> object:
        async with AuthStore(auth_db_path) as store:
            return await store.authenticate("acme-corp", "alice", "s3cr3t-password")

    user = asyncio.run(_authenticate())
    assert user is not None
    assert user.username == "alice"
