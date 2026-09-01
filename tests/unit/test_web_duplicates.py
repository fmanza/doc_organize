"""Tests del Duplicates Resolver (Fase D-2c, §2.7.4, sub-paso 3/3)."""

import json
import re

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


def _write_dedup_history(duplicados_dir: Path, *reports: dict) -> None:
    # `duplicates_resolver_page` deriva "la última deduplicación" de la última
    # línea de DEDUP_HISTORY.jsonl (no de un DEDUP_REPORT.json aparte, ver
    # web/routes/duplicates.py) -- estos tests simulan ejecuciones previas
    # escribiendo directamente ese histórico, más antigua primero.
    duplicados_dir.mkdir(parents=True, exist_ok=True)
    lines = "\n".join(json.dumps(report) for report in reports)
    (duplicados_dir / "DEDUP_HISTORY.jsonl").write_text(lines + "\n", encoding="utf-8")


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
async def test_duplicates_resolver_page_shows_search_box_folder_and_size(tmp_path) -> None:
    # La tabla de cada grupo debe mostrar la carpeta (separada del nombre de
    # archivo), el tamaño legible, marcar el conservado por defecto, y ofrecer un
    # buscador cliente cuyo filtro se apoya en `data-search` por fieldset.
    registry_path = tmp_path / "projects.json"
    project = await _create_project(tmp_path, registry_path)
    project_root = tmp_path / "workspaces" / project.name

    input_dir = tmp_path / "input"
    input_dir.mkdir()
    (input_dir / "a.pdf").write_bytes(b"x" * 2048)
    (input_dir / "b.pdf").write_bytes(b"x" * 2048)
    _write_folders_json(project_root, [str(input_dir)])

    app = create_app(registry_path=registry_path)
    async with _client(app) as client:
        response = await client.get(f"/projects/{project.name}/duplicates")

    assert response.status_code == 200
    html = response.text

    assert 'id="duplicates-search"' in html
    assert 'id="duplicates-no-results"' in html
    # La carpeta debe aparecer como CONTENIDO de una celda de tabla (no solo dentro
    # del atributo `data-search`, que también la incluye pero en minúsculas).
    assert re.search(re.escape(str(input_dir).lower()) + r"\s*</td>", html.lower())
    assert "2.0 KB" in html
    assert "conservado por defecto" in html
    # El filtro solo oculta con `hidden`/CSS via JS -- en el HTML servido ningun
    # radio debe llevar `disabled`, o el submit perderia esa seleccion al filtrar.
    assert "disabled" not in html
    # Contador (actualizado por JS al filtrar) arranca con el total sin filtrar,
    # igual que el de Caché.
    assert '<p class="text-gray-500 text-sm" id="duplicates-count">1 grupo(s).</p>' in html


@pytest.mark.asyncio
async def test_duplicates_resolver_page_no_search_box_when_no_groups(tmp_path) -> None:
    registry_path = tmp_path / "projects.json"
    project = await _create_project(tmp_path, registry_path)
    project_root = tmp_path / "workspaces" / project.name

    input_dir = tmp_path / "input"
    input_dir.mkdir()
    (input_dir / "unico.pdf").write_bytes(b"sin duplicados")
    _write_folders_json(project_root, [str(input_dir)])

    app = create_app(registry_path=registry_path)
    async with _client(app) as client:
        response = await client.get(f"/projects/{project.name}/duplicates")

    assert response.status_code == 200
    assert 'id="duplicates-search"' not in response.text


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
async def test_duplicates_page_explains_already_resolved_by_scan_dedup(tmp_path) -> None:
    # Si "Buscar duplicados" ya se ejecuto antes, un re-escaneo en vivo de las
    # carpetas de entrada no encuentra nada pendiente. La pagina no debe decir
    # simplemente "No se detectaron duplicados" (engañoso): debe explicar que ya
    # se resolvieron, leyendo la ultima linea de duplicados/DEDUP_HISTORY.jsonl.
    registry_path = tmp_path / "projects.json"
    project = await _create_project(tmp_path, registry_path)
    project_root = tmp_path / "workspaces" / project.name

    input_dir = tmp_path / "input"
    input_dir.mkdir()
    (input_dir / "unico.pdf").write_bytes(b"ya no quedan duplicados aqui")
    _write_folders_json(project_root, [str(input_dir)])

    duplicados_dir = project_root / "duplicados"
    _write_dedup_history(
        duplicados_dir,
        {
            "timestamp": "2026-08-31T10:00:00+00:00",
            "total_exact_duplicates": 2,
            "total_version_conflicts": 1,
            "duplicates_folder_path": str(duplicados_dir),
            "audit_json_path": str(duplicados_dir / "DEDUP_REPORT.json"),
            "groups": [],
        },
    )

    app = create_app(registry_path=registry_path)
    async with _client(app) as client:
        response = await client.get(f"/projects/{project.name}/duplicates")

    assert response.status_code == 200
    assert "No se detectaron duplicados." not in response.text
    # Aserciones ancladas a los valores concretos de total_exact_duplicates=2 y
    # total_version_conflicts=1 -- no a los dígitos sueltos "2"/"1", que también
    # aparecen dentro del timestamp de prueba y harían pasar el test aunque la
    # plantilla mostrara números equivocados.
    assert "2 duplicado" in response.text
    assert "1 conflicto" in response.text


