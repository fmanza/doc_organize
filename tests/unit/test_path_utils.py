"""Tests unitarios de `utils/path_utils.py` (punto central anti path-traversal).

`safe_path_join`/`is_subpath` ya se ejercitaban indirectamente vía sus llamadores
(`ProjectRegistry.create_project`, `DeduplicationManager._move_to_duplicates`,
`FolderValidator`), pero ningún test cubría directamente el caso de traversal
(`".."`) que es la razón de ser de `safe_path_join` (maturity-assessment,
sesión 2026-09-03)."""

import os

from pathlib import Path

import pytest

from doc_organize.core.exceptions import InvalidPathError
from doc_organize.utils import path_utils
from doc_organize.utils.path_utils import (
    copy_file_nofollow,
    copy_tree_nofollow,
    ensure_no_symlinks,
    ensure_tree_has_no_symlinks,
    is_subpath,
    paths_within_roots,
    safe_path_join,
)


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


def test_ensure_no_symlinks_returns_absolute_path_without_resolving(tmp_path) -> None:
    assert ensure_no_symlinks(tmp_path / "no" / "existe") == Path(os.path.abspath(tmp_path / "no" / "existe"))


def test_ensure_no_symlinks_rejects_any_symlink_segment(tmp_path) -> None:
    real = tmp_path / "real"
    real.mkdir()
    try:
        (tmp_path / "enlace").symlink_to(real, target_is_directory=True)
    except OSError:
        pytest.skip("El entorno no permite crear symlinks (privilegios insuficientes en Windows).")

    with pytest.raises(OSError):
        ensure_no_symlinks(tmp_path / "enlace")
    with pytest.raises(OSError):
        ensure_no_symlinks(tmp_path / "enlace" / "a.pdf")


# --- Copia sin seguir enlaces (L-8a, G27) ---


def _dir_link(link: Path, target: Path) -> None:
    """Enlace a carpeta; en Windows sin privilegios, una unión."""
    try:
        link.symlink_to(target, target_is_directory=True)
    except OSError:
        if os.name != "nt":
            pytest.skip("El entorno no permite crear symlinks.")
        import _winapi  # solo existe en Windows

        _winapi.CreateJunction(str(target), str(link))


def test_copy_file_nofollow_copies_content_and_mtime(tmp_path) -> None:
    source = tmp_path / "a.txt"
    source.write_bytes(b"contenido")
    os.utime(source, (1_600_000_000, 1_600_000_000))
    target = tmp_path / "b.txt"

    copy_file_nofollow(source, target)

    assert target.read_bytes() == b"contenido"
    assert int(target.stat().st_mtime) == 1_600_000_000


def test_copy_file_nofollow_overwrites_only_when_asked(tmp_path) -> None:
    source = tmp_path / "a.txt"
    source.write_bytes(b"nuevo")
    target = tmp_path / "b.txt"
    target.write_bytes(b"viejo")

    with pytest.raises(FileExistsError):
        copy_file_nofollow(source, target)
    copy_file_nofollow(source, target, overwrite=True)

    assert target.read_bytes() == b"nuevo"


def test_copy_file_nofollow_rejects_a_linked_folder_on_either_side(tmp_path) -> None:
    real = tmp_path / "real"
    real.mkdir()
    (real / "a.txt").write_bytes(b"x")
    _dir_link(tmp_path / "enlace", real)

    with pytest.raises(OSError):
        copy_file_nofollow(tmp_path / "enlace" / "a.txt", tmp_path / "b.txt")
    with pytest.raises(OSError):
        copy_file_nofollow(real / "a.txt", tmp_path / "enlace" / "c.txt")
    assert not (real / "c.txt").exists()


def test_copy_tree_nofollow_copies_nested_folders_and_overwrites(tmp_path) -> None:
    source = tmp_path / "img"
    (source / "sub").mkdir(parents=True)
    (source / "a.png").write_bytes(b"A")
    (source / "sub" / "b.png").write_bytes(b"B")
    target = tmp_path / "destino" / "img"
    target.mkdir(parents=True)
    (target / "a.png").write_bytes(b"viejo")

    copy_tree_nofollow(source, target)

    assert (target / "a.png").read_bytes() == b"A"
    assert (target / "sub" / "b.png").read_bytes() == b"B"


def test_copy_tree_nofollow_fails_on_a_link_inside_without_following_it(tmp_path) -> None:
    secret = tmp_path / "fuera"
    secret.mkdir()
    (secret / "secreto.txt").write_bytes(b"SECRETO")
    source = tmp_path / "img"
    source.mkdir()
    _dir_link(source / "enlace", secret)
    target = tmp_path / "destino"

    with pytest.raises(OSError):
        copy_tree_nofollow(source, target)
    with pytest.raises(OSError):
        ensure_tree_has_no_symlinks(source)

    assert not (target / "enlace" / "secreto.txt").exists()


@pytest.mark.skipif(not path_utils._NOFOLLOW_DIR_FD, reason="Solo POSIX: dir_fd + O_NOFOLLOW")
def test_copy_does_not_follow_a_link_set_after_the_check(tmp_path, monkeypatch) -> None:
    """Sin la comprobación con `lstat` (enlace puesto justo después), los descriptores con `O_NOFOLLOW` no lo siguen."""
    secret = tmp_path / "fuera"
    secret.mkdir()
    (secret / "secreto.txt").write_bytes(b"SECRETO")
    (tmp_path / "carpeta").symlink_to(secret, target_is_directory=True)
    (tmp_path / "fichero.txt").symlink_to(secret / "secreto.txt")
    monkeypatch.setattr(path_utils, "ensure_no_symlinks", lambda path: Path(os.path.abspath(path)))

    for source in (tmp_path / "carpeta" / "secreto.txt", tmp_path / "fichero.txt"):
        with pytest.raises(OSError):
            copy_file_nofollow(source, tmp_path / "copia.txt")
    with pytest.raises(OSError):
        copy_tree_nofollow(tmp_path / "carpeta", tmp_path / "destino")

    assert not (tmp_path / "copia.txt").exists()
    assert not (tmp_path / "destino" / "secreto.txt").exists()
