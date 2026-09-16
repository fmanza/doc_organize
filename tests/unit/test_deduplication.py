"""Tests unitarios de DeduplicationManager (REQ-005)."""

import json

from datetime import UTC, datetime, timedelta

import pytest

from doc_organize.core.models import DocumentMetadata, DuplicateReason
from doc_organize.dedup import DeduplicationManager


def _doc(full_path: str, sha256_hash: str, modified_time: float, extension: str = "pdf") -> DocumentMetadata:
    return DocumentMetadata(
        full_path=full_path,
        display_name=full_path.rsplit("/", 1)[-1],
        extension=extension,
        size_bytes=100,
        modified_time=modified_time,
        sha256_hash=sha256_hash,
    )


@pytest.fixture
def manager() -> DeduplicationManager:
    return DeduplicationManager()


def test_no_duplicates_returns_empty(manager: DeduplicationManager) -> None:
    docs = [_doc("/repo/a.pdf", "hash-a", 1.0), _doc("/repo/b.pdf", "hash-b", 2.0)]
    assert manager.find_duplicates(docs) == []


def test_exact_duplicate_keeps_oldest_as_canonical(manager: DeduplicationManager) -> None:
    older = _doc("/repo/original.pdf", "same-hash", modified_time=1.0)
    newer = _doc("/repo/copy.pdf", "same-hash", modified_time=2.0)

    groups = manager.find_duplicates([newer, older])

    assert len(groups) == 1
    group = groups[0]
    assert group.reason == DuplicateReason.EXACT_DUPLICATE
    assert group.canonical_doc.full_path == older.full_path
    assert [d.full_path for d in group.duplicates] == [newer.full_path]


def test_version_conflict_detected_by_suffix(manager: DeduplicationManager) -> None:
    v1 = _doc("/repo/report_v1.pdf", "hash-v1", modified_time=1.0)
    v2 = _doc("/repo/report_v2.pdf", "hash-v2", modified_time=2.0)

    groups = manager.find_duplicates([v2, v1])

    assert len(groups) == 1
    group = groups[0]
    assert group.reason == DuplicateReason.VERSION_CONFLICT
    assert group.canonical_doc.full_path == v1.full_path


def test_different_base_names_are_not_grouped(manager: DeduplicationManager) -> None:
    a = _doc("/repo/alpha.pdf", "hash-a", modified_time=1.0)
    b = _doc("/repo/beta.pdf", "hash-b", modified_time=2.0)
    assert manager.find_duplicates([a, b]) == []


# ===== fuzzy_threshold (FUZZY_NAME_MATCH, tercera pasada opcional) =====


def _named_doc(display_name: str, sha256_hash: str, modified_time: float) -> DocumentMetadata:
    return DocumentMetadata(
        full_path=f"/repo/{display_name}",
        display_name=display_name,
        extension="pdf",
        size_bytes=100,
        modified_time=modified_time,
        sha256_hash=sha256_hash,
    )


def test_fuzzy_threshold_none_keeps_current_behavior(manager: DeduplicationManager) -> None:
    # Nombres muy parecidos (WRatio+normalizado ~95.0, ver sesión de diseño)
    # pero sin fuzzy_threshold: debe comportarse exactamente igual que antes de
    # esta funcionalidad -- ningun grupo, ni siquiera por version_conflict (las
    # bases normalizadas son distintas).
    a = _named_doc("informe_ventas.pdf", "hash-a", modified_time=1.0)
    b = _named_doc("informe_ventas_anual.pdf", "hash-b", modified_time=2.0)
    assert manager.find_duplicates([a, b]) == []


def test_fuzzy_match_groups_similar_names_above_threshold(manager: DeduplicationManager) -> None:
    older = _named_doc("informe_ventas.pdf", "hash-a", modified_time=1.0)
    newer = _named_doc("informe_ventas_anual.pdf", "hash-b", modified_time=2.0)

    groups = manager.find_duplicates([newer, older], fuzzy_threshold=80)

    assert len(groups) == 1
    group = groups[0]
    assert group.reason == DuplicateReason.FUZZY_NAME_MATCH
    # Mismo criterio que las otras dos pasadas: canonico = mas antiguo.
    assert group.canonical_doc.full_path == older.full_path
    assert [d.full_path for d in group.duplicates] == [newer.full_path]


