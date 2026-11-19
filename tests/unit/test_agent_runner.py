"""`AgentRunner` (2.0.0, G5): bucle de herramientas, topes, cancelación y respuesta con esquema."""

import json

from typing import Any

import pytest

from doc_organize.ai.agents import FINISH_TOOL, AgentLimits, AgentRunner, AgentTool
from doc_organize.core.models import DEFAULT_MAX_TOKENS
from doc_organize.core.progress import CancelToken
from tests.unit.fake_llm import FakeRequest, agent_script, call_tools, fake_llm, say

SECRET = "Xq7#Secreto-9931"
QUESTION = [{"role": "system", "content": "Eres un agente de prueba."}, {"role": "user", "content": "¿Cuántos hay?"}]
ANSWER_SCHEMA = {"type": "object", "properties": {"total": {"type": "integer"}}, "required": ["total"]}


def _tool(name: str = "count", handler: Any = None) -> AgentTool:
    return AgentTool(name, f"Herramienta {name}", {"type": "object", "properties": {}}, handler or (lambda arguments: {"total": 3}))


def _last_message(request: FakeRequest) -> dict[str, Any]:
    return request.body["messages"][-1]


@pytest.mark.asyncio
async def test_text_answer_without_tools() -> None:
    llm = fake_llm(agent=agent_script(say("Hay 3")))

    run = await AgentRunner(llm, [_tool()]).run(QUESTION)

    assert run.finished and run.answer == "Hay 3" and len(run.steps) == 1 and run.tool_calls == []
    assert run.prompt_tokens == 100 and run.completion_tokens == 10


@pytest.mark.asyncio
async def test_tool_result_goes_back_to_the_model() -> None:
    seen: list[dict[str, Any]] = []
    llm = fake_llm(agent=agent_script(call_tools(("count", {"folder": "a"})), lambda request: seen.append(_last_message(request)) or say("Hay 3")))
    received: list[dict[str, Any]] = []

    run = await AgentRunner(llm, [_tool(handler=lambda arguments: received.append(arguments) or {"total": 3})]).run(QUESTION)

    assert run.finished and received == [{"folder": "a"}]
    assert seen == [{"role": "tool", "tool_call_id": "call_0", "content": '{"total": 3}'}]
    assert [call.name for call in run.tool_calls] == ["count"] and run.tool_calls[0].error is None
    body = llm.proxy.calls("agent")[0].body  # type: ignore[attr-defined]
    assert [tool["function"]["name"] for tool in body["tools"]] == ["count"]
    assert body["max_tokens"] == DEFAULT_MAX_TOKENS["agent"]


@pytest.mark.asyncio
async def test_async_handlers_are_awaited() -> None:
    async def handler(arguments: dict[str, Any]) -> dict[str, int]:
        return {"total": 7}

    llm = fake_llm(agent=agent_script(call_tools(("count", {})), lambda request: say(_last_message(request)["content"])))

    run = await AgentRunner(llm, [_tool(handler=handler)]).run(QUESTION)

    assert run.answer == '{"total": 7}'


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("call", "expected"),
    [
        (("delete_everything", {}), "no existe"),
        (("count", "{no es json"), "no son JSON"),
        (("count", "[1, 2]"), "deben ser un objeto"),
    ],
)
async def test_bad_calls_return_an_error_and_run_nothing(call: tuple[str, Any], expected: str) -> None:
    executed: list[Any] = []
    llm = fake_llm(agent=agent_script(call_tools(call), lambda request: say(_last_message(request)["content"])))

    run = await AgentRunner(llm, [_tool(handler=lambda arguments: executed.append(arguments))]).run(QUESTION)

    assert run.finished and executed == []
    assert expected in json.loads(run.answer)["error"] and expected in (run.tool_calls[0].error or "")


@pytest.mark.asyncio
async def test_tool_value_errors_go_back_to_the_model_and_others_propagate() -> None:
    def broken(arguments: dict[str, Any]) -> Any:
        raise ValueError("carpeta desconocida")

    llm = fake_llm(agent=agent_script(call_tools(("count", {})), lambda request: say(_last_message(request)["content"])))
    run = await AgentRunner(llm, [_tool(handler=broken)]).run(QUESTION)
    assert "carpeta desconocida" in run.answer

    def crash(arguments: dict[str, Any]) -> Any:
        raise RuntimeError("fallo del programa")

    llm = fake_llm(agent=agent_script(call_tools(("count", {}))))
    with pytest.raises(RuntimeError):
        await AgentRunner(llm, [_tool(handler=crash)]).run(QUESTION)


@pytest.mark.asyncio
async def test_max_steps() -> None:
    llm = fake_llm(agent=lambda request: call_tools(("count", {})))

    run = await AgentRunner(llm, [_tool()], limits=AgentLimits(max_steps=3)).run(QUESTION)

    assert run.stop_reason == "max_steps" and run.answer is None and len(llm.proxy.calls("agent")) == 3  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_max_tokens_stops_before_the_next_call() -> None:
    llm = fake_llm(agent=lambda request: call_tools(("count", {}), _usage={"prompt_tokens": 900, "completion_tokens": 100}))

    run = await AgentRunner(llm, [_tool()], limits=AgentLimits(max_tokens=1500)).run(QUESTION)

    assert run.stop_reason == "max_tokens" and len(run.steps) == 2 and run.total_tokens == 2000


