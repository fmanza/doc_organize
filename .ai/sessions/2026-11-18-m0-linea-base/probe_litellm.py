"""M0: sondea el LiteLLM Proxy real con **texto sintético** (plan único 2.0.0, M0; riesgos B7 y B8).

Responde, para un modelo del proxy:
1. ¿Responde con `response_format: json_object`? (lo que usa doc_organize hasta 1.7.0)
2. ¿Admite `json_schema` estricto con un `enum` de N slugs (150 por defecto, el límite de G1.1)? ¿Respeta el `enum`?
3. ¿Cachea el prefijo? Dos llamadas con el mismo prefijo largo: `usage.prompt_tokens_details.cached_tokens` (y la
   variante con `cache_control`, que necesitan los modelos de Anthropic).
4. Tokens y latencia de cada llamada.

La clave se lee de una variable de entorno (`--key-env`, por defecto `DOC_ORGANIZE_LITELLM_TAXONOMY_CLASSIFICATION_
VIRTUAL_KEY`) y **nunca se imprime**. No se envía ningún documento.

Uso:
    python probe_litellm.py --base-url https://litellm.ejemplo --model <alias> [--key-env VAR] [--enum-size 150]
"""

from __future__ import annotations

import argparse
import json
import os
import time

import httpx

FILLER = " ".join(
    f"Regla de clasificación sintética número {i}: los documentos de ejemplo van a su dominio." for i in range(250)
)


def _call(
    client: httpx.Client, model: str, messages: list[dict], response_format: dict
) -> tuple[dict | None, str | None, float]:
    start = time.perf_counter()
    try:
        response = client.post(
            "/chat/completions",
            json={"model": model, "messages": messages, "response_format": response_format, "temperature": 0},
        )
    except httpx.HTTPError as exc:
        return None, f"{type(exc).__name__}", time.perf_counter() - start
    elapsed = time.perf_counter() - start
    if response.status_code >= 400:
        return None, f"HTTP {response.status_code}: {response.text[:300]}", elapsed
    return response.json(), None, elapsed


def _usage(payload: dict | None) -> dict:
    usage = (payload or {}).get("usage") or {}
    details = usage.get("prompt_tokens_details") or {}
    return {
        "prompt": usage.get("prompt_tokens"),
        "completion": usage.get("completion_tokens"),
        "cached": details.get("cached_tokens", usage.get("cache_read_input_tokens")),
    }


def _content(payload: dict | None) -> str | None:
    try:
        return payload["choices"][0]["message"]["content"]  # type: ignore[index]
    except (KeyError, IndexError, TypeError):
        return None


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--key-env", default="DOC_ORGANIZE_LITELLM_TAXONOMY_CLASSIFICATION_VIRTUAL_KEY")
    parser.add_argument("--enum-size", type=int, default=150)
    args = parser.parse_args()
    key = os.environ.get(args.key_env)
    if not key:
        raise SystemExit(f"Define la variable {args.key_env} con la virtual key (no se imprime).")

    slugs = [f"dominio-{i:03d}" for i in range(args.enum_size)]
    question = [
        {"role": "system", "content": "Clasificas un texto en un dominio de la lista. Responde solo JSON."},
        {"role": "user", "content": f"Dominios: {', '.join(slugs)}\nTexto: el documento habla del dominio-042."},
    ]
    schema = {
        "type": "json_schema",
        "json_schema": {
            "name": "clasificacion",
            "strict": True,
            "schema": {
                "type": "object",
                "properties": {
                    "domain": {"type": ["string", "null"], "enum": [*slugs, None]},
                    "confidence": {"type": "number"},
                },
                "required": ["domain", "confidence"],
                "additionalProperties": False,
            },
        },
    }
    report: dict[str, object] = {"model": args.model, "enum_size": args.enum_size}
    with httpx.Client(base_url=args.base_url, headers={"Authorization": f"Bearer {key}"}, timeout=120) as client:
        payload, error, secs = _call(client, args.model, question, {"type": "json_object"})
        report["json_object"] = {
            "ok": error is None,
            "error": error,
            "seconds": round(secs, 2),
            "usage": _usage(payload),
            "content": _content(payload),
        }

        payload, error, secs = _call(client, args.model, question, schema)
        content = _content(payload)
        try:
            domain = json.loads(content or "").get("domain")
        except (ValueError, AttributeError):
            domain = "<no es JSON>"
        report["json_schema_strict"] = {
            "ok": error is None,
            "error": error,
            "seconds": round(secs, 2),
            "usage": _usage(payload),
            "domain": domain,
            "domain_in_enum": domain in slugs or domain is None,
        }

        for variant, system in (
            ("prefix_plain", {"role": "system", "content": FILLER}),
            (
                "prefix_cache_control",
                {
                    "role": "system",
                    "content": [{"type": "text", "text": FILLER, "cache_control": {"type": "ephemeral"}}],
                },
            ),
        ):
            runs = []
            for attempt in range(2):
                messages = [system, {"role": "user", "content": f'Responde {{"ok": true}} (intento {attempt}).'}]
                payload, error, secs = _call(client, args.model, messages, {"type": "json_object"})
                runs.append({"error": error, "seconds": round(secs, 2), "usage": _usage(payload)})
            report[variant] = runs
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
