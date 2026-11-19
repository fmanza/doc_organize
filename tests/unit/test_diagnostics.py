"""Diagnóstico del entorno (M3, F2): `check_environment`."""

import importlib.util
import json

import httpx
import pytest

from doc_organize import diagnostics
from doc_organize.diagnostics import AiEndpoint, check_environment

_KEY = "sk-diagnostico-secreta-789"


def _by_name(report) -> dict:
    return {check.name: check for check in report.checks}


@pytest.mark.asyncio
async def test_basic_checks_run_without_network_and_with_no_paths(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("HF_HUB_CACHE", str(tmp_path))  # caché vacía
    monkeypatch.delenv("DOCLING_ARTIFACTS_PATH", raising=False)

    report = await check_environment(build_site=False)

    checks = _by_name(report)
    assert list(checks)[:5] == ["python", "docling", "docling-models", "extra:export", "extra:site"]
    assert checks["python"].status == "ok"
    assert checks["docling-models"].status == "warning"
    assert not any("ai" in name for name in checks)
    assert str(tmp_path) not in json.dumps(report.model_dump())


@pytest.mark.asyncio
async def test_docling_models_folder_and_cache(monkeypatch, tmp_path) -> None:
    empty = tmp_path / "vacia"
    empty.mkdir()
    full = tmp_path / "modelos"
    (full / "layout").mkdir(parents=True)
    cache = tmp_path / "hub"
    (cache / "models--docling-project--docling-models").mkdir(parents=True)
    monkeypatch.delenv("DOCLING_ARTIFACTS_PATH", raising=False)
    monkeypatch.setenv("HF_HUB_CACHE", str(cache))

    assert _by_name(await check_environment(build_site=False, artifacts_path=empty))["docling-models"].status == "error"
    assert _by_name(await check_environment(build_site=False, artifacts_path=full))["docling-models"].status == "ok"
    assert _by_name(await check_environment(build_site=False))["docling-models"].status == "ok"


@pytest.mark.asyncio
async def test_missing_extras_are_warnings_with_the_install_command(monkeypatch) -> None:
    monkeypatch.setattr(diagnostics, "_version", lambda package: None if package in ("openpyxl", "zensical") else "1.0")

    checks = _by_name(await check_environment())

    assert (checks["extra:export"].status, checks["extra:export"].remedy) == ("warning", "pip install doc_organize[export]")
    assert (checks["extra:site"].status, checks["extra:site"].remedy) == ("warning", "pip install doc_organize[site]")


@pytest.mark.asyncio
@pytest.mark.parametrize(("version", "status"), [("0.1.1", "ok"), ("0.1.9", "ok"), ("0.2.0", "warning"), ("0.1.0", "warning")])
async def test_zensical_tested_range(monkeypatch, version, status) -> None:
    monkeypatch.setattr(diagnostics, "_version", lambda package: version if package == "zensical" else "1.0")

    assert _by_name(await check_environment(build_site=False))["extra:site"].status == status


@pytest.mark.asyncio
async def test_failed_site_build_is_an_error(monkeypatch) -> None:
    monkeypatch.setattr(diagnostics, "_version", lambda package: "0.1.1" if package == "zensical" else "1.0")
    monkeypatch.setattr(diagnostics, "_build_minimal_site", lambda: "TOML no válido")

    report = await check_environment()

    assert _by_name(report)["extra:site"].status == "error"
    assert report.ok is False


@pytest.mark.slow
@pytest.mark.asyncio
@pytest.mark.skipif(importlib.util.find_spec("zensical") is None, reason="zensical no instalado (extra site)")
async def test_real_minimal_site_build() -> None:
    assert diagnostics._build_minimal_site() is None


# --- check_ai --------------------------------------------------------------------------------------------------------


def _transport(*responses: httpx.Response, requests: list | None = None) -> httpx.MockTransport:
    queue = list(responses)

    def handler(request: httpx.Request) -> httpx.Response:
        if requests is not None:
            requests.append(request)
        return queue.pop(0)

    return httpx.MockTransport(handler)


async def _ai_check(transport: httpx.MockTransport):
    endpoint = AiEndpoint(name="clasificacion", base_url="https://proxy.test", virtual_key=_KEY, model="modelo-x")
    report = await check_environment(check_ai=True, ai_endpoints=[endpoint], build_site=False, transport=transport)
    return _by_name(report)["ai:clasificacion"], report


@pytest.mark.asyncio
async def test_ai_with_strict_json_schema_is_ok_and_sends_only_synthetic_text() -> None:
    requests: list[httpx.Request] = []

    check, report = await _ai_check(_transport(httpx.Response(200, json={"choices": [{"message": {"content": '{"ok": true}'}}]}), requests=requests))

    assert check.status == "ok"
    body = json.loads(requests[0].content)
    assert body["response_format"]["type"] == "json_schema" and body["model"] == "modelo-x"
    assert "sintético" in body["messages"][1]["content"]
    assert _KEY not in json.dumps(report.model_dump())


@pytest.mark.asyncio
async def test_ai_without_json_schema_is_a_warning() -> None:
    check, _ = await _ai_check(_transport(httpx.Response(400), httpx.Response(200, json={"choices": [{"message": {"content": "{}"}}]})))

    assert check.status == "warning" and "json_schema" in check.detail


@pytest.mark.asyncio
@pytest.mark.parametrize(("response", "fragment"), [(httpx.Response(401), "clave rechazada"), (httpx.Response(404), "HTTP 404")])
async def test_ai_errors(response, fragment) -> None:
    check, report = await _ai_check(_transport(response))

    assert check.status == "error" and fragment in check.detail
    assert report.ok is False


@pytest.mark.asyncio
async def test_ai_connection_error() -> None:
    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    check, _ = await _ai_check(httpx.MockTransport(refuse))

    assert check.status == "error" and "ConnectError" in check.detail


async def _embedding_check(transport: httpx.MockTransport):
    endpoint = AiEndpoint(name="embed", base_url="https://proxy.test", virtual_key=_KEY, model="modelo-e", kind="embedding")
    report = await check_environment(check_ai=True, ai_endpoints=[endpoint], build_site=False, transport=transport)
    return _by_name(report)["ai:embed"], report


@pytest.mark.asyncio
async def test_embedding_endpoint_asks_for_a_vector() -> None:
    requests: list[httpx.Request] = []

    check, report = await _embedding_check(
        _transport(httpx.Response(200, json={"data": [{"index": 0, "embedding": [0.1] * 1024}]}), requests=requests)
    )

    assert check.status == "ok" and "1024" in check.detail
    assert requests[0].url.path == "/embeddings" and json.loads(requests[0].content)["model"] == "modelo-e"
    assert _KEY not in json.dumps(report.model_dump())


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("response", "fragment"),
    [(httpx.Response(403), "clave rechazada"), (httpx.Response(404), "HTTP 404"), (httpx.Response(200, json={"data": []}), "no trae un vector")],
)
async def test_embedding_errors(response, fragment) -> None:
    check, _ = await _embedding_check(_transport(response))

    assert check.status == "error" and fragment in check.detail


