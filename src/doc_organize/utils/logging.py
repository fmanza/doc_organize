"""
Logging estructurado (JSON) con rotacion opcional de archivo.
"""

import json
import logging

from logging.handlers import RotatingFileHandler
from pathlib import Path


class _JsonFormatter(logging.Formatter):
    """Formatea cada registro de log como una linea JSON."""

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def get_logger(name: str, log_file: str | Path | None = None) -> logging.Logger:
    """Crea (o reutiliza) un logger estructurado en JSON.

    Args:
        name: Nombre del logger (normalmente `__name__` del modulo llamante).
        log_file: Si se indica, añade un RotatingFileHandler sobre ese archivo
            (5 MB por archivo, 3 backups) ademas de la salida por consola.

    Returns:
        Logger configurado; llamadas repetidas con el mismo `name` devuelven
        el mismo logger sin duplicar handlers.

    Example:
        >>> logger = get_logger(__name__)
        >>> logger.info("Escaneo completado")
    """
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger

    logger.setLevel(logging.INFO)
    formatter = _JsonFormatter()

    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)
    logger.addHandler(stream_handler)

    if log_file is not None:
        file_handler = RotatingFileHandler(log_file, maxBytes=5_000_000, backupCount=3, encoding="utf-8")
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

    return logger


__all__ = ["get_logger"]
