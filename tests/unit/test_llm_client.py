"""Cliente único de IA (M4, G1): `LlmClient`, `settings_from_env` y `PromptRegistry`."""

import json

import httpx
import pytest

from doc_organize.ai import LlmClient, PromptRegistry, _http_client_base, legacy_variables, settings_from_env
from doc_organize.core.exceptions import AiAuthError, AiConfigurationError, AiError, AiResponseError
from doc_organize.core.models import AiSettings, TaskSettings

SECRET = "Xq7#Secreto-9931"
SCHEMA = {"type": "object", "properties": {"ok": {"type": "boolean"}}, "required": ["ok"], "additionalProperties": False}


def _reply(content: str = '{"ok": true}', **extra: object) -> httpx.Response:
    return httpx.Response(200, json={"choices": [{"message": {"content": content}}], **extra})


class _Proxy:
    """Proxy falso: responde con la cola dada y guarda las peticiones."""

    def __init__(self, *responses: httpx.Response) -> None:
        self.queue = list(responses)
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return self.queue.pop(0) if self.queue else _reply()

    def bodies(self) -> list[dict]:
        return [json.loads(request.content) for request in self.requests]


def _client(proxy: _Proxy, **settings: object) -> LlmClient:
    base = {"base_url": "https://proxy.test", "virtual_key": "sk-general", "rate_limit_retries": 0}
    return LlmClient(AiSettings(**(base | settings)), transport=httpx.MockTransport(proxy))  # type: ignore[arg-type]


async def _ask(client: LlmClient, content: str = "Responde JSON", task: str = "classify"):
    async with client:
        return await client.complete_json(task, [{"role": "user", "content": content}], schema=SCHEMA, parse=lambda data: bool(data["ok"]))  # type: ignore[arg-type]


# --- complete_json ---------------------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sends_strict_schema_with_the_task_model_key_and_tags() -> None:
    proxy = _Proxy(_reply(usage={"prompt_tokens": 12, "completion_tokens": 3}))
    client = _client(proxy, tasks={"classify": TaskSettings(model="modelo-c", virtual_key="sk-clasificar")}, tags=["proyecto:demo"])

    result = await _ask(client)

    body = proxy.bodies()[0]
    assert body["model"] == "modelo-c" and body["temperature"] == 0
    assert body["response_format"] == {"type": "json_schema", "json_schema": {"name": "classify", "strict": True, "schema": SCHEMA}}
    assert body["metadata"] == {"tags": ["doc_organize", "task:classify", "proyecto:demo"]}
    assert proxy.requests[0].headers["Authorization"] == "Bearer sk-clasificar"
    assert (result.value, result.model, result.response_format) == (True, "modelo-c", "json_schema")
    assert (result.usage.prompt_tokens, result.usage.completion_tokens) == (12, 3)


@pytest.mark.asyncio
async def test_default_model_is_the_recommended_alias_and_general_key() -> None:
    proxy = _Proxy()

    await _ask(_client(proxy), task="enrich")

    assert proxy.bodies()[0]["model"] == "doc-organize-enrich"
    assert proxy.requests[0].headers["Authorization"] == "Bearer sk-general"


@pytest.mark.asyncio
async def test_credentials_are_redacted_before_leaving() -> None:
    proxy = _Proxy()

    result = await _ask(_client(proxy), content=f"Acceso: password: {SECRET}")

    assert SECRET not in proxy.requests[0].content.decode("utf-8")
    assert "«REDACTADO»" in proxy.bodies()[0]["messages"][0]["content"]
    assert result.redacted == {"password": 1}


@pytest.mark.asyncio
async def test_without_redaction_the_text_goes_as_is() -> None:
    proxy = _Proxy()

    result = await _ask(_client(proxy, redact_credentials=False), content=f"password: {SECRET}")

    assert SECRET in proxy.bodies()[0]["messages"][0]["content"] and result.redacted == {}