def test_fuzzy_match_below_threshold_not_grouped(manager: DeduplicationManager) -> None:
    a = _named_doc("informe_ventas.pdf", "hash-a", modified_time=1.0)
    b = _named_doc("informe_ventas_anual.pdf", "hash-b", modified_time=2.0)

    # El score real de este par (WRatio + normalizado) es 95.0 exacto -- un
    # umbral de 95 SI los agruparia (score_cutoff es inclusivo, score >= cutoff).
    # Se usa 96 para quedar de forma inequivoca por encima del score real.
    assert manager.find_duplicates([a, b], fuzzy_threshold=96) == []


def test_fuzzy_pass_excludes_docs_already_grouped_by_hash(manager: DeduplicationManager) -> None:
    # doc1/doc2 son duplicado exacto (mismo hash) -- deben quedar fuera del pool
    # de la pasada fuzzy aunque su nombre tambien se parezca a doc3, que se
    # queda solo (sin pareja) y por tanto sin grupo fuzzy propio.
    doc1 = _named_doc("informe_ventas.pdf", "hash-igual", modified_time=1.0)
    doc2 = _named_doc("informe_ventas_copy.pdf", "hash-igual", modified_time=2.0)
    doc3 = _named_doc("informe_ventas_anual.pdf", "hash-unica", modified_time=3.0)

    groups = manager.find_duplicates([doc1, doc2, doc3], fuzzy_threshold=60)

    assert len(groups) == 1
    assert groups[0].reason == DuplicateReason.EXACT_DUPLICATE
    assert {doc.full_path for doc in [groups[0].canonical_doc, *groups[0].duplicates]} == {doc1.full_path, doc2.full_path}


def test_fuzzy_match_connected_components_without_strict_pairwise_transitivity(manager: DeduplicationManager) -> None:
    # a-b (95.0) y b-c (89.7) superan el umbral 80, pero a-c (73.7) no --
    # deben terminar en el MISMO grupo (componente conexa via b), sin exigir
    # que TODOS los pares superen el umbral entre si (regla de negocio 2).
    # Nombres elegidos SIN relacion de prefijo anidado entre a y c (a diferencia
    # de "factura_0001.pdf"/"factura_0001_copia.pdf"/"..._copia_revisada.pdf"
    # de una version anterior de este test): con WRatio, si a es prefijo tanto
    # de b como de c, partial_ratio(a, c) tambien satura a un score alto y el
    # caso de "no transitividad" deja de poder probarse con esos datos.
    a = _named_doc("contrato_2024_borrador.pdf", "hash-a", modified_time=1.0)
    b = _named_doc("contrato_2024_borrador_revisado.pdf", "hash-b", modified_time=2.0)
    c = _named_doc("acta_2024_borrador_revisado.pdf", "hash-c", modified_time=3.0)

    groups = manager.find_duplicates([c, a, b], fuzzy_threshold=80)

    assert len(groups) == 1
    group = groups[0]
    assert group.reason == DuplicateReason.FUZZY_NAME_MATCH
    assert {doc.full_path for doc in [group.canonical_doc, *group.duplicates]} == {a.full_path, b.full_path, c.full_path}
    assert group.canonical_doc.full_path == a.full_path  # el mas antiguo


def test_fuzzy_match_is_case_insensitive(manager: DeduplicationManager) -> None:
    # rapidfuzz.utils.default_process pliega a minusculas como parte de la
    # normalizacion (no es un .lower() aparte): sin ese pliegue, WRatio de este
    # par cae por debajo del umbral por la diferencia de mayusculas; con el
    # pliegue, el score real es 95.0.
    a = _named_doc("INFORME_VENTAS.pdf", "hash-a", modified_time=1.0)
    b = _named_doc("informe_ventas_anual.pdf", "hash-b", modified_time=2.0)

    groups = manager.find_duplicates([a, b], fuzzy_threshold=80)

    assert len(groups) == 1
    assert groups[0].reason == DuplicateReason.FUZZY_NAME_MATCH


def test_fuzzy_pass_no_groups_when_fewer_than_two_remaining(manager: DeduplicationManager) -> None:
    single = _named_doc("unico.pdf", "hash-unica", modified_time=1.0)
    assert manager.find_duplicates([single], fuzzy_threshold=50) == []


