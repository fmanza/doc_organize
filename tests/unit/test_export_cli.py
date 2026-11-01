"""CLI `doc_organize export zip | cache-xlsx | errors-xlsx` (L-7)."""

import asyncio
import json
import zipfile

from pathlib import Path

import openpyxl
import pytest

from doc_organize.cache import CacheManager
from doc_organize.core.models import CacheEntry, ConversionStatus, DocumentStatus, Project
from doc_organize.main import build_parser, main
from doc_organize.projects import ProjectLayout, ProjectRegistry


async def _seed(layout: ProjectLayout, cache_db: Path | None = None) -> None:
    (layout.conversion_dir / "docs").mkdir(parents=True, exist_ok=True)
    (layout.conversion_dir / "docs" / "informe.md").write_text("# Informe", encoding="utf-8")
    target = cache_db or layout.cache_db
    target.parent.mkdir(parents=True, exist_ok=True)
    async with CacheManager(target) as cache:
        await cache.save_entries(
            [
                CacheEntry(
                    file_path=f"/repo/{target.parent.name}.pdf",
                    sha256_hash="c" * 64,
                    timestamp=1_700_000_000.0,
                    status=DocumentStatus.NEW,
                    conversion_status=ConversionStatus.ERROR,
                    error_message="Documento cifrado",
                )
            ]
        )


def test_parser_requires_output_or_preview_for_zip() -> None:
    with pytest.raises(SystemExit):
        build_parser().parse_args(["export", "zip", "--output-root", "x"])
    with pytest.raises(SystemExit):
        build_parser().parse_args(["export", "zip", "--output-root", "x", "--preview", "-o", "a.zip"])


def test_export_zip_and_preview_from_explicit_roots(tmp_path, capsys) -> None:
    layout = ProjectLayout(tmp_path / "salidas", state_root=tmp_path / "estado")
    asyncio.run(_seed(layout))
    destination = tmp_path / "export.zip"
    roots = ["--output-root", str(layout.output_root), "--state-root", str(layout.state_dir)]

    assert main(["export", "zip", *roots, "--preview"]) == 0
    preview_line = capsys.readouterr().out
    assert main(["export", "zip", *roots, "-o", str(destination)]) == 0

    with zipfile.ZipFile(destination) as zip_file:
        assert zip_file.namelist() == ["Conversión/docs/informe.md", "cache_export.json"]
        assert json.loads(zip_file.read("cache_export.json"))["total_entries"] == 1
        total = sum(info.file_size for info in zip_file.infolist())
    assert f"2 ficheros ({total} bytes" in preview_line


async def _create_project(registry_path: Path, location: Path) -> Project:
    async with ProjectRegistry(registry_path) as registry:
        return await registry.create_project("Proyecto CLI", location)


def test_export_xlsx_from_project_with_several_caches_and_logs(tmp_path) -> None:
    registry_path = tmp_path / "projects.json"
    project = asyncio.run(_create_project(registry_path, tmp_path))
    layout = ProjectLayout.for_project(project)
    cache_a, cache_b = tmp_path / "origen_a" / "cache.db", tmp_path / "origen_b" / "cache.db"
    asyncio.run(_seed(layout, cache_a))
    asyncio.run(_seed(layout, cache_b))
    log = tmp_path / "errores.jsonl"
    log.write_text(
        json.dumps(
            {
                "scan_run_id": "r1",
                "timestamp": "2026-11-01T00:00:00+00:00",
                "total_scanned": 1,
                "entries": [{"file_path": "/x.pdf", "error_message": "e", "error_retry_count": 1}],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    common = ["--registry-path", str(registry_path), "--project", project.name, "--cache-file", str(cache_a), str(cache_b)]

    assert main(["export", "cache-xlsx", *common, "-o", str(tmp_path / "cache.xlsx")]) == 0
    assert main(["export", "errors-xlsx", *common, "--errors-log", str(log), "-o", str(tmp_path / "errores.xlsx")]) == 0

    cache_rows = list(openpyxl.load_workbook(tmp_path / "cache.xlsx")["Cache"].iter_rows(values_only=True))
    assert [row[2] for row in cache_rows[1:]] == ["/repo/origen_a.pdf", "/repo/origen_b.pdf"]
    errors = openpyxl.load_workbook(tmp_path / "errores.xlsx")
    assert errors["Estado actual"].max_row == 3
    assert errors["Histórico"]["A2"].value == "r1"


@pytest.mark.parametrize(
    ("args", "message"),
    [
        (["export", "cache-xlsx", "-o", "x.xlsx"], "Indica --project o --output-root"),
        (["export", "cache-xlsx", "--project", "p", "--output-root", "r", "-o", "x.xlsx"], "no ambos"),
    ],
)
def test_export_requires_one_source(args, message, capsys) -> None:
    assert main(args) == 1
    assert message in capsys.readouterr().err


def test_export_reports_missing_destination_folder(tmp_path, capsys) -> None:
    assert main(["export", "zip", "--output-root", str(tmp_path), "-o", str(tmp_path / "no" / "export.zip")]) == 1
    assert "No existe la carpeta de destino" in capsys.readouterr().err
