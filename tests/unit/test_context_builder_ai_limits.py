"""Tests de los límites de la Sub-fase B de ContextBuilder (L-3a…L-3c, 0.14.0).

Parada ante clave rechazada, tras N errores de conexión seguidos o al agotar el presupuesto, y recuento de lo hecho.
Los tests de «exactamente 1 petición» usan los clientes reales con `httpx.MockTransport` (sin red).
"""

import json
import logging

from datetime import UTC, datetime

import httpx
import pytest

from doc_organize.ai import DomainClassificationClient, TaxonomyClassificationClient
from doc_organize.context.context_builder import ContextBuilder
from doc_organize.core.exceptions import (
    DomainClassificationAuthError,
    DomainClassificationConnectionError,
    DomainClassificationError,
    OperationCancelledError,
)
from doc_organize.core.models import (
    Context,
    ConversionResult,
    DomainClassificationResult,
    LiteLLMClassificationConfig,
    LiteLLMTaxonomyClassificationConfig,
    Project,
    TaxonomyCatalogEntry,
    TaxonomyManifest,
)
from doc_organize.core.progress import CancelToken

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
    return TaxonomyManifest(
        domains=[TaxonomyCatalogEntry(slug="calidad", name="Calidad")],
        material_types=[TaxonomyCatalogEntry(slug="procedimiento", name="Procedimiento")],
    )


class _ScriptedClient:
    """Doble de `DomainClassificationClient`: cada llamada consume el siguiente resultado del guion.

    `"ok"` asigna `calidad`, `"none"` responde sin dominio, `"auth"`/`"conn"`/`"err"` lanzan la excepción
    correspondiente.
    """

    def __init__(self, script: list[str]) -> None:
        self.script = list(script)
        self.calls = 0

    async def classify(self, *, chunks_text: str, title: str | None, candidate_domains: list[str]) -> DomainClassificationResult:
        outcome = self.script[self.calls] if self.calls < len(self.script) else "ok"
        self.calls += 1
        if outcome == "auth":
            raise DomainClassificationAuthError("rechazada")
        if outcome == "conn":
            raise DomainClassificationConnectionError("sin red")
        if outcome == "err":
            raise DomainClassificationError("HTTP 500")
        return DomainClassificationResult(domain="calidad" if outcome == "ok" else None, confidence=0.9)


async def _build(tmp_path, documents, client, **kwargs) -> Context:
    return await ContextBuilder().build(
        _project(tmp_path),
        documents,
        candidate_domains=["calidad"],
        ai_classification_enabled=True,
        ai_classification_client=client,
        **kwargs,
    )


def _assert_counts_consistent(context: Context, sent_without_assignment: int) -> None:
    assert context.ai_documents_sent == context.ai_documents_classified + context.ai_documents_failed + sent_without_assignment


# --- L-3a: clave rechazada -------------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_auth_error_with_real_client_makes_exactly_one_request(tmp_path):
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(401, json={"error": "invalid key"})

    documents = _documents(tmp_path, 5)
    config = LiteLLMClassificationConfig(base_url="https://proxy.test", virtual_key=_SECRET, retries=3, retry_backoff_s=0)
    async with DomainClassificationClient(config, transport=httpx.MockTransport(handler)) as client:
        context = await _build(tmp_path, documents, client)

    assert len(requests) == 1  # ni una petición más tras el 401, ni reintentos
    assert context.ai_classification_stopped == "auth"
    assert context.unclassified_documents == [document.source_path for document in documents]
    assert (context.ai_documents_sent, context.ai_documents_classified, context.ai_documents_failed) == (1, 0, 1)
    reloaded = await ContextBuilder().registry.load_context(_project(tmp_path))
    assert reloaded.ai_classification_stopped == "auth"  # el contexto se persiste igualmente


