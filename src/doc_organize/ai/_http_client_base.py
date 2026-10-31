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

import logging

from types import TracebackType
from typing import Any, Self

import httpx


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
        """
        self.logger = logger
        self._auth_error_cls = auth_error_cls
        self._connection_error_cls = connection_error_cls
        self._generic_error_cls = generic_error_cls
        self._client = httpx.AsyncClient(base_url=base_url, timeout=timeout_s, transport=transport)

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

        Returns:
            La respuesta HTTP, garantizada libre de error de transporte, 401/403 e `is_error`.
        """
        try:
            response = await self._client.request(method, url, **kwargs)
        except httpx.TimeoutException as exc:
            raise self._connection_error_cls(timeout_message) from exc
        except httpx.HTTPError as exc:
            raise self._connection_error_cls(connection_message) from exc

        if response.status_code in (401, 403):
            raise self._auth_error_cls(auth_message.format(status_code=response.status_code))
        if response.is_error:
            raise self._generic_error_cls(error_message.format(status_code=response.status_code))

        return response
