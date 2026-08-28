"""Tests del Duplicates Resolver (Fase D-2c, §2.7.4, sub-paso 3/3)."""

import json

from pathlib import Path

import httpx
import pytest

from doc_organize.projects import ProjectRegistry
from doc_organize.web import create_app


def _client(app, base_url: str = "http://testserver") -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=base_url)


async def _create_project(tmp_path, registry_path, name: str = "Proyecto Dup", tenant_id: str = "default"):
    base = tmp_path / "workspaces"
    base.mkdir(exist_ok=True)
    async with ProjectRegistry(registry_path) as registry:
        return await registry.create_project(name, base, tenant_id=tenant_id)


def _write_folders_json(project_root: Path, paths: list[str]) -> None:
    (project_root / "folders.json").write_text(json.dumps({"paths": paths}), encoding="utf-8")


@pytest.mark.asyncio
async def test_duplicates_api_409_when_never_scanned(tmp_path) -> None:
    registry_path = tmp_path / "projects.json"
    project = await _create_project(tmp_path, registry_path)
    app = create_app(registry_path=registry_path)

    async with _client(app) as client:
        response = await client.get(f"/api/projects/{project.name}/duplicates")

    assert response.status_code == 409


@pytest.mark.asyncio
async def test_duplicates_api_detects_exact_duplicate(tmp_path) -> None:
    registry_path = tmp_path / "projects.json"
    project = await _create_project(tmp_path, registry_path)
    project_root = tmp_path / "workspaces" / project.name

    input_dir = tmp_path / "input"
    input_dir.mkdir()
    (input_dir / "original.pdf").write_bytes(b"contenido identico")
    (input_dir / "copia.pdf").write_bytes(b"contenido identico")
    _write_folders_json(project_root, [str(input_dir)])

    app = create_app(registry_path=registry_path)
    async with _client(app) as client:
        response = await client.get(f"/api/projects/{project.name}/duplicates")

    assert response.status_code == 200
    payload = response.json()
    assert len(payload["groups"]) == 1
    group = payload["groups"][0]
    assert group["reason"] == "exact_duplicate"
    assert len(group["duplicates"]) == 1


@pytest.mark.asyncio
async def test_duplicates_resolve_moves_non_chosen_member(tmp_path) -> None:
    registry_path = tmp_path / "projects.json"
    project = await _create_project(tmp_path, registry_path)
    project_root = tmp_path / "workspaces" / project.name

    input_dir = tmp_path / "input"
    input_dir.mkdir()
    keep_path = input_dir / "keep.pdf"
    discard_path = input_dir / "discard.pdf"
    keep_path.write_bytes(b"contenido identico")
    discard_path.write_bytes(b"contenido identico")
    _write_folders_json(project_root, [str(input_dir)])

    app = create_app(registry_path=registry_path)
    async with _client(app) as client:
        detected = (await client.get(f"/api/projects/{project.name}/duplicates")).json()
        group = detected["groups"][0]
        # Clave estable = sha256 de las rutas ordenadas (misma logica que _group_key).
        import hashlib

        paths = sorted([group["canonical_doc"]["full_path"], *[d["full_path"] for d in group["duplicates"]]])
        group_key = hashlib.sha256("|".join(paths).encode("utf-8")).hexdigest()

        response = await client.post(
            f"/api/projects/{project.name}/duplicates/resolve",
            json={"resolutions": {group_key: str(keep_path.resolve())}},
        )

    assert response.status_code == 200
    result = response.json()
    assert result["moved"] == 1
    assert result["groups_resolved"] == 1
    assert keep_path.exists()  # el elegido se conserva en su sitio
    assert not discard_path.exists()  # el otro se movio
    assert list((project_root / "duplicados").rglob("discard.pdf"))


@pytest.mark.asyncio
async def test_duplicates_resolve_ignores_path_not_in_group(tmp_path) -> None:
    # Un "resolutions" con una ruta que no pertenece al grupo (tampering) se ignora:
    # DeduplicationManager.resolve_duplicates solo mueve miembros reales del grupo
    # ([canonical_doc, *duplicates]), asi que no hay forma de que una ruta ajena se
    # mueva -- el peor caso es que la resolucion se ignore y se aplique el default.
    registry_path = tmp_path / "projects.json"
    project = await _create_project(tmp_path, registry_path)
    project_root = tmp_path / "workspaces" / project.name

    input_dir = tmp_path / "input"
    input_dir.mkdir()
    (input_dir / "a.pdf").write_bytes(b"contenido identico")
    (input_dir / "b.pdf").write_bytes(b"contenido identico")
    _write_folders_json(project_root, [str(input_dir)])

    outside_file = tmp_path / "fuera-del-scan.pdf"
    outside_file.write_bytes(b"no deberia moverse jamas")

    app = create_app(registry_path=registry_path)
    async with _client(app) as client:
        response = await client.post(
            f"/api/projects/{project.name}/duplicates/resolve",
            json={"resolutions": {"clave-inventada": str(outside_file)}},
        )

    assert response.status_code == 200
    result = response.json()
    assert result["groups_resolved"] == 0  # la clave no coincidio con ningun grupo real
    assert result["moved"] == 1  # el grupo real igual se resuelve con el default (mas antiguo)
    assert outside_file.exists()  # el archivo ajeno nunca se toca