@pytest.mark.asyncio
async def test_auth_error_in_manifest_mode_with_real_client_makes_exactly_one_request(tmp_path):
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(403)

    documents = _documents(tmp_path, 4)
    config = LiteLLMTaxonomyClassificationConfig(base_url="https://proxy.test", virtual_key=_SECRET)
    async with TaxonomyClassificationClient(config, transport=httpx.MockTransport(handler)) as client:
        context = await ContextBuilder().build(
            _project(tmp_path),
            documents,
            taxonomy_manifest=_manifest(),
            ai_classification_enabled=True,
            taxonomy_classification_client=client,
        )

    assert len(requests) == 1
    assert context.ai_classification_stopped == "auth"
    assert [domain.slug for domain in context.domains] == ["sin-clasificar"]
    assert len(context.domains[0].documents) == 4
    assert all(document.classified_by == "rules" for document in context.domains[0].documents)
    assert (context.ai_documents_sent, context.ai_documents_classified, context.ai_documents_failed) == (1, 0, 1)


@pytest.mark.asyncio
async def test_auth_stop_keeps_emitting_progress_for_pending_documents(tmp_path):
    progress: list[tuple[int, int]] = []

    async def on_progress(index: int, total: int, _path: str) -> None:
        progress.append((index, total))

    client = _ScriptedClient(["ok", "auth"])
    context = await _build(tmp_path, _documents(tmp_path, 4), client, on_ai_progress=on_progress)

    assert client.calls == 2
    assert progress == [(1, 4), (2, 4), (3, 4), (4, 4)]
    assert context.ai_documents_classified == 1
    assert len(context.unclassified_documents) == 3


@pytest.mark.asyncio
async def test_cancel_token_still_works_between_documents_after_stop(tmp_path):
    token = CancelToken()
    seen = 0

    async def on_progress(_index: int, _total: int, _path: str) -> None:
        nonlocal seen
        seen += 1
        if seen == 2:
            token.cancel()

    with pytest.raises(OperationCancelledError):
        await _build(tmp_path, _documents(tmp_path, 4), _ScriptedClient(["auth"]), on_ai_progress=on_progress, cancel_token=token)


# --- L-3a: errores de conexión seguidos ------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_max_failures_stops_after_consecutive_connection_errors(tmp_path):
    client = _ScriptedClient(["conn", "conn", "conn", "ok", "ok"])
    context = await _build(tmp_path, _documents(tmp_path, 5), client, ai_max_failures=3)

    assert client.calls == 3
    assert context.ai_classification_stopped == "connection"
    assert (context.ai_documents_sent, context.ai_documents_failed) == (3, 3)


@pytest.mark.asyncio
async def test_max_failures_counts_only_consecutive_connection_errors(tmp_path):
    # Una respuesta (aunque sea un error genérico o sin dominio) corta la racha.
    client = _ScriptedClient(["conn", "err", "conn", "none", "conn"])
    context = await _build(tmp_path, _documents(tmp_path, 5), client, ai_max_failures=2)

    assert client.calls == 5
    assert context.ai_classification_stopped is None
    _assert_counts_consistent(context, sent_without_assignment=1)


@pytest.mark.asyncio
async def test_without_max_failures_connection_errors_never_stop(tmp_path):
    client = _ScriptedClient(["conn"] * 6)
    context = await _build(tmp_path, _documents(tmp_path, 6), client)

    assert client.calls == 6
    assert context.ai_classification_stopped is None
    assert context.ai_documents_failed == 6


# --- L-3b: presupuesto -----------------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_max_documents_caps_documents_sent(tmp_path):
    client = _ScriptedClient(["ok"] * 5)
    context = await _build(tmp_path, _documents(tmp_path, 5), client, ai_max_documents=2)

    assert client.calls == 2
    assert context.ai_classification_stopped == "budget"
    assert (context.ai_documents_sent, context.ai_documents_classified) == (2, 2)
    assert len(context.unclassified_documents) == 3


@pytest.mark.asyncio
async def test_max_documents_equal_to_pending_is_not_a_stop(tmp_path):
    context = await _build(tmp_path, _documents(tmp_path, 3), _ScriptedClient(["ok"] * 3), ai_max_documents=3)

    assert context.ai_classification_stopped is None
    assert context.ai_documents_sent == 3


