"""Tests del Folder Selector y escaneo vía web (Fase D-2b, §2.7.3)."""

import json

from pathlib import Path

import httpx
import pytest

from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from doc_organize.auth import AuthStore
from doc_organize.core.models import SecurityConfig
from doc_organize.projects import ProjectRegistry, ScannedFoldersStore
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


@pytest.mark.asyncio
async def test_folder_selector_page_shows_gpu_status(tmp_path) -> None:
    """Sin torch instalado en el entorno de test, la página debe mostrar
    las instrucciones de instalación en vez de reventar (menú Escaneo, GPU)."""
    registry_path = tmp_path / "projects.json"
    project = await _create_project(tmp_path, registry_path)
    app = create_app(registry_path=registry_path)

    async with _client(app) as client:
        response = await client.get(f"/projects/{project.name}/scan")

    assert response.status_code == 200
    assert "GPU" in response.text


# ===== API /api/projects/{name}/folders/library (lista persistente de carpetas) =====


@pytest.mark.asyncio
async def test_folder_library_starts_empty(tmp_path) -> None:
    registry_path = tmp_path / "projects.json"
    project = await _create_project(tmp_path, registry_path)
    app = create_app(registry_path=registry_path)

    async with _client(app) as client:
        response = await client.get(f"/api/projects/{project.name}/folders/library")

    assert response.status_code == 200
    assert response.json() == []


@pytest.mark.asyncio
async def test_add_folder_to_library(tmp_path) -> None:
    registry_path = tmp_path / "projects.json"
    project = await _create_project(tmp_path, registry_path)
    app = create_app(registry_path=registry_path)

    folder = tmp_path / "datos"
    folder.mkdir()

    async with _client(app) as client:
        response = await client.post(f"/api/projects/{project.name}/folders/library", json={"path": str(folder)})

    assert response.status_code == 200
    payload = response.json()
    assert payload["path"] == str(folder.resolve())
    assert payload["used"] is False


@pytest.mark.asyncio
async def test_add_folder_to_library_rejects_nonexistent_path(tmp_path) -> None:
    registry_path = tmp_path / "projects.json"
    project = await _create_project(tmp_path, registry_path)
    app = create_app(registry_path=registry_path)

    async with _client(app) as client:
        response = await client.post(f"/api/projects/{project.name}/folders/library", json={"path": str(tmp_path / "no-existe")})

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_remove_unused_folder_from_library(tmp_path) -> None:
    registry_path = tmp_path / "projects.json"
    project = await _create_project(tmp_path, registry_path)
    app = create_app(registry_path=registry_path)

    folder = tmp_path / "datos"
    folder.mkdir()

    async with _client(app) as client:
        await client.post(f"/api/projects/{project.name}/folders/library", json={"path": str(folder)})
        response = await client.request("DELETE", f"/api/projects/{project.name}/folders/library", json={"path": str(folder)})
        listing = await client.get(f"/api/projects/{project.name}/folders/library")

    assert response.status_code == 204
    assert listing.json() == []


@pytest.mark.asyncio
async def test_remove_used_folder_from_library_is_rejected(tmp_path) -> None:
    registry_path = tmp_path / "projects.json"
    project = await _create_project(tmp_path, registry_path)
    app = create_app(registry_path=registry_path)

    empty_input = tmp_path / "empty-input"
    empty_input.mkdir()

    client = TestClient(app)
    add_response = client.post(f"/api/projects/{project.name}/folders/library", json={"path": str(empty_input)})
    assert add_response.status_code == 200

    with client.websocket_connect(f"/api/projects/{project.name}/scan") as websocket:
        websocket.send_json({"use_ocr": False, "use_gpu": False})
        while True:
            message = websocket.receive_json()
            if message["event"] == "completed":
                break

    remove_response = client.request("DELETE", f"/api/projects/{project.name}/folders/library", json={"path": str(empty_input)})
    assert remove_response.status_code == 409

    listing = client.get(f"/api/projects/{project.name}/folders/library")
    assert listing.json()[0]["used"] is True


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


# ===== POST /api/projects/{name}/scan/deduplicate =====


