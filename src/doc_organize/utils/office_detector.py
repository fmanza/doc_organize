"""
Deteccion de soporte de LibreOffice del entorno servidor (menu Escaneo).

Mismo patron que `av_detector.py`/`gpu_detector.py`: solo deteccion de entorno
software (¿esta `soffice`/`libreoffice` en el PATH?) -- no hay permisos por
usuario/rol, el mismo resultado aplica a cualquier sesion. Necesario porque
Docling delega en LibreOffice la conversion de Excel legado (`.xls`) a `.xlsx`
antes de poder parsearlo (ver `docling/backend/docx/drawingml/utils.py`,
`get_libreoffice_cmd()`); sin el binario en el PATH, esa conversion falla
siempre. A diferencia de audio/video, `.xls` no es opt-in (forma parte de
`SUPPORTED_EXTENSIONS` siempre activo) -- por eso `detect_office_status()` no
se usa como pre-check bloqueante de todo el escaneo, sino en
`converter.py::convert_document` para devolver un fallo inmediato y claro en
un `.xls` concreto sin pasar por Docling (bug real: sesion 2026-09-16, un
`.xls` sin LibreOffice instalado agotaba los reintentos automaticos con el
mensaje generico de Docling).
"""

import shutil

from functools import lru_cache

from doc_organize.core.models import OfficeStatus

_INSTALL_LIBREOFFICE_INSTRUCTIONS = (
    "Falta LibreOffice en el PATH del sistema (necesario para convertir .xls legado a .xlsx). "
    "Instalalo y asegurate de que 'soffice' es accesible desde una terminal "
    "(ver docs/guides/installation.md)."
)


@lru_cache(maxsize=1)
def detect_office_status() -> OfficeStatus:
    """Detecta si LibreOffice esta disponible en este proceso servidor.

    Sincrona (comprobacion barata: `shutil.which` solo consulta el PATH) pero
    se sigue el mismo patron que `detect_av_status()` -- cacheada en proceso
    (`lru_cache`).

    Returns:
        `OfficeStatus` con `libreoffice_installed` (si `soffice` o
        `libreoffice` estan en el PATH) e `instructions` cuando no lo estan.

    Example:
        >>> status = detect_office_status()
        >>> isinstance(status.libreoffice_installed, bool)  # depende del entorno real
        True
    """
    libreoffice_installed = shutil.which("libreoffice") is not None or shutil.which("soffice") is not None
    instructions = None if libreoffice_installed else _INSTALL_LIBREOFFICE_INSTRUCTIONS
    return OfficeStatus(libreoffice_installed=libreoffice_installed, instructions=instructions)


__all__ = ["detect_office_status"]
