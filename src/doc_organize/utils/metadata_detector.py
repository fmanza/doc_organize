"""Detección de metadatos de archivos: tipo MIME, permisos, propietario (FASE 1)."""

import mimetypes
import os
import platform
from pathlib import Path
from stat import S_IMODE
from typing import Any

from doc_organize.utils.logging import get_logger

_logger = get_logger(__name__)


def detect_mime_type(path: Path | str) -> str | None:
    """Detecta tipo MIME: intenta mimetypes, luego python-magic si está disponible.

    Args:
        path: Ruta al archivo

    Returns:
        Tipo MIME (p.ej. 'application/pdf') o None si no se puede detectar
    """
    path = Path(path)

    # Intenta mimetypes (rápido, basado en extensión)
    mime, _ = mimetypes.guess_type(str(path))
    if mime:
        return mime

    # Intenta python-magic si está disponible (lento pero preciso)
    try:
        import magic

        return magic.from_file(str(path), mime=True)
    except ImportError:
        pass
    except Exception as e:
        _logger.debug(f"Error detectando MIME con magic para '{path}': {e}")

    # Fallback: detectar como binario
    return "application/octet-stream"


def get_creation_time(stat_result: os.stat_result, path: Path | str | None = None) -> float | None:
    """Obtiene fecha creación: st_birthtime (macOS) o st_ctime (otros).

    Args:
        stat_result: Resultado de Path.stat()
        path: Ruta (solo para logging)

    Returns:
        Timestamp Unix de creación, o None si no se puede obtener
    """
    try:
        # macOS tiene st_birthtime
        if hasattr(stat_result, "st_birthtime"):
            return stat_result.st_birthtime

        # Windows/Linux: usar el mínimo entre ctime y mtime
        # ctime es "change time" (metadatos), mtime es "modification time" (contenido)
        return min(stat_result.st_ctime, stat_result.st_mtime)
    except Exception as e:
        if path:
            _logger.debug(f"Error obteniendo fecha creación de '{path}': {e}")
        return None


def get_file_permissions(stat_result: os.stat_result, path: Path | str | None = None) -> str | None:
    """Obtiene permisos del archivo en notación octal (Unix) o representación Windows.

    Args:
        stat_result: Resultado de Path.stat()
        path: Ruta (solo para logging)

    Returns:
        Permisos en formato octal (3 dígitos), p.ej. '644', o None
    """
    try:
        mode = S_IMODE(stat_result.st_mode)
        return oct(mode)[-3:]  # Últimos 3 dígitos octal
    except Exception as e:
        if path:
            _logger.debug(f"Error leyendo permisos de '{path}': {e}")
        return None


def get_owner_name(stat_result: os.stat_result, path: Path | str | None = None) -> str | None:
    """Obtiene propietario del archivo (Unix/Windows).

    Args:
        stat_result: Resultado de Path.stat()
        path: Ruta (solo para logging)

    Returns:
        Nombre del propietario, o None si no se puede obtener
    """
    system = platform.system()

    if system in ("Linux", "Darwin"):  # Unix/macOS
        try:
            import pwd

            return pwd.getpwuid(stat_result.st_uid).pw_name
        except (ImportError, KeyError) as e:
            if path:
                _logger.debug(f"Error leyendo propietario Unix de '{path}': {e}")
            return None

    if system == "Windows":
        try:
            import win32security

            # Obtener SID del propietario
            descriptor = win32security.GetFileSecurity(
                str(path), win32security.OWNER_SECURITY_INFORMATION
            )
            owner_sid = descriptor.GetSecurityDescriptorOwner()
            # Convertir SID a nombre
            name, domain, _ = win32security.LookupAccountSid(None, owner_sid)
            return f"{domain}\\{name}" if domain else name
        except Exception as e:
            if path:
                _logger.debug(f"Error leyendo propietario Windows de '{path}': {e}")
            return None

    return None


def extract_basic_metadata(path: Path | str) -> dict[str, Any]:
    """Extrae metadatos básicos de un archivo (FASE 1).

    Args:
        path: Ruta al archivo

    Returns:
        Dict con claves: mime_type, created_time, file_permissions, owner_name
        Valores pueden ser None si no se pueden obtener
    """
    path = Path(path)

    try:
        stat = path.stat()

        return {
            "mime_type": detect_mime_type(path),
            "created_time": get_creation_time(stat, path),
            "file_permissions": get_file_permissions(stat, path),
            "owner_name": get_owner_name(stat, path),
        }
    except Exception as e:
        _logger.warning(f"Error extrayendo metadatos básicos de '{path}': {e}")
        return {
            "mime_type": None,
            "created_time": None,
            "file_permissions": None,
            "owner_name": None,
        }


__all__ = [
    "detect_mime_type",
    "get_creation_time",
    "get_file_permissions",
    "get_owner_name",
    "extract_basic_metadata",
]