@pytest.mark.asyncio
async def test_max_documents_zero_sends_nothing(tmp_path):
    client = _ScriptedClient([])
    context = await _build(tmp_path, _documents(tmp_path, 2), client, ai_max_documents=0)

    assert client.calls == 0
    assert context.ai_classification_stopped == "budget"
    assert context.ai_documents_sent == 0


@pytest.mark.asyncio
async def test_max_documents_in_manifest_mode(tmp_path):
    requests = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal requests
        requests += 1
        content = json.dumps({"domain": "calidad", "domain_confidence": 0.9, "material_type": "procedimiento", "material_type_confidence": 0.9})
        return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})

    config = LiteLLMTaxonomyClassificationConfig(base_url="https://proxy.test", virtual_key=_SECRET)
    async with TaxonomyClassificationClient(config, transport=httpx.MockTransport(handler)) as client:
        context = await ContextBuilder().build(
            _project(tmp_path),
            _documents(tmp_path, 3),
            taxonomy_manifest=_manifest(),
            ai_classification_enabled=True,
            taxonomy_classification_client=client,
            ai_max_documents=1,
        )

    assert requests == 1
    assert context.ai_classification_stopped == "budget"
    assert (context.ai_documents_sent, context.ai_documents_classified, context.ai_documents_failed) == (1, 1, 0)


@pytest.mark.asyncio
@pytest.mark.parametrize("kwargs", [{"ai_max_failures": 0}, {"ai_max_documents": -1}])
async def test_invalid_limits_raise_value_error(tmp_path, kwargs):
    with pytest.raises(ValueError):
        await _build(tmp_path, _documents(tmp_path, 1), _ScriptedClient([]), **kwargs)


# --- L-3c: recuentos -------------------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_counts_are_consistent_for_mixed_outcomes(tmp_path):
    client = _ScriptedClient(["ok", "none", "err", "conn", "ok", "none"])
    context = await _build(tmp_path, _documents(tmp_path, 6), client)

    assert (context.ai_documents_sent, context.ai_documents_classified, context.ai_documents_failed) == (6, 2, 2)
    _assert_counts_consistent(context, sent_without_assignment=2)


@pytest.mark.asyncio
async def test_counts_default_to_zero_without_sub_phase_b(tmp_path):
    context = await ContextBuilder().build(_project(tmp_path), _documents(tmp_path, 2), candidate_domains=["calidad"])

    assert (context.ai_documents_sent, context.ai_documents_classified, context.ai_documents_failed) == (0, 0, 0)
    assert context.ai_classification_stopped is None


def test_old_context_json_without_new_fields_still_loads():
    old = {"project_name": "Demo", "created_at": "2026-01-01T00:00:00+00:00", "updated_at": "2026-01-01T00:00:00+00:00"}

    context = Context.model_validate(old)

    assert context.ai_classification_stopped is None
    assert context.ai_documents_sent == 0


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

    config = LiteLLMClassificationConfig(base_url="https://proxy.test", virtual_key=_SECRET)
    async with DomainClassificationClient(config, transport=httpx.MockTransport(handler)) as client:
        context = await _build(tmp_path, _documents(tmp_path, 4), client)

    assert context.ai_classification_stopped == "auth"
    assert caplog.records  # hubo logs que revisar
    assert _SECRET not in caplog.text


@pytest.mark.asyncio
async def test_stop_is_logged_once_with_pending_count(tmp_path, caplog):
    caplog.set_level(logging.WARNING, logger="doc_organize")
    await _build(tmp_path, _documents(tmp_path, 5), _ScriptedClient(["ok"] * 5), ai_max_documents=2)

    stops = [record.getMessage() for record in caplog.records if "Sub-fase B detenida" in record.getMessage()]
    assert stops == ["Sub-fase B detenida (budget) tras 2 documento(s) enviado(s): 3 documento(s) pendiente(s) quedan sin clasificar"]
