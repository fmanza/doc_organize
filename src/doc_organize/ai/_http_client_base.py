"""
Base compartida de los clientes HTTP de `ai/` (LiteLLM Proxy / GitHub Billing).

Los clientes de este paquete (`DomainClassificationClient`, `TaxonomyClassificationClient`,
`TaxonomyManifestDraftClient`, `LiteLLMUsageClient`, `GitHubCopilotUsageClient`) repetían de forma
idéntica la construcción de `httpx.AsyncClient`, el ciclo de vida de context manager async, y el
mapeo try/except de timeout/error de red/401-403/HTTP de error a sus excepciones de dominio
respectivas (`/tech-debt`, sesión 2026-09-17). Esta clase centraliza esa parte mecánica; cada
cliente conserva su propia config tipada, construcción de payload y parseo de respuesta -- eso no
es mecánico y no pertenece aquí. Módulo privado (`_` inicial): no se re-exporta desde `ai/__init__.py`.
"""

from __future__ import annotations

import asyncio
import logging
import time

from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from types import TracebackType
from typing import Any, Self

import httpx

#: Respuestas que piden esperar y volver a intentarlo (límite de peticiones o servicio saturado), D5 (2.0.0).
RATE_LIMIT_STATUSES = frozenset({429, 503})


class AiHttpClientBase:
    """Ciclo de vida de context manager async y manejo de errores HTTP comunes a `ai/`.

    Una subclase típica llama a `super().__init__(...)` con la config resuelta y sus 3 clases de
    excepción, guarda `self.config` ella misma (el tipo de `config` es propio de cada cliente), y
    usa `self._request(...)` en vez de `self._client.<verbo>(...)` directamente para heredar el
    mapeo de excepciones.
    """

    def __init__(
        self,
        *,
        base_url: str,
        timeout_s: float,
        logger: logging.Logger,
        auth_error_cls: type[Exception],
        connection_error_cls: type[Exception],
        generic_error_cls: type[Exception],
        transport: httpx.AsyncBaseTransport | None = None,
        retries: int = 0,
        backoff_s: float = 0.5,
        rate_limit_retries: int = 0,
        max_retry_wait_s: float = 60.0,
    ) -> None:
        """Inicializa el cliente HTTP subyacente y el mapeo de excepciones de la subclase.

        Args:
            base_url: URL base del servicio (LiteLLM Proxy o API de GitHub).
            timeout_s: Timeout de la petición, en segundos.
            logger: Logger de la instancia (cada cliente conserva el suyo, por módulo).
            auth_error_cls: Excepción a lanzar ante HTTP 401/403.
            connection_error_cls: Excepción a lanzar ante timeout o error de red/transporte.
            generic_error_cls: Excepción a lanzar ante cualquier otro HTTP de error.
            transport: Transporte `httpx` alternativo (inyección para tests con
                `httpx.MockTransport`, sin llamadas de red reales). `None` usa el transporte HTTP
                real por defecto.
            retries: Reintentos ante timeout o error de red/transporte (`httpx.TransportError`). `0` (por defecto) no
                reintenta (L-3b).
            backoff_s: Espera base entre reintentos, en segundos; se duplica en cada intento (`backoff_s * 2**n`).
            rate_limit_retries: Reintentos ante una respuesta 429 o 503 (D5, 2.0.0). Se espera lo que diga
                `Retry-After` (segundos o fecha HTTP) o, si no lo trae, `backoff_s * 2**n`; nunca más de
                `max_retry_wait_s` por espera. La espera es **compartida**: mientras dura, ninguna otra petición de este
                cliente sale (con varias llamadas a la vez, `ContextBuilder(ai_concurrency=)`, no insisten todas a la
                vez). Ninguna otra respuesta HTTP se reintenta.
            max_retry_wait_s: Tope de cada espera ante 429/503, en segundos.

        Raises:
            ValueError: Si `retries`, `backoff_s`, `rate_limit_retries` o `max_retry_wait_s` son negativos.
        """
        if retries < 0 or backoff_s < 0 or rate_limit_retries < 0 or max_retry_wait_s < 0:
            raise ValueError("retries, backoff_s, rate_limit_retries y max_retry_wait_s no pueden ser negativos")
        self.logger = logger
        self._retries = retries
        self._backoff_s = backoff_s
        self._rate_limit_retries = rate_limit_retries
        self._max_retry_wait_s = max_retry_wait_s
        #: Hasta cuándo (`time.monotonic()`) no sale ninguna petición: la espera de un 429/503 compartida.
        self._cooldown_until = 0.0
        self._auth_error_cls = auth_error_cls
        self._connection_error_cls = connection_error_cls
        self._generic_error_cls = generic_error_cls
        self._client = httpx.AsyncClient(base_url=base_url, timeout=timeout_s, transport=transport)

    @staticmethod
    def _now() -> float:
        """Reloj de las esperas ante 429/503 (sustituible en los tests)."""
        return time.monotonic()

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        await self._client.aclose()

    async def _request(
        self,
        method: str,
        url: str,
        *,
        timeout_message: str,
        connection_message: str,
        auth_message: str,
        error_message: str,
        **kwargs: Any,
    ) -> httpx.Response:
        """Envía la petición y traduce fallos de transporte/HTTP a las excepciones de la subclase.

        Args:
            method: Verbo HTTP (`"GET"`, `"POST"`, ...).
            url: Ruta relativa a `base_url` (p. ej. `"/chat/completions"`).
            timeout_message: Mensaje de `connection_error_cls` si `httpx.TimeoutException`.
            connection_message: Mensaje de `connection_error_cls` ante cualquier otro `httpx.HTTPError`.
            auth_message: Plantilla del mensaje de `auth_error_cls` si la respuesta es HTTP 401/403.
                Puede usar el placeholder `{status_code}`.
            error_message: Plantilla del mensaje de `generic_error_cls` ante cualquier otro HTTP de
                error. Puede usar el placeholder `{status_code}`.
            **kwargs: Argumentos adicionales de `httpx.AsyncClient.request` (`json`, `params`, `headers`...).

        Un fallo de transporte (timeout incluido) se reintenta hasta `retries` veces con espera creciente; una
        respuesta 429/503, hasta `rate_limit_retries` veces con la espera que pida el servidor (D5); ninguna otra
        respuesta HTTP se reintenta.

        Returns:
            La respuesta HTTP, garantizada libre de error de transporte, 401/403 e `is_error`.
        """
        rate_limited = 0
        while True:
            response = await self._send(method, url, timeout_message, connection_message, **kwargs)
            if response.status_code not in RATE_LIMIT_STATUSES or rate_limited >= self._rate_limit_retries:
                break
            delay = self._rate_limit_delay(response, rate_limited)
            rate_limited += 1
            self._cooldown_until = max(self._cooldown_until, self._now() + delay)
            # Sin la URL: puede llevar parámetros sensibles; el código basta para diagnosticar.
            self.logger.warning(f"HTTP {response.status_code} en {method}; reintento {rate_limited}/{self._rate_limit_retries} en {delay:g} s")

        if response.status_code in (401, 403):
            raise self._auth_error_cls(auth_message.format(status_code=response.status_code))
        if response.is_error:
            raise self._generic_error_cls(error_message.format(status_code=response.status_code))

        return response

    async def _send(self, method: str, url: str, timeout_message: str, connection_message: str, **kwargs: Any) -> httpx.Response:
        """Una petición, tras la espera compartida pendiente, con los reintentos de transporte (L-3b)."""
        attempt = 0
        while True:
            pending = self._cooldown_until - self._now()
            if pending > 0:
                await asyncio.sleep(pending)
            try:
                return await self._client.request(method, url, **kwargs)
            except httpx.TransportError as exc:
                if attempt < self._retries:
                    delay = self._backoff_s * (2**attempt)
                    attempt += 1
                    # Sin la URL: puede llevar parámetros sensibles; `type(exc)` basta para diagnosticar.
                    self.logger.warning(f"{type(exc).__name__} en {method} {url}; reintento {attempt}/{self._retries} en {delay:g} s")
                    await asyncio.sleep(delay)
                    continue
                message = timeout_message if isinstance(exc, httpx.TimeoutException) else connection_message
                raise self._connection_error_cls(message) from exc
            except httpx.HTTPError as exc:
                raise self._connection_error_cls(connection_message) from exc

    def _rate_limit_delay(self, response: httpx.Response, attempt: int) -> float:
        """Segundos que pide `Retry-After` (número o fecha HTTP), o `backoff_s * 2**attempt`; con tope."""
        header = response.headers.get("Retry-After", "").strip()
        delay = self._backoff_s * (2**attempt)
        if header:
            try:
                delay = float(header)
            except ValueError:
                try:
                    delay = float((parsedate_to_datetime(header) - datetime.now(UTC)).total_seconds())
                except (TypeError, ValueError, IndexError):
                    pass
        return float(min(max(delay, 0.0), self._max_retry_wait_s))
