"""Tests del Folder Selector y escaneo vía web (Fase D-2b, §2.7.3).

Incluye también los tests de la pestaña Caché de esta misma página (antigua
página Caché independiente, fusionada aquí en la reestructuración de
navegación, Fase D-2c §2.7.4).
"""

import json
import re

from pathlib import Path

import httpx
import pytest

from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from doc_organize.auth import AuthStore
from doc_organize.cache import CacheManager
from doc_organize.core.constants import DEFAULT_CACHE_DB_NAME, SCAN_HISTORY_FOLDER_NAME, SCAN_HISTORY_JSONL_NAME
from doc_organize.core.models import CacheEntry, ConversionStatus, DocumentStatus, SecurityConfig
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


def _write_scan_history(project_root: Path, *runs: dict) -> None:
    history_dir = project_root / SCAN_HISTORY_FOLDER_NAME
    history_dir.mkdir(parents=True, exist_ok=True)
    lines = "\n".join(json.dumps(run) for run in runs)
    (history_dir / SCAN_HISTORY_JSONL_NAME).write_text(lines + "\n", encoding="utf-8")


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


@pytest.mark.asyncio
async def test_folder_selector_page_no_longer_shows_saved_folders_section(tmp_path) -> None:
    """ "Carpetas guardadas" se trasladó al Dashboard (reestructuración de
    navegación, tabs Escanear/Caché + Duplicados) -- ya no debe aparecer en la
    página Escanear."""
    registry_path = tmp_path / "projects.json"
    project = await _create_project(tmp_path, registry_path)
    app = create_app(registry_path=registry_path)

    async with _client(app) as client:
        response = await client.get(f"/projects/{project.name}/scan")

    assert response.status_code == 200
    html = response.text
    assert 'id="folder-list"' not in html
    assert 'id="add-folder-btn"' not in html


@pytest.mark.asyncio
async def test_folder_selector_page_no_longer_shows_deduplicate_step(tmp_path) -> None:
    """ "Paso 1: Buscar duplicados" se trasladó a la pestaña "Buscar duplicados"
    de la página Duplicados -- ya no debe aparecer en Escanear."""
    registry_path = tmp_path / "projects.json"
    project = await _create_project(tmp_path, registry_path)
    app = create_app(registry_path=registry_path)

    async with _client(app) as client:
        response = await client.get(f"/projects/{project.name}/scan")

    assert response.status_code == 200
    assert 'id="deduplicate-btn"' not in response.text


@pytest.mark.asyncio
async def test_folder_selector_scan_button_disabled_without_saved_folders(tmp_path) -> None:
    registry_path = tmp_path / "projects.json"
    project = await _create_project(tmp_path, registry_path)
    app = create_app(registry_path=registry_path)

    async with _client(app) as client:
        response = await client.get(f"/projects/{project.name}/scan")

    assert response.status_code == 200
    assert 'id="scan-submit-btn" disabled' in response.text


@pytest.mark.asyncio
async def test_folder_selector_scan_button_enabled_with_saved_folders(tmp_path) -> None:
    """El gate "hay que deduplicar en esta misma visita antes de escanear" se
    elimina (reestructuración de navegación: "Buscar duplicados" pasa a vivir en
    otra página, Duplicados): con al menos una carpeta guardada, "Escanear" ya
    no depende de haber ejecutado antes "Buscar duplicados"."""
    registry_path = tmp_path / "projects.json"
    project = await _create_project(tmp_path, registry_path)
    app = create_app(registry_path=registry_path)

    folder = tmp_path / "datos"
    folder.mkdir()

    async with _client(app) as client:
        await client.post(f"/api/projects/{project.name}/folders/library", json={"path": str(folder)})
        response = await client.get(f"/projects/{project.name}/scan")

    assert response.status_code == 200
    assert 'id="scan-submit-btn" disabled' not in response.text


# ===== "Última ejecución" y pestaña "Historial de ejecuciones" (tiempo de escaneo) =====


@pytest.mark.asyncio
async def test_folder_selector_shows_no_execution_yet_when_history_empty(tmp_path) -> None:
    registry_path = tmp_path / "projects.json"
    project = await _create_project(tmp_path, registry_path)
    app = create_app(registry_path=registry_path)

    async with _client(app) as client:
        response = await client.get(f"/projects/{project.name}/scan")

    assert response.status_code == 200
    assert "todavía no se ha ejecutado ningún escaneo" in response.text


@pytest.mark.asyncio
async def test_folder_selector_shows_last_execution_duration_formatted(tmp_path) -> None:
    registry_path = tmp_path / "projects.json"
    project = await _create_project(tmp_path, registry_path)
    project_root = tmp_path / "workspaces" / project.name

    _write_scan_history(
        project_root,
        {
            "scan_run_id": "run-1",
            "started_at": "2026-08-01T09:59:00+00:00",
            "finished_at": "2026-08-01T10:00:00+00:00",
            "duration_seconds": 65.4,
            "total_scanned": 3,
            "completed": True,
        },
    )

    app = create_app(registry_path=registry_path)
    async with _client(app) as client:
        response = await client.get(f"/projects/{project.name}/scan")

    assert response.status_code == 200
    text = response.text
    # 10:00 UTC en agosto (horario de verano) son las 12:00 en Europe/Madrid.
    assert "01/08/2026 12:00:00" in text
    assert "duración: 1m 5s" in text


