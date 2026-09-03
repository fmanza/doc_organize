"""
Detección de soporte de audio/vídeo del entorno servidor (menú Escaneo).

Mismo patrón que `gpu_detector.py`: solo detección de entorno software (¿está
Whisper instalado? ¿está `ffmpeg` en el PATH?) — no hay permisos por usuario/rol,
el mismo resultado aplica a cualquier sesión. A diferencia de la GPU, cuya
ausencia solo degrada a CPU, sin estas dos dependencias la conversión de
audio/vídeo (`AV_SUPPORTED_EXTENSIONS`) falla siempre — por eso
`detect_av_status()` se usa también como pre-check bloqueante en
`main.py::_run_scan` para `include_audio_video=True`, no solo como aviso
informativo en la web. `.txt` no depende de esto: forma parte de
`SUPPORTED_EXTENSIONS` (siempre activo), no de este flag.
"""

import shutil
import subprocess

from functools import lru_cache
from importlib.util import find_spec

from doc_organize.core.models import AvStatus

_INSTALL_ASR_INSTRUCTIONS = "Falta el backend de transcripción (Whisper). Instálalo con: pip install .[av]"
_INSTALL_FFMPEG_INSTRUCTIONS = "Falta el binario 'ffmpeg' en el PATH del sistema (necesario para convertir vídeo). Instálalo y asegúrate de que 'ffmpeg' es accesible desde una terminal."
_INSTALL_BOTH_INSTRUCTIONS = (
    "Falta el backend de transcripción (Whisper) y el binario 'ffmpeg' en el PATH del sistema. "
    "Instala el backend con: pip install .[av] — y luego instala 'ffmpeg' y asegúrate de que es accesible desde una terminal."
)


def _is_ffmpeg_available() -> bool:
    """Verifica si ffmpeg está disponible en el sistema.

    Intenta múltiples métodos:
    1. shutil.which() — rápido, usa el PATH del proceso
    2. Ejecución directa — fallback si el PATH no está completamente inicializado

    Returns:
        True si ffmpeg es ejecutable, False en caso contrario.
    """
    # Primer intento: shutil.which (rápido)
    if shutil.which("ffmpeg") is not None:
        return True

    # Fallback: intentar ejecutar ffmpeg -version
    # Esto es más robusto cuando el PATH del proceso no está completamente inicializado
    try:
        subprocess.run(
            ["ffmpeg", "-version"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=2,
            check=False,  # No lanzar excepción si el código de salida es distinto de 0
        )
        return True
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return False


@lru_cache(maxsize=1)
def detect_av_status() -> AvStatus:
    """Detecta si hay soporte de audio/vídeo disponible en este proceso servidor.

    Síncrona (comprobaciones baratas: `find_spec` no importa el módulo, y
    `shutil.which` solo consulta el PATH) pero se sigue el mismo patrón que
    `detect_gpu_status()` — cacheada en proceso (`lru_cache`) y pensada para
    invocarse vía `asyncio.to_thread` desde un handler async por consistencia,
    aunque su coste real sea mínimo.

    Returns:
        `AvStatus` con `asr_installed` (si el paquete `whisper` del extra `av`
        es importable), `ffmpeg_installed` (si el binario está en el PATH),
        `ready` (ambos a la vez) e `instructions` especificando exactamente
        qué falta cuando `ready` es `False`.

    Example:
        >>> status = detect_av_status()
        >>> status.ready
        False
    """
    asr_installed = find_spec("whisper") is not None
    ffmpeg_installed = _is_ffmpeg_available()
    ready = asr_installed and ffmpeg_installed

    if ready:
        instructions = None
    elif not asr_installed and not ffmpeg_installed:
        instructions = _INSTALL_BOTH_INSTRUCTIONS
    elif not asr_installed:
        instructions = _INSTALL_ASR_INSTRUCTIONS
    else:
        instructions = _INSTALL_FFMPEG_INSTRUCTIONS

    return AvStatus(asr_installed=asr_installed, ffmpeg_installed=ffmpeg_installed, ready=ready, instructions=instructions)


__all__ = ["detect_av_status"]
