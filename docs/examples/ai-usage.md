# Ejemplo: Consultar el Gasto de IA en LiteLLM

**Objetivo**: Demostrar cómo consultar con `LiteLLMUsageClient` y `LiteLLMUsageConfig` el gasto acumulado de una virtual
key de un LiteLLM Proxy, y cómo llegan los errores tipados (`UsageSourceAuthError`, `UsageSourceConnectionError`).

## 1. Contexto del Ejemplo

Todas las tareas de IA de doc_organize pasan por un LiteLLM Proxy, que lleva la cuenta del gasto de cada virtual key.
`LiteLLMUsageClient` lo consulta (`GET /key/info`) y lo devuelve como un `UsageSnapshot`; solo lee, no envía
peticiones de inferencia. doc_organize_web lo usa para mostrar el gasto de IA.

El ejemplo habla con un proxy falso en memoria (`httpx.MockTransport` pasado como `transport`): **las respuestas del
proxy son simuladas**, con la forma de `/key/info` que lee el cliente (`{"key": …, "info": {"key_alias", "spend", …}}`).
En uso real, `LiteLLMUsageClient(litellm_usage_config_from_env())` sin `transport` (variables
`DOC_ORGANIZE_LITELLM_BASE_URL` y `DOC_ORGANIZE_LITELLM_VIRTUAL_KEY`).

### Requisitos

- Python 3.12+
- `doc_organize[ai]` instalado (`httpx`)

No hay red, ni claves reales: las claves `sk-…` son de ejemplo.

## 2. Implementación de Referencia

```python
import asyncio
import hashlib
from datetime import date

import httpx

from doc_organize import (
    LiteLLMUsageClient,
    LiteLLMUsageConfig,
    UsageSourceAuthError,
    UsageSourceConnectionError,
    UsageSourceError,
)

KEYS = {  # Claves que el proxy falso conoce: clave → (alias, gasto en USD)
    "sk-equipo-calidad": ("calidad", 12.3456),
    "sk-equipo-compras": ("compras", 3.5),
}
HASHES = {hashlib.sha256(key.encode()).hexdigest(): key for key in KEYS}
seen: list[str] = []  # Lo que llega al «proxy»: ruta, query y cabecera


def fake_proxy(request: httpx.Request) -> httpx.Response:
    """LiteLLM Proxy falso en memoria: `GET /key/info` con respuestas simuladas."""
    bearer = request.headers["Authorization"].removeprefix("Bearer ")
    query = {name: value[:12] + "…" for name, value in request.url.params.items()}  # El hash, abreviado
    seen.append(f"{request.method} {request.url.path} query={query} auth=Bearer {bearer}")
    if bearer not in KEYS:
        return httpx.Response(401, json={"error": {"message": "Authentication Error, Invalid proxy server token"}})
    asked = request.url.params.get("key")
    target = HASHES.get(asked, asked) if asked else bearer  # Sin `?key=`, la clave del Bearer
    if target != bearer:
        return httpx.Response(403, json={"error": {"message": "La clave no es tuya"}})
    alias, spend = KEYS[target]
    token = hashlib.sha256(target.encode()).hexdigest()
    return httpx.Response(200, json={"key": token, "info": {"key_alias": alias, "spend": spend, "max_budget": 50.0}})


def network_down(request: httpx.Request) -> httpx.Response:
    """Un proxy que no contesta: cada intento falla en la conexión."""
    seen.append(f"{request.method} {request.url.path}")
    raise httpx.ConnectError("conexión rechazada", request=request)


async def main() -> None:
    url = "https://proxy.invalid"
    config = LiteLLMUsageConfig(base_url=url, virtual_key="sk-equipo-calidad")
    print(f"¿Clave en el repr de la config? {'sk-' in repr(config)}")  # no (2.4.2); model_dump() sí la lleva

    # 1) El gasto de la propia clave: sin `?key=`, la clave no va en la URL
    async with LiteLLMUsageClient(config, transport=httpx.MockTransport(fake_proxy)) as client:
        snapshot = await client.get_usage()
        item = snapshot.items[0]
        print(f"source={snapshot.source.value} líneas={len(snapshot.items)} hoy={snapshot.period_start == date.today().isoformat()}")
        print(f"sku={item.sku} quantity={item.quantity} unit_type={item.unit_type} cost_usd={item.cost_usd} product={item.product}")
        print(f"raw: max_budget={snapshot.raw['info']['max_budget']}")

        # 2) Otra clave, por su hash (la query sí queda en los logs): el proxy no deja verla
        try:
            await client.get_usage(key=hashlib.sha256(b"sk-equipo-compras").hexdigest())
        except UsageSourceAuthError as exc:
            print(f"Otra clave -> {type(exc).__name__}: {exc}")

    # 3) Una clave que el proxy no conoce: 401
    revoked = LiteLLMUsageConfig(base_url=url, virtual_key="sk-revocada")
    async with LiteLLMUsageClient(revoked, transport=httpx.MockTransport(fake_proxy)) as client:
        try:
            await client.get_usage()
        except UsageSourceAuthError as exc:
            print(f"Clave revocada -> {type(exc).__name__}: {exc} | ¿clave en el mensaje? {'sk-' in str(exc)}")

    print("--- Peticiones recibidas por el proxy falso")
    print("\n".join(seen))
    seen.clear()

    # 4) Sin conexión: 2 reintentos (sin espera) y luego el error tipado
    offline = LiteLLMUsageConfig(base_url=url, virtual_key="sk-equipo-calidad", retries=2, retry_backoff_s=0)
    async with LiteLLMUsageClient(offline, transport=httpx.MockTransport(network_down)) as client:
        try:
            await client.get_usage()
        except UsageSourceConnectionError as exc:
            print(f"Sin red -> {type(exc).__name__}: {exc} | intentos={len(seen)}")
            print(f"Es un UsageSourceError: {isinstance(exc, UsageSourceError)}")


if __name__ == "__main__":
    asyncio.run(main())
```

