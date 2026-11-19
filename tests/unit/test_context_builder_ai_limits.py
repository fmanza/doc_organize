"""Tests de los límites de la Sub-fase B de ContextBuilder (L-3a…L-3c, 0.14.0).

Parada ante clave rechazada, tras N errores de conexión seguidos o al agotar el presupuesto, y recuento de lo hecho.
Los tests usan el `LlmClient` real contra un proxy falso (`tests.unit.fake_llm`, `httpx.MockTransport`, sin red).
"""

import json
import logging

from datetime import UTC, datetime

import httpx
import pytest

from doc_organize.context.context_builder import ContextBuilder
from doc_organize.core.exceptions import OperationCancelledError
from doc_organize.core.models import AiSettings, Context, ConversionResult, Project, TaskSettings, TaxonomyEntry, TaxonomyManifest
from doc_organize.core.progress import CancelToken, ProgressEvent
from tests.unit.fake_llm import FakeLlmClient, fake_client, script
from tests.unit.taxonomy_helpers import two_axis_manifest

_SECRET = "sk-super-secret-virtual-key-123"


def _project(tmp_path) -> Project:
    return Project(name="Demo", root_path=str(tmp_path), created_at=datetime.now(UTC).isoformat())


def _documents(tmp_path, count: int) -> list[ConversionResult]:
    """`count` documentos en `varios/` (la Sub-fase A no los clasifica contra el catálogo `calidad`)."""
    source_dir = tmp_path / "varios"
    source_dir.mkdir(exist_ok=True)
    documents = []
    for index in range(count):
        json_path = tmp_path / f"doc{index}.json"
        json_path.write_text(json.dumps({"title": f"Receta {index}", "chunks": []}), encoding="utf-8")
        documents.append(
            ConversionResult(
                source_path=str(source_dir / f"doc{index}.pdf"),
                markdown_path=str(tmp_path / f"doc{index}.md"),
                json_path=str(json_path),
                success=True,
            )
        )
    return documents


def _manifest() -> TaxonomyManifest:
    return two_axis_manifest(
        domains=[TaxonomyEntry(slug="calidad", name="Calidad")],
        material_types=[TaxonomyEntry(slug="procedimiento", name="Procedimiento")],
    )


def _scripted(outcomes: list[str], **settings: object) -> FakeLlmClient:
    """Cliente con una respuesta por llamada (ver `fake_llm.script`)."""
    return fake_client(classify=script(*outcomes), **({"settings": _settings(**settings)} if settings else {}))


def _settings(**overrides: object) -> AiSettings:
    base = {"base_url": "https://proxy.test", "virtual_key": _SECRET, "rate_limit_retries": 0}
    return AiSettings(**(base | overrides))  # type: ignore[arg-type]


def _calls(client: FakeLlmClient) -> int:
    return len(client.proxy.calls("classify"))


async def _build(tmp_path, documents, client, **kwargs) -> Context:
    return await ContextBuilder().build(
        _project(tmp_path),
        documents,
        candidate_domains=["calidad"],
        llm=client,
        ai_scope="unclassified",
        **kwargs,
    )


def _assert_counts_consistent(context: Context, sent_without_assignment: int) -> None:
    assert (
        context.ai_stats.classification.sent
        == context.ai_stats.classification.assigned + context.ai_stats.classification.failed + sent_without_assignment
    )


# --- L-3a: clave rechazada -------------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_auth_error_with_real_client_makes_exactly_one_request(tmp_path):
    documents = _documents(tmp_path, 5)
    client = fake_client(
        classify=lambda _request: httpx.Response(401, json={"error": "invalid key"}), settings=_settings(retries=3, retry_backoff_s=0)
    )
    async with client:
        context = await _build(tmp_path, documents, client)

    assert len(client.proxy.requests) == 1  # ni una petición más tras el 401, ni reintentos
    assert context.ai_stats.classification.stopped == "auth"
    assert context.unclassified_documents == [document.source_path for document in documents]
    assert (context.ai_stats.classification.sent, context.ai_stats.classification.assigned, context.ai_stats.classification.failed) == (1, 0, 1)
    reloaded = await ContextBuilder().registry.load_context(_project(tmp_path))
    assert reloaded.ai_stats.classification.stopped == "auth"  # el contexto se persiste igualmente