@pytest.mark.asyncio
async def test_resolve_duplicates_moves_files_and_writes_report(tmp_path) -> None:
    source_dir = tmp_path / "docs"
    source_dir.mkdir()
    older = source_dir / "original.pdf"
    newer = source_dir / "copy.pdf"
    older.write_bytes(b"same-content")
    newer.write_bytes(b"same-content")

    older_doc = _doc(str(older), "same-hash", modified_time=1.0)
    newer_doc = _doc(str(newer), "same-hash", modified_time=2.0)

    manager = DeduplicationManager()
    groups = manager.find_duplicates([newer_doc, older_doc])
    duplicates_dir = tmp_path / "duplicados"

    report = await manager.resolve_duplicates(groups, duplicates_dir)

    assert older.exists()  # el canonico se queda en su sitio
    assert not newer.exists()  # el duplicado se movio
    assert report.total_exact_duplicates == 1
    assert report.total_version_conflicts == 0

    audit_path = duplicates_dir / "DEDUP_REPORT.json"
    assert audit_path.exists()
    payload = json.loads(audit_path.read_text(encoding="utf-8"))
    assert payload["total_exact_duplicates"] == 1
    # Sin `started_at`, la duracion queda sin dato -- no un `0.0` enganoso que
    # sugiera una operacion instantanea.
    assert report.duration_seconds is None
    assert report.started_at is None


@pytest.mark.asyncio
async def test_resolve_duplicates_computes_duration_from_started_at(tmp_path) -> None:
    source_dir = tmp_path / "docs"
    source_dir.mkdir()
    older = source_dir / "original.pdf"
    newer = source_dir / "copy.pdf"
    older.write_bytes(b"same-content")
    newer.write_bytes(b"same-content")

    older_doc = _doc(str(older), "same-hash", modified_time=1.0)
    newer_doc = _doc(str(newer), "same-hash", modified_time=2.0)

    manager = DeduplicationManager()
    groups = manager.find_duplicates([newer_doc, older_doc])
    duplicates_dir = tmp_path / "duplicados"
    started_at = datetime.now(UTC) - timedelta(seconds=5)

    report = await manager.resolve_duplicates(groups, duplicates_dir, started_at=started_at)

    assert report.started_at == started_at.isoformat()
    assert report.duration_seconds is not None
    assert report.duration_seconds >= 5.0


