"""Tests de los reintentos de AiHttpClientBase (L-3b, 0.14.0): solo timeout y error de transporte, nunca HTTP."""

import httpx
import pytest

from doc_organize.ai import DomainClassificationClient, _http_client_base
from doc_organize.core.exceptions import DomainClassificationAuthError, DomainClassificationConnectionError, DomainClassificationError
from doc_organize.core.models import LiteLLMClassificationConfig

_SECRET = "sk-retry-secret-456"


def _ok() -> httpx.Response:
    return httpx.Response(200, json={"choices": [{"message": {"content": '{"domain": "calidad", "confidence": 0.9}'}}]})


def _client(handler, *, retries: int, backoff_s: float = 0.0) -> DomainClassificationClient:
    config = LiteLLMClassificationConfig(base_url="https://proxy.test", virtual_key=_SECRET, retries=retries, retry_backoff_s=backoff_s)
    return DomainClassificationClient(config, transport=httpx.MockTransport(handler))


async def _classify(client: DomainClassificationClient):
    async with client:
        return await client.classify(chunks_text="texto", title="Título", candidate_domains=["calidad"])


@pytest.mark.asyncio
async def test_retries_transport_errors_until_success():
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise httpx.ConnectError("refused", request=request)
        return _ok()

    result = await _classify(_client(handler, retries=2))

    assert attempts == 3
    assert result.domain == "calidad"


@pytest.mark.asyncio
async def test_timeout_is_retried_and_mapped_when_exhausted():
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        raise httpx.ReadTimeout("slow", request=request)

    with pytest.raises(DomainClassificationConnectionError, match="Timeout"):
        await _classify(_client(handler, retries=1))
    assert attempts == 2


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status", "error_cls"), [(401, DomainClassificationAuthError), (429, DomainClassificationError), (503, DomainClassificationError)]
)
async def test_http_errors_are_never_retried(status, error_cls):
    attempts = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(status)

    with pytest.raises(error_cls):
        await _classify(_client(handler, retries=3))
    assert attempts == 1


@pytest.mark.asyncio
async def test_default_is_no_retry():
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        raise httpx.ConnectError("refused", request=request)

    with pytest.raises(DomainClassificationConnectionError):
        await _classify(
            DomainClassificationClient(
                LiteLLMClassificationConfig(base_url="https://proxy.test", virtual_key=_SECRET), transport=httpx.MockTransport(handler)
            )
        )
    assert attempts == 1


@pytest.mark.asyncio
async def test_backoff_doubles_between_attempts(monkeypatch):
    delays: list[float] = []

    async def fake_sleep(delay: float) -> None:
        delays.append(delay)

    monkeypatch.setattr(_http_client_base.asyncio, "sleep", fake_sleep)

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    with pytest.raises(DomainClassificationConnectionError):
        await _classify(_client(handler, retries=3, backoff_s=0.5))
    assert delays == [0.5, 1.0, 2.0]


def test_negative_retries_rejected_by_config():
    with pytest.raises(ValueError):
        LiteLLMClassificationConfig(base_url="https://proxy.test", virtual_key=_SECRET, retries=-1)