@pytest.mark.asyncio
async def test_auth_error_in_manifest_mode_with_real_client_makes_exactly_one_request(tmp_path):
    documents = _documents(tmp_path, 4)
    client = fake_client(classify=lambda _request: httpx.Response(403), settings=_settings())
    async with client:
        context = await ContextBuilder().build(_project(tmp_path), documents, taxonomy_manifest=_manifest(), llm=client, ai_scope="unclassified")

    assert len(client.proxy.requests) == 1
    assert context.ai_stats.classification.stopped == "auth"
    assert [domain.slug for domain in context.domains] == ["sin-clasificar"]
    assert len(context.domains[0].documents) == 4
    assert all(document.classified_by == "rules" for document in context.domains[0].documents)
    assert (context.ai_stats.classification.sent, context.ai_stats.classification.assigned, context.ai_stats.classification.failed) == (1, 0, 1)


@pytest.mark.asyncio
async def test_auth_stop_keeps_emitting_progress_for_pending_documents(tmp_path):
    progress: list[tuple[int, int]] = []

    def on_progress(event: ProgressEvent) -> None:
        progress.append((event.processed, event.total))

    client = _scripted(["ok", "auth"])
    context = await _build(tmp_path, _documents(tmp_path, 4), client, on_progress=on_progress)

    assert _calls(client) == 2
    assert progress == [(1, 4), (2, 4), (3, 4), (4, 4)]
    assert context.ai_stats.classification.assigned == 1
    assert len(context.unclassified_documents) == 3


@pytest.mark.asyncio
async def test_cancel_token_still_works_between_documents_after_stop(tmp_path):
    token = CancelToken()
    seen = 0

    def on_progress(_event: ProgressEvent) -> None:
        nonlocal seen
        seen += 1
        if seen == 2:
            token.cancel()

    with pytest.raises(OperationCancelledError):
        await _build(tmp_path, _documents(tmp_path, 4), _scripted(["auth"]), on_progress=on_progress, cancel_token=token)


# --- L-3a: errores de conexión seguidos ------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_max_failures_stops_after_consecutive_connection_errors(tmp_path):
    client = _scripted(["conn", "conn", "conn", "ok", "ok"])
    context = await _build(tmp_path, _documents(tmp_path, 5), client, ai_max_failures=3)

    assert _calls(client) == 3
    assert context.ai_stats.classification.stopped == "connection"
    assert (context.ai_stats.classification.sent, context.ai_stats.classification.failed) == (3, 3)


@pytest.mark.asyncio
async def test_max_failures_counts_only_consecutive_connection_errors(tmp_path):
    # Una respuesta (aunque sea un error genérico o sin dominio) corta la racha.
    client = _scripted(["conn", "err", "conn", "none", "conn"])
    context = await _build(tmp_path, _documents(tmp_path, 5), client, ai_max_failures=2)

    assert _calls(client) == 5
    assert context.ai_stats.classification.stopped is None
    _assert_counts_consistent(context, sent_without_assignment=1)


@pytest.mark.asyncio
async def test_without_max_failures_connection_errors_never_stop(tmp_path):
    client = _scripted(["conn"] * 6)
    context = await _build(tmp_path, _documents(tmp_path, 6), client)

    assert _calls(client) == 6
    assert context.ai_stats.classification.stopped is None
    assert context.ai_stats.classification.failed == 6


# --- L-3b: presupuesto -----------------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_max_documents_caps_documents_sent(tmp_path):
    client = _scripted(["ok"] * 5)
    context = await _build(tmp_path, _documents(tmp_path, 5), client, ai_max_documents=2)

    assert _calls(client) == 2
    assert context.ai_stats.classification.stopped == "budget"
    assert (context.ai_stats.classification.sent, context.ai_stats.classification.assigned) == (2, 2)
    assert len(context.unclassified_documents) == 3


@pytest.mark.asyncio
async def test_max_documents_equal_to_pending_is_not_a_stop(tmp_path):
    context = await _build(tmp_path, _documents(tmp_path, 3), _scripted(["ok"] * 3), ai_max_documents=3)

    assert context.ai_stats.classification.stopped is None
    assert context.ai_stats.classification.sent == 3


@pytest.mark.asyncio
async def test_max_documents_zero_sends_nothing(tmp_path):
    client = _scripted([])
    context = await _build(tmp_path, _documents(tmp_path, 2), client, ai_max_documents=0)

    assert _calls(client) == 0
    assert context.ai_stats.classification.stopped == "budget"
    assert context.ai_stats.classification.sent == 0