@pytest.mark.asyncio
async def test_folder_selector_marks_interrupted_execution_as_such(tmp_path) -> None:
    registry_path = tmp_path / "projects.json"
    project = await _create_project(tmp_path, registry_path)
    project_root = tmp_path / "workspaces" / project.name

    _write_scan_history(
        project_root,
        {
            "scan_run_id": "run-cancelado",
            "started_at": "2026-08-01T09:59:00+00:00",
            "finished_at": "2026-08-01T10:00:00+00:00",
            "duration_seconds": 12.0,
            "total_scanned": 1,
            "completed": False,
        },
    )

    app = create_app(registry_path=registry_path)
    async with _client(app) as client:
        response = await client.get(f"/projects/{project.name}/scan")

    assert response.status_code == 200
    assert "(interrumpida)" in response.text


@pytest.mark.asyncio
async def test_folder_selector_history_tab_lists_runs_most_recent_first(tmp_path) -> None:
    registry_path = tmp_path / "projects.json"
    project = await _create_project(tmp_path, registry_path)
    project_root = tmp_path / "workspaces" / project.name

    _write_scan_history(
        project_root,
        {
            "scan_run_id": "run-1",
            "started_at": "2026-08-01T09:59:00+00:00",
            "finished_at": "2026-08-01T10:00:00+00:00",
            "duration_seconds": 30.0,
            "total_scanned": 2,
            "completed": True,
        },
        {
            "scan_run_id": "run-2",
            "started_at": "2026-08-02T09:59:00+00:00",
            "finished_at": "2026-08-02T10:00:00+00:00",
            "duration_seconds": 45.0,
            "total_scanned": 4,
            "completed": True,
        },
    )

    app = create_app(registry_path=registry_path)
    async with _client(app) as client:
        response = await client.get(f"/projects/{project.name}/scan", params={"tab": "history"})

    assert response.status_code == 200
    text = response.text
    assert "02/08/2026 12:00:00" in text
    assert "01/08/2026 12:00:00" in text
    assert text.index("02/08/2026 12:00:00") < text.index("01/08/2026 12:00:00")


@pytest.mark.asyncio
async def test_folder_selector_survives_corrupted_timestamp_in_history(tmp_path) -> None:
    """AUDIT_CODE: un timestamp no-ISO en una entrada del historial (backup
    restaurado, edición manual del JSONL) no debe tumbar la página con un 500 --
    `format_datetime` degrada a mostrar el valor crudo (ver `test_date_format.py`)."""
    registry_path = tmp_path / "projects.json"
    project = await _create_project(tmp_path, registry_path)
    project_root = tmp_path / "workspaces" / project.name

    _write_scan_history(
        project_root,
        {
            "scan_run_id": "run-1",
            "started_at": "fecha-corrupta",
            "finished_at": "fecha-corrupta",
            "duration_seconds": 5.0,
            "total_scanned": 1,
            "completed": True,
        },
    )

    app = create_app(registry_path=registry_path)
    async with _client(app) as client:
        response = await client.get(f"/projects/{project.name}/scan", params={"tab": "history"})

    assert response.status_code == 200
    assert "fecha-corrupta" in response.text


@pytest.mark.asyncio
async def test_folder_selector_history_tab_empty_state(tmp_path) -> None:
    registry_path = tmp_path / "projects.json"
    project = await _create_project(tmp_path, registry_path)
    app = create_app(registry_path=registry_path)

    async with _client(app) as client:
        response = await client.get(f"/projects/{project.name}/scan", params={"tab": "history"})

    assert response.status_code == 200
    assert "Todavía no se ha registrado ninguna ejecución de escaneo." in response.text


# ===== Pestaña Caché de la página Escanear (antigua página Caché, GET /projects/{name}/cache) =====


@pytest.mark.asyncio
async def test_scan_page_cache_tab_loads_when_never_scanned(tmp_path) -> None:
    registry_path = tmp_path / "projects.json"
    project = await _create_project(tmp_path, registry_path)
    app = create_app(registry_path=registry_path)

    async with _client(app) as client:
        response = await client.get(f"/projects/{project.name}/scan", params={"tab": "cache"})

    assert response.status_code == 200
    assert "No hay entradas en caché" in response.text


@pytest.mark.asyncio
async def test_scan_page_cache_tab_shows_search_box_and_folder_column(tmp_path) -> None:
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
        response = await client.get(f"/projects/{project.name}/scan", params={"tab": "cache"})

    assert response.status_code == 200
    html = response.text
    assert 'id="cache-search"' in html
    assert 'name="q"' in html
    assert re.search(r">report\.pdf<", html)
    expected_dirname = str(Path(file_path).parent)
    assert re.search(re.escape(expected_dirname).lower() + r"\s*</td>", html.lower())
    assert "Mostrando 1–1 de 1 entradas." in html


