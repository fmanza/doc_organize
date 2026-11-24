"""Las credenciales de la API pública no aparecen en `repr()` (2.4.2).

`repr()` acaba en logs, trazas y mensajes de error: un campo con una clave debe declararse con `repr=False` (Pydantic)
o `field(repr=False)` (dataclass), como `AiSettings` y `TaskSettings`. `model_dump()` sí la incluye: el consumidor puede
necesitar guardarla.
"""

import dataclasses
import re
import warnings

import pytest

from pydantic import BaseModel

import doc_organize

from doc_organize import AiEndpoint, LiteLLMUsageConfig

SECRET_FIELD = re.compile(r"(virtual_key|api_key|access_token|password|secret)$")
SECRET = "sk-no-debe-salir-en-el-repr"


def _public_classes() -> list[type]:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        objects = [getattr(doc_organize, name) for name in doc_organize.__all__]
    return [obj for obj in objects if isinstance(obj, type)]


def _secret_fields_shown_in_repr(cls: type) -> list[str]:
    if issubclass(cls, BaseModel):
        return [name for name, info in cls.model_fields.items() if SECRET_FIELD.search(name) and info.repr]
    if dataclasses.is_dataclass(cls):
        return [field.name for field in dataclasses.fields(cls) if SECRET_FIELD.search(field.name) and field.repr]
    return []


def test_no_public_class_shows_a_credential_in_its_repr() -> None:
    shown = {cls.__name__: fields for cls in _public_classes() if (fields := _secret_fields_shown_in_repr(cls))}

    assert shown == {}


def test_the_rule_finds_the_known_credential_fields() -> None:
    """Que el test anterior no pase por no encontrar nada: estas clases tienen claves."""
    names = {cls.__name__ for cls in _public_classes() if any(SECRET_FIELD.search(name) for name in getattr(cls, "model_fields", {}))}
    names |= {
        cls.__name__
        for cls in _public_classes()
        if dataclasses.is_dataclass(cls) and any(SECRET_FIELD.search(f.name) for f in dataclasses.fields(cls))
    }

    assert {"AiSettings", "TaskSettings", "LiteLLMUsageConfig", "AiEndpoint"} <= names


@pytest.mark.parametrize(
    "value",
    [
        LiteLLMUsageConfig(base_url="http://proxy:4000", virtual_key=SECRET),
        AiEndpoint(name="classify", base_url="http://proxy:4000", virtual_key=SECRET, model="m"),
    ],
    ids=["LiteLLMUsageConfig", "AiEndpoint"],
)
def test_the_key_is_not_in_the_repr(value: object) -> None:
    assert SECRET not in repr(value)
    assert SECRET not in str(value)


def test_github_copilot_token_is_not_in_the_repr() -> None:
    from doc_organize.core.models import GitHubCopilotUsageConfig

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        config = GitHubCopilotUsageConfig(username="u", personal_access_token=SECRET)

    assert SECRET not in repr(config)


def test_model_dump_still_carries_the_key() -> None:
    """Igual que `AiSettings`: ocultarla del `repr` no la quita de lo que el consumidor guarda."""
    assert LiteLLMUsageConfig(base_url="http://proxy:4000", virtual_key=SECRET).model_dump()["virtual_key"] == SECRET
