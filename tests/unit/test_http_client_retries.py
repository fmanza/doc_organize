"""Tests de los reintentos de AiHttpClientBase: timeout y error de transporte (L-3b, 0.14.0) y 429/503 (D5, 2.0.0)."""

import httpx
import pytest

from doc_organize.ai import DomainClassificationClient, _http_client_base
from doc_organize.core.exceptions import DomainClassificationAuthError, DomainClassificationConnectionError, DomainClassificationError
from doc_organize.core.models import LiteLLMClassificationConfig

_SECRET = "sk-retry-secret-456"


def _ok() -> httpx.Response:
    return httpx.Response(200, json={"choices": [{"message": {"content": '{"domain": "calidad", "confidence": 0.9}'}}]})


def _client(handler, *, retries: int, backoff_s: float = 0.0, rate_limit_retries: int = 3, max_wait: float = 60.0) -> DomainClassificationClient:
    config = LiteLLMClassificationConfig(
        base_url="https://proxy.test",
        virtual_key=_SECRET,
        retries=retries,
        retry_backoff_s=backoff_s,
        rate_limit_retries=rate_limit_retries,
        max_retry_wait_s=max_wait,
    )
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
    ("status", "error_cls"), [(401, DomainClassificationAuthError), (500, DomainClassificationError), (404, DomainClassificationError)]
)
async def test_http_errors_other_than_429_503_are_never_retried(status, error_cls):
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


# --- D5 (2.0.0): 429 y 503 ------------------------------------------------------------------------------------------


@pytest.fixture
def sleeps(monkeypatch) -> list[float]:
    """Esperas simuladas: se anotan y hacen avanzar el reloj del cliente, sin esperar de verdad."""
    delays: list[float] = []
    clock = [1000.0]

    async def fake_sleep(delay: float) -> None:
        delays.append(delay)
        clock[0] += delay

    monkeypatch.setattr(_http_client_base.asyncio, "sleep", fake_sleep)
    monkeypatch.setattr(_http_client_base.AiHttpClientBase, "_now", staticmethod(lambda: clock[0]))
    return delays


def _script(*responses: httpx.Response):
    queue = list(responses)
    attempts: list[int] = []

    def handler(_request: httpx.Request) -> httpx.Response:
        attempts.append(1)
        return queue.pop(0) if queue else _ok()

    return handler, attempts


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [429, 503])
async def test_rate_limit_is_retried_honouring_retry_after_in_seconds(status, sleeps):
    handler, attempts = _script(httpx.Response(status, headers={"Retry-After": "7"}), httpx.Response(status, headers={"Retry-After": "2.5"}))

    result = await _classify(_client(handler, retries=0))

    assert result.domain == "calidad"
    assert len(attempts) == 3
    assert sleeps == pytest.approx([7.0, 2.5])


@pytest.mark.asyncio
async def test_retry_after_as_http_date_and_cap(sleeps):
    from datetime import UTC, datetime, timedelta
    from email.utils import format_datetime

    in_ten = format_datetime(datetime.now(UTC) + timedelta(seconds=10), usegmt=True)
    handler, _ = _script(httpx.Response(429, headers={"Retry-After": in_ten}), httpx.Response(429, headers={"Retry-After": "3600"}))

    await _classify(_client(handler, retries=0, max_wait=60))

    assert 8 <= sleeps[0] <= 10
    assert sleeps[1] == pytest.approx(60)  # tope por espera


@pytest.mark.asyncio
async def test_without_retry_after_the_wait_doubles(sleeps):
    handler, _ = _script(httpx.Response(429), httpx.Response(429), httpx.Response(429))

    await _classify(_client(handler, retries=0, backoff_s=0.5))

    assert sleeps == pytest.approx([0.5, 1.0, 2.0])


@pytest.mark.asyncio
async def test_rate_limit_retries_exhausted_raise_the_usual_error(sleeps):
    handler, attempts = _script(*[httpx.Response(429)] * 5)

    with pytest.raises(DomainClassificationError, match="429"):
        await _classify(_client(handler, retries=0, rate_limit_retries=2))
    assert len(attempts) == 3


@pytest.mark.asyncio
async def test_zero_rate_limit_retries_behaves_like_1_x(sleeps):
    handler, attempts = _script(httpx.Response(429))

    with pytest.raises(DomainClassificationError):
        await _classify(_client(handler, retries=0, rate_limit_retries=0))
    assert len(attempts) == 1 and sleeps == []


@pytest.mark.asyncio
async def test_the_wait_is_shared_by_concurrent_calls():
    """Mientras dura la espera de un 429, ninguna otra llamada del mismo cliente sale (no insisten todas a la vez)."""
    import asyncio
    import time

    sent_at: list[float] = []
    first = True

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal first
        sent_at.append(time.monotonic())
        if first:
            first = False
            return httpx.Response(429, headers={"Retry-After": "0.3"})
        return _ok()

    client = _client(handler, retries=0)
    async with client:
        start = time.monotonic()

        async def call() -> None:
            await client.classify(chunks_text="t", title="T", candidate_domains=["calidad"])

        await call()  # recibe el 429, espera 0,3 s y reintenta
        sent_at.clear()
        client._cooldown_until = time.monotonic() + 0.3  # otra espera en curso
        await asyncio.gather(call(), call())
    assert all(moment - start >= 0.55 for moment in sent_at)
