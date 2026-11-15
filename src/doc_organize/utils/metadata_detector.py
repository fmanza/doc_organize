"""Metadatos de fichero que da el sistema: tipo MIME, fecha de creación, permisos y propietario (1.5.0).

Ninguna función lee el contenido del fichero ni hace E/S más allá de la del propietario: parten del `os.stat_result`
que el escáner ya tiene. Lo que el sistema no da de forma fiable se devuelve como `None` en lugar de aproximarlo.
"""

import mimetypes
import os
import sys

from functools import lru_cache
from pathlib import Path
from stat import S_IMODE

from doc_organize.utils.logging import get_logger

_logger = get_logger(__name__)


def guess_mime_type(path: Path | str) -> str | None:
    """Tipo MIME según la extensión (`mimetypes`), o `None` si la extensión no es conocida.

    Example:
        >>> guess_mime_type("informe.pdf")
        'application/pdf'
        >>> guess_mime_type("informe.desconocida") is None
        True
    """
    mime, _ = mimetypes.guess_type(Path(path).name, strict=False)
    return mime


def creation_time(st: os.stat_result) -> float | None:
    """Fecha de creación (`st_birthtime`) en Windows, macOS y BSD; `None` donde el sistema no la da (Linux).

    En Linux `st_ctime` es la fecha del último cambio de metadatos, no la de creación, así que no se usa.
    """
    birthtime: float | None = getattr(st, "st_birthtime", None)
    return birthtime


def file_permissions(st: os.stat_result) -> str | None:
    """Permisos POSIX en octal (p. ej. `'644'`, `'4755'`); `None` en Windows, donde no reflejan las ACL."""
    if sys.platform == "win32":
        return None
    return f"{S_IMODE(st.st_mode):03o}"


if sys.platform == "win32":
    import ctypes

    from ctypes import wintypes

    _SE_FILE_OBJECT = 1
    _OWNER_SECURITY_INFORMATION = 0x1
    _NAME_BUFFER = 256

    _advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _advapi32.GetNamedSecurityInfoW.argtypes = [
        wintypes.LPCWSTR,
        ctypes.c_int,
        wintypes.DWORD,
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.POINTER(ctypes.c_void_p),
    ]
    _advapi32.GetNamedSecurityInfoW.restype = wintypes.DWORD
    _advapi32.ConvertSidToStringSidW.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)]
    _advapi32.ConvertSidToStringSidW.restype = wintypes.BOOL
    _advapi32.LookupAccountSidW.argtypes = [
        wintypes.LPCWSTR,
        ctypes.c_void_p,
        wintypes.LPWSTR,
        ctypes.POINTER(wintypes.DWORD),
        wintypes.LPWSTR,
        ctypes.POINTER(wintypes.DWORD),
        ctypes.POINTER(wintypes.DWORD),
    ]
    _advapi32.LookupAccountSidW.restype = wintypes.BOOL
    _kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    _kernel32.LocalFree.restype = ctypes.c_void_p

    # Pocas cuentas distintas por escaneo y la resolución puede ir al controlador de dominio: se guarda por SID.
    _account_names: dict[str, str | None] = {}

    def _sid_string(sid: ctypes.c_void_p) -> str | None:
        buffer = ctypes.c_void_p()
        if not _advapi32.ConvertSidToStringSidW(sid, ctypes.byref(buffer)):
            return None
        try:
            return ctypes.wstring_at(buffer.value) if buffer.value else None
        finally:
            _kernel32.LocalFree(buffer)

    def _account_name(sid: ctypes.c_void_p) -> str | None:
        name = ctypes.create_unicode_buffer(_NAME_BUFFER)
        domain = ctypes.create_unicode_buffer(_NAME_BUFFER)
        name_len = wintypes.DWORD(_NAME_BUFFER)
        domain_len = wintypes.DWORD(_NAME_BUFFER)
        sid_type = wintypes.DWORD()
        if not _advapi32.LookupAccountSidW(None, sid, name, ctypes.byref(name_len), domain, ctypes.byref(domain_len), ctypes.byref(sid_type)):
            return None  # SID huérfano (cuenta borrada) o sin acceso al dominio
        return f"{domain.value}\\{name.value}" if domain.value else name.value

    def _windows_owner(path: str) -> str | None:
        owner = ctypes.c_void_p()
        descriptor = ctypes.c_void_p()
        error = _advapi32.GetNamedSecurityInfoW(
            path, _SE_FILE_OBJECT, _OWNER_SECURITY_INFORMATION, ctypes.byref(owner), None, None, None, ctypes.byref(descriptor)
        )
        if error:
            _logger.debug(f"No se pudo leer el propietario de '{path}' (error {error})")
            return None
        try:
            key = _sid_string(owner)
            if key is None:
                return None
            if key not in _account_names:
                _account_names[key] = _account_name(owner)
            return _account_names[key]
        finally:
            _kernel32.LocalFree(descriptor)

else:
    import pwd

    @lru_cache(maxsize=256)
    def _user_name(uid: int) -> str | None:
        try:
            return pwd.getpwuid(uid).pw_name
        except KeyError:  # UID sin entrada en la base de usuarios (p. ej. fichero de un montaje NFS)
            return None


def file_owner(path: Path | str, st: os.stat_result) -> str | None:
    """Cuenta propietaria del fichero: `usuario` en POSIX, `DOMINIO\\usuario` en Windows; `None` si no se resuelve.

    En Windows lee el descriptor de seguridad del fichero (una llamada al sistema por fichero); en POSIX solo traduce
    `st.st_uid`. Las cuentas resueltas se guardan en memoria durante el proceso.
    """
    if sys.platform == "win32":
        return _windows_owner(str(path))
    else:  # Con `else`, mypy no analiza esta rama en Windows, donde `_user_name` no existe.
        return _user_name(st.st_uid)


__all__ = ["creation_time", "file_owner", "file_permissions", "guess_mime_type"]
