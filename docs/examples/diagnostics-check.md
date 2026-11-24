# Ejemplo: Diagnosticar el Entorno

**Objetivo**: Demostrar cómo comprobar el entorno con `check_environment`, sin IA y con los modelos de IA.

## 1. Contexto del Ejemplo

`check_environment` adelanta los fallos de entorno (falta un extra, no hay GPU, faltan los modelos de Docling, un
modelo de IA no responde) antes de un escaneo o de construir el sitio. Devuelve un `EnvironmentReport` con un
`EnvironmentCheck` por comprobación.

### Requisitos

- Python 3.12+
- `doc_organize` instalado; `doc_organize[ai]` para `check_ai` (usa `httpx`)

La primera parte no usa la red. La segunda comprueba cuatro modelos de IA contra un proxy LiteLLM falso en memoria
(`httpx.MockTransport` pasado como `transport`): en uso real, sin `ai_endpoints` se comprueban los modelos de las
variables de entorno, o se pasan `AiEndpoint` con la URL y la clave del proxy.

## 2. Implementación de Referencia

```python
import asyncio
import json

import httpx

from doc_organize import AiEndpoint, check_environment


def fake_proxy(request: httpx.Request) -> httpx.Response:
    """Proxy LiteLLM falso en memoria: tres modelos con respuestas distintas."""
    if request.headers["Authorization"] != "Bearer sk-ejemplo":
        return httpx.Response(401, json={"error": "clave no válida"})
    body = json.loads(request.content)
    if request.url.path.endswith("/embeddings"):
        vectors = [[0.1, 0.2, 0.3, float(len(text))] for text in body["input"]]  # Distintos si el texto difiere
        return httpx.Response(200, json={"model": body["model"], "data": [{"index": i, "embedding": v} for i, v in enumerate(vectors)]})
    if body["model"] == "modelo-antiguo" and body["response_format"]["type"] == "json_schema":
        return httpx.Response(400, json={"error": "response_format json_schema no admitido"})
    served = "proveedor/modelo-grande" if body["model"] == "clasificador" else body["model"]
    return httpx.Response(200, json={"model": served, "choices": [{"message": {"content": '{"ok": true}'}}]})


async def main() -> None:
    # 1) Sin IA: no usa la red ni toca ningún proyecto. El estado depende de la máquina; los nombres, no.
    report = await check_environment(build_site=False)
    print("Comprobaciones:", [check.name for check in report.checks])
    print("Estados válidos:", all(check.status in ("ok", "warning", "error") for check in report.checks))
    python = next(check for check in report.checks if check.name == "python")
    print(f"python: {python.status}")

    # 2) Con IA contra el proxy falso: solo las comprobaciones `ai:*`
    url = "https://proxy.invalid"
    endpoints = [
        AiEndpoint(name="clasificacion", base_url=url, virtual_key="sk-ejemplo", model="clasificador"),
        AiEndpoint(name="descripcion", base_url=url, virtual_key="sk-ejemplo", model="modelo-antiguo"),
        AiEndpoint(name="taxonomia", base_url=url, virtual_key="sk-caducada", model="disenador"),
        AiEndpoint(name="dedup", base_url=url, virtual_key="sk-ejemplo", model="embed-dedup", kind="embedding"),
    ]
    report = await check_environment(build_site=False, check_ai=True, ai_endpoints=endpoints,
                                     transport=httpx.MockTransport(fake_proxy))
    for check in report.checks:
        if check.name.startswith("ai:"):
            print(f"{check.name}: {check.status} | {check.detail}")
            print(f"  model={check.model} served_model={check.served_model} dimension={check.dimension} remedy={check.remedy}")
    print("Informe sin errores:", report.ok)


if __name__ == "__main__":
    asyncio.run(main())
```

## 3. Explicación del Código

1. **Sin IA**: `check_environment(build_site=False)` hace las comprobaciones locales en un orden fijo (`python`,
   `docling`, `docling-models`, `extra:export`, `extra:site`, `gpu`, `libreoffice`, `extra:av`). Su estado depende de
   la máquina, así que el ejemplo solo imprime los nombres y el de `python`. Con `build_site=True` (por defecto) y
   Zensical instalado, construye además un sitio mínimo en una carpeta temporal
2. **Estados**: Cada `EnvironmentCheck` trae `status` (`ok`, `warning` o `error`), `detail` (sin rutas ni claves) y
   `remedy`. `report.ok` es `False` si alguna dio `error`; los `warning` no cuentan
3. **Con IA**: `check_ai=True` con `ai_endpoints` añade una comprobación `ai:<name>` por modelo, con texto sintético
   (nunca nada de un documento):
    - `clasificacion` responde con `json_schema` estricto: `ok`. Como la respuesta dice otro modelo, `served_model`
      lo recoge y `detail` lo añade («responde …»)
    - `descripcion` rechaza el esquema con HTTP 400 y responde con `json_object`: `warning`
    - `taxonomia` usa una clave que el proxy rechaza (401): `error`, sin la clave en el detalle
    - `dedup` es de embeddings (`kind="embedding"`): pide un vector a `/embeddings` y da su `dimension`. Al llamarse
      `dedup`, prueba además dos textos largos que solo difieren al final; aquí salen vectores distintos, así que no
      corta el texto y queda en `ok`
4. **`model`**: En las de IA es el alias que se pidió; `served_model`, el que dice la respuesta (`None` si no hubo
   respuesta válida)
5. **Resultado**: `report.ok` es `False` por el `error` de `taxonomia` (en otra máquina podría serlo también por una
   comprobación local)

## 4. Ejecución y Pruebas

```bash
$ python diagnostics_example.py
Comprobaciones: ['python', 'docling', 'docling-models', 'extra:export', 'extra:site', 'gpu', 'libreoffice', 'extra:av']
Estados válidos: True
python: ok
ai:clasificacion: ok | clasificador responde y admite `json_schema` estricto (responde proveedor/modelo-grande)
  model=clasificador served_model=proveedor/modelo-grande dimension=None remedy=None
ai:descripcion: warning | modelo-antiguo responde, pero no admite la salida `json_schema` estricta
  model=modelo-antiguo served_model=modelo-antiguo dimension=None remedy=2.0 usará `json_object` con validación; con un modelo que admita `json_schema` las respuestas son más fiables
ai:taxonomia: error | disenador: clave rechazada (HTTP 401)
  model=disenador served_model=None dimension=None remedy=Revisa la virtual key
ai:dedup: ok | embed-dedup da vectores de dimensión 4
  model=embed-dedup served_model=embed-dedup dimension=4 remedy=None
Informe sin errores: False
```

La lista de nombres y `python: ok` son estables en cualquier entorno compatible (Python 3.12+); las líneas `ai:*` no
dependen de la máquina porque las responde el proxy falso. Validación sintáctica:
`python -m py_compile diagnostics_example.py`.

## 5. Referencias Relacionadas

- [Referencia técnica: Diagnóstico del entorno](../api/diagnostics.md)
- [Documentación funcional: Diagnóstico del entorno](../functional/diagnostics.md)
- [Guía: Configurar el LiteLLM Proxy](../guides/litellm_proxy_setup.md)
- [Ejemplo: Deduplicar documentos](dedup-resolve.md)
