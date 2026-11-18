"""
Cliente único de IA (2.0.0, G1): todo lo que doc_organize envía a un modelo sale por aquí.

Sustituye a los cuatro clientes de 1.x. Un solo punto de salida permite aplicar a todas las tareas lo mismo:

- **Redacción** de credenciales de cada mensaje antes de enviarlo (D7), con el recuento de lo redactado en el resultado.
- **Salida estructurada**: `json_schema` estricto con el esquema de la tarea (p. ej. un `enum` con los slugs de cada eje);
  si el proxy no lo admite (HTTP 400), se cae **una vez** a `json_object` y se recuerda para ese modelo. La respuesta se
  **valida siempre** con el esquema (en Python), también tras la caída.
- **Reintentos** de transporte y ante 429/503 (`AiHttpClientBase`, D5) y `metadata.tags` para el proxy.
- **Modelo y clave por tarea** (`AiSettings`).
"""

import json

from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from types import TracebackType
from typing import Any, Literal, Self

import httpx

from doc_organize.ai._http_client_base import AiHttpClientBase
from doc_organize.ai.cache import AiResultCache, cache_key
from doc_organize.core.exceptions import AiAuthError, AiConnectionError, AiError, AiResponseError
from doc_organize.core.models import AiSettings, AiTask
from doc_organize.security.credentials import redact_credentials
from doc_organize.utils.logging import get_logger

logger = get_logger(__name__)

ResponseFormat = Literal["json_schema", "json_object"]
Message = dict[str, Any]


@dataclass(frozen=True)
class LlmUsage:
    """Tokens de una llamada, según el proxy (`None` si no los informa)."""

    prompt_tokens: int | None = None
    completion_tokens: int | None = None


@dataclass(frozen=True)
class LlmResult[T]:
    """Resultado validado de `LlmClient.complete_json`.

    Attributes:
        value (T): La respuesta ya validada (lo que devuelve `parse`).
        model (str): Modelo pedido para la tarea.
        response_format (str): `json_schema` o `json_object` (si el modelo no admite el esquema).
        usage (LlmUsage): Tokens de la llamada.
        redacted (dict[str, int]): Credenciales redactadas por regla en lo enviado (sin valores).
        cached (bool): Si salió de la caché de resultados (`AiResultCache`), sin llamar al modelo.
    """

    value: T
    model: str
    response_format: ResponseFormat
    usage: LlmUsage = field(default_factory=LlmUsage)
    redacted: dict[str, int] = field(default_factory=dict)
    cached: bool = False


