"""
Diagnóstico del entorno (2.0.0, F2): adelanta los fallos que hoy aparecen a mitad de un escaneo o de un build.

`check_environment()` comprueba Python, docling y sus modelos, los extras (`site`, `export`, OCR con GPU, audio y vídeo),
LibreOffice y que Zensical, si está, construye un sitio en una carpeta temporal. Con `check_ai=True` comprueba además
que cada modelo de IA configurado responde y si admite la salida `json_schema` estricta, **con texto sintético**: nunca se
envía nada de un documento. Sin red salvo `check_ai`; no toca ningún proyecto. Los detalles no llevan rutas ni claves.
"""

import asyncio
import importlib.metadata
import os
import subprocess
import sys
import tempfile

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from importlib.util import find_spec
from pathlib import Path
from typing import Literal

import httpx

from doc_organize.core.exceptions import AiConfigurationError
from doc_organize.core.models import EMBEDDING_TASKS, AiTask, EnvironmentCheck, EnvironmentReport

#: Versiones de Zensical con las que se ha probado el sitio del contexto: [mínima, máxima). Fuera del rango puede
#: funcionar, pero el formato de `zensical.toml` y el límite del buscador se comprobaron con estas.
ZENSICAL_TESTED_RANGE: tuple[tuple[int, ...], tuple[int, ...]] = ((0, 1, 1), (0, 2))
_MIN_PYTHON = (3, 12)
#: Modelos de docling que usa el pipeline de PDF e imágenes, en la caché de Hugging Face.
_DOCLING_MODEL_REPOS = ("models--docling-project--docling-layout-heron", "models--docling-project--docling-models", "models--ds4sd--docling-models")
_AI_TIMEOUT_S = 60.0


@dataclass(frozen=True)
class AiEndpoint:
    """Un modelo de IA a comprobar con `check_ai`: dónde está, con qué clave y qué alias.

    Attributes:
        name (str): Para qué se usa (aparece en el informe como `ai:<name>`).
        base_url (str): URL del LiteLLM Proxy.
        virtual_key (str): Clave; nunca aparece en el informe.
        model (str): Alias del modelo en el proxy.
        kind (str): `chat` (una respuesta JSON con `json_schema`) o `embedding` (un vector de `/embeddings`, 2.0.0).
    """

    name: str
    base_url: str
    virtual_key: str
    model: str
    kind: Literal["chat", "embedding"] = "chat"


async def check_environment(
    *,
    check_ai: bool = False,
    ai_endpoints: Sequence[AiEndpoint] | None = None,
    artifacts_path: Path | str | None = None,
    build_site: bool = True,
    transport: httpx.AsyncBaseTransport | None = None,
) -> EnvironmentReport:
    """Comprueba el entorno en el que corre doc_organize.

    Args:
        check_ai: Comprueba también los modelos de IA (con red; texto sintético).
        ai_endpoints: Modelos a comprobar con `check_ai`; `None` = los configurados por variables de entorno.
        artifacts_path: Carpeta de modelos de docling, si se usa una (`DocumentConverter(artifacts_path=)`).
        build_site: Con Zensical instalado, construye un sitio mínimo en una carpeta temporal.
        transport: Transporte `httpx` alternativo para `check_ai` (tests).

    Returns:
        `EnvironmentReport` con una entrada por comprobación; `report.ok` es `False` si alguna dio error.

    Example:
        >>> import asyncio
        >>> report = asyncio.run(check_environment(build_site=False))
        >>> report.checks[0].name
        'python'
    """
    checks = [
        _check_python(),
        _check_docling(),
        _check_docling_models(artifacts_path),
        _check_extra("export", "openpyxl", "Excel de las exportaciones"),
        await _check_zensical(build_site),
        await asyncio.to_thread(_check_gpu),
        await asyncio.to_thread(_check_office),
        await asyncio.to_thread(_check_av),
    ]
    if check_ai:
        try:
            endpoints = list(ai_endpoints) if ai_endpoints is not None else _endpoints_from_env()
        except AiConfigurationError as exc:  # p. ej. variables de 1.x (D15): el mensaje dice cuáles usar, sin valores
            checks.append(EnvironmentCheck(name="ai", status="error", detail=str(exc), remedy="Configura la IA con las variables de 2.0"))
            endpoints = []
        if not endpoints and not any(check.name == "ai" for check in checks):
            checks.append(EnvironmentCheck(name="ai", status="ok", detail="Ningún modelo de IA configurado: la IA no se usará"))
        for endpoint in endpoints:
            check = await _check_ai(endpoint, transport)
            checks.append(check.model_copy(update={"model": endpoint.model}))  # 2.2.0: qué modelo se probó
    return EnvironmentReport(checks=checks, checked_at=datetime.now(UTC).isoformat())


