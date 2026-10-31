"""Lectura de secretos guardados para las funciones ``*_config_from_store_or_env`` (L-3, G3).

``ai/`` no depende de ``auth/``: solo necesita algo con ``async get(clave) -> str | None``. La web integrada le pasa su
``InstanceSecretsStore``; otros consumidores (doc_organize_web) construyen los ``*Config`` ellos mismos y no usan estas
funciones, que se retirarán en 1.0.0 junto con ``auth/``.
"""

import warnings

from typing import Protocol


class SecretValueReader(Protocol):
    """Almacén de secretos de la instancia, visto desde ``ai/``."""

    async def get(self, key: str) -> str | None:
        """Valor descifrado de ``key``, o ``None`` si no hay ninguno guardado."""
        ...


def warn_store_config_deprecated(function_name: str) -> None:
    """Avisa de que ``function_name`` se retira en 1.0.0 (construir el ``*Config`` en el consumidor)."""
    warnings.warn(
        f"{function_name}() está obsoleta y se retirará en doc_organize 1.0.0: construye el *Config en el "
        "consumidor o usa la variante *_config_from_env()",
        DeprecationWarning,
        stacklevel=3,
    )
