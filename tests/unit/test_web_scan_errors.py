"""Tests de la pestaña Errores de Escaneo (estado actual + histórico por ejecución)."""

import json

from pathlib import Path

import httpx
import pytest

from doc_organize.cache import CacheManager
from doc_organize.core.constants import DEFAULT_CACHE_DB_NAME, MAX_AUTO_ERROR_RETRIES
from doc_organize.core.models import CacheEntry, ConversionStatus, DocumentStatus
from doc_organize.projects import ProjectRegistry
from doc_organize.web import create_app


def _client(app, base_url: str = "http://testserver") -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=base_url)


async def _create_project(tmp_path, registry_path, name: str = "Proyecto Errores", tenant_id: str = "default"):
    base = tmp_path / "workspaces"
    base.mkdir(exist_ok=True)
    async with ProjectRegistry(registry_path) as registry:
        return await registry.create_project(name, base, tenant_id=tenant_id)


def _write_error_history(project_root: Path, *reports: dict) -> None:
    history_dir = project_root / "errores_escaneo"
    history_dir.mkdir(parents=True, exist_ok=True)
    lines = "\n".join(json.dumps(report) for report in reports)
    (history_dir / "SCAN_ERRORS_HISTORY.jsonl").write_text(lines + "\n", encoding="utf-8")


@pytest.mark.asyncio
async def test_scan_errors_page_404_for_missing_project(tmp_path) -> None:
    app = create_app(registry_path=tmp_path / "projects.json")
    async with _client(app) as client:
        response = await client.get("/projects/No Existe/scan-errors")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_scan_errors_page_empty_state(tmp_path) -> None:
    registry_path = tmp_path / "projects.json"
    project = await _create_project(tmp_path, registry_path)
    app = create_app(registry_path=registry_path)

    async with _client(app) as client:
        response = await client.get(f"/projects/{project.name}/scan-errors")

    assert response.status_code == 200
    assert "No hay ficheros en error en este momento." in response.text
    assert "Todavía no se ha registrado ningún error de escaneo." in response.text


@pytest.mark.asyncio
async def test_scan_errors_page_shows_current_cache_errors(tmp_path) -> None:
    registry_path = tmp_path / "projects.json"
    project = await _create_project(tmp_path, registry_path)
    cache_db = tmp_path / "workspaces" / project.name / DEFAULT_CACHE_DB_NAME
    async with CacheManager(cache_db) as cache:
        await cache.save_entries(
            [
                CacheEntry(
                    file_path="/repo/docs/roto.pdf",
                    sha256_hash="a" * 64,
                    timestamp=1_700_000_000.0,
                    status=DocumentStatus.NEW,
                    conversion_status=ConversionStatus.ERROR,
                    error_message="Documento cifrado",
                    error_retry_count=1,
                ),
                CacheEntry(
                    file_path="/repo/docs/ok.pdf",
                    sha256_hash="b" * 64,
                    timestamp=1_700_000_100.0,
                    status=DocumentStatus.NEW,
                    conversion_status=ConversionStatus.SUCCESS,
                ),
            ]
        )

    app = create_app(registry_path=registry_path)
    async with _client(app) as client:
        response = await client.get(f"/projects/{project.name}/scan-errors")

    assert response.status_code == 200
    assert "roto.pdf" in response.text
    assert "Documento cifrado" in response.text
    assert "ok.pdf" not in response.text  # exito, no aparece en errores
    assert "Se reintentará en el próximo escaneo" in response.text


@pytest.mark.asyncio
async def test_scan_errors_page_marks_capped_entries(tmp_path) -> None:
    registry_path = tmp_path / "projects.json"
    project = await _create_project(tmp_path, registry_path)
    cache_db = tmp_path / "workspaces" / project.name / DEFAULT_CACHE_DB_NAME
    async with CacheManager(cache_db) as cache:
        await cache.save_entries(
            [
                CacheEntry(
                    file_path="/repo/docs/irrecuperable.pdf",
                    sha256_hash="c" * 64,
                    timestamp=1_700_000_000.0,
                    status=DocumentStatus.UNCHANGED,
                    conversion_status=ConversionStatus.ERROR,
                    error_message="Fichero cifrado con contraseña",
                    error_retry_count=MAX_AUTO_ERROR_RETRIES,
                )
            ]
        )

    app = create_app(registry_path=registry_path)
    async with _client(app) as client:
        response = await client.get(f"/projects/{project.name}/scan-errors")

    assert response.status_code == 200
    assert "Límite alcanzado (requiere forzar rescan)" in response.text


@pytest.mark.asyncio
async def test_scan_errors_page_shows_history_grouped_by_run_most_recent_first(tmp_path) -> None:
    registry_path = tmp_path / "projects.json"
    project = await _create_project(tmp_path, registry_path)
    project_root = tmp_path / "workspaces" / project.name

    _write_error_history(
        project_root,
        {
            "scan_run_id": "run-1",
            "timestamp": "2026-08-01T10:00:00+00:00",
            "total_scanned": 10,
            "entries": [{"file_path": "/repo/a.pdf", "error_message": "Error A", "error_retry_count": 1, "capped": False}],
        },
        {
            "scan_run_id": "run-2",
            "timestamp": "2026-08-02T10:00:00+00:00",
            "total_scanned": 12,
            "entries": [
                {"file_path": "/repo/b.pdf", "error_message": "Error B", "error_retry_count": 2, "capped": False},
                {"file_path": "/repo/c.pdf", "error_message": "Error C", "error_retry_count": 3, "capped": True},
            ],
        },
    )

    app = create_app(registry_path=registry_path)
    async with _client(app) as client:
        response = await client.get(f"/projects/{project.name}/scan-errors?tab=history")

    assert response.status_code == 200
    text = response.text
    assert "2026-08-01T10:00:00+00:00" in text
    assert "2026-08-02T10:00:00+00:00" in text
    assert "a.pdf" in text
    assert "b.pdf" in text
    assert "c.pdf" in text
    assert text.index("2026-08-02T10:00:00+00:00") < text.index("2026-08-01T10:00:00+00:00")


@pytest.mark.asyncio
async def test_scan_errors_page_ignores_corrupted_history_line(tmp_path) -> None:
    registry_path = tmp_path / "projects.json"
    project = await _create_project(tmp_path, registry_path)
    project_root = tmp_path / "workspaces" / project.name
    history_dir = project_root / "errores_escaneo"
    history_dir.mkdir(parents=True)
    valid_report = {
        "scan_run_id": "run-1",
        "timestamp": "2026-08-01T10:00:00+00:00",
        "total_scanned": 1,
        "entries": [{"file_path": "/repo/a.pdf", "error_message": "Error A", "error_retry_count": 1, "capped": False}],
    }
    (history_dir / "SCAN_ERRORS_HISTORY.jsonl").write_text("{linea corrupta\n" + json.dumps(valid_report) + "\n", encoding="utf-8")

    app = create_app(registry_path=registry_path)
    async with _client(app) as client:
        response = await client.get(f"/projects/{project.name}/scan-errors?tab=history")

    assert response.status_code == 200
    assert "a.pdf" in response.text


@pytest.mark.asyncio
async def test_scan_errors_page_tenant_isolation(tmp_path) -> None:
    registry_path = tmp_path / "projects.json"
    project = await _create_project(tmp_path, registry_path, tenant_id="acme-corp")

    app = create_app(registry_path=registry_path)
    async with _client(app) as client:
        response = await client.get(f"/projects/{project.name}/scan-errors")

    assert response.status_code == 404
