"""Tests de las rutas web de Contexto (construir/ver el contexto de un proyecto)."""

import json

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


async def _create_project(tmp_path, registry_path, name: str = "Proyecto Contexto", tenant_id: str = "default"):
    base = tmp_path / "workspaces"
    base.mkdir(exist_ok=True)
    async with ProjectRegistry(registry_path) as registry:
        return await registry.create_project(name, base, tenant_id=tenant_id)


def _seed_converted_document(project_root: Path, stem: str, title: str) -> str:
    """Crea el original + `.md` + `.json` de un documento ya "convertido" (sin
    carpetas de escaneo guardadas, `resolve_output_paths` cae al layout plano
    bajo `Conversión/`) y devuelve la `file_path` a registrar en `cache.db`."""
    source_dir = project_root / "Ciberseguridad"
    source_dir.mkdir(parents=True, exist_ok=True)
    source = source_dir / f"{stem}.pdf"
    source.write_bytes(b"%PDF-1.4")

    output_dir = project_root / "Conversión"
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / f"{stem}.md").write_text(f"# {title}", encoding="utf-8")
    (output_dir / f"{stem}.json").write_text(json.dumps({"title": title, "chunks": []}), encoding="utf-8")
    return str(source)


@pytest.mark.asyncio
async def test_context_page_404_for_missing_project(tmp_path) -> None:
    app = create_app(registry_path=tmp_path / "projects.json")
    async with _client(app) as client:
        response = await client.get("/projects/No Existe/context")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_context_page_empty_state(tmp_path) -> None:
    registry_path = tmp_path / "projects.json"
    project = await _create_project(tmp_path, registry_path)
    app = create_app(registry_path=registry_path)

    async with _client(app) as client:
        response = await client.get(f"/projects/{project.name}/context")

    assert response.status_code == 200
    assert "Todavía no se ha construido el contexto de este proyecto." in response.text


@pytest.mark.asyncio
async def test_get_context_api_404_before_build(tmp_path) -> None:
    registry_path = tmp_path / "projects.json"
    project = await _create_project(tmp_path, registry_path)
    app = create_app(registry_path=registry_path)

    async with _client(app) as client:
        response = await client.get(f"/api/projects/{project.name}/context")

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_build_context_classifies_reorganizes_and_generates_mkdocs(tmp_path) -> None:
    registry_path = tmp_path / "projects.json"
    project = await _create_project(tmp_path, registry_path)
    project_root = tmp_path / "workspaces" / project.name
    file_path = _seed_converted_document(project_root, "informe", "Informe anual")

    cache_db = project_root / DEFAULT_CACHE_DB_NAME
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
        response = await client.post(f"/api/projects/{project.name}/context")

    assert response.status_code == 200
    body = response.json()
    assert body["domains"] == [{"slug": "ciberseguridad", "name": "Ciberseguridad", "status": "borrador", "document_count": 1}]

    assert (project_root / "organizado" / "ciberseguridad" / "pdf" / "informe" / "informe.pdf").exists()
    assert (project_root / "mkdocs.yml").exists()

    async with _client(app) as client:
        get_response = await client.get(f"/api/projects/{project.name}/context")
    assert get_response.status_code == 200
    assert get_response.json()["domains"][0]["slug"] == "ciberseguridad"
    assert get_response.json()["reorganized"] is True
    assert get_response.json()["mkdocs_generated"] is True


