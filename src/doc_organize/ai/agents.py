"""
Bucle de agente con herramientas (2.0.0, G5): `AgentRunner`.

Un agente es una conversación con el modelo (tarea `agent`) en la que el modelo puede pedir **herramientas** y el
runner las ejecuta y le devuelve el resultado, hasta que el modelo da su respuesta. Lo que hace seguro el bucle (B12,
U11, inyección desde los documentos):

- **Herramientas de solo lectura y locales**: el runner solo ejecuta las `AgentTool` que se le dan; lo que no está en la
  lista no existe para el modelo (un nombre desconocido vuelve como error, no se ejecuta nada). Los agentes de
  doc_organize solo dan herramientas que leen o calculan en memoria; **proponen**, nunca aplican (D14).
- **Topes** (`AgentLimits`): pasos (llamadas al modelo), tokens acumulados, llamadas a herramientas y tamaño de cada
  resultado que vuelve al modelo. Al llegar a uno, el runner para y lo dice (`AgentRun.stop_reason`); nunca lanza por
  ello.
- **Cancelación** (`CancelToken`, el mismo de `ContextBuilder.build`): se comprueba antes de cada llamada al modelo y
  de cada herramienta; se puede cancelar desde otro hilo (p. ej. la web). La cancelación de la tarea de asyncio también funciona y se propaga.
- **Redacción**: todo lo que sale (también los resultados de las herramientas) pasa por `LlmClient`, que redacta
  credenciales (D7).

La respuesta final es la herramienta `finish` si se da `answer_schema` (sus argumentos, validados con `parse_answer`), o
el texto del último mensaje del modelo si no.

Example:
    ```python
    count = AgentTool(
        name="count_documents",
        description="Número de documentos del proyecto",
        parameters={"type": "object", "properties": {}},
        handler=lambda arguments: {"documents": len(documents)},
    )
    run = await AgentRunner(llm, [count]).run([{"role": "user", "content": "¿Cuántos documentos hay?"}])
    print(run.stop_reason, run.answer)
    ```
"""

from __future__ import annotations

import inspect
import json
import re
import time

from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

from doc_organize.ai.llm_client import LlmClient, LlmUsage, Message
from doc_organize.core.exceptions import AiResponseError
from doc_organize.core.models import AiTask
from doc_organize.core.progress import CancelToken
from doc_organize.utils.logging import get_logger

logger = get_logger(__name__)

AgentStopReason = Literal["finished", "max_steps", "max_tokens", "max_tool_calls", "cancelled", "invalid_answer"]
"""Por qué terminó un agente: `finished` (respondió), un tope, `cancelled` o `invalid_answer` (su respuesta no cumplía
el esquema tras los reintentos)."""

FINISH_TOOL = "finish"
#: Caracteres por token para estimar los tokens de una llamada si el proxy no los informa.
_CHARS_PER_TOKEN = 4

ToolHandler = Callable[[dict[str, Any]], Any | Awaitable[Any]]
StepCallback = Callable[["AgentStep", int], None]
"""Callback de progreso: el paso terminado y el tope de pasos."""


@dataclass(frozen=True)
class AgentTool:
    """Una herramienta que el agente puede pedir.

    Attributes:
        name (str): Nombre (`[a-zA-Z0-9_-]`, como piden los proveedores); `finish` está reservado.
        description (str): Para qué sirve, para el modelo.
        parameters (dict[str, Any]): Esquema JSON de los argumentos.
        handler (ToolHandler): Función (o corrutina) que recibe los argumentos y devuelve algo serializable a JSON. Debe
            ser **de solo lectura**: el runner no puede comprobarlo. Un `ValueError`, `TypeError` o `KeyError` vuelve al
            modelo como error de la herramienta; cualquier otra excepción se propaga.
        idempotent (bool): La misma llamada da el mismo resultado si nada cambia entre medias. Si lo es, una llamada
            idéntica a la anterior no se ejecuta y vuelve como error (los modelos pequeños se quedan en bucle); las
            herramientas que cambian algo (deshacer en un borrador) deben ser `False`.
    """

    name: str
    description: str
    parameters: dict[str, Any]
    handler: ToolHandler
    idempotent: bool = True

    def spec(self) -> dict[str, Any]:
        """La herramienta como la pide el formato de OpenAI/LiteLLM."""
        return {"type": "function", "function": {"name": self.name, "description": self.description, "parameters": self.parameters}}