@pytest.mark.asyncio
async def test_deduplicate_endpoint_moves_exact_duplicates(tmp_path) -> None:
    registry_path = tmp_path / "projects.json"
    project = await _create_project(tmp_path, registry_path)
    app = create_app(registry_path=registry_path)

    folder = tmp_path / "datos"
    folder.mkdir()
    original = folder / "original.pdf"
    original.write_bytes(b"contenido-duplicado")
    (folder / "copia.pdf").write_bytes(original.read_bytes())

    async with _client(app) as client:
        await client.post(f"/api/projects/{project.name}/folders/library", json={"path": str(folder)})
        response = await client.post(f"/api/projects/{project.name}/scan/deduplicate")

    assert response.status_code == 200
    payload = response.json()
    assert payload == {"groups_found": 1, "moved": 1, "warnings": []}

    root = Path(project.root_path)
    assert (root / "duplicados" / "DEDUP_REPORT.json").exists()
    assert (root / "duplicados" / "DEDUP_HISTORY.jsonl").exists()
    assert (root / "folders.json").exists()  # sin haber escaneado todavia


@pytest.mark.asyncio
async def test_deduplicate_endpoint_rejects_when_no_saved_folders(tmp_path) -> None:
    registry_path = tmp_path / "projects.json"
    project = await _create_project(tmp_path, registry_path)
    app = create_app(registry_path=registry_path)

    async with _client(app) as client:
        response = await client.post(f"/api/projects/{project.name}/scan/deduplicate")

    assert response.status_code == 409


