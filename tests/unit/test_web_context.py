"""Tests de las rutas web de Contexto (construir/ver el contexto de un proyecto)."""

import json
import re

from pathlib import Path
from urllib.parse import quote

import httpx
import pytest

from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from doc_organize.cache import CacheManager
from doc_organize.context import ContextRegistry
from doc_organize.core.constants import DEFAULT_CACHE_DB_NAME
from doc_organize.core.models import CacheEntry, ConversionStatus, DocumentStatus, Project
from doc_organize.projects import ProjectRegistry
from doc_organize.web import create_app


def _client(app, base_url: str = "http://testserver") -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=base_url)


def _ai_toggle_tag(html: str) -> str:
    match = re.search(r'<input[^>]*id="ai-classification-toggle"[^>]*>', html, re.DOTALL)
    assert match is not None, "No se encontró el checkbox #ai-classification-toggle en el HTML"
    return match.group()


@pytest.fixture(autouse=True)
def _no_real_mkdocs_build(monkeypatch):
    """Ninguno de estos tests ejercita `mkdocs build` de verdad (lento, y depende
    de que `mkdocs` esté instalado en el entorno) — ese comportamiento se cubre
    aparte en `test_mkdocs_generator.py`."""
    monkeypatch.setattr("doc_organize.context.mkdocs_generator.shutil.which", lambda _name: None)


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


async def _build_context_with_fake_site(client: httpx.AsyncClient, project: Project, project_root: Path) -> None:
    """Construye el contexto (con `mkdocs build` real deshabilitado, ver
    `_no_real_mkdocs_build`) y simula a mano lo que dejaría un `mkdocs build` real
    en disco — `site/index.html` + una página de dominio con `use_directory_urls`
    (`site/<dominio>/index.html`) — marcando `mkdocs_site_built=True`, para poder
    probar `context_site_index`/`context_site_asset` sin depender de tener
    `mkdocs` instalado en el entorno de tests."""
    response = await client.post(f"/api/projects/{project.name}/context")
    assert response.status_code == 200

    site_dir = project_root / "site"
    (site_dir / "ciberseguridad").mkdir(parents=True, exist_ok=True)
    (site_dir / "index.html").write_text("<html><body>Inicio del sitio</body></html>", encoding="utf-8")
    (site_dir / "ciberseguridad" / "index.html").write_text("<html><body>Dominio Ciberseguridad</body></html>", encoding="utf-8")

    registry = ContextRegistry()
    context = await registry.load_context(project)
    context.mkdocs_site_built = True
    await registry.save_context(project, context)


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


def _seed_taxonomy_manifest(project_root: Path, domain_slug: str = "ciberseguridad", domain_name: str = "Ciberseguridad") -> None:
    """Escribe un `taxonomy_manifest.md` mínimo (front matter YAML + prosa libre) — mismo
    fichero que `_load_taxonomy_manifest_or_400` (`web/routes/context.py`) carga
    automáticamente si existe, sin que el llamador tenga que activar nada en el payload."""
    manifest_body = f"""---
domains:
  - slug: {domain_slug}
    name: {domain_name}
material_types:
  - slug: normativa
    name: Normativa
  - slug: procedimiento
    name: Procedimiento
---

# Taxonomía de prueba
"""
    (project_root / "taxonomy_manifest.md").write_text(manifest_body, encoding="utf-8")


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
async def test_build_context_copies_extracted_images(tmp_path) -> None:
    """Regresión: `_gather_converted_documents` debe recalcular `images_dir` (no
    persistido en `cache.db` ni en `document.json`) para que `Reorganizer` copie
    la carpeta de imágenes extraídas — de lo contrario MkDocs las sirve rotas
    (AUDIT_CODE, sesión 2026-09-10)."""
    registry_path = tmp_path / "projects.json"
    project = await _create_project(tmp_path, registry_path)
    project_root = tmp_path / "workspaces" / project.name
    file_path = _seed_converted_document(project_root, "informe", "Informe anual")

    images_dir = project_root / "Conversión" / "img" / "informe"
    images_dir.mkdir(parents=True)
    (images_dir / "foto.png").write_bytes(b"\x89PNG")

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
    assert (project_root / "organizado" / "ciberseguridad" / "pdf" / "informe" / "img" / "informe" / "foto.png").read_bytes() == b"\x89PNG"


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


