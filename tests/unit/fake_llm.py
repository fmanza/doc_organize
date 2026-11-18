"""Proxy LiteLLM falso para los tests: un `LlmClient` real (redacción, esquema y validación de verdad) sobre
`httpx.MockTransport`, que responde según la tarea y el documento.

Uso:
    llm = fake_llm(classify=lambda request: {"domains": "calidad", "material_types": None})
    llm = fake_llm(classify=script("ok", "auth", "conn"))     # una respuesta por llamada
    llm = fake_llm(enrich=lambda request: {"description": "D", "keywords": ["a"]})

Para `classify`, la función devuelve el valor de cada eje (slug o `None`; o `(slug, confianza)`), y el proxy arma la
respuesta con las claves del esquema enviado. También puede devolver un `httpx.Response` (un error) o lanzar
`httpx.ConnectError` (red).
"""

import json

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import httpx

from doc_organize.ai import LlmClient
from doc_organize.core.models import AiSettings, TaskSettings


@dataclass
class FakeRequest:
    """Lo que recibió el proxy en una llamada."""

    task: str
    body: dict[str, Any]

    @property
    def text(self) -> str:
        """Todo el texto de los mensajes."""
        return "\n".join(str(message.get("content")) for message in self.body.get("messages", []))

    @property
    def title(self) -> str:
        """El título que va en el mensaje del usuario (`Título: …`)."""
        for line in self.body["messages"][-1]["content"].splitlines():
            if line.startswith("Título: "):
                return line.removeprefix("Título: ")
        return ""

    @property
    def axes(self) -> list[str]:
        """Claves de los ejes pedidos (de `json_schema`)."""
        schema = self.body["response_format"].get("json_schema", {}).get("schema", {})
        return [key for key in schema.get("properties", {}) if key != "reasoning"]


Responder = Callable[[FakeRequest], Any]


