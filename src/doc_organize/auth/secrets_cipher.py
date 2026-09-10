"""
Cifrado en reposo de credenciales de IA guardadas desde la UI (panel de configuración IA).

Mismo criterio que ya documenta `docs/guides/litellm_proxy_setup.md` para
`LITELLM_SALT_KEY` del proxy externo: una clave maestra fija por instalación,
leída del entorno, nunca derivada de la contraseña de ningún usuario ni
guardada junto a los datos que cifra.
"""

import os

from types import ModuleType
from typing import TYPE_CHECKING, cast

from doc_organize.core.exceptions import SecretsCipherError, SecretsEncryptionNotConfiguredError

if TYPE_CHECKING:
    from cryptography.fernet import Fernet

_ENV_VAR_SECRETS_KEY = "DOC_ORGANIZE_SECRETS_KEY"


def is_secrets_encryption_configured() -> bool:
    """`True` si `DOC_ORGANIZE_SECRETS_KEY` está definida (sin validar su formato).

    Usado por el panel de configuración IA para mostrar "cifrado no disponible"
    sin necesidad de intentar cifrar/descifrar nada.
    """
    return bool(os.environ.get(_ENV_VAR_SECRETS_KEY))


def _cryptography_fernet_module() -> ModuleType:
    # Import perezoso (no a nivel de módulo): `cryptography` solo está declarada en
    # el extra `web` (pyproject.toml), no en `ai`/base -- `doc_organize.auth` ya lo
    # importa `doc_organize.ai.*` (config por almacén, ver `*_config_from_store_or_env()`)
    # y el propio CLI (`main.py::tenant create`/`user create`) para construir un
    # `AuthStore` sin necesitar `[web]` instalado. Un import a nivel de módulo aquí
    # rompería esos dos flujos con un `ImportError` que no tiene nada que ver con lo
    # que están haciendo.
    try:
        import cryptography.fernet

        return cryptography.fernet
    except ImportError as exc:
        raise SecretsCipherError("El cifrado de credenciales de IA requiere el extra 'web' instalado (`pip install doc_organize[web]`).") from exc


def _fernet() -> "Fernet":
    fernet_cls = _cryptography_fernet_module().Fernet

    raw_key = os.environ.get(_ENV_VAR_SECRETS_KEY)
    if not raw_key:
        raise SecretsEncryptionNotConfiguredError(
            f'Definir {_ENV_VAR_SECRETS_KEY} (32 bytes en base64, p.ej. `python -c "import secrets,base64; '
            f'print(base64.urlsafe_b64encode(secrets.token_bytes(32)).decode())"`) para poder guardar '
            "credenciales de IA cifradas desde la interfaz."
        )
    try:
        return cast("Fernet", fernet_cls(raw_key.encode("ascii")))
    except ValueError as exc:  # incluye binascii.Error (subclase de ValueError): base64 mal formado
        raise SecretsCipherError(f"{_ENV_VAR_SECRETS_KEY} no es una clave Fernet válida (32 bytes en base64 urlsafe).") from exc


def encrypt_secret(plaintext: str) -> bytes:
    """Cifra `plaintext` con la clave de `DOC_ORGANIZE_SECRETS_KEY` (AES-128-CBC + HMAC, vía Fernet).

    Raises:
        SecretsEncryptionNotConfiguredError: `DOC_ORGANIZE_SECRETS_KEY` no está definida.
        SecretsCipherError: La clave definida no es una clave Fernet válida.
    """
    return _fernet().encrypt(plaintext.encode("utf-8"))


def decrypt_secret(ciphertext: bytes) -> str:
    """Descifra `ciphertext` (producido por `encrypt_secret` con la misma clave).

    Raises:
        SecretsEncryptionNotConfiguredError: `DOC_ORGANIZE_SECRETS_KEY` no está definida.
        SecretsCipherError: La clave no es válida, o `ciphertext` no fue cifrado con
            ella (clave rotada sin volver a guardar el secreto, o dato corrupto).
    """
    invalid_token_cls = _cryptography_fernet_module().InvalidToken

    try:
        return _fernet().decrypt(ciphertext).decode("utf-8")
    except invalid_token_cls as exc:
        raise SecretsCipherError(f"No se pudo descifrar el secreto -- {_ENV_VAR_SECRETS_KEY} no coincide con la clave usada para guardarlo.") from exc


__all__ = ["decrypt_secret", "encrypt_secret", "is_secrets_encryption_configured"]
