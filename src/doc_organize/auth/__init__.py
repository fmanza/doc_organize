"""Autenticacion multi-usuario, multi-tenant y roles (revision 8 §2.7.2, revision 9).

Obsoleta desde 0.14.0 (L-10): congelada (solo hotfix) y se retira en 1.0.0. Usuarios, tenants, roles, sesiones y
secretos de instancia viven en doc_organize_web (https://github.com/fmanza/doc_organize_web).
"""

from doc_organize._deprecations import warn_deprecated_import

warn_deprecated_import("doc_organize.auth")

from doc_organize.auth.auth_store import (  # noqa: E402 - el aviso va antes de cargar el paquete
    AuthenticatedSession,
    AuthStore,
    is_factory_admin_account,
)
from doc_organize.auth.instance_secrets_store import InstanceSecretRecord, InstanceSecretsStore  # noqa: E402 - el aviso va antes de cargar el paquete
from doc_organize.auth.secrets_cipher import (  # noqa: E402 - el aviso va antes de cargar el paquete
    decrypt_secret,
    encrypt_secret,
    is_secrets_encryption_configured,
)

__all__ = [
    "AuthStore",
    "AuthenticatedSession",
    "InstanceSecretRecord",
    "InstanceSecretsStore",
    "decrypt_secret",
    "encrypt_secret",
    "is_factory_admin_account",
    "is_secrets_encryption_configured",
]