@pytest.mark.asyncio
async def test_duplicates_page_falls_back_to_no_duplicates_when_report_is_corrupt(tmp_path) -> None:
    # Un DEDUP_HISTORY.jsonl truncado/corrupto (p.ej. por un crash a mitad de
    # escritura) no debe tumbar la pagina con un 500: debe degradar al mismo
    # "No se detectaron duplicados" que se mostraba antes de que ese fichero
    # existiera.
    registry_path = tmp_path / "projects.json"
    project = await _create_project(tmp_path, registry_path)
    project_root = tmp_path / "workspaces" / project.name

    input_dir = tmp_path / "input"
    input_dir.mkdir()
    (input_dir / "unico.pdf").write_bytes(b"sin duplicados")
    _write_folders_json(project_root, [str(input_dir)])

    duplicados_dir = project_root / "duplicados"
    duplicados_dir.mkdir(parents=True)
    (duplicados_dir / "DEDUP_HISTORY.jsonl").write_text('{"timestamp": "2026-08-31T10:00', encoding="utf-8")

    app = create_app(registry_path=registry_path)
    async with _client(app) as client:
        response = await client.get(f"/projects/{project.name}/duplicates")

    assert response.status_code == 200
    assert "No se detectaron duplicados." in response.text


@pytest.mark.asyncio
async def test_duplicates_page_shows_resolved_groups_detail_from_last_scan_dedup(tmp_path) -> None:
    # Lo que se pidio explicitamente: los archivos duplicados deben verse en la
    # pagina independientemente de que el re-escaneo en vivo encuentre algo
    # pendiente o no. Aqui el escaneo ya se deduplico (folders.json apunta a una
    # carpeta sin duplicados pendientes), pero DEDUP_HISTORY.jsonl trae el
    # detalle real de los grupos que se resolvieron -- debe listarse igual, en
    # modo solo lectura (sin radios: ya no hay nada que elegir).
    registry_path = tmp_path / "projects.json"
    project = await _create_project(tmp_path, registry_path)
    project_root = tmp_path / "workspaces" / project.name

    input_dir = tmp_path / "input"
    input_dir.mkdir()
    (input_dir / "unico.pdf").write_bytes(b"sin duplicados pendientes")
    _write_folders_json(project_root, [str(input_dir)])

    duplicados_dir = project_root / "duplicados"
    kept_path = str(input_dir / "informe.pdf")
    moved_path = str(input_dir / "informe_copia.pdf")
    _write_dedup_history(
        duplicados_dir,
        {
            "timestamp": "2026-08-31T10:00:00+00:00",
            "total_exact_duplicates": 1,
            "total_version_conflicts": 0,
            "duplicates_folder_path": str(duplicados_dir),
            "audit_json_path": str(duplicados_dir / "DEDUP_REPORT.json"),
            "groups": [
                {
                    "group_id": "11111111-1111-1111-1111-111111111111",
                    "canonical_doc": {
                        "full_path": kept_path,
                        "display_name": "informe.pdf",
                        "extension": "pdf",
                        "size_bytes": 2048,
                        "modified_time": 1000.0,
                        "sha256_hash": "abc123",
                    },
                    "duplicates": [
                        {
                            "full_path": moved_path,
                            "display_name": "informe_copia.pdf",
                            "extension": "pdf",
                            "size_bytes": 2048,
                            "modified_time": 1001.0,
                            "sha256_hash": "abc123",
                        }
                    ],
                    "reason": "exact_duplicate",
                    "user_choice": None,
                }
            ],
        },
    )

    app = create_app(registry_path=registry_path)
    async with _client(app) as client:
        response = await client.get(f"/projects/{project.name}/duplicates")

    assert response.status_code == 200
    html = response.text
    assert "informe.pdf" in html
    assert "informe_copia.pdf" in html
    assert "Conservado en su carpeta" in html
    assert "Movido a duplicados/" in html
    assert 'id="duplicates-search"' in html
    # El contador suma pendientes (0 aqui) + resueltos en el historico (1), igual
    # que la busqueda cubre ambas fuentes.
    assert '<p class="text-gray-500 text-sm" id="duplicates-count">1 grupo(s).</p>' in html
    # Solo-lectura: no debe haber ningun radio en el bloque de historico.
    assert "<input" not in html.split("Histórico de deduplicaciones")[1]


