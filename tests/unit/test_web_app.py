"""Tests de la interfaz web (REQ-007, Fase D-2a): app, paginas y autenticacion."""

import httpx
import pytest

from doc_organize.core.models import SecurityConfig
from doc_organize.web import create_app


def _client(app, base_url: str = "http://testserver") -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=base_url)


# ===== Loopback (por defecto): sin autenticacion =====


@pytest.mark.asyncio
async def test_project_selector_page_loads(tmp_path) -> None:
    app = create_app(registry_path=tmp_path / "projects.json")
    async with _client(app) as client:
        response = await client.get("/")
    assert response.status_code == 200
    assert "Proyectos" in response.text


@pytest.mark.asyncio
async def test_create_and_list_project_via_api(tmp_path) -> None:
    base = tmp_path / "workspaces"
    base.mkdir()
    app = create_app(registry_path=tmp_path / "projects.json")

    async with _client(app) as client:
        create_response = await client.post("/api/projects", json={"name": "Mi Proyecto", "base_location": str(base)})
        assert create_response.status_code == 201
        assert create_response.json()["name"] == "Mi Proyecto"

        list_response = await client.get("/api/projects")
        assert list_response.status_code == 200
        projects = list_response.json()["projects"]
        assert len(projects) == 1
        assert projects[0]["name"] == "Mi Proyecto"
        assert projects[0]["missing"] is False


@pytest.mark.asyncio
async def test_create_project_duplicate_name_returns_409(tmp_path) -> None:
    base = tmp_path / "workspaces"
    base.mkdir()
    app = create_app(registry_path=tmp_path / "projects.json")

    async with _client(app) as client:
        await client.post("/api/projects", json={"name": "Duplicado", "base_location": str(base)})
        second = await client.post("/api/projects", json={"name": "duplicado", "base_location": str(base)})

    assert second.status_code == 409


@pytest.mark.asyncio
async def test_create_project_invalid_name_returns_422(tmp_path) -> None:
    base = tmp_path / "workspaces"
    base.mkdir()
    app = create_app(registry_path=tmp_path / "projects.json")

    async with _client(app) as client:
        response = await client.post("/api/projects", json={"name": "CON", "base_location": str(base)})

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_dashboard_page_for_existing_project(tmp_path) -> None:
    base = tmp_path / "workspaces"
    base.mkdir()
    app = create_app(registry_path=tmp_path / "projects.json")

    async with _client(app) as client:
        await client.post("/api/projects", json={"name": "Mi Proyecto", "base_location": str(base)})
        response = await client.get("/projects/Mi Proyecto")

    assert response.status_code == 200
    assert "Mi Proyecto" in response.text


@pytest.mark.asyncio
async def test_get_project_by_name_via_api(tmp_path) -> None:
    base = tmp_path / "workspaces"
    base.mkdir()
    app = create_app(registry_path=tmp_path / "projects.json")

    async with _client(app) as client:
        await client.post("/api/projects", json={"name": "Mi Proyecto", "base_location": str(base)})
        response = await client.get("/api/projects/Mi Proyecto")

    assert response.status_code == 200
    assert response.json()["name"] == "Mi Proyecto"


@pytest.mark.asyncio
async def test_get_project_by_name_via_api_returns_404(tmp_path) -> None:
    app = create_app(registry_path=tmp_path / "projects.json")
    async with _client(app) as client:
        response = await client.get("/api/projects/No Existe")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_create_project_nonexistent_base_location_returns_400(tmp_path) -> None:
    app = create_app(registry_path=tmp_path / "projects.json")
    async with _client(app) as client:
        response = await client.post("/api/projects", json={"name": "Proyecto", "base_location": str(tmp_path / "no-existe")})
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_dashboard_page_for_missing_project_returns_404(tmp_path) -> None:
    app = create_app(registry_path=tmp_path / "projects.json")
    async with _client(app) as client:
        response = await client.get("/projects/No Existe")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_loopback_api_works_without_session(tmp_path) -> None:
    security = SecurityConfig(bind_host="127.0.0.1")
    app = create_app(security=security, registry_path=tmp_path / "projects.json")
    async with _client(app) as client:
        response = await client.get("/api/projects")
    assert response.status_code == 200


# Suite de autenticacion no-loopback: ver test_web_auth.py (revision 8, SS2.7.2 --
# reemplaza la suite basada en bearer token de la revision 2/7, SS2.7.1 SUPERSEDIDO).