@dataclass(frozen=True)
class AgentLimits:
    """Topes de un agente.

    Attributes:
        max_steps (int): Llamadas al modelo como máximo.
        max_tokens (int): Tokens acumulados (entrada + salida de todas las llamadas) como máximo; si el proxy no los
            informa, se estiman por el tamaño de los mensajes.
        max_tool_calls (int): Herramientas ejecutadas como máximo.
        max_tool_result_chars (int): Caracteres de cada resultado que vuelve al modelo (el resto se corta y se avisa).
        answer_retries (int): Veces que se le pide al modelo que corrija una respuesta final que no cumple el esquema.
        keep_tool_results (int | None): Resultados de herramientas que se reenvían enteros (los últimos); los
            anteriores se sustituyen por un aviso breve para que cada llamada no crezca sin límite (un modelo local
            con poco contexto pierde el principio de la conversación, y con él las instrucciones). `None` = todos.
            `AgentRun.messages` los guarda siempre enteros.
    """

    max_steps: int = 12
    max_tokens: int = 80_000
    max_tool_calls: int = 40
    max_tool_result_chars: int = 8_000
    answer_retries: int = 1
    keep_tool_results: int | None = None

    def __post_init__(self) -> None:
        if min(self.max_steps, self.max_tokens, self.max_tool_calls, self.max_tool_result_chars) < 1 or self.answer_retries < 0:
            raise ValueError("Los topes del agente deben ser positivos")
        if self.keep_tool_results is not None and self.keep_tool_results < 1:
            raise ValueError("keep_tool_results debe ser 1 o más (o None)")


@dataclass(frozen=True)
class AgentToolCall:
    """Una herramienta que pidió el modelo.

    Attributes:
        name (str): Herramienta pedida.
        arguments (dict[str, Any]): Argumentos (vacío si no eran JSON válido).
        error (str | None): Error devuelto al modelo (herramienta desconocida, argumentos no válidos, fallo), o `None`.
        truncated (bool): Si el resultado se cortó por `max_tool_result_chars`.
    """

    name: str
    arguments: dict[str, Any]
    error: str | None = None
    truncated: bool = False


@dataclass(frozen=True)
class AgentStep:
    """Una llamada al modelo y las herramientas que pidió en ella."""

    index: int
    tool_calls: list[AgentToolCall]
    usage: LlmUsage
    estimated_tokens: bool = False
    #: El modelo escribió las llamadas como JSON en el texto en lugar de `tool_calls` (algunos modelos locales).
    calls_in_text: bool = False


@dataclass
class AgentRun:
    """Resultado de `AgentRunner.run`.

    Attributes:
        stop_reason (AgentStopReason): Por qué terminó.
        answer (Any): La respuesta (lo que devuelve `parse_answer`, o el texto final); `None` si no terminó con
            `finished`.
        steps (list[AgentStep]): Las llamadas al modelo, en orden.
        messages (list[Message]): La conversación completa (lo que se envió, antes de redactar, y lo que respondió).
        prompt_tokens, completion_tokens (int): Tokens acumulados (estimados en las llamadas sin datos del proxy).
        duration_s (float): Duración total.
    """

    stop_reason: AgentStopReason
    answer: Any = None
    steps: list[AgentStep] = field(default_factory=list)
    messages: list[Message] = field(default_factory=list)
    prompt_tokens: int = 0
    completion_tokens: int = 0
    duration_s: float = 0.0

    @property
    def finished(self) -> bool:
        """Si el agente dio una respuesta válida."""
        return self.stop_reason == "finished"

    @property
    def tool_calls(self) -> list[AgentToolCall]:
        """Todas las herramientas pedidas, en orden."""
        return [call for step in self.steps for call in step.tool_calls]

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens


