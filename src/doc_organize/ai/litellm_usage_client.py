"""
Cliente de monitorización de spend/uso de un LiteLLM Proxy externo (fase 2 IA).

Solo lectura de coste vía `GET /key/info` — no envía peticiones de inferencia
(`chat/completions`): enrutar llamadas de IA a través del proxy queda fuera de
alcance mientras no exista un consumidor real (PLAN/AUDIT_PLAN, sesión 2026-09-07).
"""

import os

from datetime import date

import httpx

from doc_organize.ai._http_client_base import AiHttpClientBase
from doc_organize.core.exceptions import UsageSourceAuthError, UsageSourceConnectionError, UsageSourceError
from doc_organize.core.models import LiteLLMUsageConfig, UsageLineItem, UsageSnapshot, UsageSourceName
from doc_organize.utils.logging import get_logger

_ENV_VAR_BASE_URL = "DOC_ORGANIZE_LITELLM_BASE_URL"
_ENV_VAR_VIRTUAL_KEY = "DOC_ORGANIZE_LITELLM_VIRTUAL_KEY"

logger = get_logger(__name__)


def litellm_usage_config_from_env() -> LiteLLMUsageConfig:
    """Construye `LiteLLMUsageConfig` desde variables de entorno.

    Lee `DOC_ORGANIZE_LITELLM_BASE_URL` y `DOC_ORGANIZE_LITELLM_VIRTUAL_KEY`.
    Resolución explícita (el llamador decide si usarla o construir la config a
    mano) — ningún cliente de este módulo lee el entorno por su cuenta.

    Returns:
        Config lista para `LiteLLMUsageClient`.

    Raises:
        ValueError: Si alguna de las dos variables de entorno no está definida.

    Example:
        >>> config = litellm_usage_config_from_env()  # doctest: +SKIP
    """
    base_url = os.environ.get(_ENV_VAR_BASE_URL)
    virtual_key = os.environ.get(_ENV_VAR_VIRTUAL_KEY)
    if not base_url or not virtual_key:
        raise ValueError(f"Definir {_ENV_VAR_BASE_URL} y {_ENV_VAR_VIRTUAL_KEY} para usar litellm_usage_config_from_env().")
    return LiteLLMUsageConfig(base_url=base_url, virtual_key=virtual_key)


class LiteLLMUsageClient(AiHttpClientBase):
    """Consulta el spend acumulado de una virtual key de LiteLLM Proxy (`GET /key/info`).

    Usar como context manager async para garantizar el cierre del cliente HTTP
    interno, igual convención que `CacheManager`/`AuthStore`.

    Attributes:
        config (LiteLLMUsageConfig): Configuración de acceso al proxy.
        logger (logging.Logger): Logger estructurado de la instancia.

    Example:
        >>> from doc_organize.core.models import LiteLLMUsageConfig
        >>> config = LiteLLMUsageConfig(base_url="https://litellm.example.com", virtual_key="sk-...")
        >>> async def demo() -> None:  # doctest: +SKIP
        ...     async with LiteLLMUsageClient(config) as client:
        ...         snapshot = await client.get_usage()
    """

    def __init__(self, config: LiteLLMUsageConfig, *, transport: httpx.AsyncBaseTransport | None = None) -> None:
        """Inicializa el cliente.

        Args:
            config: Configuración de acceso al LiteLLM Proxy.
            transport: Transporte `httpx` alternativo (inyección para tests con
                `httpx.MockTransport`, sin llamadas de red reales). `None` usa
                el transporte HTTP real por defecto.
        """
        self.config = config
        super().__init__(
            base_url=config.base_url,
            timeout_s=config.timeout_s,
            logger=logger,
            auth_error_cls=UsageSourceAuthError,
            connection_error_cls=UsageSourceConnectionError,
            generic_error_cls=UsageSourceError,
            transport=transport,
            retries=config.retries,
            backoff_s=config.retry_backoff_s,
        )

    async def get_usage(self, *, key: str | None = None) -> UsageSnapshot:
        """Consulta el spend acumulado de `key` (por defecto, la virtual key configurada).

        `Authorization` siempre usa `self.config.virtual_key` (documentado por
        LiteLLM como la credencial esperada en ese header). Sin `key` (o con la
        misma clave del Bearer) **no** se envía `?key=`: LiteLLM consulta entonces
        la clave del header (`info_key_fn`: `key = key or user_api_key_dict.api_key`),
        y la clave no aparece en la URL que `httpx` registra en INFO (L-3e).

        Con otra `key` (p. ej. si `virtual_key` es la master key del proxy) se
        envía `?key=<key>`, y esa URL **sí** queda en los logs de `httpx` y en los
        de acceso de cualquier proxy intermedio. LiteLLM acepta también el hash
        SHA-256 de la clave en ese parámetro: pásalo en vez de la clave en claro.

        Args:
            key: Virtual key (o su hash) cuyo spend consultar. Por defecto, la del Bearer.

        Returns:
            Snapshot con una única línea (LiteLLM `/key/info` no desglosa por
            fecha/modelo): el spend acumulado de `key`, en USD.

        Raises:
            UsageSourceAuthError: Credencial inválida o sin permiso (401/403).
            UsageSourceConnectionError: Error de red o timeout.
            UsageSourceError: Cualquier otro error de la API del proxy.
        """
        # L-3e: la clave propia nunca va en la query (httpx escribe cada URL en INFO).
        params = {"key": key} if key and key != self.config.virtual_key else None
        response = await self._request(
            "GET",
            "/key/info",
            params=params,
            headers={"Authorization": f"Bearer {self.config.virtual_key}"},
            timeout_message=f"Timeout consultando LiteLLM Proxy en {self.config.base_url}",
            connection_message=f"Error de red consultando LiteLLM Proxy en {self.config.base_url}",
            auth_message="LiteLLM Proxy rechazó la credencial (HTTP {status_code})",
            error_message="LiteLLM Proxy devolvió HTTP {status_code} en /key/info",
        )

        payload = response.json()
        info = payload.get("info", payload)
        spend = float(info.get("spend", 0.0))
        today = date.today().isoformat()
        item = UsageLineItem(
            date=today,
            product="anthropic",
            sku=info.get("key_alias"),
            quantity=spend,
            unit_type="usd",
            cost_usd=spend,
        )
        return UsageSnapshot(
            source=UsageSourceName.LITELLM,
            period_start=today,
            period_end=today,
            items=[item],
            raw=payload,
        )


__all__ = ["LiteLLMUsageClient", "litellm_usage_config_from_env"]