@pytest.mark.asyncio
async def test_context_page_hides_taxonomy_manifest_status_without_manifest(tmp_path) -> None:
    """Sin `taxonomy_manifest.md`, la página no debe insinuar el modo manifiesto — ni el
    aviso de estado ni el botón de despliegue por documento (`domain-toggle-btn`)."""
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
        build_response = await client.post(f"/api/projects/{project.name}/context")
        assert build_response.status_code == 200
        page_response = await client.get(f"/projects/{project.name}/context")

    assert page_response.status_code == 200
    assert "Modo manifiesto de taxonomía activo" not in page_response.text
    assert 'data-target="domain-detail-' not in page_response.text


@pytest.mark.asyncio
async def test_context_page_shows_taxonomy_manifest_status_and_material_type_detail(tmp_path) -> None:
    """Con `taxonomy_manifest.md`, la página debe mostrar el aviso de modo manifiesto
    activo y, al desplegar el dominio, el tipo de material de cada documento (nombre
    legible del catálogo, `DomainDocument.material_type_name`, no el slug crudo)."""
    registry_path = tmp_path / "projects.json"
    project = await _create_project(tmp_path, registry_path)
    project_root = tmp_path / "workspaces" / project.name
    # Carpeta "Ciberseguridad" para el bonus de ruta del eje de dominio; el título
    # incluye la palabra "normativa" para puntuar ese tipo de material (mismo criterio
    # de puntuación que `domain_classifier.score_catalog`, ver docs/functional/context.md).
    file_path = _seed_converted_document(project_root, "politica", "Normativa de seguridad")
    _seed_taxonomy_manifest(project_root)

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
        build_response = await client.post(f"/api/projects/{project.name}/context", json={"threshold": 0.1})
        assert build_response.status_code == 200
        page_response = await client.get(f"/projects/{project.name}/context")

    assert page_response.status_code == 200
    html = page_response.text
    assert "Modo manifiesto de taxonomía activo" in html
    assert 'class="domain-toggle-btn' in html
    assert "Tipo de material" in html
    assert "Normativa de seguridad" in html  # título del documento en la fila de detalle
    assert re.search(r">\s*Normativa\s*<", html)  # material_type_name del catálogo, no el slug "normativa"


@pytest.mark.asyncio
async def test_build_context_accepts_custom_output_folder_name_on_first_build(tmp_path) -> None:
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
        response = await client.post(f"/api/projects/{project.name}/context", json={"output_folder_name": "docs_publicados"})

    assert response.status_code == 200
    assert response.json()["output_folder_name"] == "docs_publicados"
    assert (project_root / "docs_publicados" / "ciberseguridad" / "pdf" / "informe").is_dir()
    assert not (project_root / "organizado").exists()


@pytest.mark.asyncio
async def test_build_context_rejects_path_traversal_in_output_folder_name(tmp_path) -> None:
    registry_path = tmp_path / "projects.json"
    project = await _create_project(tmp_path, registry_path)
    app = create_app(registry_path=registry_path)

    async with _client(app) as client:
        response = await client.post(f"/api/projects/{project.name}/context", json={"output_folder_name": "../fuera"})

    assert response.status_code == 400


