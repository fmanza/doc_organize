# Ejemplo: Versiones de un Documento

**Objetivo**: Demostrar cómo `detect_document_versions` agrupa las versiones de un mismo documento, cómo la construcción
del contexto marca o filtra las antiguas y cómo una persona decide cuál es la vigente.

## 1. Contexto del Ejemplo

`Manual_Calidad_v1.9.docx` y `Manual_Calidad_v1.10.docx` son el mismo documento en dos versiones. Si se tratan como dos
documentos, la versión antigua se clasifica, se publica y va a la IA como si estuviera vigente. La librería las detecta
de forma conservadora (solo un marcador explícito de versión en el nombre) y propone como vigente la más alta, pero la
más alta no siempre es la vigente (un borrador sin aprobar): eso lo decide una persona con una decisión
`set_current_version`.

El ejemplo detecta grupos a partir de nombres y luego construye el contexto sin Docling (original, `.md` y `.json`
escritos a mano, como en [Construir el contexto](context-build.md)), sin manifiesto y sin IA.

### Requisitos

- Python 3.11+
- `doc_organize[context]` instalado: aunque el ejemplo no lee ningún manifiesto, el paquete `doc_organize.context`
  (de donde salen `ContextBuilder` y `detect_document_versions`) importa PyYAML

Los ficheros se crean en un directorio temporal; no se llama a ningún servicio externo.

## 2. Implementación de Referencia

