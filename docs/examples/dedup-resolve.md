# Ejemplo: Deduplicar Documentos

**Objetivo**: Demostrar cómo detectar y resolver duplicados, por fichero y por contenido.

## 1. Contexto del Ejemplo

El `DeduplicationManager` agrupa documentos por hash exacto (duplicados reales) y por nombre base (conflictos de versión), luego mueve los descartados a una carpeta separada.

Desde 2.2.0, `ContentDuplicateFinder` añade una segunda vuelta sobre el texto ya convertido: el mismo contenido en
ficheros distintos (sin IA) y contenido parecido (embeddings de la tarea de IA `dedup`). Ver
[Duplicados por contenido](#duplicados-por-contenido-220).

### Requisitos

- Python 3.11+
- `doc_organize` instalado (`doc_organize[ai]` para la pasada semántica, que usa `httpx`)
- Documentos escaneados (con SHA-256 calculado)

Los ejemplos crean sus ficheros en un directorio temporal y no llaman a ningún servicio externo.

## 2. Implementación de Referencia

```python
import asyncio
import os
import tempfile
from pathlib import Path

from doc_organize.dedup import DeduplicationManager
from doc_organize.scanner import DocumentScanner


def write(path: Path, content: bytes, mtime: float) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    os.utime(path, (mtime, mtime))  # Fecha fija: el canónico es el más antiguo


async def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp).resolve()  # Ruta real, como la que devuelve el escáner
        source = base / "repo"
        duplicates_dir = base / "duplicados"
        write(source / "doc1.pdf", b"contenido A", 1_700_000_000)
        write(source / "backup" / "doc1.pdf", b"contenido A", 1_700_100_000)  # Mismo hash: duplicado exacto
        write(source / "informe.pdf", b"contenido B", 1_700_000_000)
        write(source / "informe_v2.pdf", b"contenido B2", 1_700_200_000)  # Mismo nombre base: conflicto de versión

        async with DocumentScanner() as scanner:
            docs = (await scanner.scan_folders([str(source)])).documents

        manager = DeduplicationManager()

        # Fase 1: detectar (síncrono, solo compara metadatos)
        groups = manager.find_duplicates(docs)
        print(f"Grupos detectados: {len(groups)}")
        for group in groups:
            canonical = Path(group.canonical_doc.full_path).relative_to(source).as_posix()
            discarded = [Path(d.full_path).relative_to(source).as_posix() for d in group.duplicates]
            print(f"  {group.reason.value}: conserva {canonical}, descarta {discarded}")

        # Fase 2: resolver (async, mueve los descartados replicando su ruta relativa a `source`)
        report = await manager.resolve_duplicates(groups, duplicates_dir, relative_to=source)
        print(f"Duplicados exactos movidos: {report.total_exact_duplicates}")
        print(f"Conflictos de versión movidos: {report.total_version_conflicts}")
        print(f"Fallidos: {report.failed_paths}")
        print(f"Informe: {Path(report.audit_json_path).name}")
        print(f"En duplicados: {sorted(p.relative_to(duplicates_dir).as_posix() for p in duplicates_dir.rglob('*') if p.is_file())}")


if __name__ == "__main__":
    asyncio.run(main())
```

### Similitud aproximada de nombre (opcional)

Pasando `fuzzy_threshold` (0-100), `find_duplicates()` añade una tercera pasada sobre los
documentos que no quedaron agrupados por hash ni por versión, comparando `display_name` con
RapidFuzz:

```python
from doc_organize.core.models import DuplicateReason

groups = manager.find_duplicates(docs, fuzzy_threshold=90)

for group in groups:
    if group.reason == DuplicateReason.FUZZY_NAME_MATCH:
        print(f"Posibles duplicados por nombre: {[d.display_name for d in group.duplicates]}")
        # canonical_doc es solo una propuesta -- nunca se resuelve sin
        # confirmación explícita del usuario (la pide el consumidor).
```

Con `informe_ventas.pdf` e `informe-ventas.pdf` (hashes distintos), sale un grupo `FUZZY_NAME_MATCH`.

**Importante**: `ScanCommand.deduplicate_streaming()` (la resolución masiva) llama a `find_duplicates()` sin
`fuzzy_threshold`, así que nunca mueve grupos `FUZZY_NAME_MATCH`: solo se resuelven pasándolos a
`resolve_duplicates()`/`move_group()` después de que el usuario elija qué conservar (`user_choice`) en cada grupo.

### Duplicados por contenido (2.2.0)

`ContentDuplicateFinder` compara el Markdown de documentos **ya convertidos** (`ContentDocument` = original +
`ConversionResult`). En el ejemplo, la pasada semántica usa un `LlmClient` real sobre un proxy LiteLLM falso en
memoria (`httpx.MockTransport`) que devuelve vectores fijos: en uso real, `LlmClient(settings_from_env())` con un
modelo de embeddings propio para la tarea `dedup` (`DOC_ORGANIZE_LITELLM_MODEL_DEDUP`).

```python
import asyncio
import hashlib
import json
import math
import tempfile
from pathlib import Path

import httpx

from doc_organize import ContentDocument, ContentDuplicateFinder, DeduplicationManager, LlmClient
from doc_organize.core.models import AiSettings, ConversionResult, DocumentMetadata, TaskSettings

PROCEDURE = "Procedimiento de alta de proveedores con los pasos de revisión y aprobación del contrato. " * 4
POLICY = "La política de viajes fija quién aprueba cada gasto, los límites por categoría y cómo se justifican. " * 3


def converted(root: Path, name: str, markdown: str, modified: float) -> ContentDocument:
    """Un original en `origen/` y su conversión en `Conversión/`, como los deja `DocumentConverter`."""
    source = root / "origen" / name
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_bytes(name.encode())  # Ficheros distintos: hashes distintos
    md = root / "Conversión" / f"{Path(name).stem}_{Path(name).suffix[1:]}.md"
    md.parent.mkdir(parents=True, exist_ok=True)
    md.write_text(markdown, encoding="utf-8")
    metadata = DocumentMetadata(
        full_path=str(source), display_name=name, extension=Path(name).suffix[1:], size_bytes=len(name),
        modified_time=modified, sha256_hash=hashlib.sha256(name.encode()).hexdigest(),
    )
    conversion = ConversionResult(source_path=str(source), markdown_path=str(md), json_path=None, success=True)
    return ContentDocument(metadata=metadata, conversion=conversion)


def fake_proxy(request: httpx.Request) -> httpx.Response:
    """Proxy LiteLLM falso para `/embeddings`: el ángulo del vector depende de una palabra del bloque."""
    body = json.loads(request.content)
    angles = {"borrador": 20, "viajes": 0, "proveedores": 90}  # cos 20° ≈ 0,94: «parecidos» con el umbral 0,90

    def vector(text: str) -> list[float]:
        degrees = next((angle for word, angle in angles.items() if word in text.lower()), 45)
        return [math.cos(math.radians(degrees)), math.sin(math.radians(degrees))]

    data = [{"index": i, "embedding": vector(text)} for i, text in enumerate(body["input"])]
    return httpx.Response(200, json={"data": data})


async def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp).resolve()
        documents = [
            converted(root, "alta.docx", PROCEDURE, 1.0),
            converted(root, "alta.pdf", "## " + PROCEDURE.upper().replace(". ", ".\n\n"), 2.0),  # Mismo texto, otro formato
            converted(root, "viajes.docx", POLICY, 1.0),
            converted(root, "viajes_borrador.docx", "Borrador. " + POLICY.replace("cada gasto", "los gastos"), 3.0),
            converted(root, "portada.pdf", "Portada", 1.0),  # Menos de 30 palabras: no se compara
        ]

        # 1) Solo «mismo contenido»: sin IA
        report = await ContentDuplicateFinder(root).find(documents)
        print(f"Sin IA -> grupos: {[g.reason.value for g in report.groups]}, comparados: {report.compared}, "
              f"sin comparar: {[Path(p).name for p in report.not_compared]}")

        # 2) También «contenido parecido»: tarea `dedup` con modelo propio (aquí, un proxy falso en memoria)
        settings = AiSettings(base_url="https://proxy.invalid", virtual_key="sk-ejemplo",
                              tasks={"dedup": TaskSettings(model="doc-organize-dedup")})
        async with LlmClient(settings, transport=httpx.MockTransport(fake_proxy)) as llm:
            report = await ContentDuplicateFinder(root, llm, semantic_threshold=0.90).find(documents, semantic=True)
        for group in report.groups:
            names = [d.display_name for d in [group.canonical_doc, *group.duplicates]]
            print(f"  {group.reason.value}: {names} similarity={group.similarity} "
                  f"lexical={group.lexical_similarity} contained={group.contained}")
        print(f"Vectores pedidos: {report.embedded}, reutilizados: {report.reused}")

        # 3) Resolver los grupos que una persona confirma; la conversión del descartado se mueve con él
        conversions = {d.metadata.full_path: d.conversion for d in documents}
        duplicates_dir = root / "duplicados"
        result = await DeduplicationManager().resolve_duplicates(
            report.groups, duplicates_dir, relative_to=root / "origen",
            conversions=conversions, conversion_dir=root / "Conversión",
        )
        print(f"Movidos: {result.total_version_conflicts}, fallidos: {result.failed_paths}")
        print(sorted(p.relative_to(duplicates_dir).as_posix() for p in duplicates_dir.rglob("*.*") if "DEDUP" not in p.name))


if __name__ == "__main__":
    asyncio.run(main())
```

## 3. Explicación del Código

1. **Detección** (síncrono): `find_duplicates()` agrupa por hash (`exact_duplicate`) y, entre los de hash único, por nombre base + extensión (`version_conflict`: sufijos `_v2`, `final`, `draft`)
2. **Selección**: Se elige canónico = documento más antiguo (`modified_time`); `user_choice` lo sustituye
3. **Resolución** (async): `resolve_duplicates()` mueve los no canónicos a `duplicates_dir` (`mode="copy"` copia y `"report_only"` no toca nada); un fichero que no se puede mover va a `failed_paths` sin abortar el resto
4. **Estructura**: Se replica la ruta del original bajo `duplicates_dir`: la relativa a `relative_to` o, sin él, la absoluta
5. **Auditoría**: Se escribe `DEDUP_REPORT.json` (último run) y se añade una línea a `DEDUP_HISTORY.jsonl`
6. **Por contenido**: «Mismo contenido» (`same_content`) compara el texto normalizado sin formato, mayúsculas ni puntuación, sin IA. «Contenido parecido» (`semantic_content_match`, `semantic=True`) exige `llm` con modelo propio para `dedup` (si no, `AiConfigurationError`) y da `similarity`, `lexical_similarity` y `contained`
7. **Sin comparar**: Los documentos sin conversión o con menos de 30 palabras (`min_words`) van a `not_compared`; los de mismo hash cuentan una vez
8. **Resolver por contenido**: Los grupos por contenido no se resuelven solos: una persona los confirma. Con `conversions` y `conversion_dir`, en modo `move` la conversión del descartado se mueve con él a `duplicados/Conversión/`; en modo `copy`, `exclude_from_context()` guarda una decisión `exclude` por descartado. Cuentan en `total_version_conflicts`

## 4. Ejecución y Pruebas

```bash
$ python dedup_example.py
Grupos detectados: 2
  exact_duplicate: conserva doc1.pdf, descarta ['backup/doc1.pdf']
  version_conflict: conserva informe.pdf, descarta ['informe_v2.pdf']
Duplicados exactos movidos: 1
Conflictos de versión movidos: 1
Fallidos: []
Informe: DEDUP_REPORT.json
En duplicados: ['DEDUP_HISTORY.jsonl', 'DEDUP_REPORT.json', 'backup/doc1.pdf', 'informe_v2.pdf']
```

```bash
$ python content_dedup_example.py
Sin IA -> grupos: ['same_content'], comparados: 4, sin comparar: ['portada.pdf']
  same_content: ['alta.docx', 'alta.pdf'] similarity=1.0 lexical=1.0 contained=False
  semantic_content_match: ['viajes.docx', 'viajes_borrador.docx'] similarity=0.9397 lexical=0.4583 contained=False
Vectores pedidos: 2, reutilizados: 0
Movidos: 2, fallidos: []
['Conversión/alta_pdf.md', 'Conversión/viajes_borrador_docx.md', 'alta.pdf', 'viajes_borrador.docx']
```

`similarity=0.9397` es el coseno de 20° entre los vectores falsos; `lexical=0.4583`, la similitud de texto real entre
las dos versiones de la política. Validación sintáctica: `python -m py_compile dedup_example.py content_dedup_example.py`.

## 5. Referencias Relacionadas

- [Documentación funcional: Deduplicación](../functional/dedup.md)
- [Referencia técnica: Deduplicación](../api/dedup.md)
- [Guía: Duplicados por contenido](../guides/duplicados_por_contenido.md)
- [Ejemplo: Escanear documentos](scanner-scan.md)
- [Ejemplo: Convertir documentos a Markdown](converter-convert.md)
