"""Tests del Export ZIP (Fase D-2c, §2.7.4, sub-paso 2/3)."""

import io
import json
import zipfile

import httpx
import pytest

from doc_organize.cache import CacheManager
from doc_organize.core.constants import DEFAULT_CACHE_DB_NAME
from doc_organize.core.models import CacheEntry, ConversionStatus, DocumentStatus, SecurityConfig
from doc_organize.projects import ProjectRegistry
from doc_organize.web import create_app


def _client(app, base_url: str = "http://testserver") -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=base_url)


async def _create_project(tmp_path, registry_path, name: str = "Proyecto Export", tenant_id: str = "default"):
    base = tmp_path / "workspaces"
    base.mkdir(exist_ok=True)
    async with ProjectRegistry(registry_path) as registry:
        return await registry.create_project(name, base, tenant_id=tenant_id)


@pytest.mark.asyncio
async def test_export_zip_404_for_missing_project(tmp_path) -> None:
    app = create_app(registry_path=tmp_path / "projects.json")
    async with _client(app) as client:
        response = await client.get("/downloads/projects/No Existe/export.zip")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_export_zip_contains_conversion_and_cache_snapshot(tmp_path) -> None:
    registry_path = tmp_path / "projects.json"
    project = await _create_project(tmp_path, registry_path)
    root = tmp_path / "workspaces" / project.name

    conversion_dir = root / "Conversión" / "docs"
    conversion_dir.mkdir(parents=True)
    (conversion_dir / "report.md").write_text("# Informe", encoding="utf-8")

    cache_db = root / DEFAULT_CACHE_DB_NAME
    async with CacheManager(cache_db) as cache:
        await cache.save_entries(
            [
                CacheEntry(
                    file_path="/repo/docs/report.pdf",
                    sha256_hash="b" * 64,
                    timestamp=1_700_000_000.0,
                    status=DocumentStatus.NEW,
                    conversion_status=ConversionStatus.SUCCESS,
                )
            ]
        )

    app = create_app(registry_path=registry_path)
    async with _client(app) as client:
        response = await client.get(f"/downloads/projects/{project.name}/export.zip")

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/zip"

    with zipfile.ZipFile(io.BytesIO(response.content)) as zip_file:
        names = set(zip_file.namelist())
        assert "cache_export.json" in names
        assert any(name.endswith("docs/report.md") for name in names)

        snapshot = json.loads(zip_file.read("cache_export.json"))
        assert snapshot["total_entries"] == 1
        assert snapshot["new_files"] == ["/repo/docs/report.pdf"]


@pytest.mark.asyncio
async def test_export_zip_includes_dedup_report_when_present(tmp_path) -> None:
    registry_path = tmp_path / "projects.json"
    project = await _create_project(tmp_path, registry_path)
    root = tmp_path / "workspaces" / project.name

    duplicados_dir = root / "duplicados"
    duplicados_dir.mkdir(parents=True)
    (duplicados_dir / "DEDUP_REPORT.json").write_text(json.dumps({"groups": []}), encoding="utf-8")

    app = create_app(registry_path=registry_path)
    async with _client(app) as client:
        response = await client.get(f"/downloads/projects/{project.name}/export.zip")

    with zipfile.ZipFile(io.BytesIO(response.content)) as zip_file:
        assert any(name.endswith("duplicados/DEDUP_REPORT.json") for name in zip_file.namelist())


@pytest.mark.asyncio
async def test_export_zip_works_when_never_scanned(tmp_path) -> None:
    # Sin Conversion/ ni cache.db previos: el ZIP igual se genera, solo con cache_export.json vacio.
    registry_path = tmp_path / "projects.json"
    project = await _create_project(tmp_path, registry_path)

    app = create_app(registry_path=registry_path)
    async with _client(app) as client:
        response = await client.get(f"/downloads/projects/{project.name}/export.zip")

    assert response.status_code == 200
    with zipfile.ZipFile(io.BytesIO(response.content)) as zip_file:
        snapshot = json.loads(zip_file.read("cache_export.json"))
        assert snapshot["total_entries"] == 0


@pytest.mark.asyncio
async def test_export_zip_tenant_isolation(tmp_path) -> None:
    registry_path = tmp_path / "projects.json"
    project = await _create_project(tmp_path, registry_path, tenant_id="acme-corp")

    # Loopback (sin sesion) -> get_tenant_id() resuelve "default", distinto del tenant real.
    app = create_app(registry_path=registry_path)
    async with _client(app) as client:
        response = await client.get(f"/downloads/projects/{project.name}/export.zip")

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_export_zip_requires_session_when_non_loopback(tmp_path) -> None:
    registry_path = tmp_path / "projects.json"
    project = await _create_project(tmp_path, registry_path)
    security = SecurityConfig(bind_host="0.0.0.0")
    app = create_app(security=security, registry_path=registry_path, auth_db_path=tmp_path / "auth.db")

    async with _client(app) as client:
        response = await client.get(f"/downloads/projects/{project.name}/export.zip")

    assert response.status_code == 401
