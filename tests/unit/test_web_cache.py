"""Tests del Cache Viewer (Fase D-2c, §2.7.4, sub-paso 1/3)."""

import re

from pathlib import Path

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
async def test_cache_viewer_page_shows_search_box_and_folder_column(tmp_path) -> None:
    # Misma mejora de visualizacion aplicada antes a "Revisar Duplicados": la tabla
    # separa carpeta y nombre de archivo, y ofrece un buscador (ahora server-side,
    # via GET ?q=) para filtrar por nombre o carpeta.
    registry_path = tmp_path / "projects.json"
    project = await _create_project(tmp_path, registry_path)
    cache_db = tmp_path / "workspaces" / project.name / DEFAULT_CACHE_DB_NAME
    file_path = str(tmp_path / "docs" / "report.pdf")
    async with CacheManager(cache_db) as cache:
        await cache.save_entries(
            [
                CacheEntry(
                    file_path=file_path,
                    sha256_hash="a" * 64,
                    timestamp=1_700_000_000.0,
                    status=DocumentStatus.NEW,
                    conversion_status=ConversionStatus.SUCCESS,
                )
            ]
        )

    app = create_app(registry_path=registry_path)
    async with _client(app) as client:
        response = await client.get(f"/projects/{project.name}/cache")

    assert response.status_code == 200
    html = response.text
    assert 'id="cache-search"' in html
    assert 'name="q"' in html
    assert re.search(r">report\.pdf<", html)
    # La carpeta debe aparecer como CONTENIDO de una celda de tabla.
    expected_dirname = str(Path(file_path).parent)
    assert re.search(re.escape(expected_dirname).lower() + r"\s*</td>", html.lower())
    # El contador arranca con el total sin filtrar.
    assert "Mostrando 1–1 de 1 entradas." in html


@pytest.mark.asyncio
async def test_cache_viewer_page_paginates_and_navigates_pages(tmp_path) -> None:
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
                for i in range(30)
            ]
        )

    app = create_app(registry_path=registry_path)
    async with _client(app) as client:
        page1 = await client.get(f"/projects/{project.name}/cache", params={"page_size": 25})
        page2 = await client.get(f"/projects/{project.name}/cache", params={"page": 2, "page_size": 25})

    assert page1.status_code == 200
    assert page2.status_code == 200
    assert "Página 1 de 2" in page1.text
    assert "Página 2 de 2" in page2.text
    # La pagina 1 trae las primeras 25 (orden alfabetico por file_path); la pagina 2,
    # las 5 restantes.
    assert "doc-000.pdf" in page1.text
    assert "doc-024.pdf" in page1.text
    assert "doc-025.pdf" not in page1.text
    assert "doc-029.pdf" in page2.text
    assert "doc-000.pdf" not in page2.text


@pytest.mark.asyncio
async def test_cache_viewer_page_clamps_out_of_range_page(tmp_path) -> None:
    registry_path = tmp_path / "projects.json"
    project = await _create_project(tmp_path, registry_path)
    cache_db = tmp_path / "workspaces" / project.name / DEFAULT_CACHE_DB_NAME
    async with CacheManager(cache_db) as cache:
        await cache.save_entries(
            [
                CacheEntry(
                    file_path="/repo/only.pdf",
                    sha256_hash="a" * 64,
                    timestamp=1_700_000_000.0,
                    status=DocumentStatus.NEW,
                    conversion_status=None,
                )
            ]
        )

    app = create_app(registry_path=registry_path)
    async with _client(app) as client:
        response = await client.get(f"/projects/{project.name}/cache", params={"page": 999})

    assert response.status_code == 200
    assert "only.pdf" in response.text


@pytest.mark.asyncio
async def test_cache_viewer_page_search_filters_server_side(tmp_path) -> None:
    registry_path = tmp_path / "projects.json"
    project = await _create_project(tmp_path, registry_path)
    cache_db = tmp_path / "workspaces" / project.name / DEFAULT_CACHE_DB_NAME
    async with CacheManager(cache_db) as cache:
        await cache.save_entries(
            [
                CacheEntry(
                    file_path="/repo/informe.pdf",
                    sha256_hash="a" * 64,
                    timestamp=1_700_000_000.0,
                    status=DocumentStatus.NEW,
                    conversion_status=None,
                ),
                CacheEntry(
                    file_path="/repo/factura.pdf",
                    sha256_hash="b" * 64,
                    timestamp=1_700_000_000.0,
                    status=DocumentStatus.NEW,
                    conversion_status=None,
                ),
            ]
        )

    app = create_app(registry_path=registry_path)
    async with _client(app) as client:
        response = await client.get(f"/projects/{project.name}/cache", params={"q": "informe"})

    assert response.status_code == 200
    html = response.text
    assert "informe.pdf" in html
    assert "factura.pdf" not in html
    assert "Mostrando 1–1 de 1 entradas." in html
    assert '<mark>informe</mark>' in html


@pytest.mark.asyncio
async def test_cache_viewer_page_escapes_malicious_file_path(tmp_path) -> None:
    registry_path = tmp_path / "projects.json"
    project = await _create_project(tmp_path, registry_path)
    cache_db = tmp_path / "workspaces" / project.name / DEFAULT_CACHE_DB_NAME
    malicious_name = "<script>alert(1)</script>.pdf"
    async with CacheManager(cache_db) as cache:
        await cache.save_entries(
            [
                CacheEntry(
                    file_path=f"/repo/{malicious_name}",
                    sha256_hash="a" * 64,
                    timestamp=1_700_000_000.0,
                    status=DocumentStatus.NEW,
                    conversion_status=None,
                )
            ]
        )

    app = create_app(registry_path=registry_path)
    async with _client(app) as client:
        without_search = await client.get(f"/projects/{project.name}/cache")
        with_search = await client.get(f"/projects/{project.name}/cache", params={"q": "script"})

    for response in (without_search, with_search):
        assert response.status_code == 200
        assert "<script>alert(1)</script>" not in response.text
        assert "&lt;" in response.text
        assert "&gt;" in response.text
    # Sin busqueda activa, `highlight` no parte el texto en fragmentos: el escape
    # de todo el nombre debe verse tal cual.
    assert "&lt;script&gt;alert(1)&lt;/script&gt;.pdf" in without_search.text


@pytest.mark.asyncio
async def test_cache_api_still_returns_all_entries_unpaginated(tmp_path) -> None:
    # Regresion: la ruta HTML pasa a paginar, pero el contrato del endpoint JSON
    # (usado potencialmente por herramientas externas) no debe cambiar.
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
async def test_cache_viewer_page_no_search_box_when_no_entries(tmp_path) -> None:
    registry_path = tmp_path / "projects.json"
    project = await _create_project(tmp_path, registry_path)
    app = create_app(registry_path=registry_path)

    async with _client(app) as client:
        response = await client.get(f"/projects/{project.name}/cache")

    assert response.status_code == 200
    assert 'id="cache-search"' not in response.text


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