def _version(package: str) -> str | None:
    try:
        return importlib.metadata.version(package)
    except importlib.metadata.PackageNotFoundError:
        return None


def _version_tuple(version: str) -> tuple[int, ...]:
    parts = []
    for part in version.split("."):
        digits = "".join(char for char in part if char.isdigit())
        if not digits:
            break
        parts.append(int(digits))
        if len(digits) != len(part):  # «1rc2»: lo que sigue ya no es la versión
            break
    return tuple(parts)


def _check_python() -> EnvironmentCheck:
    version = ".".join(str(part) for part in sys.version_info[:3])
    if sys.version_info[:2] < _MIN_PYTHON:
        return EnvironmentCheck(name="python", status="error", detail=f"Python {version}", remedy="doc_organize necesita Python 3.12 o posterior")
    return EnvironmentCheck(name="python", status="ok", detail=f"Python {version}")


def _check_docling() -> EnvironmentCheck:
    version = _version("docling")
    if version is None:
        return EnvironmentCheck(
            name="docling", status="error", detail="docling no está instalado", remedy="Reinstala doc_organize (docling es obligatorio)"
        )
    return EnvironmentCheck(name="docling", status="ok", detail=f"docling {version}")


def _check_docling_models(artifacts_path: Path | str | None) -> EnvironmentCheck:
    folder = artifacts_path or os.environ.get("DOCLING_ARTIFACTS_PATH")
    if folder:
        path = Path(folder).expanduser()
        if path.is_dir() and any(path.iterdir()):
            return EnvironmentCheck(name="docling-models", status="ok", detail="Carpeta de modelos de docling indicada y con contenido")
        return EnvironmentCheck(
            name="docling-models",
            status="error",
            detail="La carpeta de modelos de docling indicada no existe o está vacía",
            remedy="Descárgalos con `docling-tools models download` en esa carpeta",
        )
    hub = Path(os.environ.get("HF_HUB_CACHE") or Path(os.environ.get("HF_HOME") or Path.home() / ".cache" / "huggingface") / "hub")
    found = [repo for repo in _DOCLING_MODEL_REPOS if (hub / repo).is_dir()]
    if found:
        return EnvironmentCheck(name="docling-models", status="ok", detail=f"Modelos de docling en la caché de Hugging Face ({len(found)})")
    return EnvironmentCheck(
        name="docling-models",
        status="warning",
        detail="No se encuentran los modelos de docling en la caché de Hugging Face",
        remedy="Se descargarán en el primer escaneo de un PDF o una imagen (hace falta red); sin red, descárgalos antes con `docling-tools models download`",
    )


def _check_extra(extra: str, package: str, purpose: str) -> EnvironmentCheck:
    version = _version(package)
    if version is None:
        return EnvironmentCheck(
            name=f"extra:{extra}", status="warning", detail=f"{package} no está instalado: sin {purpose}", remedy=f"pip install doc_organize[{extra}]"
        )
    return EnvironmentCheck(name=f"extra:{extra}", status="ok", detail=f"{package} {version}")


