"""
Detección de soporte de GPU del entorno servidor (menú Escaneo).

Solo detección de entorno software (¿está `torch` instalado? ¿reporta una GPU
CUDA activa?) — no hay ningún permiso de GPU por usuario/rol; el mismo
resultado aplica a cualquier sesión, porque depende solo de qué hay disponible
en el proceso servidor (AUDIT_PLAN, revisión de la funcionalidad de escaneo).
"""

from functools import lru_cache
from importlib.util import find_spec

from doc_organize.core.models import GpuStatus

_INSTALL_INSTRUCTIONS = "El soporte de GPU no está instalado en este entorno. Instálalo con: pip install .[ocr-gpu]"
_ACTIVATE_INSTRUCTIONS = (
    "El soporte de GPU está instalado, pero no se detecta ninguna GPU CUDA activa. "
    "Comprueba que los drivers NVIDIA están instalados y actualizados, y que la build "
    "de PyTorch instalada corresponde a una versión con soporte CUDA. Si acabas de "
    "instalar/activar el soporte de GPU con el servidor web ya arrancado, reinicia el "
    "proceso: este resultado se cachea una vez por proceso servidor y no se vuelve a "
    "comprobar hasta el próximo reinicio (ver docs/guides/troubleshooting.md)."
)


@lru_cache(maxsize=1)
def detect_gpu_status() -> GpuStatus:
    """Detecta si hay soporte de GPU disponible en este proceso servidor.

    Síncrona y potencialmente lenta la primera vez (importar `torch` e
    inicializar CUDA tiene coste no trivial): los llamadores desde un handler
    async deben invocarla vía `asyncio.to_thread`. El resultado se cachea en
    proceso (`lru_cache`) porque no cambia mientras el servidor sigue vivo.

    Returns:
        `GpuStatus` con `gpu_support_installed` (si `torch` es importable),
        `gpu_active` (si además hay una GPU CUDA disponible ahora mismo) e
        `instructions` (no `None` solo cuando `gpu_active` es `False`).

    Example:
        >>> status = detect_gpu_status()
        >>> isinstance(status.gpu_active, bool)  # depende del entorno real (torch/CUDA instalados o no)
        True
    """
    if find_spec("torch") is None:
        return GpuStatus(gpu_support_installed=False, gpu_active=False, instructions=_INSTALL_INSTRUCTIONS)

    import torch

    gpu_active = bool(torch.cuda.is_available())
    instructions = None if gpu_active else _ACTIVATE_INSTRUCTIONS
    return GpuStatus(gpu_support_installed=True, gpu_active=gpu_active, instructions=instructions)


__all__ = ["detect_gpu_status"]
