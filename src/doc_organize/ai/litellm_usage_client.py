"""
Cliente de monitorización de spend/uso de un LiteLLM Proxy externo (fase 2 IA).

Solo lectura de coste vía `GET /key/info` — no envía peticiones de inferencia
(`chat/completions`): enrutar llamadas de IA a través del proxy queda fuera de
alcance mientras no exista un consumidor real (PLAN/AUDIT_PLAN, sesión 2026-09-07).
"""

import os
import re

from datetime import UTC, date, datetime, timedelta

import httpx

from doc_organize.ai._http_client_base import AiHttpClientBase
from doc_organize.core.exceptions import UsageSourceAuthError, UsageSourceConnectionError, UsageSourceError
from doc_organize.core.models import LiteLLMUsageConfig, UsageLineItem, UsageSnapshot, UsageSourceName
from doc_organize.utils.logging import get_logger

_ENV_VAR_BASE_URL = "DOC_ORGANIZE_LITELLM_BASE_URL"
_ENV_VAR_VIRTUAL_KEY = "DOC_ORGANIZE_LITELLM_VIRTUAL_KEY"

logger = get_logger(__name__)

#: Producto de la línea de gasto (2.5.0; antes siempre `anthropic`): LiteLLM encamina a cualquier proveedor y `/key/info`
#: no dice a cuál.
LITELLM_PRODUCT = "litellm"
#: `budget_duration` de LiteLLM (`30s`, `30m`, `12h`/`12hr`, `1d`, `2w`); `mo` no tiene una duración fija.
_DURATION = re.compile(r"^\s*(\d+)\s*(s|m|h|hr|d|w)\s*$")
_DURATION_UNITS = {"s": "seconds", "m": "minutes", "h": "hours", "hr": "hours", "d": "days", "w": "weeks"}


def _parse_datetime(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _parse_duration(value: object) -> timedelta | None:
    match = _DURATION.match(value) if isinstance(value, str) else None
    if match is None:
        return None
    return timedelta(**{_DURATION_UNITS[match.group(2)]: int(match.group(1))})


def _period_start(info: dict, today: str) -> str:
    """Desde cuándo cuenta el gasto acumulado de `/key/info` (2.5.0): el último reinicio del presupuesto
    (`budget_reset_at - budget_duration`) o, si la clave no lo reinicia o no se entiende su duración, su creación
    (`created_at`); sin fechas, hoy (como hasta 2.4.x)."""
    reset_at, duration = _parse_datetime(info.get("budget_reset_at")), _parse_duration(info.get("budget_duration"))
    if reset_at is not None and duration is not None:
        return (reset_at - duration).astimezone(UTC).date().isoformat()
    if info.get("budget_duration") and duration is None:
        logger.warning(f"Duración de presupuesto de LiteLLM no reconocida ({info.get('budget_duration')!r}); periodo desde la creación de la clave")
    created_at = _parse_datetime(info.get("created_at"))
    return created_at.astimezone(UTC).date().isoformat() if created_at is not None else today


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
    interno, igual convención que `CacheManager`.

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
            rate_limit_retries=config.rate_limit_retries,
            max_retry_wait_s=config.max_retry_wait_s,
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
            product=LITELLM_PRODUCT,
            sku=info.get("key_alias"),
            quantity=spend,
            unit_type="usd",
            cost_usd=spend,
        )
        return UsageSnapshot(
            source=UsageSourceName.LITELLM,
            period_start=_period_start(info, today),
            period_end=today,
            items=[item],
            raw=payload,
        )


__all__ = ["LiteLLMUsageClient", "litellm_usage_config_from_env"]
