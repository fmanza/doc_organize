"""Tests de InstanceSecretsStore (almacén de configuración de IA del panel /admin/configuracion-ia)."""

import pytest

from doc_organize.auth.instance_secrets_store import InstanceSecretsStore
from doc_organize.core.exceptions import SecretsCipherError, SecretsEncryptionNotConfiguredError

_VALID_KEY = "zJx3nB2v9mQY9y3ZbG8cC1eR6tK0pL4sD7fH5wA2iU8="


@pytest.mark.asyncio
async def test_get_returns_none_for_unknown_key(tmp_path) -> None:
    async with InstanceSecretsStore(tmp_path / "auth.db") as store:
        assert await store.get("no-existe") is None


@pytest.mark.asyncio
async def test_set_then_get_roundtrips_a_plain_field(tmp_path) -> None:
    async with InstanceSecretsStore(tmp_path / "auth.db") as store:
        await store.set("doc_organize_litellm_classification_model", "claude-haiku", is_secret=False)

        assert await store.get("doc_organize_litellm_classification_model") == "claude-haiku"


@pytest.mark.asyncio
async def test_set_then_get_roundtrips_a_secret_field(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("DOC_ORGANIZE_SECRETS_KEY", _VALID_KEY)
    async with InstanceSecretsStore(tmp_path / "auth.db") as store:
        await store.set("doc_organize_litellm_classification_virtual_key", "sk-abc123", is_secret=True)

        assert await store.get("doc_organize_litellm_classification_virtual_key") == "sk-abc123"


@pytest.mark.asyncio
async def test_set_secret_without_encryption_key_raises_and_stores_nothing(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("DOC_ORGANIZE_SECRETS_KEY", raising=False)
    async with InstanceSecretsStore(tmp_path / "auth.db") as store:
        with pytest.raises(SecretsEncryptionNotConfiguredError):
            await store.set("doc_organize_litellm_classification_virtual_key", "sk-abc123", is_secret=True)

        assert await store.get("doc_organize_litellm_classification_virtual_key") is None


@pytest.mark.asyncio
async def test_set_overwrites_an_existing_value(tmp_path) -> None:
    async with InstanceSecretsStore(tmp_path / "auth.db") as store:
        await store.set("doc_organize_litellm_classification_model", "v1", is_secret=False)
        await store.set("doc_organize_litellm_classification_model", "v2", is_secret=False)

        assert await store.get("doc_organize_litellm_classification_model") == "v2"


@pytest.mark.asyncio
async def test_delete_removes_a_stored_value(tmp_path) -> None:
    async with InstanceSecretsStore(tmp_path / "auth.db") as store:
        await store.set("doc_organize_litellm_classification_model", "claude-haiku", is_secret=False)

        await store.delete("doc_organize_litellm_classification_model")

        assert await store.get("doc_organize_litellm_classification_model") is None


@pytest.mark.asyncio
async def test_delete_of_unknown_key_is_a_noop(tmp_path) -> None:
    async with InstanceSecretsStore(tmp_path / "auth.db") as store:
        await store.delete("no-existe")  # no debe lanzar


@pytest.mark.asyncio
async def test_get_all_reports_status_without_ever_returning_a_secret_value(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("DOC_ORGANIZE_SECRETS_KEY", _VALID_KEY)
    async with InstanceSecretsStore(tmp_path / "auth.db") as store:
        await store.set("doc_organize_litellm_classification_virtual_key", "sk-abc123", is_secret=True)
        await store.set("doc_organize_litellm_classification_model", "claude-haiku", is_secret=False)

        records = await store.get_all(
            [
                ("doc_organize_litellm_classification_virtual_key", True),
                ("doc_organize_litellm_classification_model", False),
                ("doc_organize_litellm_classification_base_url", False),
            ]
        )

    by_key = {record.key: record for record in records}
    assert by_key["doc_organize_litellm_classification_virtual_key"].has_value is True
    assert by_key["doc_organize_litellm_classification_virtual_key"].plain_value is None
    assert by_key["doc_organize_litellm_classification_model"].plain_value == "claude-haiku"
    assert by_key["doc_organize_litellm_classification_base_url"].has_value is False


@pytest.mark.asyncio
async def test_values_persist_across_separate_store_instances_on_the_same_file(tmp_path) -> None:
    db_path = tmp_path / "auth.db"
    async with InstanceSecretsStore(db_path) as store:
        await store.set("doc_organize_litellm_classification_model", "claude-haiku", is_secret=False)

    async with InstanceSecretsStore(db_path) as store:
        assert await store.get("doc_organize_litellm_classification_model") == "claude-haiku"


@pytest.mark.asyncio
async def test_get_raises_domain_error_for_a_corrupted_secret_row(tmp_path) -> None:
    """Una fila `is_secret=1` sin `value_ciphertext` (corrupción -- nunca la produce
    `set()`) debe fallar con una excepción de dominio clara, no un `TypeError` críptico
    de `cryptography` (AUDIT_CODE, sesión 2026-09-11: antes se protegía con `assert`,
    que desaparece bajo `python -O`)."""
    db_path = tmp_path / "auth.db"
    async with InstanceSecretsStore(db_path) as store:
        await store._connection.execute(
            "INSERT INTO instance_secrets (key, value_ciphertext, value_plain, is_secret, updated_at, updated_by_user_id) "
            "VALUES ('corrupta', NULL, NULL, 1, '2026-01-01T00:00:00', NULL)"
        )
        await store._connection.commit()

        with pytest.raises(SecretsCipherError, match="no tiene ningún valor cifrado"):
            await store.get("corrupta")