```python
import asyncio
import json
import tempfile
from pathlib import Path

from doc_organize import (
    ClassificationDecision,
    ClassificationDecisionStore,
    ContextBuilder,
    ConversionResult,
    Project,
    detect_document_versions,
    review_queue,
)

FILES = [
    "calidad/Manual_Calidad_v1.2.docx",
    "calidad/Manual_Calidad_v1.9.docx",
    "calidad/Manual_Calidad_v1.10.docx",  # borrador sin aprobar: la versión más alta no siempre es la vigente
    "calidad/Acta_2023.docx",  # una fecha no es una versión
    "calidad/Acta_2024.docx",
    "calidad/ISO_9001_v2015.pdf",  # un «número de versión» con forma de año tampoco
    "calidad/Plan_rev2.pdf",
    "calidad/Plan_rev3.docx",  # otra extensión: otro grupo, salvo across_extensions=True
    "compras/Manual_Calidad_v2.docx",  # otra carpeta: otro documento
]


def converted(root: Path, relative: str) -> ConversionResult:
    """El original en `origen/` y su `.md` + `.json` en `Conversión/`, como los deja `DocumentConverter`."""
    source = root / "origen" / relative
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text(relative, encoding="utf-8")
    name = relative.replace("/", "_")
    markdown, json_path = root / "Conversión" / f"{name}.md", root / "Conversión" / f"{name}.json"
    markdown.parent.mkdir(parents=True, exist_ok=True)
    markdown.write_text(f"# {source.stem}\n", encoding="utf-8")
    json_path.write_text(json.dumps({"title": source.stem, "chunks": [{"text": source.stem}]}), encoding="utf-8")
    return ConversionResult(source_path=str(source), markdown_path=str(markdown), json_path=str(json_path), success=True)


def show_groups(context) -> None:
    for group in context.version_groups:
        print(f"  {group.key}: versiones={group.versions} vigente={Path(group.current).name} confirmada={group.confirmed}")


async def main() -> None:
    # 1) Detección: solo nombres, no hace falta leer los ficheros
    for across in (False, True):
        print(f"detect_document_versions(across_extensions={across}):")
        for group in detect_document_versions([f"/entrada/{path}" for path in FILES], across_extensions=across):
            print(f"  {group.key}: {[(m.version, m.is_current) for m in group.members]} → vigente {Path(group.current).name}")

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp).resolve()
        roots = [str(root / "origen")]
        project = Project(name="Demo", root_path=str(root), created_at="2026-01-01T00:00:00+00:00")
        documents = [converted(root, path) for path in FILES]
        builder = ContextBuilder()

        # 2) Construcción con `current_only`: las versiones antiguas no se clasifican ni se publican
        context = await builder.build(project, documents, scan_roots=roots, versions="current_only")
        print(f"\nversions={context.versions_mode}: {len(context.version_groups)} grupos")
        show_groups(context)
        print(f"  Superadas: {sorted(Path(p).name for p in context.superseded_documents)}")
        for item in review_queue(context, roots=roots):
            if item.reason == "unconfirmed_version":
                print(f"  Cola: [{item.priority}] {item.reason} {item.document_key}: {item.detail}")

        # 3) Una persona decide la vigente (también sin manifiesto: no depende del catálogo)
        store = ClassificationDecisionStore(project.root_path)
        await store.add(ClassificationDecision(document_key="calidad/Manual_Calidad_v1.9.docx", action="set_current_version",
                                               author="ana", reason="La 1.10 aún no está aprobada"))
        await store.add(ClassificationDecision(document_key="calidad/Plan_rev3.docx", action="set_current_version", author="ana"))
        await store.add(ClassificationDecision(document_key="calidad/Acta_2024.docx", action="set_current_version", author="ana"))
        context = await builder.build(project, documents, scan_roots=roots, versions="mark")
        print(f"\nversions={context.versions_mode}, decisiones aplicadas={context.decisions_applied}")
        show_groups(context)
        print(f"  Desfasadas: {[(d.document_key, d.reason) for d in context.stale_decisions]}")
        for domain in context.domains:
            for document in sorted(domain.documents, key=lambda d: Path(d.source_path).name):
                if document.version_group:
                    print(f"  {Path(document.source_path).name}: versión={document.version} vigente={document.is_current}")
        print(f"  Pendientes en la cola: {[i.document_key for i in review_queue(context, roots=roots) if i.reason == 'unconfirmed_version']}")
        context = await builder.build(project, documents, scan_roots=roots, versions="current_only")
        print(f"  Con current_only, superadas: {sorted(Path(p).name for p in context.superseded_documents)}")

        # 4) Entre formatos (2.5.0): Plan_rev2.pdf y Plan_rev3.docx forman grupo; la rev3 también existe en PDF
        documents.append(converted(root, "calidad/Plan_rev3.pdf"))
        context = await builder.build(project, documents, scan_roots=roots, versions="current_only", version_across_extensions=True)
        print(f"\nversion_across_extensions={context.versions_across_extensions}, decisiones aplicadas={context.decisions_applied}")
        show_groups(context)
        print(f"  Superadas: {sorted(Path(p).name for p in context.superseded_documents)}")
        print(f"  Desfasadas: {[(d.document_key, d.reason) for d in context.stale_decisions]}")
        planes = sorted(Path(d.source_path).name for domain in context.domains for d in domain.documents if "Plan" in d.source_path)
        print(f"  En el contexto: {planes}")


if __name__ == "__main__":
    asyncio.run(main())
```

## 3. Explicación del Código

1. **Detección conservadora**: solo cuenta un marcador explícito (`v1.2`, `rev2`, `ver 3`, `ed. 2`...). `Acta_2023` y
   `Acta_2024` son documentos distintos (una fecha no es una versión) e `ISO_9001_v2015` no tiene versión (el número
   tiene forma de año). El manual de `compras/` está en otra carpeta: es otro documento
2. **Orden numérico**: `1.10` es mayor que `1.9`, así que la vigente propuesta es `Manual_Calidad_v1.10.docx`
   (`VersionGroup.current`, `VersionMember.is_current`). La clave del grupo es la carpeta y el nombre sin el marcador,
   normalizados, más la extensión
3. **Extensiones**: `Plan_rev2.pdf` y `Plan_rev3.docx` solo se agrupan con `across_extensions=True`; en la
   construcción, con `version_across_extensions=True` (2.5.0, paso 7)
4. **`versions="current_only"`**: solo la vigente se clasifica y se publica; las demás quedan en
   `Context.superseded_documents`. En `Context.version_groups` la clave del grupo es relativa a la raíz de escaneo y el
   grupo sale `confirmada=False`, así que la cola de revisión lo pide (`unconfirmed_version`, prioridad 5)
