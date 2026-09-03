"""Tests unitarios de `utils/path_utils.py` (punto central anti path-traversal).

`safe_path_join`/`is_subpath` ya se ejercitaban indirectamente vía sus llamadores
(`ProjectRegistry.create_project`, `DeduplicationManager._move_to_duplicates`,
`FolderValidator`), pero ningún test cubría directamente el caso de traversal
(`".."`) que es la razón de ser de `safe_path_join` (maturity-assessment,
sesión 2026-09-03)."""

import pytest

from doc_organize.core.exceptions import InvalidPathError
from doc_organize.utils.path_utils import is_subpath, paths_within_roots, safe_path_join


def test_safe_path_join_joins_parts_under_base(tmp_path) -> None:
    result = safe_path_join(tmp_path, "docs", "a.pdf")
    assert result == (tmp_path / "docs" / "a.pdf").resolve()


def test_safe_path_join_rejects_parent_traversal(tmp_path) -> None:
    with pytest.raises(InvalidPathError):
        safe_path_join(tmp_path, "..", "etc", "passwd")


def test_safe_path_join_rejects_traversal_hidden_in_a_single_part(tmp_path) -> None:
    """Un único componente con "../../" en vez de partes separadas debe rechazarse
    igual — `Path.joinpath` no distingue entre ambas formas."""
    with pytest.raises(InvalidPathError):
        safe_path_join(tmp_path, "../../etc/passwd")


def test_is_subpath_true_for_nested_child(tmp_path) -> None:
    child = tmp_path / "docs" / "a.pdf"
    assert is_subpath(child, tmp_path) is True


def test_is_subpath_true_when_equal_to_parent(tmp_path) -> None:
    assert is_subpath(tmp_path, tmp_path) is True


def test_is_subpath_false_for_unrelated_path(tmp_path) -> None:
    sibling = tmp_path.parent / "otra-carpeta-no-relacionada"
    assert is_subpath(sibling, tmp_path) is False


def test_is_subpath_false_when_child_is_the_parent_of_parent(tmp_path) -> None:
    """Caso inverso al de traversal: el "padre" declarado está en realidad
    anidado dentro del "hijo" — no debe considerarse subpath."""
    assert is_subpath(tmp_path, tmp_path / "docs") is False


def test_paths_within_roots_none_means_unrestricted() -> None:
    assert paths_within_roots(["/cualquier/ruta"], None) is True


def test_paths_within_roots_empty_paths_is_always_true(tmp_path) -> None:
    assert paths_within_roots([], [str(tmp_path)]) is True


def test_paths_within_roots_rejects_path_outside_allowed_roots(tmp_path) -> None:
    allowed_root = tmp_path / "permitida"
    allowed_root.mkdir()
    outside = tmp_path / "fuera"
    assert paths_within_roots([str(outside)], [str(allowed_root)]) is False


def test_paths_within_roots_accepts_path_inside_allowed_root(tmp_path) -> None:
    allowed_root = tmp_path / "permitida"
    allowed_root.mkdir()
    inside = allowed_root / "sub"
    assert paths_within_roots([str(inside)], [str(allowed_root)]) is True


def test_paths_within_roots_restricted_role_without_roots_rejects_everything(tmp_path) -> None:
    """Un rol restringido sin `allowed_scan_roots` configuradas no puede indicar
    ninguna ruta externa — mismo criterio que documenta `paths_within_roots`."""
    assert paths_within_roots([str(tmp_path)], []) is False
