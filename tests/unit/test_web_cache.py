"""Tests de la API JSON de Caché (Fase D-2c, §2.7.4, sub-paso 1/3).

La página HTML del Cache Viewer se fusionó en la pestaña "Caché" de la página
Escanear (reestructuración de navegación) — sus tests viven ahora en
`test_web_scan.py`. Este fichero conserva solo los tests del endpoint JSON
`/api/projects/{name}/cache`, que no cambió.
"""

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
    assert payload["entries"][0]["error_message"] is None


@pytest.mark.asyncio
async def test_cache_api_returns_error_message_for_failed_conversion(tmp_path) -> None:
    registry_path = tmp_path / "projects.json"
    project = await _create_project(tmp_path, registry_path)
    cache_db = tmp_path / "workspaces" / project.name / DEFAULT_CACHE_DB_NAME
    async with CacheManager(cache_db) as cache:
        await cache.save_entries(
            [
                CacheEntry(
                    file_path="/repo/docs/roto.pdf",
                    sha256_hash="b" * 64,
                    timestamp=1_700_000_000.0,
                    status=DocumentStatus.UNCHANGED,
                    conversion_status=ConversionStatus.ERROR,
                    error_message="Documento cifrado, no se pudo abrir",
                )
            ]
        )

    app = create_app(registry_path=registry_path)
    async with _client(app) as client:
        response = await client.get(f"/api/projects/{project.name}/cache")

    assert response.status_code == 200
    entry = response.json()["entries"][0]
    assert entry["conversion_status"] == "error"
    assert entry["error_message"] == "Documento cifrado, no se pudo abrir"


@pytest.mark.asyncio
async def test_cache_api_404_for_missing_project(tmp_path) -> None:
    app = create_app(registry_path=tmp_path / "projects.json")
    async with _client(app) as client:
        response = await client.get("/api/projects/No Existe/cache")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_cache_api_still_returns_all_entries_unpaginated(tmp_path) -> None:
    # Regresion: la ruta HTML pagina (pestaña Caché de Escanear), pero el contrato
    # del endpoint JSON (usado potencialmente por herramientas externas) no cambia.
    registry_path = tmp_path / "projects.json"
    project = await _create_project(tmp_path, registry_path)
    cache_db = tmp_path / "workspaces" / project.name / DEFAULT_CACHE_DB_NAME
    async with CacheManager(cache_db) as cache:
        await cache.save_entries(
            [
                CacheEntry(
                    file_path=f"/repo/doc-{i:03d}.pdf",
                    sha256_hash="a" * 64,
                    timestamp=1_700_000_000.0,
                    status=DocumentStatus.NEW,
                    conversion_status=None,
                )
                for i in range(60)
            ]
        )

    app = create_app(registry_path=registry_path)
    async with _client(app) as client:
        response = await client.get(f"/api/projects/{project.name}/cache")

    payload = response.json()
    assert payload["total"] == 60
    assert len(payload["entries"]) == 60


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
