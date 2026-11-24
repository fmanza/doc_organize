# Ejemplo: Cliente de IA sin Red

**Objetivo**: Demostrar cómo configurar `LlmClient` con `AiSettings`/`TaskSettings` y hacer una llamada de `embed` y una de
`complete_json`, viendo qué llega realmente al proxy (credenciales redactadas) y qué devuelve `LlmResult`.

## 1. Contexto del Ejemplo

`LlmClient` es el cliente único del LiteLLM Proxy para todas las tareas de IA: elige modelo y clave por tarea, redacta
credenciales de todo lo que envía y valida la respuesta. El ejemplo lo usa de verdad, pero sobre `httpx.MockTransport`:
un proxy falso en memoria que responde con el formato OpenAI y guarda cada petición para inspeccionarla. En uso real,
`LlmClient(settings_from_env())` sin `transport`.

### Requisitos

- Python 3.11+
- `doc_organize[ai]` instalado (`httpx`)

No hay red, ni claves reales, ni modelo: las claves `sk-…` son de ejemplo.

## 2. Implementación de Referencia

```python
import asyncio
import json

import httpx

from doc_organize import AiSettings, LlmClient, LlmResult, TaskSettings

seen: list[dict] = []  # Lo que llega al «proxy»: para ver qué sale realmente de la máquina


def fake_proxy(request: httpx.Request) -> httpx.Response:
    """LiteLLM Proxy falso en memoria: `/embeddings` y `/chat/completions` con formato OpenAI."""
    body = json.loads(request.content)
    seen.append({"path": request.url.path, "auth": request.headers["Authorization"], "body": body})
    if request.url.path.endswith("/embeddings"):
        data = [{"index": i, "embedding": [float(len(text)), 1.0]} for i, text in enumerate(body["input"])]
        return httpx.Response(200, json={"data": data, "model": "proveedor/embed-v3"})
    answer = {"domain": "gestion-proveedores", "confidence": 0.82}
    return httpx.Response(200, json={
        "choices": [{"message": {"content": json.dumps(answer)}}],
        "usage": {"prompt_tokens": 57, "completion_tokens": 12},
        "model": "proveedor/modelo-grande-2026",
    })


async def main() -> None:
    settings = AiSettings(
        base_url="https://proxy.invalid",
        virtual_key="sk-general",
        tasks={
            "classify": TaskSettings(model="clasificador", virtual_key="sk-solo-clasificar", max_tokens=256),
            # Sin entrada para `embed`: modelo por defecto y clave general
        },
    )
    print(f"¿Claves en el repr? {'sk-' in repr(settings)}")  # `virtual_key` no sale en el repr ni en los logs
    print(f"Modelos: classify={settings.model_for('classify')}, embed={settings.model_for('embed')}")

    async with LlmClient(settings, transport=httpx.MockTransport(fake_proxy)) as llm:
        vectors = await llm.embed(["Alta de proveedores", "password=Sup3rS3creta! en el anexo"])
        print(f"Vectores: {vectors}")

        schema = {
            "type": "object",
            "properties": {"domain": {"type": "string"}, "confidence": {"type": "number"}},
            "required": ["domain", "confidence"],
            "additionalProperties": False,
        }
        messages = [
            {"role": "system", "content": "Clasifica el documento en un dominio del catálogo. Responde JSON."},
            {"role": "user", "content": "Alta de proveedores. Portal de compras: password=Sup3rS3creta!"},
        ]
        result: LlmResult[tuple[str, float]] = await llm.complete_json(
            "classify", messages, schema=schema, parse=lambda data: (data["domain"], float(data["confidence"]))
        )

    print(f"value={result.value} model={result.model} served_model={result.served_model}")
    print(f"response_format={result.response_format} usage={result.usage} redacted={result.redacted} cached={result.cached}")
    for call in seen:
        sent = call["body"].get("input") or [m["content"] for m in call["body"]["messages"] if m["role"] == "user"]
        print(f"{call['path']} model={call['body']['model']} auth={call['auth']} "
              f"max_tokens={call['body'].get('max_tokens')} tags={call['body']['metadata']['tags']}")
        print(f"  enviado: {sent}")


if __name__ == "__main__":
    asyncio.run(main())
```

## 3. Explicación del Código

1. **Configuración por tarea**: `AiSettings` lleva la URL del proxy y la clave general; `tasks` da a cada tarea
   (`TaskSettings`) su modelo y, si se quiere, su clave, tope de tokens, timeout o reintentos. Una tarea sin entrada usa
   el alias recomendado (`default_model_alias`: `doc-organize-embed`) y la clave general
2. **Claves fuera de la vista**: `virtual_key` está excluida del `repr` de `AiSettings` y `TaskSettings`; solo viaja en la
   cabecera `Authorization` de cada petición (`sk-solo-clasificar` para `classify`, `sk-general` para `embed`)
3. **Transporte**: `transport` es público para inyectar un transporte de `httpx` (aquí `MockTransport`); sin él, el
   cliente habla con `base_url` por la red. `async with` cierra el cliente HTTP al salir
4. **`embed`**: devuelve un vector por texto, en el mismo orden. Los textos se redactan **antes** de enviarse
5. **`complete_json`**: pide al proxy una salida `json_schema` estricta con `schema` y valida la respuesta con `parse`
   (si `parse` lanza `ValueError`/`TypeError`/`KeyError`, sale `AiResponseError`). Si el proxy rechaza `json_schema` con
   un 400, cae una vez a `json_object` y lo recuerda para ese modelo (`response_format`)
6. **`LlmResult`**: `value` (lo que devuelve `parse`), `model` (el alias pedido), `served_model` (el que dice la
   respuesta que contestó), `usage` (tokens), `redacted` (credenciales redactadas por regla, sin valores) y `cached`
   (si salió de una `AiResultCache`, sin llamar)
7. **Metadatos**: cada petición lleva `metadata.tags` con `doc_organize` y `task:<tarea>` (más `AiSettings.tags`), para
   repartir el gasto en el proxy; `max_tokens` va solo si la tarea lo tiene

## 4. Ejecución y Pruebas

```bash
$ python llm_client_example.py
¿Claves en el repr? False
Modelos: classify=clasificador, embed=doc-organize-embed
Vectores: [[19.0, 1.0], [32.0, 1.0]]
value=('gestion-proveedores', 0.82) model=clasificador served_model=proveedor/modelo-grande-2026
response_format=json_schema usage=LlmUsage(prompt_tokens=57, completion_tokens=12) redacted={'password': 1} cached=False
/embeddings model=doc-organize-embed auth=Bearer sk-general max_tokens=None tags=['doc_organize', 'task:embed']
  enviado: ['Alta de proveedores', 'password=«REDACTADO» en el anexo']
/chat/completions model=clasificador auth=Bearer sk-solo-clasificar max_tokens=256 tags=['doc_organize', 'task:classify']
  enviado: ['Alta de proveedores. Portal de compras: password=«REDACTADO»']
```

El segundo vector mide 32 porque el proxy falso usa la longitud del texto **ya redactado**: la contraseña nunca llegó.
La redacción se desactiva con `AiSettings(redact_credentials=False)`.

## 5. Referencias Relacionadas

- [Referencia técnica: Cliente único de IA](../api/llm_client.md)
- [Guía: Desplegar un LiteLLM Proxy](../guides/litellm_proxy_setup.md)
- [Ejemplo: Deduplicar documentos](dedup-resolve.md) (usa `LlmClient` sobre `MockTransport` para la tarea `dedup`)
