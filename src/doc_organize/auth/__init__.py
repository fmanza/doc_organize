"""Autenticacion multi-usuario, multi-tenant y roles (revision 8 §2.7.2, revision 9)."""

from doc_organize.auth.auth_store import AuthenticatedSession, AuthStore
from doc_organize.auth.instance_secrets_store import InstanceSecretRecord, InstanceSecretsStore
from doc_organize.auth.secrets_cipher import decrypt_secret, encrypt_secret, is_secrets_encryption_configured

__all__ = [
    "AuthStore",
    "AuthenticatedSession",
    "InstanceSecretRecord",
    "InstanceSecretsStore",
    "decrypt_secret",
    "encrypt_secret",
    "is_secrets_encryption_configured",
]
