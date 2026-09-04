"""Tests de la interfaz web (REQ-007, Fase D-2a): app, paginas y autenticacion."""

import asyncio

import httpx
import pytest

from doc_organize.core.models import SecurityConfig
from doc_organize.projects import ProjectRegistry
from doc_organize.web import create_app


def _client(app, base_url: str = "http://testserver") -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=base_url)


async def _create_project(tmp_path, registry_path, name: str, tenant_id: str = "default"):
    base = tmp_path / "workspaces"
    base.mkdir(exist_ok=True)
    async with ProjectRegistry(registry_path) as registry:
        return await registry.create_project(name, base, tenant_id=tenant_id)


# ===== Loopback (por defecto): sin autenticacion =====


@pytest.mark.asyncio
async def test_project_selector_page_loads(tmp_path) -> None:
    app = create_app(registry_path=tmp_path / "projects.json")
    async with _client(app) as client:
        response = await client.get("/")
    assert response.status_code == 200
    assert "Proyectos" in response.text


@pytest.mark.asyncio
async def test_project_selector_confirm_modal_starts_hidden(tmp_path) -> None:
    """Regresión: `hidden` + `flex` estáticos en el mismo elemento hacen que Tailwind
    (CDN) ignore `[hidden]` y el modal se muestre siempre, vacío y bloqueando la página."""
    app = create_app(registry_path=tmp_path / "projects.json")
    async with _client(app) as client:
        response = await client.get("/")
    assert response.status_code == 200
    start = response.text.index('<div id="confirm-modal"')
    modal_tag = response.text[start : response.text.index(">", start) + 1]
    assert "hidden" in modal_tag
    assert "flex" not in modal_tag


# ===== Buscador y paginación de "Proyectos" (misma funcionalidad que la pestaña Caché) =====


@pytest.mark.asyncio
async def test_project_selector_page_no_search_box_when_no_projects(tmp_path) -> None:
    app = create_app(registry_path=tmp_path / "projects.json")
    async with _client(app) as client:
        response = await client.get("/")
    assert response.status_code == 200
    assert 'id="project-search"' not in response.text


@pytest.mark.asyncio
async def test_project_selector_page_shows_search_box_and_count(tmp_path) -> None:
    registry_path = tmp_path / "projects.json"
    await _create_project(tmp_path, registry_path, "Informe Anual")
    app = create_app(registry_path=registry_path)

    async with _client(app) as client:
        response = await client.get("/")

    assert response.status_code == 200
    html = response.text
    assert 'id="project-search"' in html
    assert 'name="q"' in html
    assert "Mostrando 1–1 de 1 entradas." in html


@pytest.mark.asyncio
async def test_project_selector_page_search_filters_by_name(tmp_path) -> None:
    registry_path = tmp_path / "projects.json"
    await _create_project(tmp_path, registry_path, "Informe Anual")
    await _create_project(tmp_path, registry_path, "Facturas 2026")
    app = create_app(registry_path=registry_path)

    async with _client(app) as client:
        response = await client.get("/", params={"q": "informe"})

    assert response.status_code == 200
    html = response.text
    # El nombre coincidente se resalta con <mark>, partiendo la cadena literal.
    assert "<mark>Informe</mark> Anual" in html
    assert "Facturas 2026" not in html
    assert "Mostrando 1–1 de 1 entradas." in html


@pytest.mark.asyncio
async def test_project_selector_page_search_filters_by_location(tmp_path) -> None:
    # "misma funcionalidad que la pestaña Caché": el buscador cubre nombre Y
    # ubicación, igual que Caché cubre nombre de archivo Y carpeta.
    registry_path = tmp_path / "projects.json"
    project = await _create_project(tmp_path, registry_path, "Proyecto Uno")
    await _create_project(tmp_path, registry_path, "Proyecto Dos")
    app = create_app(registry_path=registry_path)

    async with _client(app) as client:
        response = await client.get("/", params={"q": project.root_path})

    assert response.status_code == 200
    html = response.text
    assert "Proyecto Uno" in html
    assert "Proyecto Dos" not in html


@pytest.mark.asyncio
async def test_project_selector_page_paginates_and_navigates_pages(tmp_path) -> None:
    registry_path = tmp_path / "projects.json"
    for i in range(30):
        await _create_project(tmp_path, registry_path, f"Proyecto {i:03d}")
    app = create_app(registry_path=registry_path)

    async with _client(app) as client:
        page1 = await client.get("/", params={"page_size": 25})
        page2 = await client.get("/", params={"page": 2, "page_size": 25})

    assert page1.status_code == 200
    assert page2.status_code == 200
    assert "Página 1 de 2" in page1.text
    assert "Página 2 de 2" in page2.text
    assert "Proyecto 000" in page1.text
    assert "Proyecto 024" in page1.text
    assert "Proyecto 025" not in page1.text
    assert "Proyecto 029" in page2.text
    assert "Proyecto 000" not in page2.text


@pytest.mark.asyncio
async def test_project_selector_page_clamps_out_of_range_page(tmp_path) -> None:
    registry_path = tmp_path / "projects.json"
    await _create_project(tmp_path, registry_path, "Único Proyecto")
    app = create_app(registry_path=registry_path)

    async with _client(app) as client:
        response = await client.get("/", params={"page": 999})

    assert response.status_code == 200
    assert "Único Proyecto" in response.text


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
async def test_concurrent_project_creation_does_not_lose_either_project(tmp_path) -> None:
    """AUDIT_CODE (sesión 2026-09-03): `get_project_registry()` creaba antes una
    instancia (y por tanto un `asyncio.Lock`) nueva por petición, así que el
    lock no serializaba nada entre dos requests concurrentes -- dos proyectos
    creados a la vez podían pisarse el `os.replace()` final, perdiendo uno de
    los dos en silencio (reproducido empíricamente antes del fix). Ahora
    `create_app()` comparte una única instancia (`app.state.project_registry`)
    entre todas las peticiones, así que el lock sí protege de verdad."""
    base = tmp_path / "workspaces"
    base.mkdir()
    app = create_app(registry_path=tmp_path / "projects.json")

    async with _client(app) as client:
        first, second = await asyncio.gather(
            client.post("/api/projects", json={"name": "Proyecto A", "base_location": str(base)}),
            client.post("/api/projects", json={"name": "Proyecto B", "base_location": str(base)}),
        )
        assert first.status_code == 201
        assert second.status_code == 201

        list_response = await client.get("/api/projects")
        names = {project["name"] for project in list_response.json()["projects"]}
    assert names == {"Proyecto A", "Proyecto B"}


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
async def test_dashboard_page_shows_saved_folders_section(tmp_path) -> None:
    """ "Carpetas guardadas" se trasladó de la página Escanear al Dashboard
    (reestructuración de navegación)."""
    base = tmp_path / "workspaces"
    base.mkdir()
    app = create_app(registry_path=tmp_path / "projects.json")

    folder = tmp_path / "datos"
    folder.mkdir()

    async with _client(app) as client:
        await client.post("/api/projects", json={"name": "Mi Proyecto", "base_location": str(base)})
        await client.post("/api/projects/Mi Proyecto/folders/library", json={"path": str(folder)})
        response = await client.get("/projects/Mi Proyecto")

    assert response.status_code == 200
    html = response.text
    assert "Carpetas guardadas" in html
    assert str(folder.resolve()) in html
    assert 'id="add-folder-btn"' in html


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
