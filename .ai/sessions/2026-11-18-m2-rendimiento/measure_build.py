"""M2: tiempo de construcción del contexto antes y después de B (lectura única y IA en paralelo).

Construye el contexto de un corpus ya convertido **en una carpeta temporal** (el proyecto real no se toca: solo se leen
sus `.json` y sus originales). Dos mediciones:

- **Sin IA**, con una latencia simulada de carpeta de red en cada lectura de un `.json` (`--json-latency`, segundos;
  se añade en el hilo que lee, como haría SMB).
- **Con IA**, con un cliente falso que tarda `--ai-latency` segundos por llamada, con `ai_concurrency` 1 y 4 (en la
  versión de antes, sin el parámetro, solo 1).

La versión que se mide es la de `doc_organize` importable (usar `PYTHONPATH=<otro árbol>/src` para medir otra).

Uso:
    python measure_build.py --project-root <raíz con context.json> --template plantilla.md \
        [--path-map /mnt/documentation=C:/Desarrollo/documentation] [--json-latency 0.02] [--ai-latency 0.5] --label antes
"""

from __future__ import annotations

import argparse
import asyncio
import inspect
import json
import pathlib
import tempfile
import time

from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import doc_organize

from doc_organize import ContextBuilder, ContextRegistry, Project, parse_taxonomy_template
from doc_organize.core.models import ConversionResult, TaxonomyClassificationResult


class _FakeAI:
    config = SimpleNamespace(model="falso")

    def __init__(self, latency: float, domain: str, material: str) -> None:
        self.latency, self.domain, self.material, self.calls = latency, domain, material, 0

    async def classify(self, **_: object) -> TaxonomyClassificationResult:
        self.calls += 1
        await asyncio.sleep(self.latency)
        return TaxonomyClassificationResult(domain=self.domain, domain_confidence=0.7, material_type=self.material, material_type_confidence=0.6)


def _slow_json_reads(latency: float) -> None:
    original = pathlib.Path.read_text

    def read_text(self: Path, *args: object, **kwargs: object) -> str:
        if self.suffix == ".json":
            time.sleep(latency)
        return original(self, *args, **kwargs)  # type: ignore[arg-type]

    pathlib.Path.read_text = read_text  # type: ignore[method-assign]


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--template", type=Path, required=True)
    parser.add_argument("--path-map", default=None)
    parser.add_argument("--json-latency", type=float, default=0.02)
    parser.add_argument("--ai-latency", type=float, default=0.5)
    parser.add_argument("--label", required=True)
    args = parser.parse_args()
    prefix, local = args.path_map.split("=", 1) if args.path_map else ("", "")

    def fix(path: str | None) -> str | None:
        return local + path[len(prefix) :] if path and prefix and path.startswith(prefix) else path

    real = Project(name=args.project_root.name, root_path=str(args.project_root), created_at=datetime.now(UTC).isoformat())
    context = await ContextRegistry().load_context(real)
    documents = [
        ConversionResult(source_path=fix(d.source_path) or "", markdown_path=fix(d.markdown_path), json_path=fix(d.json_path), success=True)
        for domain in context.domains
        for d in domain.documents
    ]
    manifest = parse_taxonomy_template(args.template.read_text(encoding="utf-8"))
    folder = manifest.folder_axis.entries[0].slug
    material = manifest.subfolder_axis.entries[0].slug
    _slow_json_reads(args.json_latency)
    has_concurrency = "ai_concurrency" in inspect.signature(ContextBuilder.__init__).parameters
    report: dict[str, object] = {"label": args.label, "doc_organize": doc_organize.__version__, "documents": len(documents)}

    with tempfile.TemporaryDirectory() as tmp:
        project = Project(name="medida", root_path=tmp, created_at=datetime.now(UTC).isoformat())
        start = time.perf_counter()
        await ContextBuilder().build(project, documents, taxonomy_manifest=manifest)
        report["sin_ia_s"] = round(time.perf_counter() - start, 2)

        for concurrency in (1, 4) if has_concurrency else (1,):
            client = _FakeAI(args.ai_latency, folder, material)
            builder = ContextBuilder(ai_concurrency=concurrency) if has_concurrency else ContextBuilder()
            start = time.perf_counter()
            await builder.build(project, documents, taxonomy_manifest=manifest, ai_classification_enabled=True, taxonomy_classification_client=client)
            report[f"con_ia_c{concurrency}_s"] = round(time.perf_counter() - start, 2)
            report["llamadas_ia"] = client.calls
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())