class AgentRunner:
    """Ejecuta un agente: llama al modelo, ejecuta las herramientas que pide y repite hasta su respuesta o un tope.

    Args:
        llm: Cliente de IA (tarea `agent` por defecto).
        tools: Herramientas disponibles (de solo lectura).
        limits: Topes (`AgentLimits`).
        answer_schema: Esquema JSON de la respuesta; si se da, el modelo responde con la herramienta `finish` y sus
            argumentos son la respuesta.
        parse_answer: Valida y convierte la respuesta (los argumentos de `finish`); un `ValueError`, `TypeError` o
            `KeyError` le pide al modelo que la corrija (`AgentLimits.answer_retries`).
        task: Tarea del cliente (modelo, clave, etiquetas).

    Raises:
        ValueError: Dos herramientas con el mismo nombre o una llamada `finish`.
    """

    def __init__(
        self,
        llm: LlmClient,
        tools: Sequence[AgentTool],
        *,
        limits: AgentLimits | None = None,
        answer_schema: dict[str, Any] | None = None,
        parse_answer: Callable[[dict[str, Any]], Any] | None = None,
        task: AiTask = "agent",
    ) -> None:
        names = [tool.name for tool in tools]
        if len(set(names)) != len(names) or FINISH_TOOL in names:
            raise ValueError(f"Herramientas con nombre repetido o reservado ({FINISH_TOOL}): {sorted(names)}")
        self.llm = llm
        self.tools = {tool.name: tool for tool in tools}
        self.limits = limits or AgentLimits()
        self.answer_schema = answer_schema
        self.parse_answer = parse_answer
        self.task = task

    def tool_specs(self) -> list[dict[str, Any]]:
        """Las herramientas tal como se envían al modelo (con `finish` si hay `answer_schema`)."""
        specs = [tool.spec() for tool in self.tools.values()]
        if self.answer_schema is not None:
            finish = AgentTool(
                FINISH_TOOL, "Da la respuesta final; llama a esta herramienta una sola vez, al terminar.", self.answer_schema, _no_handler
            )
            specs.append(finish.spec())
        return specs

    async def run(self, messages: Sequence[Message], *, cancel_token: CancelToken | None = None, on_step: StepCallback | None = None) -> AgentRun:
        """Ejecuta el agente desde `messages` (sistema e instrucciones del usuario).

        Args:
            messages: Mensajes iniciales.
            cancel_token: Para cancelar desde fuera.
            on_step: Se llama tras cada paso (llamada al modelo y sus herramientas) con el `AgentStep` y el tope de
                pasos, para mostrar el progreso. Un fallo del callback se registra y no para el agente.

        Raises:
            AiAuthError, AiConnectionError, AiError: Fallos del proxy (no se reintentan aquí: los reintentos son del
                cliente).
        """
        started = time.monotonic()
        run = AgentRun(stop_reason="max_steps", messages=[dict(message) for message in messages])
        state = _RunState(retries_left=self.limits.answer_retries)
        specs = self.tool_specs()
        try:
            for index in range(self.limits.max_steps):
                stop = self._stop_before_call(run, cancel_token)
                if stop is not None:
                    run.stop_reason = stop
                    return run
                if self.answer_schema is not None and self.limits.max_steps - index == _FINISH_WARNING_STEPS:
                    run.messages.append({"role": "user", "content": _FINISH_WARNING.format(steps=_FINISH_WARNING_STEPS, finish=FINISH_TOOL)})
                sent = _compact(run.messages, self.limits.keep_tool_results)
                message, usage = await self.llm.complete_with_tools(self.task, sent, specs)
                estimated = usage.prompt_tokens is None or usage.completion_tokens is None
                run.prompt_tokens += usage.prompt_tokens if usage.prompt_tokens is not None else _estimate(sent)
                run.completion_tokens += usage.completion_tokens if usage.completion_tokens is not None else _estimate([message])
                assistant, in_text = self._assistant(message)
                run.messages.append(assistant)
                step = AgentStep(index=index, tool_calls=[], usage=usage, estimated_tokens=estimated, calls_in_text=in_text)
                run.steps.append(step)
                requested = assistant.get("tool_calls") or []
                done = await self._calls(run, step, requested, state, cancel_token) if requested else self._final_text(run, assistant, state)
                _notify(on_step, step, self.limits.max_steps)
                if done:
                    return run
            run.stop_reason = "max_steps"
            return run
        finally:
            run.duration_s = time.monotonic() - started
            logger.info(
                "Agente %s: %s en %d pasos, %d herramientas, %d tokens",
                self.task,
                run.stop_reason,
                len(run.steps),
                len(run.tool_calls),
                run.total_tokens,
            )

    # --- Internos ------------------------------------------------------------------------------------------------------

    def _stop_before_call(self, run: AgentRun, cancel_token: CancelToken | None) -> AgentStopReason | None:
        if cancel_token is not None and cancel_token.cancelled:
            return "cancelled"
        if run.total_tokens >= self.limits.max_tokens:
            return "max_tokens"
        return None

    def _assistant(self, message: Message) -> tuple[Message, bool]:
        """El mensaje del asistente, con las llamadas escritas como texto convertidas en `tool_calls` (y si lo eran)."""
        assistant = _assistant_message(message)
        if assistant.get("tool_calls"):
            return assistant, False
        known = {*self.tools, FINISH_TOOL} if self.answer_schema is not None else set(self.tools)
        calls = _calls_from_text(assistant.get("content"), known)
        if not calls:
            return assistant, False
        return {"role": "assistant", "content": None, "tool_calls": calls}, True  # modelos locales que escriben JSON

    async def _calls(self, run: AgentRun, step: AgentStep, requested: list[Any], state: _RunState, cancel_token: CancelToken | None) -> bool:
        """Ejecuta las herramientas pedidas en un paso; `True` si el agente termina."""
        for call in requested:
            if cancel_token is not None and cancel_token.cancelled:
                run.stop_reason = "cancelled"
                return True
            name, arguments, error = _decode_call(call)
            if name == FINISH_TOOL and self.answer_schema is not None and error is None:
                done, reply = self._finish(run, arguments, state)
                step.tool_calls.append(AgentToolCall(name, arguments, error=None if done else reply))
                if done:
                    return True
                run.messages.append(_tool_message(call, reply))
                continue
            if state.tool_calls >= self.limits.max_tool_calls:
                run.stop_reason = "max_tool_calls"
                return True
            state.tool_calls += 1
            signature = (name, json.dumps(arguments, sort_keys=True, ensure_ascii=False))
            if error is None and signature == state.last_call and name in self.tools and self.tools[name].idempotent:
                error = _REPEATED_CALL
            state.last_call = signature
            content, error, truncated = await self._execute(name, arguments, error)
            step.tool_calls.append(AgentToolCall(name, arguments, error=error, truncated=truncated))
            run.messages.append(_tool_message(call, content))
        return False

    def _final_text(self, run: AgentRun, assistant: Message, state: _RunState) -> bool:
        """El modelo respondió sin herramientas. Sin esquema, es la respuesta; con esquema, se le recuerda `finish`."""
        if self.answer_schema is None:
            run.answer = assistant.get("content") or ""
            run.stop_reason = "finished"
            return True
        if state.retries_left <= 0:
            run.stop_reason = "invalid_answer"
            return True
        run.messages.append(
            {
                "role": "user",
                "content": f"Responde siempre llamando a una herramienta; cuando hayas terminado, da la respuesta final con `{FINISH_TOOL}`.",
            }
        )
        state.retries_left -= 1
        return False

    def _finish(self, run: AgentRun, arguments: dict[str, Any], state: _RunState) -> tuple[bool, str]:
        try:
            run.answer = self.parse_answer(arguments) if self.parse_answer is not None else arguments
        except (ValueError, TypeError, KeyError) as exc:
            run.answer = None
            if state.retries_left <= 0:
                run.stop_reason = "invalid_answer"
                return True, ""
            state.retries_left -= 1
            return False, f"Respuesta no válida ({_short(exc)}); corrígela y vuelve a llamar a `{FINISH_TOOL}`."
        run.stop_reason = "finished"
        return True, ""

    async def _execute(self, name: str, arguments: dict[str, Any], error: str | None) -> tuple[str, str | None, bool]:
        """Contenido para el modelo, error (o `None`) y si se cortó."""
        if error is None and name not in self.tools:
            error = f"La herramienta '{name}' no existe; las disponibles son: {', '.join(sorted(self.tools))}"
        if error is not None:
            return json.dumps({"error": error}, ensure_ascii=False), error, False
        try:
            result = self.tools[name].handler(arguments)
            if inspect.isawaitable(result):
                result = await result
        except (ValueError, TypeError, KeyError) as exc:
            error = f"La herramienta '{name}' falló: {_short(exc)}"
            return json.dumps({"error": error}, ensure_ascii=False), error, False
        content = result if isinstance(result, str) else json.dumps(result, ensure_ascii=False, default=str)
        limit = self.limits.max_tool_result_chars
        if len(content) <= limit:
            return content, None, False
        return content[:limit] + f"\n[... resultado cortado: {len(content) - limit} caracteres más]", None, True