@pytest.mark.asyncio
async def test_falls_back_once_to_json_object_and_remembers_it() -> None:
    proxy = _Proxy(httpx.Response(400, json={"error": "response_format not supported"}), _reply(), _reply())
    client = _client(proxy)

    async with client:
        first = await client.complete_json("classify", [{"role": "user", "content": "JSON"}], schema=SCHEMA, parse=lambda data: data["ok"])
        second = await client.complete_json("classify", [{"role": "user", "content": "JSON"}], schema=SCHEMA, parse=lambda data: data["ok"])

    assert [body["response_format"]["type"] for body in proxy.bodies()] == ["json_schema", "json_object", "json_object"]
    assert first.response_format == second.response_format == "json_object"


@pytest.mark.asyncio
async def test_400_also_without_schema_is_an_error() -> None:
    proxy = _Proxy(httpx.Response(400), httpx.Response(400))

    with pytest.raises(AiError, match="400"):
        await _ask(_client(proxy))


@pytest.mark.asyncio
@pytest.mark.parametrize("content", ["no es json", '{"otra": 1}', "[1, 2]"])
async def test_responses_are_always_validated(content: str) -> None:
    with pytest.raises(AiResponseError):
        await _ask(_client(_Proxy(_reply(content))))


@pytest.mark.asyncio
async def test_rejected_key_is_an_auth_error() -> None:
    with pytest.raises(AiAuthError):
        await _ask(_client(_Proxy(httpx.Response(401))))


@pytest.mark.asyncio
async def test_rate_limit_is_retried(monkeypatch) -> None:
    async def no_sleep(_delay: float) -> None:
        return None

    monkeypatch.setattr(_http_client_base.asyncio, "sleep", no_sleep)
    proxy = _Proxy(httpx.Response(429), _reply())

    result = await _ask(_client(proxy, rate_limit_retries=2))

    assert result.value is True and len(proxy.requests) == 2


# --- complete_with_tools y embed -------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_complete_with_tools_returns_the_assistant_message() -> None:
    call = {"id": "1", "type": "function", "function": {"name": "buscar", "arguments": "{}"}}
    proxy = _Proxy(httpx.Response(200, json={"choices": [{"message": {"role": "assistant", "content": None, "tool_calls": [call]}}]}))
    tools = [{"type": "function", "function": {"name": "buscar", "parameters": {"type": "object"}}}]

    async with _client(proxy) as client:
        message, _ = await client.complete_with_tools("agent", [{"role": "user", "content": f"clave = {SECRET}"}], tools)

    assert message["tool_calls"] == [call]
    assert proxy.bodies()[0]["tools"] == tools and SECRET not in proxy.requests[0].content.decode("utf-8")


@pytest.mark.asyncio
async def test_embed_keeps_order_redacts_and_checks_the_count() -> None:
    proxy = _Proxy(
        httpx.Response(200, json={"data": [{"index": 1, "embedding": [0.0, 1.0]}, {"index": 0, "embedding": [1.0, 0.0]}]}),
        httpx.Response(200, json={"data": [{"index": 0, "embedding": [1.0]}]}),
    )

    async with _client(proxy) as client:
        vectors = await client.embed(["uno", f"password: {SECRET}"])
        with pytest.raises(AiResponseError):
            await client.embed(["a", "b"])
        assert await client.embed([]) == []

    assert vectors == [[1.0, 0.0], [0.0, 1.0]]
    assert proxy.bodies()[0]["model"] == "doc-organize-embed" and SECRET not in proxy.requests[0].content.decode("utf-8")


# --- settings_from_env -----------------------------------------------------------------------------------------------


def test_settings_from_env_reads_the_2_0_variables() -> None:
    settings = settings_from_env(
        {
            "DOC_ORGANIZE_LITELLM_BASE_URL": "http://localhost:4000",
            "DOC_ORGANIZE_LITELLM_VIRTUAL_KEY": "sk-general",
            "DOC_ORGANIZE_LITELLM_MODEL_CLASSIFY": "qwen",
            "DOC_ORGANIZE_LITELLM_VIRTUAL_KEY_ENRICH": "sk-enrich",
        }
    )

    assert settings is not None
    assert (settings.model_for("classify"), settings.key_for("classify")) == ("qwen", "sk-general")
    assert (settings.model_for("enrich"), settings.key_for("enrich")) == ("doc-organize-enrich", "sk-enrich")