def _clear_ai_env(monkeypatch) -> None:
    import os

    for name in list(os.environ):
        if name.startswith("DOC_ORGANIZE_LITELLM_"):
            monkeypatch.delenv(name, raising=False)


@pytest.mark.asyncio
async def test_ai_endpoints_come_from_the_2_0_environment(monkeypatch) -> None:
    _clear_ai_env(monkeypatch)
    report = await check_environment(check_ai=True, build_site=False)
    assert _by_name(report)["ai"].detail.startswith("Ningún modelo")

    monkeypatch.setenv("DOC_ORGANIZE_LITELLM_BASE_URL", "https://proxy.test")
    monkeypatch.setenv("DOC_ORGANIZE_LITELLM_VIRTUAL_KEY", _KEY)
    monkeypatch.setenv("DOC_ORGANIZE_LITELLM_MODEL_CLASSIFY", "modelo-c")
    requests: list[httpx.Request] = []
    transport = _transport(*[httpx.Response(200, json={"choices": [{"message": {"content": '{"ok": true}'}}]})] * 3, requests=requests)
    report = await check_environment(check_ai=True, build_site=False, transport=transport)

    checks = _by_name(report)
    assert [checks[name].status for name in ("ai:classify", "ai:enrich", "ai:taxonomy_design")] == ["ok", "ok", "ok"]
    assert [json.loads(request.content)["model"] for request in requests] == ["modelo-c", "doc-organize-enrich", "doc-organize-taxonomy-design"]

    monkeypatch.setenv("DOC_ORGANIZE_LITELLM_MODEL_EMBED", "modelo-e")  # con modelo propio, también los embeddings
    chat = httpx.Response(200, json={"choices": [{"message": {"content": '{"ok": true}'}}]})
    vector = httpx.Response(200, json={"data": [{"index": 0, "embedding": [0.0, 1.0]}]})
    report = await check_environment(check_ai=True, build_site=False, transport=_transport(chat, chat, chat, vector))
    assert _by_name(report)["ai:embed"].status == "ok"


@pytest.mark.asyncio
async def test_1_x_variables_are_reported_with_their_replacement(monkeypatch) -> None:
    _clear_ai_env(monkeypatch)
    monkeypatch.setenv("DOC_ORGANIZE_LITELLM_ENRICHMENT_MODEL", "modelo-viejo")

    report = await check_environment(check_ai=True, build_site=False)

    check = _by_name(report)["ai"]
    assert check.status == "error" and "DOC_ORGANIZE_LITELLM_MODEL_ENRICH" in check.detail and "modelo-viejo" not in check.detail
    assert report.ok is False