@pytest.mark.asyncio
async def test_scan_page_cache_tab_shows_error_message_as_tooltip(tmp_path) -> None:
    """La celda "Conversión" de una entrada en ERROR lleva el mensaje de error
    como `title` (tooltip) — ver `folder_selector.html.j2`. Las entradas sin
    error (o no fallidas) no deben llevar ese atributo."""
    registry_path = tmp_path / "projects.json"
    project = await _create_project(tmp_path, registry_path)
    cache_db = tmp_path / "workspaces" / project.name / DEFAULT_CACHE_DB_NAME
    async with CacheManager(cache_db) as cache:
        await cache.save_entries(
            [
                CacheEntry(
                    file_path=str(tmp_path / "docs" / "roto.pdf"),
                    sha256_hash="a" * 64,
                    timestamp=1_700_000_000.0,
                    status=DocumentStatus.UNCHANGED,
                    conversion_status=ConversionStatus.ERROR,
                    error_message="Documento cifrado, no se pudo abrir",
                ),
                CacheEntry(
                    file_path=str(tmp_path / "docs" / "ok.pdf"),
                    sha256_hash="b" * 64,
                    timestamp=1_700_000_000.0,
                    status=DocumentStatus.NEW,
                    conversion_status=ConversionStatus.SUCCESS,
                ),
            ]
        )

    app = create_app(registry_path=registry_path)
    async with _client(app) as client:
        response = await client.get(f"/projects/{project.name}/scan", params={"tab": "cache"})

    assert response.status_code == 200
    html = response.text
    # Celda "Conversión" de la fila en error: lleva el mensaje como title.
    assert 'whitespace-nowrap" title="Documento cifrado, no se pudo abrir">error</td>' in html
    # Celda "Conversión" de la fila sin error: sin atributo title (el `title` de
    # la celda "Carpeta", ver folder_selector.html.j2:122, es un tooltip distinto
    # que sí aparece siempre y no debe confundirse con este).
    assert 'whitespace-nowrap">success</td>' in html


@pytest.mark.asyncio
async def test_scan_page_cache_tab_paginates_and_navigates_pages(tmp_path) -> None:
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
        page1 = await client.get(f"/projects/{project.name}/scan", params={"tab": "cache", "page_size": 25})
        page2 = await client.get(f"/projects/{project.name}/scan", params={"tab": "cache", "page": 2, "page_size": 25})

    assert page1.status_code == 200
    assert page2.status_code == 200
    assert "Página 1 de 2" in page1.text
    assert "Página 2 de 2" in page2.text
    assert "doc-000.pdf" in page1.text
    assert "doc-024.pdf" in page1.text
    assert "doc-025.pdf" not in page1.text
    assert "doc-029.pdf" in page2.text
    assert "doc-000.pdf" not in page2.text


@pytest.mark.asyncio
async def test_scan_page_cache_tab_search_filters_server_side(tmp_path) -> None:
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
        response = await client.get(f"/projects/{project.name}/scan", params={"tab": "cache", "q": "informe"})

    assert response.status_code == 200
    html = response.text
    assert "informe.pdf" in html
    assert "factura.pdf" not in html
    assert "Mostrando 1–1 de 1 entradas." in html
    assert "<mark>informe</mark>" in html


@pytest.mark.asyncio
async def test_scan_page_cache_tab_escapes_malicious_file_path(tmp_path) -> None:
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
        response = await client.get(f"/projects/{project.name}/scan", params={"tab": "cache"})

    assert response.status_code == 200
    assert "<script>alert(1)</script>" not in response.text
    assert "&lt;" in response.text
    assert "&gt;" in response.text
    assert "&lt;script&gt;alert(1)&lt;/script&gt;.pdf" in response.text


@pytest.mark.asyncio
async def test_scan_page_cache_tab_no_search_box_when_no_entries(tmp_path) -> None:
    registry_path = tmp_path / "projects.json"
    project = await _create_project(tmp_path, registry_path)
    app = create_app(registry_path=registry_path)

    async with _client(app) as client:
        response = await client.get(f"/projects/{project.name}/scan", params={"tab": "cache"})

    assert response.status_code == 200
    assert 'id="cache-search"' not in response.text


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


# ===== WS /api/projects/{name}/scan/deduplicate =====


def _run_dedup_websocket(client: TestClient, project_name: str) -> list[dict]:
    events: list[dict] = []
    with client.websocket_connect(f"/api/projects/{project_name}/scan/deduplicate") as websocket:
        while True:
            message = websocket.receive_json()
            events.append(message)
            if message["event"] == "completed":
                break
    return events


@pytest.mark.asyncio
async def test_deduplicate_websocket_moves_exact_duplicates(tmp_path) -> None:
    registry_path = tmp_path / "projects.json"
    project = await _create_project(tmp_path, registry_path)
    app = create_app(registry_path=registry_path)

    folder = tmp_path / "datos"
    folder.mkdir()
    original = folder / "original.pdf"
    original.write_bytes(b"contenido-duplicado")
    (folder / "copia.pdf").write_bytes(original.read_bytes())

    client = TestClient(app)
    add_response = client.post(f"/api/projects/{project.name}/folders/library", json={"path": str(folder)})
    assert add_response.status_code == 200

    events = _run_dedup_websocket(client, project.name)

    event_types = [event["event"] for event in events]
    assert event_types == ["started", "duplicates_found", "group_started", "group_resolved", "completed"]
    duplicates_found = next(event for event in events if event["event"] == "duplicates_found")
    assert duplicates_found["data"]["groups_found"] == 1
    completed = events[-1]
    duration_seconds = completed["data"].pop("duration_seconds")
    assert completed["data"] == {"groups_found": 1, "moved": 1, "warnings": [], "failed_paths": []}
    assert duration_seconds >= 0.0

    root = Path(project.root_path)
    assert (root / "duplicados" / "DEDUP_REPORT.json").exists()
    assert (root / "duplicados" / "DEDUP_HISTORY.jsonl").exists()
    assert (root / "folders.json").exists()  # sin haber escaneado todavia