@pytest.mark.asyncio
async def test_tokens_are_estimated_when_the_proxy_does_not_report_them() -> None:
    llm = fake_llm(agent=agent_script(say("Hay 3", _usage=None)))

    run = await AgentRunner(llm, [_tool()]).run(QUESTION)

    assert run.steps[0].estimated_tokens and run.prompt_tokens > 0 and run.completion_tokens > 0


@pytest.mark.asyncio
async def test_max_tool_calls() -> None:
    executed: list[Any] = []
    llm = fake_llm(agent=lambda request: call_tools(("count", {"page": 1}), ("count", {"page": 2})))

    run = await AgentRunner(llm, [_tool(handler=lambda arguments: executed.append(1))], limits=AgentLimits(max_tool_calls=3)).run(QUESTION)

    assert run.stop_reason == "max_tool_calls" and len(executed) == 3


@pytest.mark.asyncio
async def test_long_results_are_cut() -> None:
    llm = fake_llm(agent=agent_script(call_tools(("count", {})), lambda request: say(_last_message(request)["content"])))

    run = await AgentRunner(llm, [_tool(handler=lambda arguments: "x" * 500)], limits=AgentLimits(max_tool_result_chars=100)).run(QUESTION)

    assert run.answer.startswith("x" * 100) and "400 caracteres más" in run.answer and run.tool_calls[0].truncated


@pytest.mark.asyncio
async def test_cancelled_before_starting_calls_nothing() -> None:
    llm = fake_llm(agent=agent_script(say("Hay 3")))
    token = CancelToken()
    token.cancel()

    run = await AgentRunner(llm, [_tool()]).run(QUESTION, cancel_token=token)

    assert run.stop_reason == "cancelled" and llm.proxy.requests == []  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_cancelled_between_tools_stops_before_the_next() -> None:
    token = CancelToken()
    executed: list[str] = []

    def first(arguments: dict[str, Any]) -> str:
        executed.append("first")
        token.cancel()
        return "ok"

    second = _tool("second", handler=lambda arguments: executed.append("second"))
    llm = fake_llm(agent=agent_script(call_tools(("first", {}), ("second", {}))))

    run = await AgentRunner(llm, [_tool("first", handler=first), second]).run(QUESTION, cancel_token=token)

    assert run.stop_reason == "cancelled" and executed == ["first"] and len(llm.proxy.calls("agent")) == 1  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_finish_tool_gives_the_parsed_answer() -> None:
    llm = fake_llm(agent=agent_script(call_tools(("count", {})), call_tools((FINISH_TOOL, {"total": 3}))))

    run = await AgentRunner(llm, [_tool()], answer_schema=ANSWER_SCHEMA, parse_answer=lambda data: int(data["total"])).run(QUESTION)

    assert run.finished and run.answer == 3
    tools = llm.proxy.calls("agent")[0].body["tools"]  # type: ignore[attr-defined]
    assert tools[-1]["function"]["name"] == FINISH_TOOL and tools[-1]["function"]["parameters"] == ANSWER_SCHEMA


@pytest.mark.asyncio
async def test_invalid_answer_is_corrected_once() -> None:
    replies: list[str] = []
    llm = fake_llm(
        agent=agent_script(
            call_tools((FINISH_TOOL, {"total": "tres"})),
            lambda request: replies.append(_last_message(request)["content"]) or call_tools((FINISH_TOOL, {"total": 3})),
        )
    )

    run = await AgentRunner(llm, [], answer_schema=ANSWER_SCHEMA, parse_answer=lambda data: int(data["total"])).run(QUESTION)

    assert run.finished and run.answer == 3 and "Respuesta no válida" in replies[0]
    assert run.tool_calls[0].error is not None


@pytest.mark.asyncio
async def test_answer_still_invalid_after_retries() -> None:
    llm = fake_llm(agent=lambda request: call_tools((FINISH_TOOL, {"total": "tres"})))

    run = await AgentRunner(llm, [], answer_schema=ANSWER_SCHEMA, parse_answer=lambda data: int(data["total"])).run(QUESTION)

    assert run.stop_reason == "invalid_answer" and run.answer is None and len(run.steps) == 2


@pytest.mark.asyncio
async def test_text_instead_of_finish_gets_a_reminder() -> None:
    llm = fake_llm(agent=agent_script(say("Son 3"), call_tools((FINISH_TOOL, {"total": 3}))))

    run = await AgentRunner(llm, [], answer_schema=ANSWER_SCHEMA).run(QUESTION)

    assert run.finished and run.answer == {"total": 3}
    assert FINISH_TOOL in _last_message(llm.proxy.calls("agent")[1])["content"]  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_tool_results_are_redacted_before_leaving() -> None:
    llm = fake_llm(agent=agent_script(call_tools(("count", {})), say("ok")))

    run = await AgentRunner(llm, [_tool(handler=lambda arguments: f"password: {SECRET}")]).run(QUESTION)

    assert run.finished
    assert all(SECRET not in json.dumps(request.body) for request in llm.proxy.requests)  # type: ignore[attr-defined]


