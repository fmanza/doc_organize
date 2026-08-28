"""Tests unitarios de FolderValidator (REQ-001)."""

import pytest

from doc_organize.core.exceptions import InvalidPathError
from doc_organize.validators import FolderValidator


@pytest.fixture
def validator() -> FolderValidator:
    return FolderValidator()


def test_empty_input_is_invalid(validator: FolderValidator) -> None:
    result = validator.validate_folder_set([])
    assert result.is_valid is False
    assert result.clean_paths == []


def test_single_valid_folder(validator: FolderValidator, tmp_path) -> None:
    result = validator.validate_folder_set([str(tmp_path)])
    assert result.is_valid is True
    assert result.warnings == []
    assert result.clean_paths == [str(tmp_path.resolve())]


def test_detects_subfolder_redundancy(validator: FolderValidator, tmp_path) -> None:
    child = tmp_path / "docs"
    child.mkdir()

    result = validator.validate_folder_set([str(tmp_path), str(child)])

    assert result.is_valid is True
    assert result.clean_paths == [str(tmp_path.resolve())]
    assert len(result.warnings) == 1
    assert "docs" in result.warnings[0]


def test_redundancy_independent_of_input_order(validator: FolderValidator, tmp_path) -> None:
    child = tmp_path / "docs"
    child.mkdir()

    result = validator.validate_folder_set([str(child), str(tmp_path)])

    assert result.clean_paths == [str(tmp_path.resolve())]
    assert len(result.warnings) == 1


def test_nonexistent_folder_raises(validator: FolderValidator, tmp_path) -> None:
    missing = tmp_path / "does-not-exist"
    with pytest.raises(InvalidPathError):
        validator.validate_folder_set([str(missing)])


def test_file_instead_of_folder_raises(validator: FolderValidator, tmp_path) -> None:
    file_path = tmp_path / "not-a-folder.txt"
    file_path.write_text("x")
    with pytest.raises(InvalidPathError):
        validator.validate_folder_set([str(file_path)])


def test_unrelated_folders_are_all_kept(validator: FolderValidator, tmp_path) -> None:
    docs = tmp_path / "docs"
    papers = tmp_path / "papers"
    docs.mkdir()
    papers.mkdir()

    result = validator.validate_folder_set([str(docs), str(papers)])

    assert result.warnings == []
    assert set(result.clean_paths) == {str(docs.resolve()), str(papers.resolve())}