@pytest.mark.asyncio
async def test_max_documents_in_manifest_mode(tmp_path):
    client = fake_client(classify=lambda request: {request.axes[0]: ("calidad", 0.9), request.axes[1]: ("procedimiento", 0.9)}, settings=_settings())
    async with client:
        context = await ContextBuilder().build(
            _project(tmp_path), _documents(tmp_path, 3), taxonomy_manifest=_manifest(), llm=client, ai_scope="unclassified", ai_max_documents=1
        )

    assert len(client.proxy.requests) == 1
    assert context.ai_stats.classification.stopped == "budget"
    assert (context.ai_stats.classification.sent, context.ai_stats.classification.assigned, context.ai_stats.classification.failed) == (1, 1, 0)


@pytest.mark.asyncio
@pytest.mark.parametrize(("own", "general", "sent"), [(1, None, 1), (3, 2, 2), (1, 4, 1), (None, None, 4)])
async def test_task_budget_combines_with_the_build_budget(tmp_path, own, general, sent):
    """2.0.0: `TaskSettings.max_documents` es el presupuesto de la fase de la tarea; con `ai_max_documents`, el menor."""
    client = _scripted(["ok"] * 4, tasks={"classify": TaskSettings(model="stub", max_documents=own)})

    context = await _build(tmp_path, _documents(tmp_path, 4), client, ai_max_documents=general)

    assert _calls(client) == sent and context.ai_stats.classification.sent == sent


@pytest.mark.asyncio
@pytest.mark.parametrize("kwargs", [{"ai_max_failures": 0}, {"ai_max_documents": -1}])
async def test_invalid_limits_raise_value_error(tmp_path, kwargs):
    with pytest.raises(ValueError):
        await _build(tmp_path, _documents(tmp_path, 1), _scripted([]), **kwargs)


# --- L-3c: recuentos -------------------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_counts_are_consistent_for_mixed_outcomes(tmp_path):
    client = _scripted(["ok", "none", "err", "conn", "ok", "none"])
    context = await _build(tmp_path, _documents(tmp_path, 6), client)

    assert (context.ai_stats.classification.sent, context.ai_stats.classification.assigned, context.ai_stats.classification.failed) == (6, 2, 2)
    _assert_counts_consistent(context, sent_without_assignment=2)


@pytest.mark.asyncio
async def test_counts_default_to_zero_without_sub_phase_b(tmp_path):
    context = await ContextBuilder().build(_project(tmp_path), _documents(tmp_path, 2), candidate_domains=["calidad"])

    assert (context.ai_stats.classification.sent, context.ai_stats.classification.assigned, context.ai_stats.classification.failed) == (0, 0, 0)
    assert context.ai_stats.classification.stopped is None


def test_old_context_json_without_new_fields_still_loads():
    old = {"project_name": "Demo", "created_at": "2026-01-01T00:00:00+00:00", "updated_at": "2026-01-01T00:00:00+00:00"}

    context = Context.model_validate(old)

    assert context.ai_stats.classification.stopped is None
    assert context.ai_stats.classification.sent == 0


# --- seguridad: la clave no sale en logs ni mensajes -----------------------------------------------------------------


@pytest.mark.asyncio
async def test_secret_never_appears_in_logs_or_messages(tmp_path, caplog):
    caplog.set_level(logging.DEBUG)
    for name in ("httpx", "httpcore", "doc_organize"):
        caplog.set_level(logging.DEBUG, logger=name)
    outcomes = iter(["connect", "500", "401"])

    def handler(request: httpx.Request) -> httpx.Response:
        outcome = next(outcomes)
        if outcome == "connect":
            raise httpx.ConnectError("refused", request=request)
        return httpx.Response(int(outcome))

    client = fake_client(classify=lambda request: handler(httpx.Request("POST", "https://proxy.test")), settings=_settings())
    async with client:
        context = await _build(tmp_path, _documents(tmp_path, 4), client)

    assert context.ai_stats.classification.stopped == "auth"
    assert caplog.records  # hubo logs que revisar
    assert _SECRET not in caplog.text


@pytest.mark.asyncio
async def test_stop_is_logged_once_with_pending_count(tmp_path, caplog):
    caplog.set_level(logging.WARNING, logger="doc_organize")
    await _build(tmp_path, _documents(tmp_path, 5), _scripted(["ok"] * 5), ai_max_documents=2)

    stops = [record.getMessage() for record in caplog.records if "Sub-fase B detenida" in record.getMessage()]
    assert stops == ["Sub-fase B detenida (budget) tras 2 documento(s) enviado(s): 3 documento(s) pendiente(s) quedan sin clasificar"]