@dataclass
class FakeProxy:
    """Proxy falso con una función por tarea; guarda las peticiones."""

    responders: dict[str, Responder]
    requests: list[FakeRequest] = field(default_factory=list)

    def __call__(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        task = next(tag.removeprefix("task:") for tag in body["metadata"]["tags"] if tag.startswith("task:"))
        fake = FakeRequest(task=task, body=body)
        self.requests.append(fake)
        responder = self.responders.get(task)
        if responder is None:
            return httpx.Response(500, json={"error": f"tarea {task} sin respuesta en el test"})
        answer = responder(fake)
        if isinstance(answer, httpx.Response):
            return answer
        if task == "classify" and not (
            isinstance(answer, dict) and "reasoning" in answer and all(isinstance(answer.get(key), dict) for key in fake.axes)
        ):
            answer = _classification(fake, answer)
        return httpx.Response(
            200, json={"choices": [{"message": {"content": json.dumps(answer)}}], "usage": {"prompt_tokens": 100, "completion_tokens": 10}}
        )

    def calls(self, task: str) -> list[FakeRequest]:
        return [request for request in self.requests if request.task == task]


def _classification(request: FakeRequest, answer: Any) -> dict[str, Any]:
    """`{"eje": slug | (slug, confianza) | None}` → la respuesta del esquema de clasificación."""
    values = answer if isinstance(answer, dict) else {}
    result: dict[str, Any] = {"reasoning": values.get("reasoning", "Justificación de prueba")}
    for key in request.axes:
        value = values.get(key)
        slug, confidence = value if isinstance(value, tuple) else (value, 0.8)
        result[key] = {"value": slug, "confidence": confidence}
    return result


def fake_llm(*, settings: AiSettings | None = None, **responders: Responder) -> LlmClient:
    """Un `LlmClient` contra un `FakeProxy`; el proxy queda en `llm.proxy`."""
    proxy = FakeProxy(dict(responders))
    settings = settings or AiSettings(
        base_url="https://proxy.test",
        virtual_key="sk-test",
        rate_limit_retries=0,
        tasks={"classify": TaskSettings(model="stub-classify"), "enrich": TaskSettings(model="stub-enrich")},
    )
    client = LlmClient(settings, transport=httpx.MockTransport(proxy))
    client.proxy = proxy  # type: ignore[attr-defined]
    return client


def script(*outcomes: str, axis_values: dict[str, Any] | None = None) -> Responder:
    """Una respuesta por llamada: `ok` (asigna `axis_values` o `calidad` al primer eje), `none` (nada), `auth` (401),
    `conn` (error de red) o `err` (500). Tras el guion, `ok`."""
    queue = list(outcomes)

    def respond(request: FakeRequest) -> Any:
        outcome = queue.pop(0) if queue else "ok"
        if outcome == "auth":
            return httpx.Response(401)
        if outcome == "err":
            return httpx.Response(500)
        if outcome == "conn":
            raise httpx.ConnectError("sin red")
        if outcome == "none":
            return {}
        return axis_values if axis_values is not None else {request.axes[0]: "calidad"}

    return respond


class FakeLlmClient(LlmClient):
    """`LlmClient` sobre un `FakeProxy`, con lo que recibió a mano."""

    proxy: FakeProxy

    @property
    def calls(self) -> list[Any]:
        """Catálogos pedidos en cada clasificación: la lista de slugs si hubo un eje, una tupla de listas si varios
        (como guardaban los dobles de 1.x)."""
        catalogs = []
        for request in self.proxy.calls("classify"):
            schema = request.body["response_format"]["json_schema"]["schema"]["properties"]
            enums = [[slug for slug in schema[key]["properties"]["value"]["enum"] if slug is not None] for key in request.axes]
            catalogs.append(enums[0] if len(enums) == 1 else tuple(enums))
        return catalogs

    @property
    def sent_texts(self) -> list[str]:
        """El texto de los mensajes de cada llamada (para comprobar lo que salió)."""
        return [request.text for request in self.proxy.requests]


def fake_client(*, settings: AiSettings | None = None, **responders: Responder) -> FakeLlmClient:
    """Como `fake_llm`, con `calls` y `sent_texts`."""
    proxy = FakeProxy(dict(responders))
    settings = settings or AiSettings(
        base_url="https://proxy.test",
        virtual_key="sk-test",
        rate_limit_retries=0,
        tasks={"classify": TaskSettings(model="stub-classify"), "enrich": TaskSettings(model="stub-enrich")},
    )
    client = FakeLlmClient(settings, transport=httpx.MockTransport(proxy))
    client.proxy = proxy
    return client


def domain_ai(domain: str | None, confidence: float = 0.8, *, error: bool = False, **extra: Responder) -> FakeLlmClient:
    """Clasificación de un eje (como el doble de `DomainClassificationClient` de 1.x): siempre `domain`."""

    def respond(request: FakeRequest) -> Any:
        return httpx.Response(500) if error else {request.axes[0]: (domain, confidence)}

    return fake_client(classify=respond, **extra)


def taxonomy_ai(
    domain: str | None = None,
    domain_confidence: float = 0.8,
    material_type: str | None = None,
    material_type_confidence: float = 0.8,
    *,
    error: bool = False,
    **extra: Responder,
) -> FakeLlmClient:
    """Clasificación de los dos ejes organizadores en una llamada (como el doble de `TaxonomyClassificationClient`)."""

    def respond(request: FakeRequest) -> Any:
        if error:
            return httpx.Response(500)
        folder, subfolder = request.axes[:2]
        return {folder: (domain, domain_confidence), subfolder: (material_type, material_type_confidence)}

    return fake_client(classify=respond, **extra)


def enrichment(description: str | None = "Descripción de la IA", keywords: list[str] | None = None) -> Responder:
    """Respuesta de la tarea `enrich`."""
    return lambda _request: {"description": description, "keywords": ["clave"] if keywords is None else keywords}