@pytest.mark.asyncio
async def test_duplicates_page_shows_history_of_all_dedup_runs(tmp_path) -> None:
    # "los duplicados generan una lista incremental que permita su consulta", con
    # el detalle de archivos de CADA ejecucion (no solo la ultima): dos ejecuciones,
    # cada una con un grupo real de duplicados distinto -- ambas deben verse con su
    # propio detalle de archivos, no solo un resumen de contadores.
    registry_path = tmp_path / "projects.json"
    project = await _create_project(tmp_path, registry_path)
    project_root = tmp_path / "workspaces" / project.name

    input_dir = tmp_path / "input"
    input_dir.mkdir()
    (input_dir / "unico.pdf").write_bytes(b"sin duplicados pendientes")
    _write_folders_json(project_root, [str(input_dir)])

    duplicados_dir = project_root / "duplicados"

    def _group(kept_name: str, moved_name: str) -> dict:
        return {
            "group_id": "11111111-1111-1111-1111-111111111111",
            "canonical_doc": {
                "full_path": str(input_dir / kept_name),
                "display_name": kept_name,
                "extension": "pdf",
                "size_bytes": 1024,
                "modified_time": 1000.0,
                "sha256_hash": "abc123",
            },
            "duplicates": [
                {
                    "full_path": str(input_dir / moved_name),
                    "display_name": moved_name,
                    "extension": "pdf",
                    "size_bytes": 1024,
                    "modified_time": 1001.0,
                    "sha256_hash": "abc123",
                }
            ],
            "reason": "exact_duplicate",
            "user_choice": None,
        }

    first_report = {
        "timestamp": "2026-08-30T09:00:00+00:00",
        "total_exact_duplicates": 1,
        "total_version_conflicts": 0,
        "duplicates_folder_path": str(duplicados_dir),
        "audit_json_path": str(duplicados_dir / "DEDUP_REPORT.json"),
        "groups": [_group("antiguo.pdf", "antiguo_copia.pdf")],
    }
    second_report = {
        "timestamp": "2026-08-31T10:00:00+00:00",
        "total_exact_duplicates": 1,
        "total_version_conflicts": 0,
        "duplicates_folder_path": str(duplicados_dir),
        "audit_json_path": str(duplicados_dir / "DEDUP_REPORT.json"),
        "groups": [_group("reciente.pdf", "reciente_copia.pdf")],
    }
    _write_dedup_history(duplicados_dir, first_report, second_report)

    app = create_app(registry_path=registry_path)
    async with _client(app) as client:
        response = await client.get(f"/projects/{project.name}/duplicates")

    assert response.status_code == 200
    html = response.text
    assert "Histórico de deduplicaciones" in html
    assert "2026-08-30T09:00:00+00:00" in html
    assert "2026-08-31T10:00:00+00:00" in html
    # Mas reciente primero.
    assert html.index("2026-08-31T10:00:00+00:00") < html.index("2026-08-30T09:00:00+00:00")
    # El detalle de archivos de AMBAS ejecuciones debe verse, no solo el de la
    # ultima -- esto es justo lo que se pidio: histórico de cada ejecución.
    assert "reciente.pdf" in html
    assert "reciente_copia.pdf" in html
    assert "antiguo.pdf" in html
    assert "antiguo_copia.pdf" in html
    # El contador cuenta los grupos de AMBAS ejecuciones (1 + 1 = 2).
    assert '<p class="text-gray-500 text-sm" id="duplicates-count">2 grupo(s).</p>' in html