class LlmClient:
    """Cliente único del LiteLLM Proxy para todas las tareas de IA (2.0.0).

    Example:
        >>> import asyncio, httpx
        >>> from doc_organize.core.models import AiSettings
        >>> def proxy(request):  # un proxy falso
        ...     return httpx.Response(200, json={"choices": [{"message": {"content": '{"ok": true}'}}]})
        >>> async def main():
        ...     settings = AiSettings(base_url="https://proxy.test", virtual_key="sk-x")
        ...     async with LlmClient(settings, transport=httpx.MockTransport(proxy)) as client:
        ...         result = await client.complete_json(
        ...             "classify", [{"role": "user", "content": "Responde JSON"}],
        ...             schema={"type": "object", "properties": {"ok": {"type": "boolean"}}, "required": ["ok"]},
        ...             parse=lambda data: data["ok"],
        ...         )
        ...     return result.value, result.response_format
        >>> asyncio.run(main())
        (True, 'json_schema')
    """

    def __init__(self, settings: AiSettings, *, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self.settings = settings
        self._http = AiHttpClientBase(
            base_url=settings.base_url,
            timeout_s=settings.timeout_s,
            logger=logger,
            auth_error_cls=AiAuthError,
            connection_error_cls=AiConnectionError,
            generic_error_cls=AiError,
            transport=transport,
            retries=settings.retries,
            backoff_s=settings.retry_backoff_s,
            rate_limit_retries=settings.rate_limit_retries,
            max_retry_wait_s=settings.max_retry_wait_s,
        )
        #: Modelos que han rechazado `json_schema` en esta sesión: se les pide `json_object` directamente.
        self._no_schema: set[str] = set()

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, exc_type: type[BaseException] | None, exc: BaseException | None, traceback: TracebackType | None) -> None:
        await self._http.__aexit__(exc_type, exc, traceback)

    def model_for(self, task: AiTask) -> str:
        """El modelo de `task` según la configuración."""
        return self.settings.model_for(task)

    async def complete_json[T](
        self,
        task: AiTask,
        messages: Sequence[Message],
        *,
        schema: dict[str, Any],
        parse: Callable[[Any], T],
        schema_name: str | None = None,
        on_redacted: Callable[[dict[str, int]], None] | None = None,
        cache: AiResultCache | None = None,
    ) -> LlmResult[T]:
        """Pide una respuesta JSON para `task` y la valida.

        Args:
            task: Tarea (elige modelo y clave).
            messages: Mensajes `system`/`user`; su texto se redacta antes de enviarlo si `redact_credentials`.
            schema: Esquema JSON de la respuesta: se envía como `json_schema` estricto.
            parse: Valida y convierte el JSON recibido (lanza `ValueError`/`TypeError`/`KeyError` si no vale).
            schema_name: Nombre del esquema para el proxy (por defecto, la tarea).
            on_redacted: Recibe lo redactado (recuento por regla) **antes** de enviar, aunque la llamada falle después:
                así quien llama puede anotarlo por documento (`Context.credential_findings`). No se llama si el
                resultado sale de la caché (no se envía nada).
            cache: Caché de resultados: si ya tiene esta petición exacta (`cache_key_for`), se devuelve sin llamar
                (`LlmResult.cached`), validada otra vez; si no, se guarda la respuesta tras validarla.

        Returns:
            `LlmResult` con el valor validado, el formato usado, los tokens y lo redactado.

        Raises:
            AiAuthError: Clave rechazada (401/403).
            AiConnectionError: Red o timeout, tras los reintentos.
            AiResponseError: La respuesta no es JSON o no pasa `parse`.
            AiError: Cualquier otro error del proxy.
        """
        model = self.model_for(task)
        sent, redacted = self._redact(messages)
        key = cache_key(task, model, sent, schema, redacted=self.settings.redact_credentials) if cache is not None else None
        if cache is not None and key is not None:
            cached = self._from_cache(task, model, cache, key, parse)
            if cached is not None:
                return cached
        if redacted and on_redacted is not None:
            on_redacted(redacted)
        payload, response_format = await self._chat_with_fallback(task, model, sent, schema, schema_name or task)
        data = self._content(task, payload)
        value = self._parse(task, data, parse)
        if cache is not None and key is not None:
            cache.put(key, data, response_format=response_format)
        return LlmResult(value=value, model=model, response_format=response_format, usage=_usage(payload), redacted=redacted)

    def _from_cache[T](self, task: AiTask, model: str, cache: AiResultCache, key: str, parse: Callable[[Any], T]) -> LlmResult[T] | None:
        """El resultado guardado para `key`, validado otra vez; `None` si no está o ya no es válido."""
        hit = cache.get(key)
        if hit is None:
            return None
        data, stored_format = hit
        response_format: ResponseFormat = "json_object" if stored_format == "json_object" else "json_schema"
        try:
            return LlmResult(value=self._parse(task, data, parse), model=model, response_format=response_format, cached=True)
        except AiResponseError:
            logger.warning(f"Una entrada de la caché de IA de '{task}' ya no es válida: se vuelve a preguntar")
            return None

    async def _chat_with_fallback(
        self, task: AiTask, model: str, sent: list[Message], schema: dict[str, Any], schema_name: str
    ) -> tuple[dict[str, Any], ResponseFormat]:
        """Pide `json_schema` estricto; si el proxy lo rechaza (400), cae **una vez** a `json_object` y lo recuerda."""
        response_format: ResponseFormat = "json_object" if model in self._no_schema else "json_schema"
        payload = await self._chat(task, model, sent, self._format(response_format, schema, schema_name))
        if payload is None:
            self._no_schema.add(model)
            logger.warning(f"El modelo '{model}' no admite la salida json_schema estricta: se usa json_object con validación")
            response_format = "json_object"
            payload = await self._chat(task, model, sent, self._format(response_format, schema, schema_name))
            if payload is None:
                raise AiError(f"El LiteLLM Proxy rechazó la petición de '{task}' (HTTP 400)")
        return payload, response_format

    def cache_key_for(self, task: AiTask, messages: Sequence[Message], schema: dict[str, Any]) -> str:
        """La clave de caché que tendría esta petición (con los mensajes ya redactados), sin enviar nada."""
        sent, _ = self._redact(messages)
        return cache_key(task, self.model_for(task), sent, schema, redacted=self.settings.redact_credentials)

    async def complete_with_tools(self, task: AiTask, messages: Sequence[Message], tools: Sequence[dict[str, Any]]) -> tuple[Message, LlmUsage]:
        """Una vuelta de conversación con herramientas (agentes, M8): el mensaje del asistente, con `tool_calls` si las
        pide, y los tokens. El texto de los mensajes se redacta igual que en `complete_json`.

        Raises:
            AiAuthError, AiConnectionError, AiError: Como `complete_json`; `AiResponseError` si no hay mensaje.
        """
        model = self.model_for(task)
        sent, _ = self._redact(messages)
        payload = await self._post(task, "/chat/completions", {"model": model, "messages": sent, "tools": list(tools), "temperature": 0})
        try:
            message = payload["choices"][0]["message"]
        except (KeyError, IndexError, TypeError) as exc:
            raise AiResponseError(f"La respuesta de '{task}' no trae mensaje") from exc
        return message, _usage(payload)

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        """Embeddings de `texts` (tarea `embed`), redactados antes de enviarlos y en el mismo orden.

        Raises:
            AiAuthError, AiConnectionError, AiError: Como `complete_json`; `AiResponseError` si faltan vectores.
        """
        if not texts:
            return []
        inputs = [redact_credentials(text).text if self.settings.redact_credentials else text for text in texts]
        payload = await self._post("embed", "/embeddings", {"model": self.model_for("embed"), "input": inputs})
        try:
            data = sorted(payload["data"], key=lambda item: item["index"])
            vectors = [[float(value) for value in item["embedding"]] for item in data]
        except (KeyError, TypeError, ValueError) as exc:
            raise AiResponseError("La respuesta de embeddings no tiene el formato esperado") from exc
        if len(vectors) != len(texts):
            raise AiResponseError(f"Se pidieron {len(texts)} embeddings y llegaron {len(vectors)}")
        return vectors

    # --- Internos ------------------------------------------------------------------------------------------------------

    def _redact(self, messages: Sequence[Message]) -> tuple[list[Message], dict[str, int]]:
        if not self.settings.redact_credentials:
            return [dict(message) for message in messages], {}
        counts: Counter[str] = Counter()
        sent = []
        for message in messages:
            content = message.get("content")
            if isinstance(content, str):
                result = redact_credentials(content)
                counts.update(finding.rule for finding in result.findings)
                message = {**message, "content": result.text}
            sent.append(dict(message))
        return sent, dict(sorted(counts.items()))

    @staticmethod
    def _format(response_format: ResponseFormat, schema: dict[str, Any], name: str) -> dict[str, Any]:
        if response_format == "json_object":
            return {"type": "json_object"}
        return {"type": "json_schema", "json_schema": {"name": name, "strict": True, "schema": schema}}

    async def _chat(self, task: AiTask, model: str, messages: list[Message], response_format: dict[str, Any]) -> dict[str, Any] | None:
        """`None` si el proxy respondió 400 (no admite el formato pedido)."""
        body = {"model": model, "messages": messages, "response_format": response_format, "temperature": 0}
        payload = await self._post(task, "/chat/completions", body, allow_bad_request=response_format["type"] == "json_schema")
        if payload is not None and not isinstance(payload, dict):
            raise AiResponseError(f"La respuesta de '{task}' no es un objeto JSON")
        return payload

    async def _post(self, task: AiTask, url: str, body: dict[str, Any], *, allow_bad_request: bool = False) -> Any:
        body = {**body, "metadata": {"tags": ["doc_organize", f"task:{task}", *self.settings.tags]}}
        response = await self._http._request(
            "POST",
            url,
            json=body,
            headers={"Authorization": f"Bearer {self.settings.key_for(task)}"},
            allow_statuses=frozenset({400}) if allow_bad_request else frozenset(),
            timeout_message=f"Timeout consultando el LiteLLM Proxy para '{task}'",
            connection_message=f"Error de red consultando el LiteLLM Proxy para '{task}'",
            auth_message=f"El LiteLLM Proxy rechazó la clave de '{task}' (HTTP {{status_code}})",
            error_message=f"El LiteLLM Proxy devolvió HTTP {{status_code}} para '{task}'",
        )
        if response.status_code == 400:
            return None
        try:
            return response.json()
        except ValueError as exc:
            raise AiResponseError(f"La respuesta de '{task}' no es JSON") from exc

    @staticmethod
    def _content(task: AiTask, payload: Any) -> Any:
        try:
            return json.loads(payload["choices"][0]["message"]["content"])
        except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
            raise AiResponseError(f"La respuesta de '{task}' no es el JSON esperado") from exc

    @staticmethod
    def _parse[T](task: AiTask, data: Any, parse: Callable[[Any], T]) -> T:
        try:
            return parse(data)
        except (ValueError, TypeError, KeyError, AttributeError) as exc:
            raise AiResponseError(f"La respuesta de '{task}' no cumple su esquema: {type(exc).__name__}") from exc


def _usage(payload: Any) -> LlmUsage:
    usage = payload.get("usage") if isinstance(payload, dict) else None
    if not isinstance(usage, dict):
        return LlmUsage()
    return LlmUsage(prompt_tokens=usage.get("prompt_tokens"), completion_tokens=usage.get("completion_tokens"))


__all__ = ["LlmClient", "LlmResult", "LlmUsage", "ResponseFormat"]
