"""Tests de secrets_cipher (cifrado en reposo de credenciales de IA guardadas desde la UI)."""

import pytest

from doc_organize.auth.secrets_cipher import decrypt_secret, encrypt_secret, is_secrets_encryption_configured
from doc_organize.core.exceptions import SecretsCipherError, SecretsEncryptionNotConfiguredError

_VALID_KEY = "zJx3nB2v9mQY9y3ZbG8cC1eR6tK0pL4sD7fH5wA2iU8="


def test_is_secrets_encryption_configured_reflects_env_var(monkeypatch) -> None:
    monkeypatch.delenv("DOC_ORGANIZE_SECRETS_KEY", raising=False)
    assert is_secrets_encryption_configured() is False

    monkeypatch.setenv("DOC_ORGANIZE_SECRETS_KEY", _VALID_KEY)
    assert is_secrets_encryption_configured() is True


def test_encrypt_then_decrypt_roundtrips(monkeypatch) -> None:
    monkeypatch.setenv("DOC_ORGANIZE_SECRETS_KEY", _VALID_KEY)

    ciphertext = encrypt_secret("sk-super-secret")

    assert decrypt_secret(ciphertext) == "sk-super-secret"


def test_encrypt_raises_when_key_not_configured(monkeypatch) -> None:
    monkeypatch.delenv("DOC_ORGANIZE_SECRETS_KEY", raising=False)

    with pytest.raises(SecretsEncryptionNotConfiguredError):
        encrypt_secret("sk-super-secret")


def test_encrypt_raises_when_key_is_not_valid_base64(monkeypatch) -> None:
    monkeypatch.setenv("DOC_ORGANIZE_SECRETS_KEY", "not-a-valid-fernet-key")

    with pytest.raises(SecretsCipherError, match="no es una clave Fernet válida"):
        encrypt_secret("sk-super-secret")


def test_decrypt_raises_when_key_does_not_match(monkeypatch) -> None:
    monkeypatch.setenv("DOC_ORGANIZE_SECRETS_KEY", _VALID_KEY)
    ciphertext = encrypt_secret("sk-super-secret")

    monkeypatch.setenv("DOC_ORGANIZE_SECRETS_KEY", "Y3JhY2tlZC1rZXktdGVzdC1vbmx5LTEyMzQ1Njc4OTA=")

    with pytest.raises(SecretsCipherError, match="no coincide con la clave"):
        decrypt_secret(ciphertext)