async def _check_zensical(build_site: bool) -> EnvironmentCheck:
    version = _version("zensical")
    if version is None:
        return EnvironmentCheck(
            name="extra:site",
            status="warning",
            detail="zensical no está instalado: sin sitio navegable del contexto",
            remedy="pip install doc_organize[site]",
        )
    low, high = ZENSICAL_TESTED_RANGE
    tested = low <= _version_tuple(version) < high
    tested_range = f"{'.'.join(map(str, low))} a <{'.'.join(map(str, high))}"
    if build_site:
        error = await asyncio.to_thread(_build_minimal_site)
        if error is not None:
            return EnvironmentCheck(
                name="extra:site",
                status="error",
                detail=f"zensical {version}: el build de un sitio mínimo falla ({error})",
                remedy=f"Reinstala el extra `site`; versiones probadas: {tested_range}",
            )
    if not tested:
        return EnvironmentCheck(
            name="extra:site",
            status="warning",
            detail=f"zensical {version}, fuera del rango probado ({tested_range})",
            remedy=f"Instala una versión probada: pip install 'zensical>={'.'.join(map(str, low))},<{'.'.join(map(str, high))}'",
        )
    return EnvironmentCheck(name="extra:site", status="ok", detail=f"zensical {version}" + (", build de prueba correcto" if build_site else ""))