## 3. Explicación del Código

1. **La clave no sale en el `repr` de la config (2.4.2)**: `LiteLLMUsageConfig.virtual_key` se declara con
   `repr=False`, como en `AiSettings`/`TaskSettings` (las de `LlmClient`); hasta 2.4.1 aparecía en `repr(config)`.
   `model_dump()` la sigue incluyendo: no registres su resultado. Lo que el cliente escribe (mensajes de error y logs de
   reintento) tampoco lleva la clave
2. **Transporte**: `transport` es público para inyectar un transporte de `httpx`; sin él, el cliente habla con
   `base_url` por la red. `async with` cierra el cliente HTTP al salir
3. **La propia clave**: `get_usage()` sin `key` manda la clave solo en `Authorization` y **no** añade `?key=`: LiteLLM
   consulta entonces la clave de la cabecera, y la clave no queda en la URL que `httpx` registra
4. **`UsageSnapshot`**: `source` es `litellm` y trae **una sola línea** (LiteLLM no desglosa por fecha ni modelo):
   `sku` es el alias de la clave, `quantity` y `cost_usd` el gasto acumulado en USD (`unit_type="usd"`) y `product`,
   `"litellm"` (2.5.0; antes siempre `"anthropic"`). `period_end` y la fecha de la línea son las del día de la consulta, y
   `period_start` es desde cuándo cuenta el gasto: el último reinicio del presupuesto o la creación de la clave
   (`created_at`); el proxy falso no manda esas fechas, así que aquí también es hoy (`hoy=True`) y el ejemplo no las
   imprime. La respuesta completa queda en `raw`
5. **Otra clave**: `get_usage(key=...)` añade `?key=`, que sí queda en los logs; por eso se pasa el hash SHA-256 de la
   clave (LiteLLM lo acepta). Ver otra clave exige ser su dueño, de su equipo o administrador del proxy: aquí el proxy
   contesta 403 y sale `UsageSourceAuthError`
6. **401**: una clave que el proxy no conoce (revocada o mal copiada) da `UsageSourceAuthError`. El mensaje solo dice el
   código HTTP. 401 y 403 no se reintentan nunca
7. **Sin red**: un error de transporte se reintenta `retries` veces con espera `retry_backoff_s * 2**n` (aquí 0, para que
   el ejemplo no espere) y luego sale `UsageSourceConnectionError`. Cualquier otro HTTP de error da `UsageSourceError`,
   la base de las tres: `except UsageSourceError` las recoge todas. Las respuestas 429 y 503 se reintentan aparte
   (`rate_limit_retries`, por defecto 3)

## 4. Ejecución y Pruebas

```bash
$ python ai_usage_example.py 2>/dev/null
¿Clave en el repr de la config? False
source=litellm líneas=1 hoy=True
sku=calidad quantity=12.3456 unit_type=usd cost_usd=12.3456 product=litellm
raw: max_budget=50.0
Otra clave -> UsageSourceAuthError: LiteLLM Proxy rechazó la credencial (HTTP 403)
Clave revocada -> UsageSourceAuthError: LiteLLM Proxy rechazó la credencial (HTTP 401) | ¿clave en el mensaje? False
--- Peticiones recibidas por el proxy falso
GET /key/info query={} auth=Bearer sk-equipo-calidad
GET /key/info query={'key': 'f93f80ab2995…'} auth=Bearer sk-equipo-calidad
GET /key/info query={} auth=Bearer sk-revocada
Sin red -> UsageSourceConnectionError: Error de red consultando LiteLLM Proxy en https://proxy.invalid | intentos=3
Es un UsageSourceError: True
```

`2>/dev/null` solo oculta los dos avisos del log de los reintentos («ConnectError en GET /key/info; reintento 1/2 en
0 s»). La salida no depende de la máquina ni del día: las respuestas son las del proxy falso. Validación sintáctica:
`python -m py_compile ai_usage_example.py`.

## 5. Referencias Relacionadas

- [Referencia técnica: Monitorización de uso/coste de IA](../api/ai_usage_monitoring.md)
- [Documentación funcional: Monitorización de uso/coste de IA](../functional/ai_usage_monitoring.md)
- [Guía: Desplegar un LiteLLM Proxy](../guides/litellm_proxy_setup.md) (crear las virtual keys)
- [Ejemplo: Cliente de IA sin red](llm-client.md) (las llamadas de IA cuyo gasto se consulta aquí)
- [Ejemplo: Diagnosticar el entorno](diagnostics-check.md) (otro proxy falso con `httpx.MockTransport`)