@pytest.mark.asyncio
async def test_deduplicate_endpoint_history_accumulates_across_runs(tmp_path) -> None:
    registry_path = tmp_path / "projects.json"
    project = await _create_project(tmp_path, registry_path)
    app = create_app(registry_path=registry_path)

    folder = tmp_path / "datos"
    folder.mkdir()
    first = folder / "first.pdf"
    first.write_bytes(b"primer-duplicado")
    (folder / "first_copy.pdf").write_bytes(first.read_bytes())

    async with _client(app) as client:
        await client.post(f"/api/projects/{project.name}/folders/library", json={"path": str(folder)})
        first_response = await client.post(f"/api/projects/{project.name}/scan/deduplicate")
        assert first_response.json()["groups_found"] == 1

        # Segunda tanda de duplicados, tras la primera ejecucion.
        second = folder / "second.pdf"
        second.write_bytes(b"segundo-duplicado")
        (folder / "second_copy.pdf").write_bytes(second.read_bytes())
        second_response = await client.post(f"/api/projects/{project.name}/scan/deduplicate")
        assert second_response.json()["groups_found"] == 1

    history_path = Path(project.root_path) / "duplicados" / "DEDUP_HISTORY.jsonl"
    lines = [line for line in history_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(lines) == 2
    for line in lines:
        json.loads(line)  # cada linea es un DeduplicationReport valido por si solo


@pytest.mark.asyncio
async def test_deduplicate_endpoint_rejects_path_outside_allowed_roots(tmp_path) -> None:
    auth_db_path = tmp_path / "auth.db"
    async with AuthStore(auth_db_path) as store:
        tenant = await store.create_tenant("Acme Corp")
        allowed_root = tmp_path / "allowed-root"
        allowed_root.mkdir()
        role = await store.create_role(tenant.id, "Lector", project_names=["Proyecto Scan"], allowed_scan_roots=[str(allowed_root)])
        alice = await store.create_user(tenant.id, "alice", "s3cr3t-password", role_id=role.id)
        session = await store.create_session(alice)

    registry_path = tmp_path / "projects.json"
    project = await _create_project(tmp_path, registry_path, tenant_id=tenant.id)
    security = SecurityConfig(bind_host="0.0.0.0")
    app = create_app(security=security, registry_path=registry_path, auth_db_path=auth_db_path)

    outside_path = tmp_path / "outside-root"
    outside_path.mkdir()
    await ScannedFoldersStore().add_folder(project, str(outside_path))

    async with _client(app) as client:
        client.cookies.set(SESSION_COOKIE_NAME, session.token)
        response = await client.post(f"/api/projects/{project.name}/scan/deduplicate")

    assert response.status_code == 403


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
    add_response = client.post(f"/api/projects/{project.name}/folders/library", json={"path": str(empty_input)})
    assert add_response.status_code == 200

    with client.websocket_connect(f"/api/projects/{project.name}/scan") as websocket:
        websocket.send_json({"use_ocr": False, "use_gpu": False})
        events = []
        while True:
            message = websocket.receive_json()
            events.append(message)
            if message["event"] == "completed":
                break

    event_types = [event["event"] for event in events]
    # La deduplicación ya no forma parte del escaneo (acción separada, ver
    # POST /scan/deduplicate) — el escaneo ya no emite "deduplicated".
    assert event_types == ["started", "scanned", "completed"]
    assert events[-1]["data"]["scanned"] == 0


@pytest.mark.asyncio
async def test_scan_websocket_rejects_when_no_saved_folders(tmp_path) -> None:
    """Rediseño scan->dedup->cache: el cliente ya no envía `paths` — si el proyecto
    no tiene ninguna carpeta guardada, no hay nada que escanear y se rechaza la
    conexión en vez de intentar un escaneo vacío silencioso."""
    registry_path = tmp_path / "projects.json"
    project = await _create_project(tmp_path, registry_path)
    app = create_app(registry_path=registry_path)

    client = TestClient(app)
    with pytest.raises(WebSocketDisconnect) as exc_info, client.websocket_connect(f"/api/projects/{project.name}/scan") as websocket:
        websocket.send_json({"use_ocr": False, "use_gpu": False})
        websocket.receive_json()
    assert exc_info.value.code == 1008


@pytest.mark.asyncio
async def test_scan_websocket_scans_all_saved_folders_not_a_subset(tmp_path) -> None:
    """El cliente ya no elige un subconjunto de carpetas por checkbox: cada escaneo
    procesa siempre TODAS las carpetas guardadas en la lista persistente.

    Ambas carpetas se dejan vacías a propósito: lo que se comprueba es que las DOS
    llegan al pipeline (via `folders.json` y el flag `used`), no el resultado de
    convertir documentos reales (ya cubierto, con Docling real, por los tests
    `@slow` de arriba).
    """
    registry_path = tmp_path / "projects.json"
    project = await _create_project(tmp_path, registry_path)
    app = create_app(registry_path=registry_path)

    folder_a = tmp_path / "carpeta-a"
    folder_b = tmp_path / "carpeta-b"
    folder_a.mkdir()
    folder_b.mkdir()

    client = TestClient(app)
    client.post(f"/api/projects/{project.name}/folders/library", json={"path": str(folder_a)})
    client.post(f"/api/projects/{project.name}/folders/library", json={"path": str(folder_b)})

    with client.websocket_connect(f"/api/projects/{project.name}/scan") as websocket:
        websocket.send_json({"use_ocr": False, "use_gpu": False})
        while websocket.receive_json()["event"] != "completed":
            pass

    folders_json = json.loads((Path(project.root_path) / "folders.json").read_text(encoding="utf-8"))
    assert set(folders_json["paths"]) == {str(folder_a.resolve()), str(folder_b.resolve())}

    library = client.get(f"/api/projects/{project.name}/folders/library").json()
    assert {entry["path"] for entry in library} == {str(folder_a.resolve()), str(folder_b.resolve())}
    assert all(entry["used"] for entry in library)


@pytest.mark.asyncio
async def test_scan_websocket_includes_folder_added_after_previous_scan(tmp_path) -> None:
    """Una carpeta añadida DESPUÉS de un escaneo previo entra automáticamente en el
    siguiente "escanear todas", sin ninguna acción extra aparte de guardarla."""
    registry_path = tmp_path / "projects.json"
    project = await _create_project(tmp_path, registry_path)
    app = create_app(registry_path=registry_path)

    folder_a = tmp_path / "carpeta-a"
    folder_a.mkdir()

    client = TestClient(app)
    client.post(f"/api/projects/{project.name}/folders/library", json={"path": str(folder_a)})

    with client.websocket_connect(f"/api/projects/{project.name}/scan") as websocket:
        websocket.send_json({"use_ocr": False, "use_gpu": False})
        while websocket.receive_json()["event"] != "completed":
            pass

    folders_json_path = Path(project.root_path) / "folders.json"
    assert json.loads(folders_json_path.read_text(encoding="utf-8"))["paths"] == [str(folder_a.resolve())]

    # Se añade una segunda carpeta DESPUÉS del primer escaneo, sin volver a marcar
    # nada más.
    folder_b = tmp_path / "carpeta-b"
    folder_b.mkdir()
    client.post(f"/api/projects/{project.name}/folders/library", json={"path": str(folder_b)})

    with client.websocket_connect(f"/api/projects/{project.name}/scan") as websocket:
        websocket.send_json({"use_ocr": False, "use_gpu": False})
        while websocket.receive_json()["event"] != "completed":
            pass

    assert set(json.loads(folders_json_path.read_text(encoding="utf-8"))["paths"]) == {
        str(folder_a.resolve()),
        str(folder_b.resolve()),
    }


@pytest.mark.slow
@pytest.mark.asyncio
async def test_scan_websocket_loopback_converts_real_document(tmp_path, native_pdf) -> None:
    registry_path = tmp_path / "projects.json"
    project = await _create_project(tmp_path, registry_path)
    app = create_app(registry_path=registry_path)

    client = TestClient(app)
    add_response = client.post(f"/api/projects/{project.name}/folders/library", json={"path": str(native_pdf.parent)})
    assert add_response.status_code == 200

    with client.websocket_connect(f"/api/projects/{project.name}/scan") as websocket:
        websocket.send_json({"use_ocr": False, "use_gpu": False})
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

    with pytest.raises(WebSocketDisconnect) as exc_info, client.websocket_connect("/api/projects/No Existe/scan") as websocket:
        websocket.receive_json()
    assert exc_info.value.code == 1008


@pytest.mark.asyncio
async def test_scan_websocket_non_loopback_requires_session(tmp_path) -> None:
    registry_path = tmp_path / "projects.json"
    project = await _create_project(tmp_path, registry_path)
    security = SecurityConfig(bind_host="0.0.0.0")
    app = create_app(security=security, registry_path=registry_path, auth_db_path=tmp_path / "auth.db")
    client = TestClient(app)

    with pytest.raises(WebSocketDisconnect) as exc_info, client.websocket_connect(f"/api/projects/{project.name}/scan") as websocket:
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
    add_response = client.post(f"/api/projects/{project.name}/folders/library", json={"path": str(empty_input)})
    assert add_response.status_code == 200

    with client.websocket_connect(f"/api/projects/{project.name}/scan") as websocket:
        websocket.send_json({"use_ocr": False, "use_gpu": False})
        events = []
        while True:
            message = websocket.receive_json()
            events.append(message)
            if message["event"] == "completed":
                break

    assert [event["event"] for event in events] == ["started", "scanned", "completed"]


@pytest.mark.asyncio
async def test_scan_websocket_non_admin_role_rejects_path_outside_allowed_roots(tmp_path) -> None:
    """Revisión de seguridad (revisión 9): un rol restringido a `allowed_scan_roots`
    no puede escanear una ruta fuera de esas raíces, aunque tenga acceso al proyecto."""
    auth_db_path = tmp_path / "auth.db"
    async with AuthStore(auth_db_path) as store:
        tenant = await store.create_tenant("Acme Corp")
        allowed_root = tmp_path / "allowed-root"
        allowed_root.mkdir()
        role = await store.create_role(tenant.id, "Lector", project_names=["Proyecto Scan"], allowed_scan_roots=[str(allowed_root)])
        alice = await store.create_user(tenant.id, "alice", "s3cr3t-password", role_id=role.id)
        session = await store.create_session(alice)

    registry_path = tmp_path / "projects.json"
    project = await _create_project(tmp_path, registry_path, tenant_id=tenant.id)
    security = SecurityConfig(bind_host="0.0.0.0")
    app = create_app(security=security, registry_path=registry_path, auth_db_path=auth_db_path)

    outside_path = tmp_path / "outside-root"
    outside_path.mkdir()
    # Se guarda directamente en el store (no vía API): simula una carpeta guardada
    # antes de que el rol quedara restringido a `allowed_root` — la propia API de
    # guardado ya rechazaría este alta para este rol.
    await ScannedFoldersStore().add_folder(project, str(outside_path))

    client = TestClient(app, cookies={SESSION_COOKIE_NAME: session.token})
    with pytest.raises(WebSocketDisconnect) as exc_info, client.websocket_connect(f"/api/projects/{project.name}/scan") as websocket:
        websocket.send_json({"use_ocr": False, "use_gpu": False})
        websocket.receive_json()
    assert exc_info.value.code == 1008


@pytest.mark.asyncio
async def test_scan_websocket_non_admin_role_allows_path_inside_allowed_roots(tmp_path) -> None:
    auth_db_path = tmp_path / "auth.db"
    async with AuthStore(auth_db_path) as store:
        tenant = await store.create_tenant("Acme Corp")
        allowed_root = tmp_path / "allowed-root"
        allowed_root.mkdir()
        role = await store.create_role(tenant.id, "Lector", project_names=["Proyecto Scan"], allowed_scan_roots=[str(allowed_root)])
        alice = await store.create_user(tenant.id, "alice", "s3cr3t-password", role_id=role.id)
        session = await store.create_session(alice)

    registry_path = tmp_path / "projects.json"
    project = await _create_project(tmp_path, registry_path, tenant_id=tenant.id)
    security = SecurityConfig(bind_host="0.0.0.0")
    app = create_app(security=security, registry_path=registry_path, auth_db_path=auth_db_path)

    client = TestClient(app, cookies={SESSION_COOKIE_NAME: session.token})
    add_response = client.post(f"/api/projects/{project.name}/folders/library", json={"path": str(allowed_root)})
    assert add_response.status_code == 200

    with client.websocket_connect(f"/api/projects/{project.name}/scan") as websocket:
        websocket.send_json({"use_ocr": False, "use_gpu": False})
        events = []
        while True:
            message = websocket.receive_json()
            events.append(message)
            if message["event"] == "completed":
                break

    assert [event["event"] for event in events] == ["started", "scanned", "completed"]


@pytest.mark.asyncio
async def test_scan_websocket_non_admin_role_without_allowed_roots_rejects_any_path(tmp_path) -> None:
    """Un rol restringido sin `allowed_scan_roots` configuradas no puede escanear
    ninguna ruta externa (por defecto, no la lista vacía == sin restricción)."""
    auth_db_path = tmp_path / "auth.db"
    async with AuthStore(auth_db_path) as store:
        tenant = await store.create_tenant("Acme Corp")
        role = await store.create_role(tenant.id, "Lector", project_names=["Proyecto Scan"])
        alice = await store.create_user(tenant.id, "alice", "s3cr3t-password", role_id=role.id)
        session = await store.create_session(alice)

    registry_path = tmp_path / "projects.json"
    project = await _create_project(tmp_path, registry_path, tenant_id=tenant.id)
    security = SecurityConfig(bind_host="0.0.0.0")
    app = create_app(security=security, registry_path=registry_path, auth_db_path=auth_db_path)

    somewhere = tmp_path / "somewhere"
    somewhere.mkdir()
    # Igual que en el test de arriba: se guarda directamente en el store, ya que
    # este rol (sin `allowed_scan_roots`) tampoco podría darla de alta vía API.
    await ScannedFoldersStore().add_folder(project, str(somewhere))

    client = TestClient(app, cookies={SESSION_COOKIE_NAME: session.token})
    with pytest.raises(WebSocketDisconnect) as exc_info, client.websocket_connect(f"/api/projects/{project.name}/scan") as websocket:
        websocket.send_json({"use_ocr": False, "use_gpu": False})
        websocket.receive_json()
    assert exc_info.value.code == 1008


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
    with pytest.raises(WebSocketDisconnect) as exc_info, client.websocket_connect(f"/api/projects/{project.name}/scan") as websocket:
        websocket.receive_json()
    assert exc_info.value.code == 1008
