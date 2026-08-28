"""Tests del Folder Selector y escaneo vía web (Fase D-2b, §2.7.3)."""

import httpx
import pytest

from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from doc_organize.auth import AuthStore
from doc_organize.core.models import SecurityConfig
from doc_organize.projects import ProjectRegistry
from doc_organize.web import create_app
from doc_organize.web.auth import SESSION_COOKIE_NAME


def _client(app, base_url: str = "http://testserver") -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=base_url)


async def _create_project(tmp_path, registry_path, name: str = "Proyecto Scan", tenant_id: str = "default"):
    base = tmp_path / "workspaces"
    base.mkdir(exist_ok=True)
    async with ProjectRegistry(registry_path) as registry:
        return await registry.create_project(name, base, tenant_id=tenant_id)


# ===== GET /projects/{name}/scan (Folder Selector) =====


@pytest.mark.asyncio
async def test_folder_selector_page_loads_for_existing_project(tmp_path) -> None:
    registry_path = tmp_path / "projects.json"
    project = await _create_project(tmp_path, registry_path)
    app = create_app(registry_path=registry_path)

    async with _client(app) as client:
        response = await client.get(f"/projects/{project.name}/scan")

    assert response.status_code == 200
    assert "Escanear" in response.text


@pytest.mark.asyncio
async def test_folder_selector_page_404_for_missing_project(tmp_path) -> None:
    app = create_app(registry_path=tmp_path / "projects.json")
    async with _client(app) as client:
        response = await client.get("/projects/No Existe/scan")
    assert response.status_code == 404


# ===== POST /api/projects/{name}/folders/validate =====


@pytest.mark.asyncio
async def test_validate_folders_returns_clean_paths(tmp_path) -> None:
    registry_path = tmp_path / "projects.json"
    project = await _create_project(tmp_path, registry_path)
    app = create_app(registry_path=registry_path)

    input_dir = tmp_path / "input"
    input_dir.mkdir()

    async with _client(app) as client:
        response = await client.post(f"/api/projects/{project.name}/folders/validate", json={"paths": [str(input_dir)]})

    assert response.status_code == 200
    payload = response.json()
    assert payload["valid"] is True
    assert payload["clean_paths"] == [str(input_dir)]


@pytest.mark.asyncio
async def test_validate_folders_404_for_missing_project(tmp_path) -> None:
    app = create_app(registry_path=tmp_path / "projects.json")
    async with _client(app) as client:
        response = await client.post("/api/projects/No Existe/folders/validate", json={"paths": []})
    assert response.status_code == 404


# ===== WS /api/projects/{name}/scan =====


@pytest.mark.asyncio
async def test_scan_websocket_loopback_full_pipeline_empty_paths(tmp_path) -> None:
    # Sin documentos de entrada: ejercita started/scanned/completed sin pagar el
    # coste de una conversion Docling real -- eso ya lo cubre el test @slow de abajo.
    registry_path = tmp_path / "projects.json"
    project = await _create_project(tmp_path, registry_path)
    app = create_app(registry_path=registry_path)

    empty_input = tmp_path / "empty-input"
    empty_input.mkdir()

    client = TestClient(app)
    with client.websocket_connect(f"/api/projects/{project.name}/scan") as websocket:
        websocket.send_json({"paths": [str(empty_input)], "deduplicate": False, "use_ocr": False, "use_gpu": False})
        events = []
        while True:
            message = websocket.receive_json()
            events.append(message)
            if message["event"] == "completed":
                break

    event_types = [event["event"] for event in events]
    assert event_types == ["started", "scanned", "completed"]
    assert events[-1]["data"]["scanned"] == 0