@pytest.mark.asyncio
async def test_duplicates_page_history_skips_corrupt_lines(tmp_path) -> None:
    # Igual que DEDUP_REPORT.json (test_duplicates_page_falls_back_to_no_duplicates_when_report_is_corrupt):
    # una linea truncada del historico no debe tumbar la pagina, solo se ignora esa linea.
    registry_path = tmp_path / "projects.json"
    project = await _create_project(tmp_path, registry_path)
    project_root = tmp_path / "workspaces" / project.name

    input_dir = tmp_path / "input"
    input_dir.mkdir()
    (input_dir / "unico.pdf").write_bytes(b"sin duplicados")
    _write_folders_json(project_root, [str(input_dir)])

    duplicados_dir = project_root / "duplicados"
    duplicados_dir.mkdir(parents=True)
    valid_report = {
        "timestamp": "2026-08-31T10:00:00+00:00",
        "total_exact_duplicates": 1,
        "total_version_conflicts": 0,
        "duplicates_folder_path": str(duplicados_dir),
        "audit_json_path": str(duplicados_dir / "DEDUP_REPORT.json"),
        "groups": [],
    }
    (duplicados_dir / "DEDUP_HISTORY.jsonl").write_text(
        '{"timestamp": "corrupta-truncada\n' + json.dumps(valid_report) + "\n", encoding="utf-8"
    )

    app = create_app(registry_path=registry_path)
    async with _client(app) as client:
        response = await client.get(f"/projects/{project.name}/duplicates")

    assert response.status_code == 200
    assert "Histórico de deduplicaciones" in response.text
    assert "2026-08-31T10:00:00+00:00" in response.text


@pytest.mark.asyncio
async def test_duplicates_page_no_history_section_when_no_history_file(tmp_path) -> None:
    registry_path = tmp_path / "projects.json"
    project = await _create_project(tmp_path, registry_path)
    project_root = tmp_path / "workspaces" / project.name

    input_dir = tmp_path / "input"
    input_dir.mkdir()
    (input_dir / "unico.pdf").write_bytes(b"sin duplicados")
    _write_folders_json(project_root, [str(input_dir)])

    app = create_app(registry_path=registry_path)
    async with _client(app) as client:
        response = await client.get(f"/projects/{project.name}/duplicates")

    assert response.status_code == 200
    assert "Histórico de deduplicaciones" not in response.text


@pytest.mark.asyncio
async def test_duplicates_page_escapes_malicious_display_name_in_history(tmp_path) -> None:
    # Revision de seguridad: `doc.display_name`/`doc.full_path` (renderizados sin
    # filtro en duplicates_resolver.html.j2) vienen de nombres de fichero reales, sin
    # restriccion de caracteres -- a diferencia de `project.name`/`username`, que si
    # se validan. En Windows no se puede CREAR un fichero llamado literalmente
    # "<script>...", asi que este test inyecta el nombre malicioso directamente en
    # DEDUP_HISTORY.jsonl (que solo contiene JSON validado por Pydantic, sin pasar
    # por el sistema de ficheros) para ejercitar la misma ruta de renderizado que
    # explotaria un fichero real con ese nombre en un filesystem que si lo permita
    # (Linux/macOS, o un recurso de red no NTFS).
    registry_path = tmp_path / "projects.json"
    project = await _create_project(tmp_path, registry_path)
    project_root = tmp_path / "workspaces" / project.name
    _write_folders_json(project_root, [])
    duplicados_dir = project_root / "duplicados"

    malicious_name = "<script>alert(1)</script>.pdf"
    report = {
        "timestamp": "2026-08-30T09:00:00+00:00",
        "total_exact_duplicates": 1,
        "total_version_conflicts": 0,
        "duplicates_folder_path": str(duplicados_dir),
        "audit_json_path": str(duplicados_dir / "DEDUP_REPORT.json"),
        "groups": [
            {
                "group_id": "11111111-1111-1111-1111-111111111111",
                "canonical_doc": {
                    "full_path": f"/repo/{malicious_name}",
                    "display_name": malicious_name,
                    "extension": "pdf",
                    "size_bytes": 1024,
                    "modified_time": 1000.0,
                    "sha256_hash": "abc123",
                },
                "duplicates": [],
                "reason": "exact_duplicate",
                "user_choice": None,
            }
        ],
    }
    _write_dedup_history(duplicados_dir, report)

    app = create_app(registry_path=registry_path)
    async with _client(app) as client:
        response = await client.get(f"/projects/{project.name}/duplicates")

    assert response.status_code == 200
    assert "<script>alert(1)</script>" not in response.text
    assert "&lt;script&gt;alert(1)&lt;/script&gt;.pdf" in response.text


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
