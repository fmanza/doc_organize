"""
Protocolo estructural común a los clientes de monitorización de uso/coste de
IA de `doc_organize.ai` (fase 2 — sin funcionalidad de inferencia, solo
lectura de uso/coste).
"""

from typing import Protocol, runtime_checkable

from doc_organize.core.models import UsageSnapshot


@runtime_checkable
class UsageSource(Protocol):
    """Cualquier cliente capaz de reportar un `UsageSnapshot` sin argumentos obligatorios.

    Cumplido estructuralmente por `LiteLLMUsageClient` y
    `GitHubCopilotUsageClient` sin herencia compartida (ISP): cada cliente
    solo expone los parámetros adicionales opcionales que le aplican a su
    propia fuente, pero ambos son invocables como `await fuente.get_usage()`
    sin argumentos — así un futuro agregador puede tratar `list[UsageSource]`
    de forma uniforme sin conocer la fuente concreta.
    """

    async def get_usage(self) -> UsageSnapshot: ...


__all__ = ["UsageSource"]