@pytest.mark.asyncio
async def test_deduplicate_websocket_never_groups_by_fuzzy_name_match(tmp_path) -> None:
    # Regla de negocio CRITICA: "Buscar duplicados" (esta accion masiva, WS
    # /scan/deduplicate) llama a find_duplicates() SIN fuzzy_threshold -- nunca
    # debe mover nada por similitud aproximada de nombre, solo por hash exacto
    # o conflicto de version. Los nombres de este test son deliberadamente muy
    # parecidos (score RapidFuzz alto, WRatio+normalizado) pero con contenido y base distintos, para
    # que la unica forma de que groups_found > 0 sea que la pasada fuzzy se
    # hubiera colado aqui por error.
    registry_path = tmp_path / "projects.json"
    project = await _create_project(tmp_path, registry_path)
    app = create_app(registry_path=registry_path)

    folder = tmp_path / "datos"
    folder.mkdir()
    (folder / "informe_ventas.pdf").write_bytes(b"contenido a")
    (folder / "informe_ventas_anual.pdf").write_bytes(b"contenido b")

    client = TestClient(app)
    add_response = client.post(f"/api/projects/{project.name}/folders/library", json={"path": str(folder)})
    assert add_response.status_code == 200

    events = _run_dedup_websocket(client, project.name)

    duplicates_found = next(event for event in events if event["event"] == "duplicates_found")
    assert duplicates_found["data"]["groups_found"] == 0
    completed = events[-1]
    assert completed["data"]["moved"] == 0
    assert (folder / "informe_ventas.pdf").exists()
    assert (folder / "informe_ventas_anual.pdf").exists()


@pytest.mark.asyncio
async def test_deduplicate_websocket_rejects_when_no_saved_folders(tmp_path) -> None:
    registry_path = tmp_path / "projects.json"
    project = await _create_project(tmp_path, registry_path)
    app = create_app(registry_path=registry_path)

    client = TestClient(app)
    with (
        pytest.raises(WebSocketDisconnect) as exc_info,
        client.websocket_connect(f"/api/projects/{project.name}/scan/deduplicate") as websocket,
    ):
        websocket.receive_json()
    assert exc_info.value.code == 1008