@pytest.mark.parametrize(
    "reserved_name", ["Conversión", "conversión", "domains", "DOMAINS", "site", "duplicados", "historial_escaneo", "errores_escaneo"]
)
@pytest.mark.asyncio
async def test_build_context_rejects_output_folder_name_reserved_by_another_subsystem(tmp_path, reserved_name) -> None:
    """Sin este rechazo, elegir "Conversión"/"domains" como `output_folder_name`
    haría que `Reorganizer` escribiera dentro de la carpeta de otro subsistema, y
    que `DELETE .../context` (que hace `shutil.rmtree` sobre `output_folder_name`)
    pudiera borrar por completo esa carpeta ajena (p. ej. todo lo convertido del
    proyecto, si coincide con "Conversión") — AUDIT_CODE, sesión 2026-09-10."""
    registry_path = tmp_path / "projects.json"
    project = await _create_project(tmp_path, registry_path)
    app = create_app(registry_path=registry_path)

    async with _client(app) as client:
        response = await client.post(f"/api/projects/{project.name}/context", json={"output_folder_name": reserved_name})

    assert response.status_code == 400


@pytest.mark.asyncio
async def test_build_context_ignores_output_folder_name_change_on_rebuild(tmp_path) -> None:
    """`output_folder_name` solo es elegible la primera vez — una vez construido el
    contexto, una reconstrucción con un valor distinto lo ignora en silencio."""
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
        first = await client.post(f"/api/projects/{project.name}/context", json={"output_folder_name": "primera"})
    assert first.json()["output_folder_name"] == "primera"

    async with _client(app) as client:
        second = await client.post(f"/api/projects/{project.name}/context", json={"output_folder_name": "segunda"})
    assert second.status_code == 200
    assert second.json()["output_folder_name"] == "primera"
    assert (project_root / "primera").exists()
    assert not (project_root / "segunda").exists()


@pytest.mark.asyncio
async def test_delete_context_requires_explicit_confirmation(tmp_path) -> None:
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
        await client.post(f"/api/projects/{project.name}/context")

    async with _client(app) as client:
        response = await client.request("DELETE", f"/api/projects/{project.name}/context", json={"confirm": False})

    assert response.status_code == 400
    assert (project_root / "organizado").exists()


@pytest.mark.asyncio
async def test_delete_context_404_when_nothing_built(tmp_path) -> None:
    registry_path = tmp_path / "projects.json"
    project = await _create_project(tmp_path, registry_path)
    app = create_app(registry_path=registry_path)

    async with _client(app) as client:
        response = await client.request("DELETE", f"/api/projects/{project.name}/context", json={"confirm": True})

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_delete_context_removes_everything_and_allows_choosing_a_new_folder_name(tmp_path) -> None:
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
        await client.post(f"/api/projects/{project.name}/context", json={"output_folder_name": "primera"})
    assert (project_root / "primera").exists()
    assert (project_root / "mkdocs.yml").exists()
    assert (project_root / "context.json").exists()

    async with _client(app) as client:
        delete_response = await client.request("DELETE", f"/api/projects/{project.name}/context", json={"confirm": True})
    assert delete_response.status_code == 204
    assert not (project_root / "primera").exists()
    assert not (project_root / "mkdocs.yml").exists()
    assert not (project_root / "context.json").exists()

    async with _client(app) as client:
        get_after_delete = await client.get(f"/api/projects/{project.name}/context")
    assert get_after_delete.status_code == 404

    async with _client(app) as client:
        rebuild = await client.post(f"/api/projects/{project.name}/context", json={"output_folder_name": "segunda"})
    assert rebuild.status_code == 200
    assert rebuild.json()["output_folder_name"] == "segunda"
    assert (project_root / "segunda").exists()


@pytest.mark.asyncio
async def test_delete_context_rejected_while_operation_in_progress(tmp_path) -> None:
    registry_path = tmp_path / "projects.json"
    project = await _create_project(tmp_path, registry_path)
    app = create_app(registry_path=registry_path)
    app.state.active_project_operations.add(("default", project.name.lower()))

    async with _client(app) as client:
        response = await client.request("DELETE", f"/api/projects/{project.name}/context", json={"confirm": True})

    assert response.status_code == 409


