"""Tests de `utils.logging`: configuración centralizada del logger raíz `doc_organize`
(consola + fichero con rotación diaria, nivel/entorno parametrizables)."""

import json
import logging

from logging.handlers import TimedRotatingFileHandler
from pathlib import Path

import pytest

import doc_organize.utils.logging as logging_module

from doc_organize.utils.logging import configure_logging, get_logger

_ROOT_LOGGER_NAME = "doc_organize"
_ENV_VARS = ("DOC_ORGANIZE_ENV", "DOC_ORGANIZE_LOG_LEVEL", "DOC_ORGANIZE_LOG_DIR")


@pytest.fixture(autouse=True)
def _isolated_root_logger(monkeypatch: pytest.MonkeyPatch):
    """`configure_logging()` es idempotente por diseño (guarda de modulo
    `_configured`, no "¿tiene ya handlers?") -- sin resetear ese flag entre tests,
    el primero que la llame "ganaría" para el resto de la sesión de pytest. También
    aísla las variables de entorno para que el entorno real de quien ejecuta los
    tests no las contamine.

    No asume que `root.handlers` empiece vacío en cada test: el propio pytest
    añade sus `LogCaptureHandler` a cualquier logger con `propagate=False` (el
    que `configure_logging()` fija) antes de invocar el test -- de ahí que las
    aserciones de este fichero filtren por tipo de handler en vez de por longitud
    total de `root.handlers`.
    """
    for name in _ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    root = logging.getLogger(_ROOT_LOGGER_NAME)
    original_handlers = list(root.handlers)
    original_level = root.level
    original_propagate = root.propagate
    original_configured = logging_module._configured
    root.handlers.clear()
    logging_module._configured = False
    yield
    for handler in root.handlers:
        if handler not in original_handlers:
            handler.close()
    root.handlers.clear()
    root.handlers.extend(original_handlers)
    root.setLevel(original_level)
    root.propagate = original_propagate
    logging_module._configured = original_configured


def test_get_logger_returns_named_logger_without_own_handlers() -> None:
    logger = get_logger("doc_organize.some.module")
    assert isinstance(logger, logging.Logger)
    assert logger.name == "doc_organize.some.module"
    # No instala handlers propios: propaga por jerarquía al logger raíz
    # `doc_organize`, configurado (o no) por `configure_logging()`.
    assert logger.handlers == []


def test_configure_logging_installs_console_and_file_handlers(tmp_path: Path) -> None:
    configure_logging(env="development", log_dir=tmp_path, level="INFO")
    root = logging.getLogger(_ROOT_LOGGER_NAME)

    file_handlers = [h for h in root.handlers if isinstance(h, TimedRotatingFileHandler)]
    # `type(h) is StreamHandler` (no `isinstance`): el propio pytest añade sus
    # `LogCaptureHandler` -- subclase de `StreamHandler` -- a este logger porque
    # `configure_logging()` fija `propagate=False`; `isinstance` los contaría como
    # si fueran nuestro handler de consola.
    console_handlers = [h for h in root.handlers if type(h) is logging.StreamHandler]

    assert len(console_handlers) == 1
    assert len(file_handlers) == 1
    assert file_handlers[0].when == "MIDNIGHT"
    assert file_handlers[0].interval == 86400  # 1 dia, en segundos, tras normalizar "MIDNIGHT"
    assert file_handlers[0].backupCount == 15
    assert root.level == logging.INFO


def test_configure_logging_is_idempotent(tmp_path: Path) -> None:
    configure_logging(env="development", log_dir=tmp_path, level="INFO")
    root = logging.getLogger(_ROOT_LOGGER_NAME)
    handlers_after_first_call = list(root.handlers)

    configure_logging(env="production", log_dir=tmp_path / "otra", level="ERROR")

    assert root.handlers == handlers_after_first_call  # la segunda llamada no toca los handlers
    assert root.level == logging.INFO  # ni el nivel: se queda con la configuracion de la primera llamada
    assert not (tmp_path / "otra").exists()  # ni siquiera crea el directorio de la segunda llamada


def test_configure_logging_writes_json_lines(tmp_path: Path) -> None:
    configure_logging(env="development", log_dir=tmp_path, level="DEBUG")
    logger = get_logger("doc_organize.test_module")

    logger.info("hola mundo")
    for handler in logging.getLogger(_ROOT_LOGGER_NAME).handlers:
        handler.flush()

    log_file = tmp_path / "doc_organize.log"
    assert log_file.is_file()
    lines = [line for line in log_file.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(lines) == 1
    payload = json.loads(lines[0])
    assert payload["message"] == "hola mundo"
    assert payload["level"] == "INFO"
    assert payload["logger"] == "doc_organize.test_module"


def test_configure_logging_resolves_level_from_env_var(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DOC_ORGANIZE_LOG_LEVEL", "WARNING")
    configure_logging(env="development", log_dir=tmp_path)
    assert logging.getLogger(_ROOT_LOGGER_NAME).level == logging.WARNING


def test_configure_logging_default_level_is_debug_in_development(tmp_path: Path) -> None:
    configure_logging(env="development", log_dir=tmp_path)
    assert logging.getLogger(_ROOT_LOGGER_NAME).level == logging.DEBUG


def test_configure_logging_default_level_is_info_in_production(tmp_path: Path) -> None:
    configure_logging(env="production", log_dir=tmp_path)
    assert logging.getLogger(_ROOT_LOGGER_NAME).level == logging.INFO


def test_configure_logging_invalid_level_raises(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        configure_logging(env="development", log_dir=tmp_path, level="NO_EXISTE")


def test_configure_logging_creates_log_dir_if_missing(tmp_path: Path) -> None:
    log_dir = tmp_path / "nested" / "logs"
    assert not log_dir.exists()

    configure_logging(env="development", log_dir=log_dir)

    assert log_dir.is_dir()
    assert (log_dir / "doc_organize.log").exists()


def test_configure_logging_honors_log_dir_env_var(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    log_dir = tmp_path / "desde-env"
    monkeypatch.setenv("DOC_ORGANIZE_LOG_DIR", str(log_dir))

    configure_logging(env="development")

    assert (log_dir / "doc_organize.log").exists()