def _build_minimal_site() -> str | None:
    """Construye un sitio de una página en una carpeta temporal; `None` si va bien, o la última línea del error."""
    command = [sys.executable, "-m", "zensical"] if find_spec("zensical") is not None else None
    if command is None:
        return "no se puede ejecutar zensical"
    with tempfile.TemporaryDirectory(prefix="doc_organize_diag_") as tmp:
        root = Path(tmp)
        (root / "docs").mkdir()
        (root / "docs" / "index.md").write_text("# Diagnóstico\n", encoding="utf-8")
        (root / "zensical.toml").write_text('[project]\nsite_name = "Diagnóstico"\ndocs_dir = "docs"\nsite_dir = "site"\n', encoding="utf-8")
        try:
            result = subprocess.run(
                [*command, "build", "-f", str(root / "zensical.toml")],
                cwd=root,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=120,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return type(exc).__name__
        if result.returncode != 0 or not (root / "site" / "index.html").is_file():
            output = (result.stderr or result.stdout).strip().splitlines()
            return output[-1][:200] if output else f"código {result.returncode}"
    return None


def _check_gpu() -> EnvironmentCheck:
    from doc_organize.utils.gpu_detector import detect_gpu_status

    status = detect_gpu_status()
    if status.gpu_active:
        return EnvironmentCheck(name="gpu", status="ok", detail="GPU CUDA disponible para el OCR")
    detail = (
        "Soporte de GPU instalado, sin GPU CUDA activa" if status.gpu_support_installed else "Sin soporte de GPU en este proceso (PyTorch sin CUDA)"
    )
    return EnvironmentCheck(name="gpu", status="warning", detail=f"{detail}: el OCR irá por CPU", remedy=status.instructions)


def _check_office() -> EnvironmentCheck:
    from doc_organize.utils.office_detector import detect_office_status

    status = detect_office_status()
    if status.libreoffice_installed:
        return EnvironmentCheck(name="libreoffice", status="ok", detail="LibreOffice disponible para los formatos de Office antiguos")
    return EnvironmentCheck(name="libreoffice", status="warning", detail="LibreOffice no está disponible", remedy=status.instructions)


def _check_av() -> EnvironmentCheck:
    from doc_organize.utils.av_detector import detect_av_status

    status = detect_av_status()
    if status.ready:
        return EnvironmentCheck(name="extra:av", status="ok", detail="Transcripción de audio y vídeo disponible")
    return EnvironmentCheck(name="extra:av", status="warning", detail="Sin transcripción de audio y vídeo", remedy=status.instructions)


#: Tareas de texto que se comprueban siempre que la IA esté configurada (con su alias recomendado si no tienen modelo);
#: `agent`, `embed` y `dedup` (2.2.0) solo si tienen modelo propio (las de embeddings, con una petición a `/embeddings`).
_CHECKED_TASKS: tuple[AiTask, ...] = ("classify", "enrich", "taxonomy_design")
_OPTIONAL_TASKS: tuple[AiTask, ...] = ("agent", "embed", "dedup")

#: Prueba de corte del texto de `dedup` (2.2.0): dos textos con el mismo relleno largo y un final distinto. Si los
#: vectores salen iguales, el modelo (o el proxy) no llegó al final: corta antes de unas `_PROBE_WORDS` palabras.
_PROBE_WORDS = 1500
_TRUNCATION_FILLER = " ".join(["Texto de relleno para comprobar hasta dónde lee el modelo de embeddings."] * (_PROBE_WORDS // 11))
_TRUNCATION_ENDINGS = (
    "El contrato regula el suministro eléctrico del edificio de oficinas y sus penalizaciones.",
    "La receta de la tarta lleva harina, huevos, azúcar y una pizca de canela.",
)


def _endpoints_from_env() -> list[AiEndpoint]:
    """Un `AiEndpoint` por tarea del cliente único configurado por variables de entorno (`settings_from_env`).

    Raises:
        AiConfigurationError: Configuración incompleta o con variables de 1.x (lo recoge `check_environment`).
    """
    from doc_organize.ai.settings import settings_from_env

    settings = settings_from_env()
    if settings is None:
        return []
    tasks: list[AiTask] = [*_CHECKED_TASKS, *(task for task in _OPTIONAL_TASKS if task in settings.tasks)]
    return [
        AiEndpoint(
            name=task,
            base_url=settings.base_url,
            virtual_key=settings.key_for(task),
            model=settings.model_for(task),
            kind="embedding" if task in EMBEDDING_TASKS else "chat",
        )
        for task in tasks
    ]


def _served_model(response: httpx.Response) -> str | None:
    """El modelo que dice la respuesta que contestó (campo `model` del formato OpenAI), si lo dice (2.2.0)."""
    try:
        model = response.json().get("model")
    except (ValueError, AttributeError):
        return None
    return model if isinstance(model, str) and model.strip() else None


def _with_served(detail: str, requested: str, served: str | None) -> str:
    return f"{detail} (responde {served})" if served and served != requested else detail


async def _truncates(client: httpx.AsyncClient, endpoint: AiEndpoint, headers: Mapping[str, str]) -> bool | None:
    """Si el modelo corta el texto antes de `_PROBE_WORDS` palabras (`None` si no se pudo saber)."""
    texts = [f"{_TRUNCATION_FILLER} {ending}" for ending in _TRUNCATION_ENDINGS]
    try:
        response = await client.post("/embeddings", json={"model": endpoint.model, "input": texts}, headers=dict(headers))
        data = sorted(response.json()["data"], key=lambda item: item["index"])
        first, second = (list(map(float, item["embedding"])) for item in data[:2])
    except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError):
        return None
    return first == second


_PROBE_MESSAGES = [
    {"role": "system", "content": "Respondes solo JSON."},
    {"role": "user", "content": 'Texto sintético de diagnóstico. Responde {"ok": true}.'},
]
_STRICT_SCHEMA = {
    "type": "json_schema",
    "json_schema": {
        "name": "diagnostico",
        "strict": True,
        "schema": {"type": "object", "properties": {"ok": {"type": "boolean"}}, "required": ["ok"], "additionalProperties": False},
    },
}


async def _check_embedding(endpoint: AiEndpoint, transport: httpx.AsyncBaseTransport | None) -> EnvironmentCheck:
    """Un vector de `/embeddings` para un texto sintético."""
    name = f"ai:{endpoint.name}"
    headers = {"Authorization": f"Bearer {endpoint.virtual_key}"}
    async with httpx.AsyncClient(base_url=endpoint.base_url, timeout=_AI_TIMEOUT_S, transport=transport) as client:
        try:
            response = await client.post("/embeddings", json={"model": endpoint.model, "input": ["Texto sintético de diagnóstico"]}, headers=headers)
        except httpx.TimeoutException:
            return EnvironmentCheck(
                name=name,
                status="error",
                detail=f"{endpoint.model}: sin respuesta en {_AI_TIMEOUT_S:g} s",
                remedy="Comprueba el proxy y que el modelo está cargado",
            )
        except httpx.HTTPError as exc:
            return EnvironmentCheck(
                name=name, status="error", detail=f"{endpoint.model}: error de red ({type(exc).__name__})", remedy="Comprueba la URL del proxy"
            )
    if response.status_code in (401, 403):
        return EnvironmentCheck(
            name=name, status="error", detail=f"{endpoint.model}: clave rechazada (HTTP {response.status_code})", remedy="Revisa la virtual key"
        )
    if response.is_error:
        return EnvironmentCheck(
            name=name,
            status="error",
            detail=f"{endpoint.model}: HTTP {response.status_code}",
            remedy="Comprueba que el alias de embeddings existe en el proxy",
        )
    try:
        dimension = len(response.json()["data"][0]["embedding"])
    except (KeyError, IndexError, TypeError, ValueError):
        return EnvironmentCheck(
            name=name, status="error", detail=f"{endpoint.model}: la respuesta no trae un vector", remedy="¿Es un modelo de embeddings?"
        )
    served = _served_model(response)
    detail = _with_served(f"{endpoint.model} da vectores de dimensión {dimension}", endpoint.model, served)
    if endpoint.name == "dedup":
        async with httpx.AsyncClient(base_url=endpoint.base_url, timeout=_AI_TIMEOUT_S, transport=transport) as client:
            truncates = await _truncates(client, endpoint, headers)
        if truncates:
            return EnvironmentCheck(
                name=name,
                status="warning",
                detail=f"{detail}, pero corta el texto antes de unas {_PROBE_WORDS} palabras",
                remedy="Usa bloques más pequeños en la búsqueda por contenido (`chunk_words`) o sube el contexto del modelo en el proxy",
                served_model=served,
                dimension=dimension,
            )
    return EnvironmentCheck(name=name, status="ok", detail=detail, served_model=served, dimension=dimension)


async def _check_ai(endpoint: AiEndpoint, transport: httpx.AsyncBaseTransport | None) -> EnvironmentCheck:
    """Una llamada con texto sintético y salida `json_schema` estricta; si el proxy la rechaza (400), otra con `json_object`.
    Un endpoint de embeddings, con `_check_embedding`."""
    if endpoint.kind == "embedding":
        return await _check_embedding(endpoint, transport)
    name = f"ai:{endpoint.name}"
    headers = {"Authorization": f"Bearer {endpoint.virtual_key}"}
    async with httpx.AsyncClient(base_url=endpoint.base_url, timeout=_AI_TIMEOUT_S, transport=transport) as client:
        try:
            strict = await client.post("/chat/completions", json=_payload(endpoint.model, _STRICT_SCHEMA), headers=headers)
            if strict.status_code == 400:
                plain = await client.post("/chat/completions", json=_payload(endpoint.model, {"type": "json_object"}), headers=headers)
            else:
                plain = None
        except httpx.TimeoutException:
            return EnvironmentCheck(
                name=name,
                status="error",
                detail=f"{endpoint.model}: sin respuesta en {_AI_TIMEOUT_S:g} s",
                remedy="Comprueba el proxy y que el modelo está cargado",
            )
        except httpx.HTTPError as exc:
            return EnvironmentCheck(
                name=name, status="error", detail=f"{endpoint.model}: error de red ({type(exc).__name__})", remedy="Comprueba la URL del proxy"
            )
    response = plain if plain is not None else strict
    if response.status_code in (401, 403):
        return EnvironmentCheck(
            name=name, status="error", detail=f"{endpoint.model}: clave rechazada (HTTP {response.status_code})", remedy="Revisa la virtual key"
        )
    if response.is_error:
        return EnvironmentCheck(
            name=name, status="error", detail=f"{endpoint.model}: HTTP {response.status_code}", remedy="Comprueba que el alias existe en el proxy"
        )
    served = _served_model(response)
    if plain is not None:
        return EnvironmentCheck(
            name=name,
            status="warning",
            detail=_with_served(f"{endpoint.model} responde, pero no admite la salida `json_schema` estricta", endpoint.model, served),
            remedy="2.0 usará `json_object` con validación; con un modelo que admita `json_schema` las respuestas son más fiables",
            served_model=served,
        )
    return EnvironmentCheck(
        name=name,
        status="ok",
        detail=_with_served(f"{endpoint.model} responde y admite `json_schema` estricto", endpoint.model, served),
        served_model=served,
    )


def _payload(model: str, response_format: Mapping[str, object]) -> dict[str, object]:
    return {"model": model, "messages": _PROBE_MESSAGES, "response_format": response_format, "temperature": 0, "max_tokens": 20}


__all__ = ["ZENSICAL_TESTED_RANGE", "AiEndpoint", "check_environment"]