def test_without_base_url_there_is_no_ai_and_without_key_it_is_an_error() -> None:
    assert settings_from_env({}) is None
    with pytest.raises(AiConfigurationError, match="VIRTUAL_KEY"):
        settings_from_env({"DOC_ORGANIZE_LITELLM_BASE_URL": "http://x"})


def test_1_x_variables_fail_loudly_with_their_replacement() -> None:
    environ = {
        "DOC_ORGANIZE_LITELLM_BASE_URL": "http://x",
        "DOC_ORGANIZE_LITELLM_VIRTUAL_KEY": "k",
        "DOC_ORGANIZE_LITELLM_TAXONOMY_CLASSIFICATION_MODEL": "viejo",
        "DOC_ORGANIZE_LITELLM_ENRICHMENT_VIRTUAL_KEY": "k2",
    }

    with pytest.raises(AiConfigurationError) as error:
        settings_from_env(environ)

    message = str(error.value)
    assert "DOC_ORGANIZE_LITELLM_TAXONOMY_CLASSIFICATION_MODEL → DOC_ORGANIZE_LITELLM_MODEL_CLASSIFY" in message
    assert "DOC_ORGANIZE_LITELLM_ENRICHMENT_VIRTUAL_KEY → DOC_ORGANIZE_LITELLM_VIRTUAL_KEY_ENRICH" in message
    assert "k2" not in message and "viejo" not in message  # nunca los valores
    assert legacy_variables({"DOC_ORGANIZE_LITELLM_BASE_URL": "x"}) == {}  # la del proxy de 2.0 (y del uso) no es antigua


def test_keys_never_show_in_repr() -> None:
    settings = AiSettings(base_url="u", virtual_key="sk-general-secreta", tasks={"classify": TaskSettings(model="m", virtual_key="sk-tarea-secreta")})

    assert "secreta" not in repr(settings) and "secreta" not in str(settings)


# --- PromptRegistry --------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("task", ["classify", "enrich", "taxonomy_design"])
def test_builtin_prompts_load_with_their_provenance(task: str) -> None:
    template = PromptRegistry().get(task)  # type: ignore[arg-type]

    provenance = template.provenance("modelo-x")
    assert (provenance.task, provenance.prompt_id, provenance.version, provenance.source, provenance.model) == (
        task,
        task,
        "1",
        "builtin",
        "modelo-x",
    )
    assert len(provenance.sha256) == 64


def test_project_prompt_overrides_the_builtin_and_dollars_in_values_are_safe(tmp_path) -> None:
    folder = tmp_path / ".doc_organize" / "prompts"
    folder.mkdir(parents=True)
    (folder / "enrich.md").write_text("---\nid: enrich-vd\nversion: 3\n---\n## system\nDescribe.\n## user\n$title: $content\n", encoding="utf-8")

    template = PromptRegistry(tmp_path).get("enrich")
    messages = template.render(title="Coste", content="vale $100 y ${VAR}")

    assert (template.prompt_id, template.version, template.source) == ("enrich-vd", "3", "project")
    assert messages == [{"role": "system", "content": "Describe."}, {"role": "user", "content": "Coste: vale $100 y ${VAR}"}]


@pytest.mark.parametrize(
    ("text", "match"),
    [
        ("sin front matter", "front matter"),
        ("---\nid: x\n---\n## system\na\n## user\nb\n", "version"),
        ("---\nid: x\nversion: 1\n---\n## system\nsolo system\n", "secciones"),
    ],
)
def test_malformed_project_prompts_are_rejected(tmp_path, text: str, match: str) -> None:
    folder = tmp_path / ".doc_organize" / "prompts"
    folder.mkdir(parents=True)
    (folder / "classify.md").write_text(text, encoding="utf-8")

    with pytest.raises(AiConfigurationError, match=match):
        PromptRegistry(tmp_path).get("classify")


def test_missing_placeholder_and_unknown_task() -> None:
    with pytest.raises(AiConfigurationError, match="marcador"):
        PromptRegistry().get("classify").render(title="T")
    with pytest.raises(AiConfigurationError, match="no tiene prompt"):
        PromptRegistry().get("agent")  # llega en M8
    with pytest.raises(AiConfigurationError, match="desconocida"):
        PromptRegistry().get("otra")  # type: ignore[arg-type]