5. **La vigente la decide una persona**: `set_current_version` sobre `Manual_Calidad_v1.9.docx` la hace vigente; el
   grupo pasa a `confirmada=True` y sale de la cola. Se aplica sin manifiesto (no depende del catálogo). Sobre un
   documento que no está en ningún grupo (`Acta_2024.docx`, y `Plan_rev3.docx` por la extensión) la decisión queda en
   `stale_decisions` con `not_versioned`
6. **`versions="mark"`**: todas las versiones se clasifican y cada documento del grupo lleva `version`,
   `version_group` e `is_current`. Con `current_only`, tras la decisión, la superada es la `1.10` y no la `1.9`
7. **Entre formatos (2.5.0)**: con `version_across_extensions=True` el plan forma grupo aunque cambie el formato, así
   que la decisión sobre `Plan_rev3.docx` ya se aplica y deja de estar desfasada. La `rev3` existe también en PDF: la
   misma versión en varios formatos es vigente entera, así que con `current_only` solo sale `Plan_rev2.pdf` y los dos
   formatos de la `rev3` siguen en el contexto

## 4. Ejecución y Pruebas

```bash
$ python versions_example.py
detect_document_versions(across_extensions=False):
  /entrada/calidad/manual calidad.docx: [('1.2', False), ('1.9', False), ('1.10', True)] → vigente Manual_Calidad_v1.10.docx
detect_document_versions(across_extensions=True):
  /entrada/calidad/manual calidad: [('1.2', False), ('1.9', False), ('1.10', True)] → vigente Manual_Calidad_v1.10.docx
  /entrada/calidad/plan: [('2', False), ('3', True)] → vigente Plan_rev3.docx

versions=current_only: 1 grupos
  calidad/manual calidad.docx: versiones=['1.2', '1.9', '1.10'] vigente=Manual_Calidad_v1.10.docx confirmada=False
  Superadas: ['Manual_Calidad_v1.2.docx', 'Manual_Calidad_v1.9.docx']
  Cola: [5] unconfirmed_version calidad/Manual_Calidad_v1.10.docx: Versiones 1.2, 1.9, 1.10; vigente propuesta: la más alta

versions=mark, decisiones aplicadas=1
  calidad/manual calidad.docx: versiones=['1.2', '1.9', '1.10'] vigente=Manual_Calidad_v1.9.docx confirmada=True
  Desfasadas: [('calidad/Plan_rev3.docx', 'not_versioned'), ('calidad/Acta_2024.docx', 'not_versioned')]
  Manual_Calidad_v1.10.docx: versión=1.10 vigente=False
  Manual_Calidad_v1.2.docx: versión=1.2 vigente=False
  Manual_Calidad_v1.9.docx: versión=1.9 vigente=True
  Pendientes en la cola: []
  Con current_only, superadas: ['Manual_Calidad_v1.10.docx', 'Manual_Calidad_v1.2.docx']

version_across_extensions=True, decisiones aplicadas=2
  calidad/manual calidad: versiones=['1.2', '1.9', '1.10'] vigente=Manual_Calidad_v1.9.docx confirmada=True
  calidad/plan: versiones=['2', '3', '3'] vigente=Plan_rev3.docx confirmada=True
  Superadas: ['Manual_Calidad_v1.10.docx', 'Manual_Calidad_v1.2.docx', 'Plan_rev2.pdf']
  Desfasadas: [('calidad/Acta_2024.docx', 'not_versioned')]
  En el contexto: ['Plan_rev3.docx', 'Plan_rev3.pdf']
```

La salida es determinista: el primer bloque usa rutas ficticias (`/entrada/...`) y el resto no imprime rutas
temporales. Validación sintáctica: `python -m py_compile versions_example.py`.

## 5. Referencias Relacionadas

- [Referencia técnica: Versiones de un documento](../api/versions.md)
- [Documentación funcional: Contexto](../functional/context.md)
- [Documentación funcional: Revisión y calidad de la clasificación](../functional/revision_clasificacion.md)
- [Ejemplo: Decisiones de personas y cola de revisión](decisions-review.md)
- [Ejemplo: Construir el contexto](context-build.md)
