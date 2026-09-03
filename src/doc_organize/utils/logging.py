"""
Logging estructurado (JSON) con salida a consola y rotacion diaria a fichero.
"""

import json
import logging
import os

from logging.handlers import TimedRotatingFileHandler
from pathlib import Path

_ROOT_LOGGER_NAME = "doc_organize"
_LOG_FILE_NAME = "doc_organize.log"
_LOG_RETENTION_DAYS = 15

_ENV_VAR_ENVIRONMENT = "DOC_ORGANIZE_ENV"
_ENV_VAR_LOG_LEVEL = "DOC_ORGANIZE_LOG_LEVEL"
_ENV_VAR_LOG_DIR = "DOC_ORGANIZE_LOG_DIR"

#: Nivel por defecto segun entorno cuando ni el parametro ni la variable de
#: entorno lo fijan explicitamente: mas detalle en desarrollo, menos ruido en
#: produccion.
_DEFAULT_LEVEL_BY_ENV = {"development": "DEBUG", "production": "INFO"}

#: Guarda si `configure_logging()` ya se ejecuto en este proceso (AUDIT_CODE:
#: deliberadamente independiente de `root.handlers`). Comprobar "¿tiene ya
#: handlers?" para decidir si configurar es fragil: cualquier tercero que anada un
#: handler al logger `doc_organize` por su cuenta haria que esa comprobacion diera
#: un falso positivo. Ocurre en la practica con pytest: su plugin de captura de
#: logs anade sus propios `LogCaptureHandler` a cualquier logger con
#: `propagate=False` (ver mas abajo) antes de cada test, lo que rompia
#: `configure_logging()` en la suite completa (pero no al ejecutar el fichero de
#: test de logging de forma aislada, donde ese logger nunca acumulaba handlers
#: ajenos entre tests).
_configured = False


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


def _default_log_dir(env: str) -> Path:
    """Ruta de logs por defecto segun `env`, sin depender de dependencias nuevas.

    - `development`: `./logs`, relativa al directorio de trabajo actual (encaja
      con ejecutar la CLI/web dentro de un proyecto concreto).
    - `production`: ruta persistente por usuario del sistema operativo —
      `%LOCALAPPDATA%\\doc_organize\\logs` en Windows, `~/.local/share/doc_organize/logs`
      en Linux/macOS — para no depender de cual sea el directorio de trabajo del
      proceso que arranca el servicio.
    """
    if env != "production":
        return Path("logs")
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(base) / "doc_organize" / "logs"
    return Path.home() / ".local" / "share" / "doc_organize" / "logs"


def _resolve_level(level: str | None, env: str) -> int:
    name = (level or os.environ.get(_ENV_VAR_LOG_LEVEL) or _DEFAULT_LEVEL_BY_ENV.get(env, "INFO")).upper()
    mapping = logging.getLevelNamesMapping()
    if name not in mapping:
        raise ValueError(f"Nivel de log invalido: '{name}' (valores validos: {sorted(mapping)})")
    return mapping[name]


def configure_logging(*, env: str | None = None, log_dir: str | Path | None = None, level: str | None = None) -> None:
    """Configura (una unica vez por proceso) el logger raiz `doc_organize`.

    Instala un `StreamHandler` (consola) y un `TimedRotatingFileHandler` (fichero,
    rotacion diaria a medianoche, retencion de 15 dias) sobre el logger `doc_organize`.
    Los loggers de modulo (`get_logger(__name__)`, con nombre `doc_organize.xxx`) no
    instalan handlers propios: propagan aqui por jerarquia de `logging`, asi que deben
    llamar a esta funcion una unica vez al arrancar cada punto de entrada (hoy,
    `main.py::main()`, compartido por CLI y por el comando `web`) antes de que se emita
    ningun log. Si no se llama nunca (p. ej. un test que instancia un servicio
    directamente sin pasar por `main()`), Python usa su handler `lastResort`
    (WARNING+ a stderr) — no falla, simplemente no hay fichero ni nivel configurado.

    Args:
        env: `"development"` o `"production"`. Por defecto, la variable de entorno
            `DOC_ORGANIZE_ENV`, o `"development"` si no esta definida (entorno mas
            verboso/menos critico como valor por defecto seguro).
        log_dir: Carpeta donde escribir `doc_organize.log`. Por defecto, la variable
            de entorno `DOC_ORGANIZE_LOG_DIR`, o una ruta derivada de `env` (ver
            `_default_log_dir`).
        level: Nivel de log (`DEBUG`/`INFO`/`WARNING`/`ERROR`/`CRITICAL`). Por
            defecto, la variable de entorno `DOC_ORGANIZE_LOG_LEVEL`, o `DEBUG` en
            desarrollo / `INFO` en produccion.

    Raises:
        ValueError: Si `level` (o `DOC_ORGANIZE_LOG_LEVEL`) no es un nivel de
            logging valido.

    Example:
        >>> configure_logging(env="production", level="INFO")
    """
    global _configured
    if _configured:
        return

    root = logging.getLogger(_ROOT_LOGGER_NAME)
    resolved_env = env or os.environ.get(_ENV_VAR_ENVIRONMENT, "development")
    root.setLevel(_resolve_level(level, resolved_env))
    # Sin esto, un registro de "doc_organize.xxx" también se propagaría al logger
    # raiz real de Python (nombre ""): si algun futuro proceso host o una
    # dependencia (docling, uvicorn, etc.) llega a llamar a `logging.basicConfig()`
    # o a añadir un handler ahi, cada linea se emitiria por duplicado (una vez con
    # el formato JSON de aqui, otra con el formato que sea que tenga ese handler).
    root.propagate = False

    formatter = _JsonFormatter()

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    root.addHandler(console_handler)

    resolved_dir = Path(log_dir) if log_dir is not None else Path(os.environ.get(_ENV_VAR_LOG_DIR) or _default_log_dir(resolved_env))
    resolved_dir.mkdir(parents=True, exist_ok=True)
    file_handler = TimedRotatingFileHandler(
        resolved_dir / _LOG_FILE_NAME,
        when="midnight",
        interval=1,
        backupCount=_LOG_RETENTION_DAYS,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)

    _configured = True


def get_logger(name: str) -> logging.Logger:
    """Devuelve el logger de modulo `name`.

    No instala handlers propios: el logger `name` (p. ej. `doc_organize.scan.scan_command`)
    propaga por jerarquia al logger raiz `doc_organize`, configurado por
    `configure_logging()`. Llamadas repetidas con el mismo `name` devuelven el mismo
    objeto `logging.Logger` (comportamiento nativo de `logging.getLogger`).

    Args:
        name: Nombre del logger (normalmente `__name__` del modulo llamante).

    Returns:
        Logger listo para usar.

    Example:
        >>> logger = get_logger(__name__)
        >>> logger.info("Escaneo completado")
    """
    return logging.getLogger(name)


__all__ = ["configure_logging", "get_logger"]