@pytest.mark.asyncio
async def test_resolve_duplicates_appends_to_history_across_runs(tmp_path) -> None:
    # "los duplicados generan una lista incremental que permita su consulta":
    # DEDUP_REPORT.json solo guarda el ultimo run, pero DEDUP_HISTORY.jsonl debe
    # acumular todas las ejecuciones -- una linea por resolve_duplicates(), sin
    # sobrescribir las anteriores.
    source_dir = tmp_path / "docs"
    source_dir.mkdir()
    duplicates_dir = tmp_path / "duplicados"
    manager = DeduplicationManager()

    first_older = source_dir / "first_original.pdf"
    first_newer = source_dir / "first_copy.pdf"
    first_older.write_bytes(b"first-content")
    first_newer.write_bytes(b"first-content")
    first_groups = manager.find_duplicates(
        [
            _doc(str(first_newer), "first-hash", modified_time=2.0),
            _doc(str(first_older), "first-hash", modified_time=1.0),
        ]
    )
    await manager.resolve_duplicates(first_groups, duplicates_dir)

    second_older = source_dir / "second_original.pdf"
    second_newer = source_dir / "second_copy.pdf"
    second_older.write_bytes(b"second-content")
    second_newer.write_bytes(b"second-content")
    second_groups = manager.find_duplicates(
        [
            _doc(str(second_newer), "second-hash", modified_time=2.0),
            _doc(str(second_older), "second-hash", modified_time=1.0),
        ]
    )
    await manager.resolve_duplicates(second_groups, duplicates_dir)

    history_path = duplicates_dir / "DEDUP_HISTORY.jsonl"
    lines = [line for line in history_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(lines) == 2
    reports = [json.loads(line) for line in lines]
    assert [report["total_exact_duplicates"] for report in reports] == [1, 1]
    # DEDUP_REPORT.json (solo lectura del ultimo run) no se ve afectado por el
    # historico: sigue reflejando unicamente la segunda ejecucion.
    last_report = json.loads((duplicates_dir / "DEDUP_REPORT.json").read_text(encoding="utf-8"))
    assert last_report["total_exact_duplicates"] == 1


@pytest.mark.asyncio
async def test_resolve_duplicates_avoids_overwrite_on_name_collision(tmp_path) -> None:
    source_dir = tmp_path / "a"
    source_dir.mkdir()
    source_file = source_dir / "report.pdf"
    source_file.write_bytes(b"content-a")

    duplicates_dir = tmp_path / "duplicados"
    # Archivo preexistente en la ruta destino reflejada, para forzar una colision.
    mirrored_parts = source_file.resolve().parts[1:]
    pre_existing = duplicates_dir.joinpath(*mirrored_parts)
    pre_existing.parent.mkdir(parents=True, exist_ok=True)
    pre_existing.write_bytes(b"already-there")

    manager = DeduplicationManager()
    await manager._move_to_duplicates(source_file, duplicates_dir, "hash-a-collision")

    assert not source_file.exists()
    assert pre_existing.exists()  # el archivo preexistente no se sobrescribio
    suffixed = pre_existing.with_name(f"{pre_existing.stem}_{'hash-a-collision'[:8]}{pre_existing.suffix}")
    assert suffixed.exists()


@pytest.mark.asyncio
async def test_move_to_duplicates_raises_on_double_collision_instead_of_overwriting(tmp_path) -> None:
    """AUDIT_CODE (sesión 2026-09-03): si tanto el destino base como el destino
    ya sufijado con el hash existían, `shutil.move` sobrescribía el segundo en
    silencio (`os.rename` falla por destino existente, y su fallback copy+unlink
    no vuelve a comprobar la existencia -- verificado empíricamente en Windows),
    pese al comentario "nunca sobrescribe". Ahora se rechaza explícitamente en
    vez de arriesgar esa pérdida silenciosa de datos."""
    source_dir = tmp_path / "a"
    source_dir.mkdir()
    source_file = source_dir / "report.pdf"
    source_file.write_bytes(b"content-a")

    duplicates_dir = tmp_path / "duplicados"
    mirrored_parts = source_file.resolve().parts[1:]
    base_target = duplicates_dir.joinpath(*mirrored_parts)
    base_target.parent.mkdir(parents=True, exist_ok=True)
    base_target.write_bytes(b"ya-habia-algo-aqui")

    sha256_hash = "hash-a-collision"
    suffixed_target = base_target.with_name(f"{base_target.stem}_{sha256_hash[:8]}{base_target.suffix}")
    suffixed_target.write_bytes(b"y-tambien-en-el-sufijado")

    manager = DeduplicationManager()
    with pytest.raises(FileExistsError):
        await manager._move_to_duplicates(source_file, duplicates_dir, sha256_hash)

    assert source_file.exists()  # no se movio ni se borro
    assert base_target.read_bytes() == b"ya-habia-algo-aqui"  # sin sobrescribir
    assert suffixed_target.read_bytes() == b"y-tambien-en-el-sufijado"  # sin sobrescribir


@pytest.mark.asyncio
async def test_move_group_continues_after_one_file_fails_to_move(tmp_path, monkeypatch) -> None:
    """AUDIT_CODE (sesión 2026-09-04): resiliencia por fichero -- un fallo al
    mover UN documento del grupo (permiso denegado, fichero bloqueado, ausente)
    no debe abortar el resto del grupo, mismo criterio que
    `DocumentConverter.convert_document()` aísla un documento del resto del
    batch de conversión."""
    source_dir = tmp_path / "docs"
    source_dir.mkdir()
    canonical = source_dir / "original.pdf"
    dup_a = source_dir / "copia_a.pdf"
    dup_b = source_dir / "copia_b.pdf"
    canonical.write_bytes(b"contenido")
    dup_a.write_bytes(b"contenido")
    dup_b.write_bytes(b"contenido")

    manager = DeduplicationManager()
    groups = manager.find_duplicates(
        [
            _doc(str(canonical), "hash-igual", modified_time=1.0),
            _doc(str(dup_a), "hash-igual", modified_time=2.0),
            _doc(str(dup_b), "hash-igual", modified_time=3.0),
        ]
    )
    assert len(groups) == 1
    group = groups[0]

    original_move = DeduplicationManager._move_to_duplicates

    async def _flaky_move(self, source, dup_dir, sha256_hash):
        if source.name == "copia_a.pdf":
            raise PermissionError("simulado: fichero bloqueado por otra aplicación")
        return await original_move(self, source, dup_dir, sha256_hash)

    monkeypatch.setattr(DeduplicationManager, "_move_to_duplicates", _flaky_move)

    duplicates_dir = tmp_path / "duplicados"
    exact, version, failed = await manager.move_group(group, duplicates_dir)

    assert exact == 1  # copia_b.pdf sí se movió, pese al fallo de copia_a.pdf
    assert version == 0
    assert failed == [str(dup_a)]
    assert dup_a.exists()  # no se movió: el fallo la dejó donde estaba, sin perderla
    assert not dup_b.exists()  # esta sí se movió con normalidad