@pytest.mark.asyncio
async def test_context_page_shows_litellm_not_configured_warning(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("DOC_ORGANIZE_LITELLM_CLASSIFICATION_BASE_URL", raising=False)
    monkeypatch.delenv("DOC_ORGANIZE_LITELLM_CLASSIFICATION_VIRTUAL_KEY", raising=False)
    registry_path = tmp_path / "projects.json"
    project = await _create_project(tmp_path, registry_path)
    app = create_app(registry_path=registry_path)

    async with _client(app) as client:
        response = await client.get(f"/projects/{project.name}/context")

    assert response.status_code == 200
    assert "LiteLLM Proxy no configurado" in response.text
    assert "disabled" in _ai_toggle_tag(response.text)
    assert "checked" not in _ai_toggle_tag(response.text)


@pytest.mark.asyncio
async def test_context_page_shows_litellm_configured_confirmation(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("DOC_ORGANIZE_LITELLM_CLASSIFICATION_BASE_URL", "https://proxy.example.test")
    monkeypatch.setenv("DOC_ORGANIZE_LITELLM_CLASSIFICATION_VIRTUAL_KEY", "sk-test")
    registry_path = tmp_path / "projects.json"
    project = await _create_project(tmp_path, registry_path)
    app = create_app(registry_path=registry_path)

    async with _client(app) as client:
        response = await client.get(f"/projects/{project.name}/context")

    assert response.status_code == 200
    assert "LiteLLM Proxy configurado" in response.text
    assert "LiteLLM Proxy no configurado" not in response.text
    assert "disabled" not in _ai_toggle_tag(response.text)


@pytest.mark.asyncio
async def test_context_page_with_manifest_checks_taxonomy_proxy_config_not_the_1_axis_one(tmp_path, monkeypatch) -> None:
    """Con `taxonomy_manifest.md` presente, la página debe consultar la config de
    `TaxonomyClassificationClient` (2 ejes) para decidir si mostrar el checkbox de IA
    habilitado -- que la config de `DomainClassificationClient` (1 eje) esté definida no
    debe bastar, son proxies/env vars separados (ISP, mismo criterio que en `build_context`)."""
    monkeypatch.setenv("DOC_ORGANIZE_LITELLM_CLASSIFICATION_BASE_URL", "https://proxy.example.test")
    monkeypatch.setenv("DOC_ORGANIZE_LITELLM_CLASSIFICATION_VIRTUAL_KEY", "sk-test")
    monkeypatch.delenv("DOC_ORGANIZE_LITELLM_TAXONOMY_CLASSIFICATION_BASE_URL", raising=False)
    monkeypatch.delenv("DOC_ORGANIZE_LITELLM_TAXONOMY_CLASSIFICATION_VIRTUAL_KEY", raising=False)
    registry_path = tmp_path / "projects.json"
    project = await _create_project(tmp_path, registry_path)
    project_root = tmp_path / "workspaces" / project.name
    (project_root / "taxonomy_manifest.md").write_text(_VALID_TAXONOMY_MANIFEST, encoding="utf-8")
    app = create_app(registry_path=registry_path)

    async with _client(app) as client:
        response = await client.get(f"/projects/{project.name}/context")

    assert response.status_code == 200
    assert "LiteLLM Proxy no configurado" in response.text
    assert "disabled" in _ai_toggle_tag(response.text)

    monkeypatch.setenv("DOC_ORGANIZE_LITELLM_TAXONOMY_CLASSIFICATION_BASE_URL", "https://proxy.example.test")
    monkeypatch.setenv("DOC_ORGANIZE_LITELLM_TAXONOMY_CLASSIFICATION_VIRTUAL_KEY", "sk-test")

    async with _client(app) as client:
        second_response = await client.get(f"/projects/{project.name}/context")

    assert "LiteLLM Proxy configurado" in second_response.text
    assert "disabled" not in _ai_toggle_tag(second_response.text)


@pytest.mark.asyncio
async def test_ai_toggle_is_unchecked_and_disabled_if_litellm_becomes_unconfigured_after_being_enabled(tmp_path, monkeypatch) -> None:
    """Si un contexto se construyó con `ai_classification_enabled=True` cuando
    LiteLLM sí estaba configurado, y luego el proxy deja de estarlo, el checkbox
    debe mostrarse desmarcado y deshabilitado (no "marcado pero deshabilitado") —
    así la siguiente reconstrucción nunca reenvía `ai_classification_enabled: true`
    para una casilla que el usuario ya no puede desmarcar desde la UI."""
    monkeypatch.setenv("DOC_ORGANIZE_LITELLM_CLASSIFICATION_BASE_URL", "https://proxy.example.test")
    monkeypatch.setenv("DOC_ORGANIZE_LITELLM_CLASSIFICATION_VIRTUAL_KEY", "sk-test")
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
        build_response = await client.post(f"/api/projects/{project.name}/context", json={"ai_classification_enabled": True})
    assert build_response.status_code == 200
    assert build_response.json()["ai_classification_enabled"] is True

    monkeypatch.delenv("DOC_ORGANIZE_LITELLM_CLASSIFICATION_BASE_URL", raising=False)
    monkeypatch.delenv("DOC_ORGANIZE_LITELLM_CLASSIFICATION_VIRTUAL_KEY", raising=False)
    async with _client(app) as client:
        page_response = await client.get(f"/projects/{project.name}/context")

    tag = _ai_toggle_tag(page_response.text)
    assert "disabled" in tag
    assert "checked" not in tag


# ===== WS /api/projects/{name}/context/build =====


def _run_context_build_websocket(client: TestClient, project_name: str, payload: dict | None = None) -> list[dict]:
    events: list[dict] = []
    with client.websocket_connect(f"/api/projects/{project_name}/context/build") as websocket:
        websocket.send_json(payload or {})
        while True:
            message = websocket.receive_json()
            events.append(message)
            if message["event"] == "completed":
                break
    return events


@pytest.mark.asyncio
async def test_context_build_websocket_reports_progress_and_completes(tmp_path) -> None:
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
    client = TestClient(app)

    events = _run_context_build_websocket(client, project.name)

    event_names = [event["event"] for event in events]
    assert event_names == ["started", "reorganize_started", "document_copied", "mkdocs_started", "completed"]
    reorganize_started = events[1]
    assert reorganize_started["data"] == {"total": 1}
    document_copied = events[2]
    assert document_copied["data"] == {"index": 1, "total": 1, "path": file_path}
    completed = events[-1]
    assert completed["data"]["domains"] == [{"slug": "ciberseguridad", "name": "Ciberseguridad", "status": "borrador", "document_count": 1}]
    assert completed["data"]["reorganized"] is True
    assert completed["data"]["mkdocs_generated"] is True
    assert (project_root / "organizado" / "ciberseguridad" / "pdf" / "informe" / "informe.pdf").exists()


@pytest.mark.asyncio
async def test_context_build_websocket_accepts_custom_output_folder_name(tmp_path) -> None:
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
    client = TestClient(app)

    events = _run_context_build_websocket(client, project.name, {"output_folder_name": "docs_publicados"})

    assert events[-1]["data"]["output_folder_name"] == "docs_publicados"
    assert (project_root / "docs_publicados").is_dir()


@pytest.mark.asyncio
async def test_context_build_websocket_rejects_reserved_output_folder_name(tmp_path) -> None:
    registry_path = tmp_path / "projects.json"
    project = await _create_project(tmp_path, registry_path)
    app = create_app(registry_path=registry_path)
    client = TestClient(app)

    with pytest.raises(WebSocketDisconnect) as exc_info, client.websocket_connect(f"/api/projects/{project.name}/context/build") as websocket:
        websocket.send_json({"output_folder_name": "domains"})
        websocket.receive_json()
    assert exc_info.value.code == 1008


@pytest.mark.asyncio
async def test_context_build_websocket_closes_with_1008_when_ai_enabled_but_litellm_not_configured(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("DOC_ORGANIZE_LITELLM_CLASSIFICATION_BASE_URL", raising=False)
    monkeypatch.delenv("DOC_ORGANIZE_LITELLM_CLASSIFICATION_VIRTUAL_KEY", raising=False)
    registry_path = tmp_path / "projects.json"
    project = await _create_project(tmp_path, registry_path)
    app = create_app(registry_path=registry_path)
    client = TestClient(app)

    with pytest.raises(WebSocketDisconnect) as exc_info, client.websocket_connect(f"/api/projects/{project.name}/context/build") as websocket:
        websocket.send_json({"ai_classification_enabled": True})
        websocket.receive_json()
    assert exc_info.value.code == 1008


@pytest.mark.asyncio
async def test_context_build_websocket_rejects_when_operation_already_in_progress(tmp_path) -> None:
    registry_path = tmp_path / "projects.json"
    project = await _create_project(tmp_path, registry_path)
    app = create_app(registry_path=registry_path)
    app.state.active_project_operations.add(("default", project.name.lower()))
    client = TestClient(app)

    with pytest.raises(WebSocketDisconnect) as exc_info, client.websocket_connect(f"/api/projects/{project.name}/context/build") as websocket:
        websocket.send_json({})
        websocket.receive_json()
    assert exc_info.value.code == 1008


@pytest.mark.asyncio
async def test_context_build_websocket_releases_lock_after_completion_allowing_next_build(tmp_path) -> None:
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
    client = TestClient(app)

    _run_context_build_websocket(client, project.name)
    events = _run_context_build_websocket(client, project.name)  # segunda reconstrucción, sin 409/1008 residual

    assert events[-1]["event"] == "completed"


@pytest.mark.asyncio
async def test_context_build_websocket_404_equivalent_for_missing_project(tmp_path) -> None:
    app = create_app(registry_path=tmp_path / "projects.json")
    client = TestClient(app)

    with pytest.raises(WebSocketDisconnect) as exc_info, client.websocket_connect("/api/projects/No Existe/context/build") as websocket:
        websocket.send_json({})
        websocket.receive_json()
    assert exc_info.value.code == 1008


# ===== WS /api/projects/{name}/context/delete =====


@pytest.mark.asyncio
async def test_context_delete_websocket_removes_everything_and_reports_progress(tmp_path) -> None:
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
    client = TestClient(app)
    with client.websocket_connect(f"/api/projects/{project.name}/context/build") as websocket:
        websocket.send_json({})
        while websocket.receive_json()["event"] != "completed":
            pass
    assert (project_root / "organizado").exists()
    assert (project_root / "context.json").exists()

    events: list[dict] = []
    with client.websocket_connect(f"/api/projects/{project.name}/context/delete") as websocket:
        websocket.send_json({"confirm": True})
        while True:
            message = websocket.receive_json()
            events.append(message)
            if message["event"] == "completed":
                break

    assert [event["event"] for event in events] == ["started", "output_deleted", "site_deleted", "completed"]
    assert not (project_root / "organizado").exists()
    assert not (project_root / "mkdocs.yml").exists()
    assert not (project_root / "context.json").exists()


@pytest.mark.asyncio
async def test_context_delete_websocket_requires_explicit_confirmation(tmp_path) -> None:
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
    client = TestClient(app)
    _run_context_build_websocket(client, project.name)

    with pytest.raises(WebSocketDisconnect) as exc_info, client.websocket_connect(f"/api/projects/{project.name}/context/delete") as websocket:
        websocket.send_json({"confirm": False})
        websocket.receive_json()
    assert exc_info.value.code == 1008
    assert (project_root / "organizado").exists()


@pytest.mark.asyncio
async def test_context_delete_websocket_rejects_when_no_context_built(tmp_path) -> None:
    registry_path = tmp_path / "projects.json"
    project = await _create_project(tmp_path, registry_path)
    app = create_app(registry_path=registry_path)
    client = TestClient(app)

    with pytest.raises(WebSocketDisconnect) as exc_info, client.websocket_connect(f"/api/projects/{project.name}/context/delete") as websocket:
        websocket.send_json({"confirm": True})
        websocket.receive_json()
    assert exc_info.value.code == 1008


@pytest.mark.asyncio
async def test_context_delete_websocket_rejects_when_operation_already_in_progress(tmp_path) -> None:
    registry_path = tmp_path / "projects.json"
    project = await _create_project(tmp_path, registry_path)
    app = create_app(registry_path=registry_path)
    app.state.active_project_operations.add(("default", project.name.lower()))
    client = TestClient(app)

    with pytest.raises(WebSocketDisconnect) as exc_info, client.websocket_connect(f"/api/projects/{project.name}/context/delete") as websocket:
        websocket.send_json({"confirm": True})
        websocket.receive_json()
    assert exc_info.value.code == 1008


# ===== GET /projects/{name}/context/site (visualización, independiente del build) =====


@pytest.mark.asyncio
async def test_context_site_index_redirects_to_trailing_slash(tmp_path) -> None:
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
        await _build_context_with_fake_site(client, project, project_root)
        response = await client.get(f"/projects/{project.name}/context/site", follow_redirects=False)

    assert response.status_code == 307
    assert response.headers["location"] == f"/projects/{quote(project.name)}/context/site/"


@pytest.mark.asyncio
async def test_context_site_index_serves_built_index_html(tmp_path) -> None:
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
        await _build_context_with_fake_site(client, project, project_root)
        response = await client.get(f"/projects/{project.name}/context/site/")

    assert response.status_code == 200
    assert "Inicio del sitio" in response.text


@pytest.mark.asyncio
async def test_context_site_asset_redirects_directory_without_trailing_slash(tmp_path) -> None:
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
        await _build_context_with_fake_site(client, project, project_root)
        response = await client.get(f"/projects/{project.name}/context/site/ciberseguridad", follow_redirects=False)

    assert response.status_code == 307
    assert response.headers["location"] == f"/projects/{quote(project.name)}/context/site/ciberseguridad/"


@pytest.mark.asyncio
async def test_context_site_asset_serves_domain_page(tmp_path) -> None:
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
        await _build_context_with_fake_site(client, project, project_root)
        response = await client.get(f"/projects/{project.name}/context/site/ciberseguridad/")

    assert response.status_code == 200
    assert "Dominio Ciberseguridad" in response.text


@pytest.mark.asyncio
async def test_context_site_404_when_no_context_built(tmp_path) -> None:
    registry_path = tmp_path / "projects.json"
    project = await _create_project(tmp_path, registry_path)
    app = create_app(registry_path=registry_path)

    async with _client(app) as client:
        response = await client.get(f"/projects/{project.name}/context/site/")

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_context_site_404_when_context_built_but_mkdocs_site_not_built(tmp_path) -> None:
    """`_no_real_mkdocs_build` deja `mkdocs_site_built=False` tras un build normal
    (sin sitio simulado a mano) — el visor debe devolver 404, no servir un sitio
    que nunca llegó a construirse."""
    registry_path = tmp_path / "projects.json"
    project = await _create_project(tmp_path, registry_path)
    app = create_app(registry_path=registry_path)

    async with _client(app) as client:
        await client.post(f"/api/projects/{project.name}/context")
        response = await client.get(f"/projects/{project.name}/context/site/")

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_context_site_rejects_path_traversal_outside_site_dir(tmp_path) -> None:
    """`mkdocs.yml` vive en `project.root_path`, un nivel por encima de `site/` —
    si el guard de `context_site_asset` fallara, este `..` lo expondría."""
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
        await _build_context_with_fake_site(client, project, project_root)
        assert (project_root / "mkdocs.yml").exists()
        response = await client.get(f"/projects/{project.name}/context/site/../mkdocs.yml")

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_context_site_tenant_isolation(tmp_path) -> None:
    registry_path = tmp_path / "projects.json"
    project = await _create_project(tmp_path, registry_path, tenant_id="acme-corp")
    app = create_app(registry_path=registry_path)

    async with _client(app) as client:
        response = await client.get(f"/projects/{project.name}/context/site/")

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_context_page_links_to_site_when_built(tmp_path) -> None:
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
        await _build_context_with_fake_site(client, project, project_root)
        response = await client.get(f"/projects/{project.name}/context")

    assert response.status_code == 200
    assert f"/projects/{quote(project.name)}/context/site/" in response.text
    assert "ver documentación generada" in response.text


_VALID_TAXONOMY_MANIFEST = """---
domains:
  - slug: ciberseguridad
    name: Ciberseguridad
material_types:
  - slug: normativa
    name: Normativa
---

Prosa libre, no se parsea.
"""


@pytest.mark.asyncio
async def test_build_context_uses_taxonomy_manifest_when_present(tmp_path) -> None:
    registry_path = tmp_path / "projects.json"
    project = await _create_project(tmp_path, registry_path)
    project_root = tmp_path / "workspaces" / project.name
    file_path = _seed_converted_document(project_root, "politica", "Política de seguridad normativa")
    (project_root / "taxonomy_manifest.md").write_text(_VALID_TAXONOMY_MANIFEST, encoding="utf-8")

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
        response = await client.post(f"/api/projects/{project.name}/context", json={"threshold": 0.1})

    assert response.status_code == 200
    assert (project_root / "organizado" / "ciberseguridad" / "normativa" / "politica").is_dir()


@pytest.mark.asyncio
async def test_build_context_rejects_manifest_combined_with_candidate_domains(tmp_path) -> None:
    registry_path = tmp_path / "projects.json"
    project = await _create_project(tmp_path, registry_path)
    project_root = tmp_path / "workspaces" / project.name
    file_path = _seed_converted_document(project_root, "politica", "Política")
    (project_root / "taxonomy_manifest.md").write_text(_VALID_TAXONOMY_MANIFEST, encoding="utf-8")

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
        response = await client.post(f"/api/projects/{project.name}/context", json={"candidate_domains": ["calidad"]})

    assert response.status_code == 400
    assert "taxonomy_manifest.md" in response.json()["detail"]


@pytest.mark.asyncio
async def test_build_context_reports_invalid_manifest_front_matter_as_400(tmp_path) -> None:
    registry_path = tmp_path / "projects.json"
    project = await _create_project(tmp_path, registry_path)
    project_root = tmp_path / "workspaces" / project.name
    (project_root / "taxonomy_manifest.md").write_text("# Sin front matter\n", encoding="utf-8")

    app = create_app(registry_path=registry_path)
    async with _client(app) as client:
        response = await client.post(f"/api/projects/{project.name}/context")

    assert response.status_code == 400


@pytest.mark.asyncio
async def test_build_context_with_manifest_and_ai_enabled_but_taxonomy_proxy_not_configured_returns_400(tmp_path, monkeypatch) -> None:
    """Con manifiesto activo, `ai_classification_enabled=True` construye
    `TaxonomyClassificationClient` -- sus propias env vars
    (`DOC_ORGANIZE_LITELLM_TAXONOMY_CLASSIFICATION_*`) deben estar definidas, no basta con
    que lo estén las de `DomainClassificationClient` (1 eje): son configs separadas (ISP),
    por diseño no hay fallback implícito de una a otra."""
    monkeypatch.delenv("DOC_ORGANIZE_LITELLM_TAXONOMY_CLASSIFICATION_BASE_URL", raising=False)
    monkeypatch.delenv("DOC_ORGANIZE_LITELLM_TAXONOMY_CLASSIFICATION_VIRTUAL_KEY", raising=False)
    monkeypatch.setenv("DOC_ORGANIZE_LITELLM_CLASSIFICATION_BASE_URL", "https://proxy.example.test")
    monkeypatch.setenv("DOC_ORGANIZE_LITELLM_CLASSIFICATION_VIRTUAL_KEY", "sk-test")
    registry_path = tmp_path / "projects.json"
    project = await _create_project(tmp_path, registry_path)
    project_root = tmp_path / "workspaces" / project.name
    (project_root / "taxonomy_manifest.md").write_text(_VALID_TAXONOMY_MANIFEST, encoding="utf-8")

    app = create_app(registry_path=registry_path)
    async with _client(app) as client:
        response = await client.post(f"/api/projects/{project.name}/context", json={"ai_classification_enabled": True})

    assert response.status_code == 400
