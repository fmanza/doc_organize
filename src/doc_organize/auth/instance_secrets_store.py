"""
Almacén de configuración de IA editable desde la UI (panel de configuración IA),
persistido en el mismo `auth.db` que `AuthStore` pero en su propia tabla.
"""

import asyncio

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Self

import aiosqlite

from doc_organize.auth.secrets_cipher import decrypt_secret, encrypt_secret
from doc_organize.core.exceptions import SecretsCipherError
from doc_organize.utils.logging import get_logger

logger = get_logger(__name__)

_DEFAULT_AUTH_DB_PATH = Path.home() / ".doc_organize" / "auth.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS instance_secrets (
    key TEXT PRIMARY KEY,
    value_ciphertext BLOB,
    value_plain TEXT,
    is_secret INTEGER NOT NULL,
    updated_at TEXT NOT NULL,
    updated_by_user_id TEXT
);
"""


@dataclass(frozen=True)
class InstanceSecretRecord:
    """Un campo de configuración de IA guardado desde la UI (`InstanceSecretsStore.get_all`).

    A diferencia de `get()` (valor ya descifrado, para construir un `LiteLLM*Config`),
    esta forma es la que consume el panel de configuración IA: nunca lleva el valor
    real de un campo secreto, solo si hay uno guardado (`has_value`), para no
    reexponer una credencial ya cifrada en la respuesta de un `GET`.
    """

    key: str
    is_secret: bool
    has_value: bool
    plain_value: str | None
    updated_at: str


class InstanceSecretsStore:
    """Persiste, cifrados en reposo, los valores de configuración de IA que un admin
    guarda desde el panel `/admin/configuracion-ia` — complementa, sin sustituir, la
    resolución por `DOC_ORGANIZE_*` del entorno que ya usan `litellm_classification_config_from_env()`
    y equivalentes (`doc_organize.ai`).

    De instancia, no por tenant (mismo criterio que `TaxonomyTemplateRegistry`: una
    única config de IA compartida por toda la instalación). Cada fila se identifica
    por `key` = nombre de la variable `DOC_ORGANIZE_*` equivalente, en minúsculas
    (p.ej. `"doc_organize_litellm_classification_virtual_key"`) — trazabilidad directa
    con `.env.example` y las funciones `*_config_from_env()`, sin vocabulario nuevo.

    Los campos marcados `is_secret=True` (virtual keys, PAT) se cifran con
    `secrets_cipher.encrypt_secret()` antes de escribirse (`DOC_ORGANIZE_SECRETS_KEY`);
    los demás (`base_url`, alias de modelo) se guardan en texto plano — no son
    credenciales, cifrarlos no aportaría nada.

    Attributes:
        db_path (Path): Ruta al archivo SQLite (compartido con `AuthStore`).

    Example:
        >>> import asyncio, tempfile
        >>> from pathlib import Path
        >>> async def main():
        ...     db_path = Path(tempfile.mkdtemp()) / "auth.db"
        ...     async with InstanceSecretsStore(db_path) as store:
        ...         await store.set("doc_organize_litellm_classification_model", "claude-classifier", is_secret=False)
        ...         return await store.get("doc_organize_litellm_classification_model")
        >>> asyncio.run(main())
        'claude-classifier'
    """

    def __init__(self, db_path: str | Path = _DEFAULT_AUTH_DB_PATH) -> None:
        self.db_path = Path(db_path)
        self._conn: aiosqlite.Connection | None = None

    async def __aenter__(self) -> Self:
        await asyncio.to_thread(self.db_path.parent.mkdir, parents=True, exist_ok=True)
        self._conn = await aiosqlite.connect(self.db_path)
        await self._conn.execute("PRAGMA journal_mode=WAL")
        await self._conn.executescript(_SCHEMA)
        await self._conn.commit()
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        if self._conn is not None:
            await self._conn.close()
            self._conn = None

    @property
    def _connection(self) -> aiosqlite.Connection:
        if self._conn is None:
            raise RuntimeError("InstanceSecretsStore debe usarse como context manager async ('async with').")
        return self._conn

    async def get(self, key: str) -> str | None:
        """Valor ya descifrado (si `is_secret`) de `key`, o `None` si no hay fila guardada.

        Raises:
            SecretsEncryptionNotConfiguredError: La fila es secreta pero
                `DOC_ORGANIZE_SECRETS_KEY` no está definida.
            SecretsCipherError: La fila es secreta pero la clave no coincide con la
                usada para cifrarla.
        """
        cursor = await self._connection.execute("SELECT value_ciphertext, value_plain, is_secret FROM instance_secrets WHERE key = ?", (key,))
        row = await cursor.fetchone()
        if row is None:
            return None
        value_ciphertext: bytes | None = row[0]
        value_plain: str | None = row[1]
        is_secret: int = row[2]
        if not is_secret:
            return value_plain
        if value_ciphertext is None:
            # Invariante de `set()`: `is_secret=1` siempre guarda `value_ciphertext` -- si esto
            # salta, la fila se corrompió por otra vía (edición manual de `auth.db`, migración
            # incompleta...). Excepción de dominio explícita, no `assert` (AUDIT_CODE, sesión
            # 2026-09-11: un `assert` desaparece bajo `python -O`, dejando pasar `None` a
            # `decrypt_secret()` para fallar después con un `TypeError` críptico sin relación
            # con la causa real).
            raise SecretsCipherError(f"La fila '{key}' de instance_secrets está marcada como secreta pero no tiene ningún valor cifrado guardado.")
        return decrypt_secret(value_ciphertext)

    async def get_all(self, keys: list[tuple[str, bool]]) -> list[InstanceSecretRecord]:
        """Estado de cada `(key, is_secret)` de `keys`, en el mismo orden -- para poblar el
        panel de configuración IA sin reexponer ningún valor secreto ya guardado.

        A diferencia de `get()`, nunca descifra: un campo secreto solo reporta
        `has_value` (booleano), nunca el texto plano -- evitar que un `GET` del panel
        de configuración devuelva la credencial ya guardada es una propiedad de
        seguridad, no un detalle de implementación (ver `AUDIT_PLAN` de esta sesión).
        """
        records = []
        for key, is_secret in keys:
            cursor = await self._connection.execute(
                "SELECT value_ciphertext, value_plain, is_secret, updated_at FROM instance_secrets WHERE key = ?", (key,)
            )
            row = await cursor.fetchone()
            if row is None:
                records.append(InstanceSecretRecord(key=key, is_secret=is_secret, has_value=False, plain_value=None, updated_at=""))
                continue
            value_ciphertext, value_plain, stored_is_secret, updated_at = row
            records.append(
                InstanceSecretRecord(
                    key=key,
                    is_secret=bool(stored_is_secret),
                    has_value=(value_ciphertext if stored_is_secret else value_plain) is not None,
                    plain_value=None if stored_is_secret else value_plain,
                    updated_at=updated_at,
                )
            )
        return records

    async def set(self, key: str, value: str, *, is_secret: bool, updated_by_user_id: str | None = None) -> None:
        """Guarda (o sobrescribe) `value` bajo `key`, cifrándolo primero si `is_secret`.

        Raises:
            SecretsEncryptionNotConfiguredError: `is_secret=True` pero `DOC_ORGANIZE_SECRETS_KEY`
                no está definida -- nunca se guarda un secreto en texto plano como
                degradación silenciosa.
        """
        ciphertext = encrypt_secret(value) if is_secret else None
        plain = None if is_secret else value
        await self._connection.execute(
            """
            INSERT INTO instance_secrets (key, value_ciphertext, value_plain, is_secret, updated_at, updated_by_user_id)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET
                value_ciphertext = excluded.value_ciphertext,
                value_plain = excluded.value_plain,
                is_secret = excluded.is_secret,
                updated_at = excluded.updated_at,
                updated_by_user_id = excluded.updated_by_user_id
            """,
            (key, ciphertext, plain, int(is_secret), datetime.now(UTC).isoformat(), updated_by_user_id),
        )
        await self._connection.commit()

    async def delete(self, key: str) -> None:
        """Borra el override guardado para `key` -- vuelve a depender de `DOC_ORGANIZE_*` del entorno."""
        await self._connection.execute("DELETE FROM instance_secrets WHERE key = ?", (key,))
        await self._connection.commit()


__all__ = ["InstanceSecretRecord", "InstanceSecretsStore"]