@dataclass
class _RunState:
    """Lo que el runner lleva entre pasos."""

    retries_left: int
    tool_calls: int = 0
    last_call: tuple[str, str] | None = None


#: Pasos que quedan cuando se avisa al modelo de que termine (con `answer_schema`).
_FINISH_WARNING_STEPS = 2
_FINISH_WARNING = "Te quedan {steps} llamadas: deja de explorar y da la respuesta final con `{finish}`."
_REPEATED_CALL = "Acabas de hacer esta misma llamada con los mismos argumentos; su resultado ya está en la conversación. Haz otra cosa o termina."


def _notify(callback: StepCallback | None, step: AgentStep, max_steps: int) -> None:
    if callback is None:
        return
    try:
        callback(step, max_steps)
    except Exception as exc:  # noqa: BLE001 - un callback del consumidor nunca debe parar el agente
        logger.warning(f"El callback de progreso del agente falló: {type(exc).__name__}: {exc}")


def _no_handler(arguments: dict[str, Any]) -> Any:  # pragma: no cover - `finish` nunca se ejecuta como herramienta
    return arguments


def _assistant_message(message: Message) -> Message:
    """El mensaje del asistente con solo lo que se reenvía en la siguiente vuelta."""
    if not isinstance(message, dict):
        raise AiResponseError("La respuesta del agente no es un mensaje")
    result: Message = {"role": "assistant", "content": message.get("content")}
    if message.get("tool_calls"):
        result["tool_calls"] = message["tool_calls"]
    return result


