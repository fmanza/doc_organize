"""Script de generación automática de documentación via APIs de IA.

Invocado por .github/workflows/doc_agents.yml.
Soporta Anthropic (Claude) y OpenAI (GPT-4o).
"""

from __future__ import annotations

import argparse
import os
import sys

from pathlib import Path

FUNCTIONAL_SYSTEM = """Eres un Senior Product Owner especializado en herramientas de DevOps y gestión de proyectos.
Generas documentación funcional clara para equipos no técnicos (jefes de proyecto, responsables de calidad).
Tu objetivo es explicar el valor de negocio, no los detalles de implementación."""

TECHNICAL_SYSTEM = """Eres un arquitecto de software senior especializado en Python y herramientas DevOps.
Generas documentación técnica precisa con diagramas Mermaid.js para equipos de desarrollo.
Usas terminología técnica exacta con tipos Python explícitos."""

FUNCTIONAL_PROMPT = """\
Analiza el siguiente módulo Python de doc_organize (extractor de timelogs de GitLab).
doc_organize extrae timelogs de GitLab vía REST API y genera reportes en Excel, CSV y JSON.
Sus usuarios son jefes de proyecto, responsables de calidad y equipos de datos.

MÓDULO: {module_name}
```python
{code}
```

Genera un documento Markdown con estas secciones en este orden exacto:

## Objetivo de negocio
Qué problema de negocio resuelve este módulo (1-2 párrafos, sin jerga técnica).

## Precondiciones
Lista de requisitos que deben cumplirse antes de usar este módulo.

## Flujo principal del usuario
Diagrama Mermaid sequenceDiagram: actor → componente → salida.
Omite nombres de clases internas. Usa etiquetas en español.

## Reglas de negocio críticas
Tabla: | Regla | Descripción | Impacto si se viola |

## Límites y exclusiones
Qué NO hace este módulo. Máximo 5 ítems.

Restricciones: NO expliques implementación interna. Responde SOLO con el Markdown."""

TECHNICAL_PROMPT = """\
Analiza el siguiente módulo Python de doc_organize (extractor de timelogs de GitLab).
doc_organize usa: python-gitlab, xlsxwriter, pandas, TOML config, Decimal para precisión.

MÓDULO: {module_name}
```python
{code}
```

Genera documentación técnica en Markdown con estas secciones:

## Responsabilidad del módulo
Una frase. Qué hace exactamente en el sistema.

## Diagrama
Elige el tipo más apropiado:
- sequenceDiagram → flujo I/O o request/response
- flowchart TD → lógica de decisión o pipeline
- classDiagram → jerarquía de clases relevante

Criterios: omite variables internas, rutas de implementación y puertos.
Incluye actores, operaciones de negocio y flujo de datos. Máximo 12 nodos.

## API pública
Tabla: | Función/Clase | Firma simplificada | Descripción | Retorna |
Solo lo exportado en __all__ o __init__.py.

## Contrato de entrada
Tabla: | Parámetro | Tipo | Descripción | Restricciones |

## Contrato de salida
Tipos, estructura de datos, casos especiales.

## Errores y casos especiales
Qué ocurre con entradas inválidas o condiciones de error.

Restricciones: SOLO lo exportado públicamente. Responde SOLO con el Markdown."""


def read_module(module_path: str) -> tuple[str, str]:
    path = Path(module_path)
    if not path.exists():
        print(f"ERROR: El módulo {module_path} no existe.", file=sys.stderr)
        sys.exit(1)
    return path.name, path.read_text(encoding="utf-8")


def generate_with_anthropic(module_name: str, code: str, doc_type: str) -> dict[str, str]:
    try:
        import anthropic
    except ImportError:
        print("ERROR: anthropic no instalado. Ejecuta: pip install anthropic", file=sys.stderr)
        sys.exit(1)

    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    results = {}

    if doc_type in ("functional", "both"):
        msg = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=2048,
            system=FUNCTIONAL_SYSTEM,
            messages=[{"role": "user", "content": FUNCTIONAL_PROMPT.format(module_name=module_name, code=code)}],
        )
        results["functional"] = msg.content[0].text

    if doc_type in ("technical", "both"):
        msg = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=2048,
            system=TECHNICAL_SYSTEM,
            messages=[{"role": "user", "content": TECHNICAL_PROMPT.format(module_name=module_name, code=code)}],
        )
        results["technical"] = msg.content[0].text

    return results


def generate_with_openai(module_name: str, code: str, doc_type: str) -> dict[str, str]:
    try:
        from openai import OpenAI
    except ImportError:
        print("ERROR: openai no instalado. Ejecuta: pip install openai", file=sys.stderr)
        sys.exit(1)

    client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
    results = {}

    if doc_type in ("functional", "both"):
        resp = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": FUNCTIONAL_SYSTEM},
                {"role": "user", "content": FUNCTIONAL_PROMPT.format(module_name=module_name, code=code)},
            ],
        )
        results["functional"] = resp.choices[0].message.content or ""

    if doc_type in ("technical", "both"):
        resp = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": TECHNICAL_SYSTEM},
                {"role": "user", "content": TECHNICAL_PROMPT.format(module_name=module_name, code=code)},
            ],
        )
        results["technical"] = resp.choices[0].message.content or ""

    return results


def write_output(results: dict[str, str], output_dir: str, module_name: str, dry_run: bool) -> None:
    stem = Path(module_name).stem.replace("_", "-")
    out_path = Path(output_dir)

    for doc_type, content in results.items():
        suffix = "" if doc_type == "functional" else f"-{doc_type}"
        file_path = out_path / f"{stem}{suffix}.md"

        if dry_run:
            print(f"\n{'=' * 60}")
            print(f"[DRY RUN] {file_path}")
            print("=" * 60)
            print(content[:500] + "..." if len(content) > 500 else content)
        else:
            out_path.mkdir(parents=True, exist_ok=True)
            file_path.write_text(content, encoding="utf-8")
            print(f"Generado: {file_path}")
            print("  Entrada mkdocs.yml sugerida:")
            title = stem.replace("-", " ").title()
            rel = str(file_path).replace("\\", "/").replace("docs/", "")
            print(f"      - {title}: {rel}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Genera documentación de módulos doc_organize via IA")
    parser.add_argument("--provider", choices=["anthropic", "openai"], required=True)
    parser.add_argument("--module", required=True, help="Ruta al módulo Python")
    parser.add_argument("--doc-type", choices=["functional", "technical", "both"], default="both")
    parser.add_argument("--output-dir", default="docs/functional")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    module_name, code = read_module(args.module)
    print(f"Módulo: {args.module} ({len(code)} chars)")
    print(f"Tipo: {args.doc_type} | Proveedor: {args.provider} | Destino: {args.output_dir}")

    if args.provider == "anthropic":
        results = generate_with_anthropic(module_name, code, args.doc_type)
    else:
        results = generate_with_openai(module_name, code, args.doc_type)

    write_output(results, args.output_dir, module_name, args.dry_run)
    print("Completado.")


if __name__ == "__main__":
    main()