@pytest.mark.asyncio
async def test_duplicates_resolve_ignores_tampered_path_with_valid_group_key(tmp_path) -> None:
    # Variante mas realista del tampering: el cliente reenvia una group_key REAL
    # (obtenida de un GET legitimo) pero con una ruta que no es miembro de ese grupo
    # -- ejercita la rama "member is None" (a diferencia de una clave inventada, que
    # ni siquiera llega a buscar member).
    registry_path = tmp_path / "projects.json"
    project = await _create_project(tmp_path, registry_path)
    project_root = tmp_path / "workspaces" / project.name

    input_dir = tmp_path / "input"
    input_dir.mkdir()
    (input_dir / "a.pdf").write_bytes(b"contenido identico")
    (input_dir / "b.pdf").write_bytes(b"contenido identico")
    _write_folders_json(project_root, [str(input_dir)])

    outside_file = tmp_path / "fuera-del-scan.pdf"
    outside_file.write_bytes(b"no deberia moverse jamas")

    app = create_app(registry_path=registry_path)
    async with _client(app) as client:
        detected = (await client.get(f"/api/projects/{project.name}/duplicates")).json()
        group = detected["groups"][0]
        import hashlib

        paths = sorted([group["canonical_doc"]["full_path"], *[d["full_path"] for d in group["duplicates"]]])
        real_group_key = hashlib.sha256("|".join(paths).encode("utf-8")).hexdigest()

        response = await client.post(
            f"/api/projects/{project.name}/duplicates/resolve",
            json={"resolutions": {real_group_key: str(outside_file)}},
        )

    assert response.status_code == 200
    result = response.json()
    assert result["groups_resolved"] == 0  # la ruta no es miembro del grupo -> se ignora
    assert result["moved"] == 1  # el grupo real se resuelve igual con el default
    assert outside_file.exists()


@pytest.mark.asyncio
async def test_duplicates_resolver_page_loads_with_detected_groups(tmp_path) -> None:
    registry_path = tmp_path / "projects.json"
    project = await _create_project(tmp_path, registry_path)
    project_root = tmp_path / "workspaces" / project.name

    input_dir = tmp_path / "input"
    input_dir.mkdir()
    (input_dir / "a.pdf").write_bytes(b"contenido identico")
    (input_dir / "b.pdf").write_bytes(b"contenido identico")
    _write_folders_json(project_root, [str(input_dir)])

    app = create_app(registry_path=registry_path)
    async with _client(app) as client:
        response = await client.get(f"/projects/{project.name}/duplicates")

    assert response.status_code == 200
    assert "Grupo 1" in response.text


@pytest.mark.asyncio
async def test_duplicates_resolve_no_duplicates_is_noop(tmp_path) -> None:
    registry_path = tmp_path / "projects.json"
    project = await _create_project(tmp_path, registry_path)
    project_root = tmp_path / "workspaces" / project.name

    input_dir = tmp_path / "input"
    input_dir.mkdir()
    (input_dir / "unico.pdf").write_bytes(b"sin duplicados")
    _write_folders_json(project_root, [str(input_dir)])

    app = create_app(registry_path=registry_path)
    async with _client(app) as client:
        response = await client.post(f"/api/projects/{project.name}/duplicates/resolve", json={"resolutions": {}})

    assert response.status_code == 200
    result = response.json()
    assert result == {"moved": 0, "groups_resolved": 0}


@pytest.mark.asyncio
async def test_duplicates_api_tenant_isolation(tmp_path) -> None:
    registry_path = tmp_path / "projects.json"
    project = await _create_project(tmp_path, registry_path, tenant_id="acme-corp")
    project_root = tmp_path / "workspaces" / project.name
    _write_folders_json(project_root, [])

    app = create_app(registry_path=registry_path)
    async with _client(app) as client:
        response = await client.get(f"/api/projects/{project.name}/duplicates")

    assert response.status_code == 404