def _decode_call(call: Any) -> tuple[str, dict[str, Any], str | None]:
    """Nombre, argumentos y error de una `tool_call` (argumentos no JSON o que no son un objeto → error)."""
    try:
        function = call["function"]
        name = str(function["name"])
    except (KeyError, TypeError):
        return "", {}, "Llamada a herramienta sin nombre"
    raw = function.get("arguments") or "{}"
    try:
        arguments = json.loads(raw) if isinstance(raw, str) else raw
    except json.JSONDecodeError:
        return name, {}, "Los argumentos no son JSON válido"
    if not isinstance(arguments, dict):
        return name, {}, "Los argumentos deben ser un objeto JSON"
    return name, arguments, None


_FENCE = re.compile(r"^```(?:json)?\s*(.*?)\s*```$", re.DOTALL)


def _calls_from_text(content: Any, known: set[str]) -> list[dict[str, Any]]:
    """Llamadas a herramientas escritas como JSON en el texto (`{"name", "arguments"}`, `{"function": {...}}`, una
    lista de ellas o `{"tool_calls": [...]}`), con el formato de `tool_calls`. Solo si **todas** son de herramientas
    conocidas; si no, ninguna (el texto es una respuesta)."""
    if not isinstance(content, str) or not content.strip():
        return []
    text = content.strip()
    fenced = _FENCE.match(text)
    try:
        data = json.loads(fenced.group(1) if fenced else text)
    except json.JSONDecodeError:
        return []
    items = data.get("tool_calls") if isinstance(data, dict) and "tool_calls" in data else data
    items = items if isinstance(items, list) else [items]
    calls = []
    for index, item in enumerate(items):
        function = item.get("function", item) if isinstance(item, dict) else None
        if isinstance(function, dict) and "name" not in function and "function_name" in function:
            function = {**function, "name": function["function_name"]}  # otra forma que escriben algunos modelos
        if not isinstance(function, dict) or function.get("name") not in known:
            return []
        arguments = function.get("arguments", function.get("parameters", {}))
        calls.append(
            {
                "id": f"text_call_{index}",
                "type": "function",
                "function": {
                    "name": function["name"],
                    "arguments": arguments if isinstance(arguments, str) else json.dumps(arguments, ensure_ascii=False),
                },
            }
        )
    return calls


_OMITTED = "[Resultado anterior omitido para ahorrar contexto; vuelve a pedirlo si lo necesitas]"


def _compact(messages: list[Message], keep: int | None) -> list[Message]:
    """`messages` con solo los últimos `keep` resultados de herramientas enteros (los demás, un aviso)."""
    if keep is None:
        return messages
    positions = [index for index, message in enumerate(messages) if message.get("role") == "tool"]
    old = set(positions[:-keep])
    return [{**message, "content": _OMITTED} if index in old else message for index, message in enumerate(messages)]


def _tool_message(call: Any, content: str) -> Message:
    call_id = call.get("id") if isinstance(call, dict) else None
    return {"role": "tool", "tool_call_id": call_id or "", "content": content}


def _estimate(messages: Sequence[Message]) -> int:
    return len(json.dumps(list(messages), ensure_ascii=False, default=str)) // _CHARS_PER_TOKEN + 1


def _short(exc: Exception) -> str:
    text = str(exc) or type(exc).__name__
    return text if len(text) <= 300 else text[:300] + "…"


__all__ = [
    "AgentLimits",
    "AgentRun",
    "AgentRunner",
    "AgentStep",
    "AgentStopReason",
    "AgentTool",
    "AgentToolCall",
]
