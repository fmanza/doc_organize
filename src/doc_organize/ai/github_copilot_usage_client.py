"""
Cliente de monitorización de consumo de GitHub Copilot Pro (premium requests)
vía la API REST oficial de GitHub Billing Usage (fase 2 IA).

No interactúa con el endpoint interno de completions de Copilot (fuera de
alcance, incumpliría los términos de uso individuales): es puramente lectura
de facturación, vía `GET /users/{username}/settings/billing/premium_request/usage`
(verificado contra la documentación oficial de GitHub — válido para un plan
Copilot Individual/Pro comprado por el propio usuario, sin organización).
"""

import calendar
import os

from datetime import date
from types import TracebackType
from typing import Any, Self

import httpx

from doc_organize.core.exceptions import UsageSourceAuthError, UsageSourceConnectionError, UsageSourceError
from doc_organize.core.models import GitHubCopilotUsageConfig, UsageLineItem, UsageSnapshot, UsageSourceName
from doc_organize.utils.logging import get_logger

_ENV_VAR_USERNAME = "DOC_ORGANIZE_GITHUB_USERNAME"
_ENV_VAR_PAT = "DOC_ORGANIZE_GITHUB_PAT"
_GITHUB_API_VERSION = "2022-11-28"
_GITHUB_API_BASE_URL = "https://api.github.com"

logger = get_logger(__name__)


def github_copilot_usage_config_from_env() -> GitHubCopilotUsageConfig:
    """Construye `GitHubCopilotUsageConfig` desde variables de entorno.

    Lee `DOC_ORGANIZE_GITHUB_USERNAME` y `DOC_ORGANIZE_GITHUB_PAT`. Mismo
    criterio que `litellm_usage_config_from_env()`: resolución explícita, no
    implícita dentro del cliente.

    Returns:
        Config lista para `GitHubCopilotUsageClient`.

    Raises:
        ValueError: Si alguna de las dos variables de entorno no está definida.

    Example:
        >>> config = github_copilot_usage_config_from_env()  # doctest: +SKIP
    """
    username = os.environ.get(_ENV_VAR_USERNAME)
    pat = os.environ.get(_ENV_VAR_PAT)
    if not username or not pat:
        raise ValueError(f"Definir {_ENV_VAR_USERNAME} y {_ENV_VAR_PAT} para usar github_copilot_usage_config_from_env().")
    return GitHubCopilotUsageConfig(username=username, personal_access_token=pat)


class GitHubCopilotUsageClient:
    """Consulta el consumo de "premium requests" de un plan Copilot Pro individual.

    El scope exacto de PAT que autoriza este endpoint no está documentado
    explícitamente por GitHub (AUDIT_PLAN, sesión 2026-09-07) — pendiente de
    confirmar empíricamente contra una cuenta real antes de dar el cliente por
    cerrado; recomendado usar un fine-grained PAT limitado a permiso de
    facturación de solo lectura si el endpoint lo admite.

    Attributes:
        config (GitHubCopilotUsageConfig): Usuario y PAT de acceso a Billing Usage.
        logger (logging.Logger): Logger estructurado de la instancia.

    Example:
        >>> from doc_organize.core.models import GitHubCopilotUsageConfig
        >>> config = GitHubCopilotUsageConfig(username="octocat", personal_access_token="github_pat_...")
        >>> async def demo() -> None:  # doctest: +SKIP
        ...     async with GitHubCopilotUsageClient(config) as client:
        ...         snapshot = await client.get_usage(year=2026, month=9)
    """

    def __init__(self, config: GitHubCopilotUsageConfig, *, transport: httpx.AsyncBaseTransport | None = None) -> None:
        """Inicializa el cliente.

        Args:
            config: Usuario y PAT de acceso a la API de Billing Usage de GitHub.
            transport: Transporte `httpx` alternativo (inyección para tests con
                `httpx.MockTransport`, sin llamadas de red reales). `None` usa
                el transporte HTTP real por defecto.
        """
        self.config = config
        self.logger = logger
        self._client = httpx.AsyncClient(base_url=_GITHUB_API_BASE_URL, timeout=config.timeout_s, transport=transport)

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        await self._client.aclose()

    async def get_usage(self, *, year: int | None = None, month: int | None = None) -> UsageSnapshot:
        """Consulta el consumo de premium requests de Copilot para `year`/`month`.

        Args:
            year: Año (4 dígitos) del periodo a consultar. Por defecto, el año actual.
            month: Mes (1-12) del periodo a consultar. Si se omite, GitHub
                devuelve el año completo.

        Returns:
            Snapshot con una línea por cada elemento de `usageItems[]` devuelto
            por GitHub.

        Raises:
            UsageSourceAuthError: PAT inválido o sin permiso (401/403).
            UsageSourceConnectionError: Error de red o timeout.
            UsageSourceError: Cualquier otro error de la API de GitHub.
        """
        resolved_year = year or date.today().year
        params: dict[str, Any] = {"year": resolved_year}
        if month is not None:
            params["month"] = month

        try:
            response = await self._client.get(
                f"/users/{self.config.username}/settings/billing/premium_request/usage",
                params=params,
                headers={
                    "Authorization": f"Bearer {self.config.personal_access_token}",
                    "Accept": "application/vnd.github+json",
                    "X-GitHub-Api-Version": _GITHUB_API_VERSION,
                },
            )
        except httpx.TimeoutException as exc:
            raise UsageSourceConnectionError("Timeout consultando la API de Billing Usage de GitHub") from exc
        except httpx.HTTPError as exc:
            raise UsageSourceConnectionError("Error de red consultando la API de Billing Usage de GitHub") from exc

        if response.status_code in (401, 403):
            raise UsageSourceAuthError(f"GitHub rechazó el PAT (HTTP {response.status_code})")
        if response.is_error:
            raise UsageSourceError(f"La API de Billing Usage de GitHub devolvió HTTP {response.status_code}")

        payload = response.json()
        items = [
            UsageLineItem(
                date=raw_item.get("date", ""),
                product=raw_item.get("product", "copilot"),
                sku=raw_item.get("sku"),
                quantity=float(raw_item.get("quantity", 0)),
                unit_type=raw_item.get("unitType", "premium_requests"),
                cost_usd=raw_item.get("netAmount"),
            )
            for raw_item in payload.get("usageItems", [])
        ]
        last_month = month or 12
        last_day = calendar.monthrange(resolved_year, last_month)[1]
        return UsageSnapshot(
            source=UsageSourceName.GITHUB_COPILOT,
            period_start=date(resolved_year, month or 1, 1).isoformat(),
            period_end=date(resolved_year, last_month, last_day).isoformat(),
            items=items,
            raw=payload,
        )


__all__ = ["GitHubCopilotUsageClient", "github_copilot_usage_config_from_env"]