@pytest.mark.asyncio
async def test_build_context_partial_failure_persists_honest_state(tmp_path) -> None:
    """Si `Reorganizer` falla a mitad, `context.json` debe reflejarlo (`reorganized:
    false`) en vez de quedar como si la construcción hubiese terminado bien."""
    registry_path = tmp_path / "projects.json"
    project = await _create_project(tmp_path, registry_path)
    project_root = tmp_path / "workspaces" / project.name
    file_path = _seed_converted_document(project_root, "informe", "Informe anual")

    cache_db = project_root / DEFAULT_CACHE_DB_NAME
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
    # El `.md` desaparece justo antes de construir el contexto (el original y el
    # `.json` siguen intactos, así que `_gather_converted_documents` no lo filtra
    # y la Sub-fase A clasifica con éxito leyendo el `.json`) — `Reorganizer` no
    # puede copiar un `.md` ausente. Borrar el original en su lugar ya no
    # reproduce este caso: `_gather_converted_documents` lo excluye antes de
    # clasificar nada (AUDIT_CODE, sesión 2026-09-09, fix 3).
    (project_root / "Conversión" / "informe.md").unlink()

    app = create_app(registry_path=registry_path)
    async with _client(app) as client:
        response = await client.post(f"/api/projects/{project.name}/context")
    assert response.status_code == 400

    async with _client(app) as client:
        get_response = await client.get(f"/api/projects/{project.name}/context")
    assert get_response.status_code == 200
    body = get_response.json()
    assert body["reorganized"] is False
    assert body["mkdocs_generated"] is False
    assert body["domains"][0]["document_count"] == 1  # clasificado, aunque no reorganizado


@pytest.mark.asyncio
async def test_build_context_rejected_while_operation_in_progress(tmp_path) -> None:
    registry_path = tmp_path / "projects.json"
    project = await _create_project(tmp_path, registry_path)
    app = create_app(registry_path=registry_path)
    app.state.active_project_operations.add(("default", project.name.lower()))

    async with _client(app) as client:
        response = await client.post(f"/api/projects/{project.name}/context")

    assert response.status_code == 409


@pytest.mark.asyncio
async def test_build_context_with_ai_enabled_but_no_proxy_configured_returns_400(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("DOC_ORGANIZE_LITELLM_CLASSIFICATION_BASE_URL", raising=False)
    monkeypatch.delenv("DOC_ORGANIZE_LITELLM_CLASSIFICATION_VIRTUAL_KEY", raising=False)
    registry_path = tmp_path / "projects.json"
    project = await _create_project(tmp_path, registry_path)
    app = create_app(registry_path=registry_path)

    async with _client(app) as client:
        response = await client.post(f"/api/projects/{project.name}/context", json={"ai_classification_enabled": True})
    assert response.status_code == 400

    # El lock de operación se libera incluso si falla antes de clasificar nada —
    # una segunda petición no se queda bloqueada por un 409 residual.
    async with _client(app) as client:
        second_response = await client.post(f"/api/projects/{project.name}/context", json={"ai_classification_enabled": True})
    assert second_response.status_code == 400


@pytest.mark.asyncio
async def test_build_context_skips_cache_entries_whose_original_no_longer_exists(tmp_path) -> None:
    """Una entrada `SUCCESS` en `cache.db` cuyo original ya no existe (p. ej.
    movido a `duplicados/` por una deduplicación que no actualiza `cache.db`) se
    omite en vez de intentar clasificarla/reorganizarla y fallar con un error
    confuso (AUDIT_CODE, sesión 2026-09-09, fix 3)."""
    registry_path = tmp_path / "projects.json"
    project = await _create_project(tmp_path, registry_path)
    project_root = tmp_path / "workspaces" / project.name
    file_path = _seed_converted_document(project_root, "informe", "Informe anual")
    Path(file_path).unlink()  # el original "ya se movió" — cache.db no se enteró

    cache_db = project_root / DEFAULT_CACHE_DB_NAME
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
        response = await client.post(f"/api/projects/{project.name}/context")

    assert response.status_code == 200
    body = response.json()
    assert body["domains"] == []
    assert body["unclassified_count"] == 0  # ni clasificado ni "sin clasificar": se omitió antes
    assert body["reorganized"] is True
    assert body["mkdocs_generated"] is True


@pytest.mark.asyncio
async def test_context_page_tenant_isolation(tmp_path) -> None:
    registry_path = tmp_path / "projects.json"
    project = await _create_project(tmp_path, registry_path, tenant_id="acme-corp")

    app = create_app(registry_path=registry_path)
    async with _client(app) as client:
        response = await client.get(f"/projects/{project.name}/context")

    assert response.status_code == 404
