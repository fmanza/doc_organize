"""Tests del Cache Viewer (Fase D-2c, §2.7.4, sub-paso 1/3)."""

import httpx
import pytest

from doc_organize.cache import CacheManager
from doc_organize.core.constants import DEFAULT_CACHE_DB_NAME
from doc_organize.core.models import CacheEntry, ConversionStatus, DocumentStatus
from doc_organize.projects import ProjectRegistry
from doc_organize.web import create_app


def _client(app, base_url: str = "http://testserver") -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=base_url)


async def _create_project(tmp_path, registry_path, name: str = "Proyecto Cache", tenant_id: str = "default"):
    base = tmp_path / "workspaces"
    base.mkdir(exist_ok=True)
    async with ProjectRegistry(registry_path) as registry:
        return await registry.create_project(name, base, tenant_id=tenant_id)


@pytest.mark.asyncio
async def test_cache_viewer_page_loads_when_never_scanned(tmp_path) -> None:
    registry_path = tmp_path / "projects.json"
    project = await _create_project(tmp_path, registry_path)
    app = create_app(registry_path=registry_path)

    async with _client(app) as client:
        response = await client.get(f"/projects/{project.name}/cache")

    assert response.status_code == 200
    assert "No hay entradas en caché" in response.text


@pytest.mark.asyncio
async def test_cache_viewer_page_404_for_missing_project(tmp_path) -> None:
    app = create_app(registry_path=tmp_path / "projects.json")
    async with _client(app) as client:
        response = await client.get("/projects/No Existe/cache")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_cache_api_returns_saved_entries(tmp_path) -> None:
    registry_path = tmp_path / "projects.json"
    project = await _create_project(tmp_path, registry_path)
    cache_db = tmp_path / "workspaces" / project.name / DEFAULT_CACHE_DB_NAME
    async with CacheManager(cache_db) as cache:
        await cache.save_entries(
            [
                CacheEntry(
                    file_path="/repo/docs/report.pdf",
                    sha256_hash="a" * 64,
                    timestamp=1_700_000_000.0,
                    status=DocumentStatus.NEW,
                    conversion_status=ConversionStatus.SUCCESS,
                )
            ]
        )

    app = create_app(registry_path=registry_path)
    async with _client(app) as client:
        response = await client.get(f"/api/projects/{project.name}/cache")

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 1
    assert payload["entries"][0]["file_path"] == "/repo/docs/report.pdf"
    assert payload["entries"][0]["status"] == "new"
    assert payload["entries"][0]["conversion_status"] == "success"


@pytest.mark.asyncio
async def test_cache_api_404_for_missing_project(tmp_path) -> None:
    app = create_app(registry_path=tmp_path / "projects.json")
    async with _client(app) as client:
        response = await client.get("/api/projects/No Existe/cache")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_cache_api_tenant_isolation(tmp_path) -> None:
    registry_path = tmp_path / "projects.json"
    acme_project = await _create_project(tmp_path, registry_path, name="Proyecto Acme", tenant_id="acme-corp")
    await _create_project(tmp_path, registry_path, name="Proyecto Globex", tenant_id="globex-inc")

    # En loopback (sin sesion), get_tenant_id() siempre resuelve "default" -- ninguno
    # de los dos proyectos (creados en tenants reales) es visible.
    app = create_app(registry_path=registry_path)
    async with _client(app) as client:
        response = await client.get(f"/api/projects/{acme_project.name}/cache")

    assert response.status_code == 404
