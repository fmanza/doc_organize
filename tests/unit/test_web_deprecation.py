"""Tests de la obsolescencia de la web integrada (L-10, 0.14.0): avisos del CLI y de los imports."""

import os
import subprocess
import sys
import warnings

import pytest

from doc_organize._deprecations import WEB_REMOVAL_VERSION, WEB_REPLACEMENT_URL
from doc_organize.main import build_parser, main


def _run_python(code: str, *args: str) -> subprocess.CompletedProcess[str]:
    """Proceso nuevo: los módulos se importan desde cero y los avisos se ven tal cual."""
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}  # el aviso lleva tildes: en Windows la consola no es UTF-8
    return subprocess.run([sys.executable, *args, "-c", code], capture_output=True, text=True, encoding="utf-8", check=False, env=env)


# --- CLI ---------------------------------------------------------------------------------------------------------


def test_tenant_command_warns_once_on_stderr_and_keeps_stdout_and_exit_code(tmp_path, capsys):
    exit_code = main(["tenant", "create", "Acme Corp", "--auth-db-path", str(tmp_path / "auth.db")])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert captured.err.count("obsoleto") == 1
    assert WEB_REPLACEMENT_URL in captured.err
    assert WEB_REMOVAL_VERSION in captured.err
    assert "obsoleto" not in captured.out
    assert WEB_REPLACEMENT_URL not in captured.out
    assert "acme-corp" in captured.out  # el comando sigue funcionando igual


def test_failing_deprecated_command_keeps_its_exit_code(tmp_path, capsys):
    auth_db = str(tmp_path / "auth.db")
    main(["tenant", "create", "Acme Corp", "--auth-db-path", auth_db])
    capsys.readouterr()

    exit_code = main(["tenant", "create", "Acme Corp", "--auth-db-path", auth_db])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert captured.err.count("obsoleto") == 1
    assert "Error" in captured.err


def test_user_command_warns_on_stderr(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr("doc_organize.main.getpass.getpass", lambda prompt="": "s3cr3t-password")
    auth_db = str(tmp_path / "auth.db")
    main(["tenant", "create", "Acme", "--auth-db-path", auth_db])
    capsys.readouterr()

    main(["user", "create", "--tenant", "acme", "ana", "--auth-db-path", auth_db])

    captured = capsys.readouterr()
    assert "El subcomando 'user'" in captured.err
    assert "obsoleto" not in captured.out


def test_web_command_warns_on_stderr(tmp_path, monkeypatch, capsys):
    pytest.importorskip("uvicorn")
    monkeypatch.setattr("uvicorn.run", lambda *args, **kwargs: None)

    exit_code = main(["web", "--registry-path", str(tmp_path / "projects.json"), "--auth-db-path", str(tmp_path / "auth.db")])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert captured.err.count("obsoleto") == 1
    assert "El subcomando 'web'" in captured.err
    assert "obsoleto" not in captured.out


def test_library_commands_do_not_warn(tmp_path, capsys):
    main(["project", "list", "--registry-path", str(tmp_path / "projects.json")])

    captured = capsys.readouterr()
    assert "obsoleto" not in captured.err
    assert "obsoleto" not in captured.out


@pytest.mark.parametrize("command", ["web", "tenant", "user"])
def test_help_of_deprecated_subcommands_says_obsolete(command, capsys):
    with pytest.raises(SystemExit):
        build_parser().parse_args([command, "--help"])

    assert "[obsoleto]" in capsys.readouterr().out


def test_top_level_help_marks_only_deprecated_subcommands(capsys):
    with pytest.raises(SystemExit):
        build_parser().parse_args(["--help"])

    lines = capsys.readouterr().out.splitlines()
    marked = {line.split()[0] for line in lines if "[obsoleto]" in line and line.strip()}
    assert marked == {"web", "tenant", "user"}


# --- imports ------------------------------------------------------------------------------------------------------


@pytest.mark.slow
@pytest.mark.parametrize("module", ["doc_organize.web", "doc_organize.auth"])
def test_import_emits_deprecation_warning_pointing_at_the_importer(module):
    pytest.importorskip("fastapi") if module == "doc_organize.web" else None
    code = (
        "import warnings\n"
        "with warnings.catch_warnings(record=True) as caught:\n"
        "    warnings.simplefilter('always')\n"
        f"    import {module}\n"
        "for w in caught:\n"
        "    if issubclass(w.category, DeprecationWarning) and 'doc_organize_web' in str(w.message):\n"
        "        print(w.filename, '|', w.message)\n"
    )

    result = _run_python(code)

    assert result.returncode == 0, result.stderr
    lines = [line for line in result.stdout.splitlines() if line]
    messages = [line.split(" | ", 1)[1] for line in lines]
    assert any(message.startswith(f"{module} está obsoleto") for message in messages)
    assert all(WEB_REMOVAL_VERSION in message and WEB_REPLACEMENT_URL in message for message in messages)
    # stacklevel correcto: el aviso apunta al código del consumidor, no a doc_organize ni a importlib.
    assert all(line.split(" | ", 1)[0] == "<string>" for line in lines)


@pytest.mark.slow
@pytest.mark.parametrize("command", ["scan", "project", "deduplicate", "export"])
def test_library_cli_never_imports_web_or_auth(command):
    code = (
        "import sys\n"
        "from doc_organize.main import build_parser\n"
        f"try:\n    build_parser().parse_args(['{command}', '--help'])\n"
        "except SystemExit:\n    pass\n"
        "assert 'doc_organize.auth' not in sys.modules and 'doc_organize.web' not in sys.modules\n"
    )

    result = _run_python(code, "-W", "error::DeprecationWarning")

    assert result.returncode == 0, result.stderr


@pytest.mark.slow
def test_package_import_does_not_warn():
    with warnings.catch_warnings():
        warnings.simplefilter("error", DeprecationWarning)
        result = _run_python("import doc_organize, doc_organize.context, doc_organize.ai, doc_organize.main", "-W", "error::DeprecationWarning")

    assert result.returncode == 0, result.stderr