@pytest.mark.asyncio
async def test_deduplicate_websocket_history_accumulates_across_runs(tmp_path) -> None:
    registry_path = tmp_path / "projects.json"
    project = await _create_project(tmp_path, registry_path)
    app = create_app(registry_path=registry_path)

    folder = tmp_path / "datos"
    folder.mkdir()
    first = folder / "first.pdf"
    first.write_bytes(b"primer-duplicado")
    (folder / "first_copy.pdf").write_bytes(first.read_bytes())

    client = TestClient(app)
    add_response = client.post(f"/api/projects/{project.name}/folders/library", json={"path": str(folder)})
    assert add_response.status_code == 200

    first_events = _run_dedup_websocket(client, project.name)
    assert first_events[-1]["data"]["groups_found"] == 1

    # Segunda tanda de duplicados, tras la primera ejecucion.
    second = folder / "second.pdf"
    second.write_bytes(b"segundo-duplicado")
    (folder / "second_copy.pdf").write_bytes(second.read_bytes())
    second_events = _run_dedup_websocket(client, project.name)
    assert second_events[-1]["data"]["groups_found"] == 1

    history_path = Path(project.root_path) / "duplicados" / "DEDUP_HISTORY.jsonl"
    lines = [line for line in history_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(lines) == 2
    for line in lines:
        json.loads(line)  # cada linea es un DeduplicationReport valido por si solo


@pytest.mark.asyncio
async def test_deduplicate_websocket_rejects_path_outside_allowed_roots(tmp_path) -> None:
    """Acceso implícito por proyecto (rediseño Tenant/Role/User): la única raíz
    permitida para un rol restringido es `project.root_path` — una carpeta fuera
    de ella, aunque ya esté guardada en el store, debe seguir rechazándose."""
    auth_db_path = tmp_path / "auth.db"
    async with AuthStore(auth_db_path) as store:
        tenant = await store.create_tenant("Acme Corp")
        role = await store.create_role("Lector", project_names=["Proyecto Scan"])
        alice = await store.create_user(tenant.id, "alice", "s3cr3t-password", role_id=role.id)
        session = await store.create_session(alice)

    registry_path = tmp_path / "projects.json"
    project = await _create_project(tmp_path, registry_path, tenant_id=tenant.id)
    security = SecurityConfig(bind_host="0.0.0.0")
    app = create_app(security=security, registry_path=registry_path, auth_db_path=auth_db_path)

    # Fuera de `project.root_path` (hermana de la carpeta del proyecto, no dentro):
    # guardada directamente en el store (no vía API), simulando una carpeta dada de
    # alta antes de que el rol quedara restringido — la propia API de guardado ya
    # rechazaría este alta para este rol.
    outside_path = tmp_path / "outside-root"
    outside_path.mkdir()
    await ScannedFoldersStore().add_folder(project, str(outside_path))

    client = TestClient(app, cookies={SESSION_COOKIE_NAME: session.token})
    with (
        pytest.raises(WebSocketDisconnect) as exc_info,
        client.websocket_connect(f"/api/projects/{project.name}/scan/deduplicate") as websocket,
    ):
        websocket.receive_json()
    assert exc_info.value.code == 1008


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
    assert events[-1]["data"]["duration_seconds"] > 0

    # Descubrimiento de ficheros (ya calculado por DocumentScanner, ahora
    # tambien surfaced en el evento SCANNED y en el resumen final).
    scanned_event = next(event for event in events if event["event"] == "scanned")
    assert scanned_event["data"]["discovery_duration_seconds"] >= 0.0
    assert events[-1]["data"]["discovery_duration_seconds"] >= 0.0
    # Sin documentos que convertir, el acumulado de conversion es 0.
    assert events[-1]["data"]["total_conversion_seconds"] == 0.0

    # El histórico de duración de ejecuciones (nueva funcionalidad) registra esta
    # ejecución como completada.
    history_path = tmp_path / "workspaces" / project.name / SCAN_HISTORY_FOLDER_NAME / SCAN_HISTORY_JSONL_NAME
    assert history_path.is_file()
    history_entry = json.loads(history_path.read_text(encoding="utf-8").strip())
    assert history_entry["completed"] is True
    assert history_entry["total_scanned"] == 0
    assert history_entry["discovery_duration_seconds"] >= 0.0
    assert history_entry["total_conversion_seconds"] == 0.0


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
async def test_scan_websocket_rejects_non_json_payload(tmp_path) -> None:
    """AUDIT_CODE (sesión 2026-09-03): un payload no-JSON lanzaba antes
    `json.JSONDecodeError` sin capturar en vez de cerrar limpio con `code=1008`,
    como hace el resto de esta función ante entrada inválida."""
    registry_path = tmp_path / "projects.json"
    project = await _create_project(tmp_path, registry_path)
    app = create_app(registry_path=registry_path)

    client = TestClient(app)
    with pytest.raises(WebSocketDisconnect) as exc_info, client.websocket_connect(f"/api/projects/{project.name}/scan") as websocket:
        websocket.send_text("esto no es json{{{")
        websocket.receive_json()
    assert exc_info.value.code == 1008


@pytest.mark.asyncio
async def test_scan_websocket_rejects_non_dict_json_payload(tmp_path) -> None:
    """Mismo caso que el anterior (AUDIT_CODE, sesión 2026-09-03), pero con JSON
    válido que no es un objeto (p.ej. una lista) — antes lanzaba `AttributeError`
    sin capturar al llamar a `.get()` sobre él."""
    registry_path = tmp_path / "projects.json"
    project = await _create_project(tmp_path, registry_path)
    app = create_app(registry_path=registry_path)

    client = TestClient(app)
    with pytest.raises(WebSocketDisconnect) as exc_info, client.websocket_connect(f"/api/projects/{project.name}/scan") as websocket:
        websocket.send_json(["use_ocr", False])
        websocket.receive_json()
    assert exc_info.value.code == 1008


@pytest.mark.asyncio
async def test_scan_websocket_rejects_when_project_already_has_operation_in_progress(tmp_path) -> None:
    """AUDIT_CODE (sesión 2026-09-04): un escaneo y una deduplicación (o dos
    escaneos) del MISMO proyecto no estaban coordinados entre sí -- ambos
    leen/escriben cache.db/Conversión/mueven ficheros duplicados sin ningún
    lock compartido. Ahora una segunda operación sobre el mismo proyecto se
    rechaza mientras la primera sigue en curso (simulada aquí fijando
    directamente el estado que dejaría una primera conexión real a mitad de
    la operación, sin depender de temporización real)."""
    registry_path = tmp_path / "projects.json"
    project = await _create_project(tmp_path, registry_path)
    app = create_app(registry_path=registry_path)

    app.state.active_project_operations.add(("default", project.name.lower()))

    client = TestClient(app)
    with pytest.raises(WebSocketDisconnect) as exc_info, client.websocket_connect(f"/api/projects/{project.name}/scan") as websocket:
        websocket.send_json({"use_ocr": False, "use_gpu": False})
        websocket.receive_json()
    assert exc_info.value.code == 1008


@pytest.mark.asyncio
async def test_deduplicate_websocket_rejects_when_scan_already_in_progress(tmp_path) -> None:
    """Mismo lock compartido entre `scan_websocket` y `deduplicate_websocket`
    (AUDIT_CODE, sesión 2026-09-04): un escaneo en curso también bloquea una
    deduplicación sobre el mismo proyecto, no solo otro escaneo."""
    registry_path = tmp_path / "projects.json"
    project = await _create_project(tmp_path, registry_path)
    app = create_app(registry_path=registry_path)

    folder = tmp_path / "datos"
    folder.mkdir()
    client = TestClient(app)
    add_response = client.post(f"/api/projects/{project.name}/folders/library", json={"path": str(folder)})
    assert add_response.status_code == 200

    app.state.active_project_operations.add(("default", project.name.lower()))

    with (
        pytest.raises(WebSocketDisconnect) as exc_info,
        client.websocket_connect(f"/api/projects/{project.name}/scan/deduplicate") as websocket,
    ):
        websocket.receive_json()
    assert exc_info.value.code == 1008


@pytest.mark.asyncio
async def test_scan_websocket_releases_lock_after_completion_allowing_next_scan(tmp_path) -> None:
    """El lock se libera al terminar (`finally`), incluso en el camino feliz --
    un segundo escaneo del mismo proyecto, tras completarse el primero, no debe
    quedar bloqueado para siempre."""
    registry_path = tmp_path / "projects.json"
    project = await _create_project(tmp_path, registry_path)
    app = create_app(registry_path=registry_path)

    empty_input = tmp_path / "empty-input"
    empty_input.mkdir()
    client = TestClient(app)
    add_response = client.post(f"/api/projects/{project.name}/folders/library", json={"path": str(empty_input)})
    assert add_response.status_code == 200

    for _ in range(2):
        with client.websocket_connect(f"/api/projects/{project.name}/scan") as websocket:
            websocket.send_json({"use_ocr": False, "use_gpu": False})
            while websocket.receive_json()["event"] != "completed":
                pass

    assert app.state.active_project_operations == set()


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

    # Duración de conversión por documento (ConversionResult.duration_seconds,
    # antes calculada y descartada) ahora viaja en el evento y se acumula en el
    # resumen final.
    file_converted_event = next(event for event in events if event["event"] == "file_converted")
    assert file_converted_event["data"]["duration_seconds"] >= 0.0
    assert events[-1]["data"]["total_conversion_seconds"] >= 0.0


@pytest.mark.slow
@pytest.mark.asyncio
async def test_scan_websocket_propagates_audio_video_and_extract_images_flags(tmp_path, native_pdf) -> None:
    """Flags nuevos (sesion 'soporte de formatos docling') llegan desde el payload
    JSON del WebSocket hasta `ScanCommand.run_streaming`: `.txt` ya se escanea
    siempre (sin flag, forma parte de `SUPPORTED_EXTENSIONS`), `include_audio_video`
    hace que se recoja tambien el audio de la carpeta (aunque su conversion pueda
    fallar sin el extra `[av]` instalado en este entorno de test — lo relevante es
    que se DESCUBRA, no que se convierta con exito), y `extract_images` no rompe la
    conversion de un documento sin imagenes embebidas."""
    registry_path = tmp_path / "projects.json"
    project = await _create_project(tmp_path, registry_path)
    app = create_app(registry_path=registry_path)

    (native_pdf.parent / "notes.txt").write_text("nota suelta, siempre escaneada", encoding="utf-8")
    (native_pdf.parent / "clip.mp3").write_bytes(b"fake-audio-content")

    client = TestClient(app)
    add_response = client.post(f"/api/projects/{project.name}/folders/library", json={"path": str(native_pdf.parent)})
    assert add_response.status_code == 200

    with client.websocket_connect(f"/api/projects/{project.name}/scan") as websocket:
        websocket.send_json(
            {
                "use_ocr": False,
                "use_gpu": False,
                "include_audio_video": True,
                "extract_images": True,
                "use_picture_description": False,
            }
        )
        events = []
        while True:
            message = websocket.receive_json()
            events.append(message)
            if message["event"] == "completed":
                break

    # pdf + txt (siempre) + mp3 (opt-in via include_audio_video)
    assert events[-1]["data"]["scanned"] == 3
    # pdf + txt deben convertir bien; el mp3 puede fallar si el entorno de test no
    # tiene el extra [av] instalado — no se afirma nada sobre su resultado concreto.
    assert events[-1]["data"]["converted"] >= 2


@pytest.mark.slow
@pytest.mark.asyncio
async def test_scan_websocket_force_reconverts_unchanged_document(tmp_path, native_pdf) -> None:
    registry_path = tmp_path / "projects.json"
    project = await _create_project(tmp_path, registry_path)
    app = create_app(registry_path=registry_path)

    client = TestClient(app)
    add_response = client.post(f"/api/projects/{project.name}/folders/library", json={"path": str(native_pdf.parent)})
    assert add_response.status_code == 200

    def _scan(payload: dict) -> list[dict]:
        with client.websocket_connect(f"/api/projects/{project.name}/scan") as websocket:
            websocket.send_json(payload)
            events = []
            while True:
                message = websocket.receive_json()
                events.append(message)
                if message["event"] == "completed":
                    break
            return events

    _scan({"use_ocr": False, "use_gpu": False})
    unchanged_events = _scan({"use_ocr": False, "use_gpu": False})
    assert unchanged_events[-1]["data"]["converted"] == 0  # sin force, no se reconvierte

    forced_events = _scan({"use_ocr": False, "use_gpu": False, "force": True})
    assert forced_events[-1]["data"]["converted"] == 1  # con force, se reconvierte igual


@pytest.mark.slow
@pytest.mark.asyncio
async def test_scan_websocket_retries_error_entries_without_force(tmp_path, native_pdf) -> None:
    """Un fichero sin cambios cuya conversión anterior quedó en ERROR debe
    reintentarse en un escaneo normal — antes quedaba excluido para siempre
    (`get_changes()` lo clasifica como `unchanged` por hash, y solo
    `force=True`, que reprocesa todo el proyecto, volvía a intentarlo)."""
    registry_path = tmp_path / "projects.json"
    project = await _create_project(tmp_path, registry_path)
    app = create_app(registry_path=registry_path)

    client = TestClient(app)
    add_response = client.post(f"/api/projects/{project.name}/folders/library", json={"path": str(native_pdf.parent)})
    assert add_response.status_code == 200

    def _scan(payload: dict) -> list[dict]:
        with client.websocket_connect(f"/api/projects/{project.name}/scan") as websocket:
            websocket.send_json(payload)
            events = []
            while True:
                message = websocket.receive_json()
                events.append(message)
                if message["event"] == "completed":
                    break
            return events

    first_events = _scan({"use_ocr": False, "use_gpu": False})
    assert first_events[-1]["data"]["converted"] == 1

    cache_db = tmp_path / "workspaces" / project.name / DEFAULT_CACHE_DB_NAME
    async with CacheManager(cache_db) as cache:
        cached = await cache.load_cache()
        ((file_path, entry),) = cached.items()
        await cache.save_entries(
            [
                CacheEntry(
                    file_path=entry.file_path,
                    sha256_hash=entry.sha256_hash,
                    timestamp=entry.timestamp,
                    status=DocumentStatus.UNCHANGED,
                    conversion_status=ConversionStatus.ERROR,
                    error_message="fallo simulado en un escaneo anterior",
                )
            ]
        )

    retry_events = _scan({"use_ocr": False, "use_gpu": False})
    assert retry_events[-1]["data"]["unchanged"] == 1  # el hash no cambió
    assert retry_events[-1]["data"]["converted"] == 1  # pero se reintentó por estar en ERROR
    assert retry_events[-1]["data"]["error_retries"] == 1

    async with CacheManager(cache_db) as cache:
        reloaded = await cache.load_cache()
    assert reloaded[file_path].conversion_status == ConversionStatus.SUCCESS
    assert reloaded[file_path].error_message is None
    assert reloaded[file_path].error_retry_count == 0


@pytest.mark.asyncio
async def test_scan_websocket_does_not_retry_error_entry_past_retry_limit(tmp_path, native_pdf) -> None:
    """Un fichero en ERROR que ya acumula `MAX_AUTO_ERROR_RETRIES` fallos
    consecutivos deja de reintentarse en escaneos normales (evita reprocesar
    para siempre un fichero irrecuperable) — pero el escaneo lo refleja en
    `error_retries_capped`, no lo descarta en silencio (ver AUDIT_PLAN)."""
    registry_path = tmp_path / "projects.json"
    project = await _create_project(tmp_path, registry_path)
    app = create_app(registry_path=registry_path)

    client = TestClient(app)
    add_response = client.post(f"/api/projects/{project.name}/folders/library", json={"path": str(native_pdf.parent)})
    assert add_response.status_code == 200

    from doc_organize.core.constants import MAX_AUTO_ERROR_RETRIES
    from doc_organize.utils.hash_utils import hash_file

    file_hash = await hash_file(str(native_pdf))
    cache_db = tmp_path / "workspaces" / project.name / DEFAULT_CACHE_DB_NAME
    async with CacheManager(cache_db) as cache:
        await cache.save_entries(
            [
                CacheEntry(
                    file_path=str(native_pdf),
                    sha256_hash=file_hash,
                    timestamp=native_pdf.stat().st_mtime,
                    status=DocumentStatus.UNCHANGED,
                    conversion_status=ConversionStatus.ERROR,
                    error_message="fallo persistente",
                    error_retry_count=MAX_AUTO_ERROR_RETRIES,
                )
            ]
        )

    with client.websocket_connect(f"/api/projects/{project.name}/scan") as websocket:
        websocket.send_json({"use_ocr": False, "use_gpu": False})
        events = []
        while True:
            message = websocket.receive_json()
            events.append(message)
            if message["event"] == "completed":
                break

    assert events[-1]["data"]["converted"] == 0  # no se reintenta: limite ya alcanzado
    assert events[-1]["data"]["error_retries"] == 0
    assert events[-1]["data"]["error_retries_capped"] == 1

    async with CacheManager(cache_db) as cache:
        reloaded = await cache.load_cache()
    # La entrada no se toca: sigue en ERROR con el mismo contador y mensaje.
    assert reloaded[str(native_pdf)].conversion_status == ConversionStatus.ERROR
    assert reloaded[str(native_pdf)].error_retry_count == MAX_AUTO_ERROR_RETRIES


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
    """Acceso implícito por proyecto (rediseño Tenant/Role/User): un rol restringido
    no puede escanear una ruta fuera de `project.root_path`, aunque tenga acceso
    al proyecto."""
    auth_db_path = tmp_path / "auth.db"
    async with AuthStore(auth_db_path) as store:
        tenant = await store.create_tenant("Acme Corp")
        role = await store.create_role("Lector", project_names=["Proyecto Scan"])
        alice = await store.create_user(tenant.id, "alice", "s3cr3t-password", role_id=role.id)
        session = await store.create_session(alice)

    registry_path = tmp_path / "projects.json"
    project = await _create_project(tmp_path, registry_path, tenant_id=tenant.id)
    security = SecurityConfig(bind_host="0.0.0.0")
    app = create_app(security=security, registry_path=registry_path, auth_db_path=auth_db_path)

    outside_path = tmp_path / "outside-root"
    outside_path.mkdir()
    # Se guarda directamente en el store (no vía API): simula una carpeta guardada
    # antes de que el proyecto se moviera, o dada de alta por un admin — la propia
    # API de guardado ya rechazaría este alta para este rol (fuera de root_path).
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
        role = await store.create_role("Lector", project_names=["Proyecto Scan"])
        alice = await store.create_user(tenant.id, "alice", "s3cr3t-password", role_id=role.id)
        session = await store.create_session(alice)

    registry_path = tmp_path / "projects.json"
    project = await _create_project(tmp_path, registry_path, tenant_id=tenant.id)
    security = SecurityConfig(bind_host="0.0.0.0")
    app = create_app(security=security, registry_path=registry_path, auth_db_path=auth_db_path)

    # Dentro de `project.root_path` (acceso implícito, rediseño Tenant/Role/User):
    # un rol restringido con acceso al proyecto puede escanear cualquier
    # subcarpeta de su propia carpeta de trabajo.
    inside_path = Path(project.root_path) / "entrada"
    inside_path.mkdir()

    client = TestClient(app, cookies={SESSION_COOKIE_NAME: session.token})
    add_response = client.post(f"/api/projects/{project.name}/folders/library", json={"path": str(inside_path)})
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
async def test_folder_library_get_filters_out_folders_outside_allowed_roots(tmp_path) -> None:
    """AUDIT_CODE (sesión 2026-09-03/04); rediseño Tenant/Role/User: antes
    `GET .../folders/library` devolvía la lista completa sin filtrar — un rol
    restringido con acceso al proyecto podía ver rutas absolutas del servidor
    guardadas por otro usuario/admin fuera de `project.root_path`. Ahora se
    filtran, mismo criterio que ya se exigía al dar de alta una carpeta."""
    auth_db_path = tmp_path / "auth.db"
    async with AuthStore(auth_db_path) as store:
        tenant = await store.create_tenant("Acme Corp")
        role = await store.create_role("Lector", project_names=["Proyecto Scan"])
        alice = await store.create_user(tenant.id, "alice", "s3cr3t-password", role_id=role.id)
        session = await store.create_session(alice)

    registry_path = tmp_path / "projects.json"
    project = await _create_project(tmp_path, registry_path, tenant_id=tenant.id)
    security = SecurityConfig(bind_host="0.0.0.0")
    app = create_app(security=security, registry_path=registry_path, auth_db_path=auth_db_path)

    inside_path = Path(project.root_path) / "entrada"
    inside_path.mkdir()
    outside_path = tmp_path / "outside-root"
    outside_path.mkdir()
    # Guardadas directamente en el store (no vía API), simulando carpetas dadas
    # de alta por un admin (u otro rol) antes/fuera de esta restricción.
    await ScannedFoldersStore().add_folder(project, str(outside_path))
    await ScannedFoldersStore().add_folder(project, str(inside_path))

    client = TestClient(app, cookies={SESSION_COOKIE_NAME: session.token})
    response = client.get(f"/api/projects/{project.name}/folders/library")

    assert response.status_code == 200
    paths = {entry["path"] for entry in response.json()}
    assert paths == {str(inside_path.resolve())}  # la de fuera de ambito no aparece


@pytest.mark.asyncio
async def test_folder_library_delete_rejects_folder_outside_allowed_roots(tmp_path) -> None:
    """AUDIT_CODE (sesión 2026-09-03/04); rediseño Tenant/Role/User: antes
    `DELETE .../folders/library` borraba cualquier entrada no usada sin exigir
    acceso a esa ruta. Ahora aplica la misma restricción implícita
    (`project.root_path`) que `add_folder_to_library`."""
    auth_db_path = tmp_path / "auth.db"
    async with AuthStore(auth_db_path) as store:
        tenant = await store.create_tenant("Acme Corp")
        role = await store.create_role("Lector", project_names=["Proyecto Scan"])
        alice = await store.create_user(tenant.id, "alice", "s3cr3t-password", role_id=role.id)
        session = await store.create_session(alice)

    registry_path = tmp_path / "projects.json"
    project = await _create_project(tmp_path, registry_path, tenant_id=tenant.id)
    security = SecurityConfig(bind_host="0.0.0.0")
    app = create_app(security=security, registry_path=registry_path, auth_db_path=auth_db_path)

    outside_path = tmp_path / "outside-root"
    outside_path.mkdir()
    await ScannedFoldersStore().add_folder(project, str(outside_path))

    client = TestClient(app, cookies={SESSION_COOKIE_NAME: session.token})
    response = client.request("DELETE", f"/api/projects/{project.name}/folders/library", json={"path": str(outside_path)})

    assert response.status_code == 403
    # sigue en la lista (no se llego a borrar) -- comprobado directamente en el
    # store, ya que el propio GET la filtraria del listado de este rol.
    remaining = await ScannedFoldersStore().list_folders(project)
    assert str(outside_path.resolve()) in {folder.path for folder in remaining}


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
