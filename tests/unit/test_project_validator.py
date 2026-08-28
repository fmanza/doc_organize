"""Tests unitarios de ProjectValidator (REQ-008)."""

import unicodedata

import pytest

from doc_organize.validators import ProjectValidator


@pytest.fixture
def validator() -> ProjectValidator:
    return ProjectValidator()


@pytest.mark.parametrize(
    "name",
    [
        "Mi Proyecto",
        "proyecto-2026",
        "proyecto_final",
        "Documentacion Tecnica",
        "a",
        "a" * 100,
    ],
)
def test_accepts_valid_names(validator: ProjectValidator, name: str) -> None:
    result = validator.validate_name(name)
    assert result.is_valid is True
    assert result.normalized_name == name


def test_rejects_empty_name(validator: ProjectValidator) -> None:
    result = validator.validate_name("")
    assert result.is_valid is False
    assert result.normalized_name is None


def test_rejects_whitespace_only_name(validator: ProjectValidator) -> None:
    result = validator.validate_name("   ")
    assert result.is_valid is False


def test_rejects_leading_or_trailing_space(validator: ProjectValidator) -> None:
    assert validator.validate_name(" proyecto").is_valid is False
    assert validator.validate_name("proyecto ").is_valid is False


def test_rejects_trailing_dot(validator: ProjectValidator) -> None:
    result = validator.validate_name("proyecto.")
    assert result.is_valid is False


def test_rejects_dots_only(validator: ProjectValidator) -> None:
    assert validator.validate_name(".").is_valid is False
    assert validator.validate_name("..").is_valid is False


def test_rejects_too_long_name(validator: ProjectValidator) -> None:
    result = validator.validate_name("a" * 101)
    assert result.is_valid is False


@pytest.mark.parametrize("char", list('<>:"/\\|?*'))
def test_rejects_forbidden_characters(validator: ProjectValidator, char: str) -> None:
    result = validator.validate_name(f"proyecto{char}malo")
    assert result.is_valid is False


def test_rejects_control_characters(validator: ProjectValidator) -> None:
    result = validator.validate_name("proyecto\x01malo")
    assert result.is_valid is False


@pytest.mark.parametrize(
    "name",
    ["CON", "con", "PRN", "AUX", "NUL", "COM1", "com9", "LPT1", "con.txt", "COM1.bak"],
)
def test_rejects_windows_reserved_names(validator: ProjectValidator, name: str) -> None:
    result = validator.validate_name(name)
    assert result.is_valid is False


def test_does_not_reject_reserved_name_as_substring(validator: ProjectValidator) -> None:
    # "CONtratos" no es el nombre reservado "CON", solo empieza igual.
    result = validator.validate_name("CONtratos")
    assert result.is_valid is True


def test_unicode_nfd_input_normalizes_to_nfc(validator: ProjectValidator) -> None:
    composed = unicodedata.normalize("NFC", "café")
    decomposed = unicodedata.normalize("NFD", composed)
    assert decomposed != composed  # confirma que el test realmente ejercita la descomposicion

    result = validator.validate_name(decomposed)

    assert result.is_valid is True
    assert result.normalized_name == composed
    assert len(result.normalized_name) == 4
