# Agentes (2.0.0)

Un **agente** es una conversación con el modelo (tarea `agent` de `AiSettings`) en la que el modelo puede pedir
**herramientas**: el runner las ejecuta y le devuelve el resultado, hasta que el modelo da su respuesta o se llega a un
tope. `AgentRunner` es el bucle que usan los agentes de doc_organize y sirve también para los tuyos.

```python
from doc_organize import AgentLimits, AgentRunner, AgentTool

count = AgentTool(
    name="count_documents",
    description="Número de documentos del proyecto por carpeta",
    parameters={"type": "object", "properties": {"folder": {"type": "string"}}},
    handler=lambda arguments: {"documents": contar(arguments.get("folder"))},
)
runner = AgentRunner(llm, [count], limits=AgentLimits(max_steps=8, max_tokens=40_000))
run = await runner.run([
    {"role": "system", "content": "Respondes sobre el proyecto usando las herramientas."},
    {"role": "user", "content": "¿Cuántos documentos hay en Procedimientos?"},
])
print(run.stop_reason, run.answer, run.total_tokens)
```

## Seguridad

Los agentes leen texto que viene de los documentos, y un documento puede intentar dar instrucciones al modelo
(inyección). Por eso el bucle está acotado:

- **Solo las herramientas que se le dan**. Un nombre que no está en la lista vuelve al modelo como error y no ejecuta
  nada; unos argumentos que no son un objeto JSON, también. Las herramientas deben ser **de solo lectura y locales**:
  el runner no puede comprobarlo, así que es responsabilidad de quien las define. Los agentes de doc_organize solo
  proponen; nunca aplican cambios (D14).
- **Topes** (`AgentLimits`): llamadas al modelo (`max_steps`), tokens acumulados de entrada y salida (`max_tokens`;
  estimados por tamaño si el proxy no los informa), herramientas ejecutadas (`max_tool_calls`) y caracteres de cada
  resultado que vuelve al modelo (`max_tool_result_chars`; el resto se corta y se le avisa). Al llegar a un tope, el
  agente para con `stop_reason` y **no lanza** excepción.
- **Cancelación**: `AgentCancellation().cancel()` (se puede llamar desde otro hilo) para el agente antes de la
  siguiente llamada al modelo o herramienta: `stop_reason == "cancelled"`. Cancelar la tarea de asyncio también
  funciona.
- **Redacción**: todo lo que se envía, también los resultados de las herramientas, pasa por `LlmClient`, que redacta
  credenciales (D7).

Si una herramienta lanza `ValueError`, `TypeError` o `KeyError`, el error vuelve al modelo como resultado (puede
corregir los argumentos). Cualquier otra excepción es un fallo del programa y se propaga.

## Respuesta estructurada

Con `answer_schema`, el runner añade la herramienta `finish`: el modelo da su respuesta llamándola, y sus argumentos son
la respuesta. `parse_answer` la valida; si lanza `ValueError`, `TypeError` o `KeyError`, se le pide al modelo que la
corrija (`AgentLimits.answer_retries`, una vez por defecto), y si sigue sin valer, `stop_reason == "invalid_answer"`.
Si el modelo contesta con texto en lugar de llamar a `finish`, se le recuerda.

```python
runner = AgentRunner(
    llm, tools,
    answer_schema={"type": "object", "properties": {"total": {"type": "integer"}}, "required": ["total"]},
    parse_answer=lambda data: int(data["total"]),
)
```

## Motivos de parada

| `stop_reason` | Qué pasó |
|---|---|
| `finished` | El modelo respondió (`run.answer`) |
| `max_steps`, `max_tokens`, `max_tool_calls` | Se llegó a ese tope |
| `cancelled` | Se canceló con `AgentCancellation` |
| `invalid_answer` | La respuesta no cumplía `answer_schema` tras los reintentos |

`run.steps` trae cada llamada al modelo con las herramientas que pidió (y sus errores) y `run.messages` la conversación
completa, para auditarla.

El tope de tokens de **cada respuesta** del modelo es `TaskSettings.max_tokens` de la tarea `agent` (2048 por
defecto); `AgentLimits.max_tokens` es el del agente entero.

::: doc_organize.ai.agents
    options:
      show_root_heading: false
      members:
        - AgentRunner
        - AgentTool
        - AgentLimits
        - AgentCancellation
        - AgentRun
        - AgentStep
        - AgentToolCall
