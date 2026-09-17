"""
Helpers puros de hashing de contraseñas y timestamps, compartidos por los stores de `auth/`.

Sin acceso a base de datos -- extraídos de `auth_store.py` al separar `AuthStore` en
`TenantStore`/`RoleStore`/`UserStore`/`SessionStore` (`/tech-debt`, sesión 2026-09-17) para
que ninguno de los 4 tenga que importar de otro solo por estas funciones. Módulo privado
(`_` inicial): no se re-exporta desde `auth/__init__.py`.
"""

import hashlib
import secrets

from datetime import UTC, datetime

from doc_organize.core.constants import SCRYPT_DKLEN, SCRYPT_MAXMEM, SCRYPT_N, SCRYPT_P, SCRYPT_R


def hash_password(password: str, salt: str | None = None) -> tuple[str, str]:
    """Hashea `password` con `hashlib.scrypt`. Genera un salt nuevo si no se pasa uno.

    Síncrona y con coste de CPU/memoria deliberado (parámetros OWASP) -- se ejecuta
    siempre vía `asyncio.to_thread` desde los métodos async de los stores de `auth/`
    para no bloquear el event loop (mismo motivo por el que `hash_file()` usa `aiofiles`).
    """
    salt = salt or secrets.token_hex(16)
    digest = hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt.encode("utf-8"),
        n=SCRYPT_N,
        r=SCRYPT_R,
        p=SCRYPT_P,
        maxmem=SCRYPT_MAXMEM,
        dklen=SCRYPT_DKLEN,
    )
    return salt, digest.hex()


def verify_password(password: str, salt: str, expected_hash: str) -> bool:
    """Compara `password` contra `expected_hash` en tiempo constante."""
    _, computed_hash = hash_password(password, salt=salt)
    return secrets.compare_digest(computed_hash, expected_hash)


def now_iso() -> str:
    return datetime.now(UTC).isoformat()