@pytest.mark.slow
@pytest.mark.asyncio
async def test_scan_websocket_loopback_converts_real_document(tmp_path, native_pdf) -> None:
    registry_path = tmp_path / "projects.json"
    project = await _create_project(tmp_path, registry_path)
    app = create_app(registry_path=registry_path)

    client = TestClient(app)
    with client.websocket_connect(f"/api/projects/{project.name}/scan") as websocket:
        websocket.send_json({"paths": [str(native_pdf.parent)], "deduplicate": False, "use_ocr": False, "use_gpu": False})
        events = []
        while True:
            message = websocket.receive_json()
            events.append(message)
            if message["event"] == "completed":
                break

    event_types = [event["event"] for event in events]
    assert "file_converted" in event_types
    assert events[-1]["data"]["converted"] == 1


@pytest.mark.asyncio
async def test_scan_websocket_rejects_missing_project(tmp_path) -> None:
    app = create_app(registry_path=tmp_path / "projects.json")
    client = TestClient(app)

    with pytest.raises(WebSocketDisconnect) as exc_info:
        with client.websocket_connect("/api/projects/No Existe/scan") as websocket:
            websocket.receive_json()
    assert exc_info.value.code == 1008


@pytest.mark.asyncio
async def test_scan_websocket_non_loopback_requires_session(tmp_path) -> None:
    registry_path = tmp_path / "projects.json"
    project = await _create_project(tmp_path, registry_path)
    security = SecurityConfig(bind_host="0.0.0.0")
    app = create_app(security=security, registry_path=registry_path, auth_db_path=tmp_path / "auth.db")
    client = TestClient(app)

    with pytest.raises(WebSocketDisconnect) as exc_info:
        with client.websocket_connect(f"/api/projects/{project.name}/scan") as websocket:
            websocket.receive_json()
    assert exc_info.value.code == 1008


@pytest.mark.asyncio
async def test_scan_websocket_non_loopback_with_valid_session_succeeds(tmp_path) -> None:
    auth_db_path = tmp_path / "auth.db"
    async with AuthStore(auth_db_path) as store:
        tenant = await store.create_tenant("Acme Corp")
        user = await store.create_user(tenant.id, "alice", "s3cr3t-password")
        session = await store.create_session(user)

    registry_path = tmp_path / "projects.json"
    project = await _create_project(tmp_path, registry_path, tenant_id=tenant.id)
    security = SecurityConfig(bind_host="0.0.0.0")
    app = create_app(security=security, registry_path=registry_path, auth_db_path=auth_db_path)

    empty_input = tmp_path / "empty-input"
    empty_input.mkdir()

    client = TestClient(app, cookies={SESSION_COOKIE_NAME: session.token})
    with client.websocket_connect(f"/api/projects/{project.name}/scan") as websocket:
        websocket.send_json({"paths": [str(empty_input)], "deduplicate": False, "use_ocr": False, "use_gpu": False})
        events = []
        while True:
            message = websocket.receive_json()
            events.append(message)
            if message["event"] == "completed":
                break

    assert [event["event"] for event in events] == ["started", "scanned", "completed"]


@pytest.mark.asyncio
async def test_scan_websocket_non_loopback_rejects_other_tenants_project(tmp_path) -> None:
    auth_db_path = tmp_path / "auth.db"
    async with AuthStore(auth_db_path) as store:
        acme = await store.create_tenant("Acme Corp")
        globex = await store.create_tenant("Globex Inc")
        alice = await store.create_user(acme.id, "alice", "s3cr3t-password")
        session = await store.create_session(alice)

    registry_path = tmp_path / "projects.json"
    # El proyecto pertenece a "globex", pero la sesion es de "acme".
    project = await _create_project(tmp_path, registry_path, tenant_id=globex.id)
    security = SecurityConfig(bind_host="0.0.0.0")
    app = create_app(security=security, registry_path=registry_path, auth_db_path=auth_db_path)

    client = TestClient(app, cookies={SESSION_COOKIE_NAME: session.token})
    with pytest.raises(WebSocketDisconnect) as exc_info:
        with client.websocket_connect(f"/api/projects/{project.name}/scan") as websocket:
            websocket.receive_json()
    assert exc_info.value.code == 1008