def test_tool_names_must_be_unique_and_not_reserved() -> None:
    llm = fake_llm()
    with pytest.raises(ValueError):
        AgentRunner(llm, [_tool(), _tool()])
    with pytest.raises(ValueError):
        AgentRunner(llm, [_tool(FINISH_TOOL)])
    with pytest.raises(ValueError):
        AgentLimits(max_steps=0)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "content",
    [
        '{"name": "count", "arguments": {"folder": "a"}}',
        '```json\n{"function": {"name": "count", "arguments": "{\\"folder\\": \\"a\\"}"}}\n```',
        '{"tool_calls": [{"type": "function", "function": {"name": "count", "parameters": {"folder": "a"}}}]}',
        '{"tool_calls": [{"id": "c1", "type": "function_call", "function_name": "count", "arguments": {"folder": "a"}}]}',
    ],
)
async def test_tool_calls_written_as_text_are_run(content: str) -> None:
    received: list[Any] = []
    llm = fake_llm(agent=agent_script(say(content), say("Hay 3")))

    run = await AgentRunner(llm, [_tool(handler=lambda arguments: received.append(arguments) or 3)]).run(QUESTION)

    assert run.finished and run.answer == "Hay 3" and received == [{"folder": "a"}] and run.steps[0].calls_in_text
    assert run.messages[2]["content"] is None and run.messages[2]["tool_calls"][0]["function"]["name"] == "count"


@pytest.mark.asyncio
@pytest.mark.parametrize("content", ['{"name": "delete_everything", "arguments": {}}', '{"total": 3}', "[1, 2]", "Hay {3}"])
async def test_text_that_is_not_a_known_tool_call_is_an_answer(content: str) -> None:
    llm = fake_llm(agent=agent_script(say(content)))

    run = await AgentRunner(llm, [_tool()]).run(QUESTION)

    assert run.finished and run.answer == content and not run.steps[0].calls_in_text


@pytest.mark.asyncio
async def test_finish_written_as_text() -> None:
    llm = fake_llm(agent=agent_script(say('{"name": "finish", "arguments": {"total": 3}}')))

    run = await AgentRunner(llm, [], answer_schema=ANSWER_SCHEMA, parse_answer=lambda data: int(data["total"])).run(QUESTION)

    assert run.finished and run.answer == 3


@pytest.mark.asyncio
async def test_old_tool_results_are_omitted_but_kept_in_the_run() -> None:
    llm = fake_llm(agent=agent_script(*(call_tools(("count", {"page": page})) for page in range(3)), say("fin")))
    results = iter(["uno", "dos", "tres"])

    run = await AgentRunner(llm, [_tool(handler=lambda arguments: next(results))], limits=AgentLimits(keep_tool_results=1)).run(QUESTION)

    last = llm.proxy.calls("agent")[-1].body["messages"]  # type: ignore[attr-defined]
    sent = [message["content"] for message in last if message["role"] == "tool"]
    assert sent[2] == "tres" and all("omitido" in content for content in sent[:2])
    assert [message["content"] for message in run.messages if message["role"] == "tool"] == ["uno", "dos", "tres"]
    with pytest.raises(ValueError):
        AgentLimits(keep_tool_results=0)


@pytest.mark.asyncio
async def test_a_repeated_idempotent_call_is_not_run_again() -> None:
    executed: list[Any] = []
    replies: list[str] = []
    undo = AgentTool("undo", "Deshace", {"type": "object", "properties": {}}, lambda arguments: executed.append("undo") or "ok", idempotent=False)
    llm = fake_llm(
        agent=agent_script(
            call_tools(("count", {"page": 1})),
            call_tools(("count", {"page": 1})),
            lambda request: replies.append(_last_message(request)["content"]) or call_tools(("undo", {})),
            call_tools(("undo", {})),
            say("fin"),
        )
    )

    run = await AgentRunner(llm, [_tool(handler=lambda arguments: executed.append("count") or 1), undo]).run(QUESTION)

    assert executed == ["count", "undo", "undo"] and "misma llamada" in replies[0] and "misma llamada" in (run.tool_calls[1].error or "")


@pytest.mark.asyncio
async def test_the_model_is_told_to_finish_before_the_last_steps() -> None:
    llm = fake_llm(agent=lambda request: call_tools(("count", {"page": len(request.body["messages"])})))

    run = await AgentRunner(llm, [_tool()], limits=AgentLimits(max_steps=4), answer_schema=ANSWER_SCHEMA).run(QUESTION)

    warnings = [message for message in run.messages if message["role"] == "user" and "Te quedan 2 llamadas" in message["content"]]
    assert run.stop_reason == "max_steps" and len(warnings) == 1
    assert "Te quedan" in llm.proxy.calls("agent")[2].body["messages"][-1]["content"]  # type: ignore[attr-defined]
