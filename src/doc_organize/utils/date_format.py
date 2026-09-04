"""
Formato de fecha/hora localizado y parametrizable para mostrar al usuario.

El resto del proyecto genera timestamps con `datetime.now(timezone.utc).isoformat()`
(disperso en varios módulos: `scan_command.py`, `auth_store.py`, `project_registry.py`,
`scanned_folders_store.py`, `dedup/deduplication.py`, `web/routes/downloads.py`) y los
plantillas Jinja los mostraban tal cual, en ISO 8601 UTC crudo. Este módulo centraliza
la conversión a una zona horaria y un patrón de visualización configurables, con
formato español (`dd/mm/aaaa HH:MM:SS`) y zona horaria de España como valores por
defecto — mismo patrón de variable de entorno `DOC_ORGANIZE_*` que
`utils/logging.py`.
"""

import os

from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from doc_organize.utils.logging import get_logger

logger = get_logger(__name__)

_ENV_VAR_DATE_FORMAT = "DOC_ORGANIZE_DATE_FORMAT"
_ENV_VAR_TIMEZONE = "DOC_ORGANIZE_TIMEZONE"

_DEFAULT_DATE_FORMAT = "%d/%m/%Y %H:%M:%S"
_DEFAULT_TIMEZONE = "Europe/Madrid"


def format_datetime(value: str | datetime | None, *, pattern: str | None = None, tz_name: str | None = None) -> str:
    """Formatea un timestamp ISO 8601 (o `datetime`) en la zona horaria/patrón configurados.

    Args:
        value: Timestamp ISO 8601 con offset (p. ej. el resultado de
            `datetime.now(timezone.utc).isoformat()`) o un `datetime` ya construido.
            `None` o cadena vacía devuelve `""` (usado por las plantillas con
            campos de fecha opcionales).
        pattern: Patrón `strftime` a usar. Por defecto, la variable de entorno
            `DOC_ORGANIZE_DATE_FORMAT`, o `"%d/%m/%Y %H:%M:%S"` (formato español).
        tz_name: Zona horaria IANA a la que convertir antes de formatear. Por
            defecto, la variable de entorno `DOC_ORGANIZE_TIMEZONE`, o
            `"Europe/Madrid"`.

    Returns:
        La fecha/hora formateada en la zona horaria configurada, o `""` si `value`
        es `None`/vacío. Si `value` no es un timestamp ISO 8601 válido, o la zona
        horaria configurada (`tz_name`/`DOC_ORGANIZE_TIMEZONE`) no existe, se
        devuelve `value` tal cual (sin formatear) en vez de propagar la excepción:
        mismo criterio de tolerancia a datos corruptos que
        `web/scan_errors_data.py::load_error_history` — un valor inesperado no
        debe tumbar la página, solo perder el formateo.

    Example:
        >>> format_datetime("2026-09-03T10:00:00+00:00")
        '03/09/2026 12:00:00'
    """
    if not value:
        return ""
    try:
        parsed = datetime.fromisoformat(value) if isinstance(value, str) else value
        resolved_tz = ZoneInfo(tz_name or os.environ.get(_ENV_VAR_TIMEZONE) or _DEFAULT_TIMEZONE)
        resolved_pattern = pattern or os.environ.get(_ENV_VAR_DATE_FORMAT) or _DEFAULT_DATE_FORMAT
        return parsed.astimezone(resolved_tz).strftime(resolved_pattern)
    except (ValueError, TypeError, ZoneInfoNotFoundError) as exc:
        logger.warning(f"No se pudo formatear el timestamp '{value}': {exc}")
        return str(value)


def format_duration(seconds: float) -> str:
    """Formatea una duración en segundos como `"Xm Ys"` (o `"Ys"` si dura menos de un minuto).

    Args:
        seconds: Duración en segundos (p. ej. `ScanRunReport.duration_seconds`).
            Se trata como `0` si es negativa (AUDIT_CODE, sesión 2026-09-04):
            `duration_seconds` se calcula con reloj de pared
            (`datetime.now(UTC)`), no monótono — un ajuste del reloj del
            sistema hacia atrás (resync NTP) a mitad de una operación larga
            podría producir una duración negativa; mostrarla tal cual
            (`"-1m 55s"`) no tiene sentido para el usuario.

    Returns:
        Cadena legible: `"2m 5s"`, `"48s"`.

    Example:
        >>> format_duration(125.4)
        '2m 5s'
        >>> format_duration(-5.0)
        '0s'
    """
    total_seconds = max(0, round(seconds))
    minutes, secs = divmod(total_seconds, 60)
    return f"{minutes}m {secs}s" if minutes else f"{secs}s"


__all__ = ["format_datetime", "format_duration"]
