# Ejemplo: Decisiones de Personas y Cola de Revisión

**Objetivo**: Demostrar cómo una persona corrige la clasificación con `ClassificationDecisionStore`, cómo se aplican sus
decisiones en la siguiente construcción del contexto y qué pasa cuando una decisión queda obsoleta.

## 1. Contexto del Ejemplo

Las reglas dejan documentos sin clasificar o en el dominio equivocado. `review_queue` dice qué conviene mirar y por qué;
la persona lo resuelve con una `ClassificationDecision` (fijar un eje, confirmar o excluir) que se guarda en
`<raíz>/.doc_organize/decisions.json` y que `ContextBuilder.build` vuelve a aplicar en cada construcción, después de las
reglas, sin que las reglas ni la IA la cambien.

Una decisión va atada a la versión del original con su huella (`source_sha256`): si el original cambia, deja de
aplicarse y vuelve a la cola para que alguien la revise. El ejemplo construye el contexto sin Docling (escribe a mano el
original, su `.md` y su `.json`, como en [Construir el contexto](context-build.md)) y solo con reglas, sin IA.

### Requisitos

- Python 3.11+
- `doc_organize[context]` instalado (PyYAML, para leer el manifiesto)

Los ficheros se crean en un directorio temporal; no se llama a ningún servicio externo.

## 2. Implementación de Referencia

```python
import asyncio
import hashlib
import json
import tempfile
from pathlib import Path

from doc_organize import (
    ClassificationDecision,
    ClassificationDecisionStore,
    ContextBuilder,
    ConversionResult,
    Project,
    parse_taxonomy_template,
    review_queue,
)

MANIFEST = """\
---
schema: 2
title: Calidad mínima
axes:
- key: domains
  name: Dominios
  organizes: folder
  entries:
  - slug: gestion-proveedores
    name: Gestión de Proveedores
    keywords: [proveedor, homologacion]
  - slug: mejora-continua
    name: Mejora Continua
    keywords: [no conformidad, accion correctiva]
- key: material_types
  name: Tipos de material
  organizes: subfolder
  entries:
  - slug: procedimiento
    name: Procedimiento
  - slug: registro
    name: Registro
---
"""


def converted(root: Path, relative: str, title: str, text: str) -> ConversionResult:
    """El original en `origen/` y su `.md` + `.json` en `Conversión/`, con la huella del original (`source_sha256`)."""
    source = root / "origen" / relative
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text(text, encoding="utf-8")
    stem = Path(relative).stem
    markdown, json_path = root / "Conversión" / f"{stem}.md", root / "Conversión" / f"{stem}.json"
    markdown.parent.mkdir(parents=True, exist_ok=True)
    markdown.write_text(f"# {title}\n\n{text}\n", encoding="utf-8")
    json_path.write_text(json.dumps({"title": title, "chunks": [{"text": text}]}, ensure_ascii=False), encoding="utf-8")
    sha = hashlib.sha256(source.read_bytes()).hexdigest()
    return ConversionResult(source_path=str(source), markdown_path=str(markdown), json_path=str(json_path), success=True, source_sha256=sha)


def show(context, roots) -> None:
    for domain in context.domains:
        for document in domain.documents:
            print(f"  {domain.slug:<20} {Path(document.source_path).name:<15} material={document.material_type:<15} por={document.classified_by}")
    print(f"  aplicadas={context.decisions_applied} excluidos={[Path(p).name for p in context.excluded_documents]}")
    print(f"  desfasadas={[(d.document_key, d.reason) for d in context.stale_decisions]}")
    print(f"  huérfanas={[(d.document_key, d.reason) for d in context.orphan_decisions]}")
    print("  Cola de revisión:")
    for item in review_queue(context, roots=roots):
        print(f"    [{item.priority}] {item.reason:<16} {item.document_key:<22} eje={item.axis} valor={item.value} detalle={item.detail}")


async def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp).resolve()
        roots = [str(root / "origen")]  # raíz de escaneo: las claves de las decisiones son relativas a ella
        project = Project(name="Demo", root_path=str(root), created_at="2026-01-01T00:00:00+00:00")
        manifest = parse_taxonomy_template(MANIFEST)
        documents = {
            "alta": converted(root, "compras/alta.txt", "Procedimiento de homologación de proveedores",
                              "Procedimiento para dar de alta a un proveedor y revisar su homologacion anual."),
            "auditoria": converted(root, "calidad/auditoria.txt", "Registro de la auditoría interna",
                                   "Registro de los hallazgos de la auditoria interna de 2026."),
            "menu": converted(root, "varios/menu.txt", "Menú de la cafetería", "Lunes: lentejas. Martes: paella."),
        }
        builder = ContextBuilder()

        print("1) Primera construcción, solo reglas")
        context = await builder.build(project, list(documents.values()), taxonomy_manifest=manifest, scan_roots=roots)
        show(context, roots)

        # 2) Una persona revisa la cola y decide; la huella (`source_sha256`) ata la decisión a esa versión del original
        sha = {item.document_key: item.source_sha256 for item in review_queue(context, roots=roots)}
        sha["compras/alta.txt"] = documents["alta"].source_sha256  # no está en la cola: se confirma igualmente
        store = ClassificationDecisionStore(project.root_path)
        await store.add(ClassificationDecision(
            document_key="calidad/auditoria.txt", source_sha256=sha["calidad/auditoria.txt"], action="set_axis",
            axes={"domains": ["mejora-continua"]}, author="ana", reason="Las auditorías internas son de mejora continua"))
        await store.add(ClassificationDecision(
            document_key="calidad/auditoria.txt", source_sha256=sha["calidad/auditoria.txt"], action="set_axis",
            axes={"material_types": ["registro"]}, author="ana"))
        await store.add(ClassificationDecision(document_key="varios/menu.txt", action="exclude", author="ana", reason="No es documentación"))
        await store.add(ClassificationDecision(
            document_key="compras/alta.txt", source_sha256=sha["compras/alta.txt"], action="confirm",
            axes={"domains": ["gestion-proveedores"], "material_types": ["procedimiento"]}, author="luis"))
        await store.add(ClassificationDecision(document_key="ventas/tarifas.txt", action="exclude", author="luis"))
        print(f"\n2) Decisiones vigentes: {[(d.document_key, d.action, d.axis) for d in await store.load()]}")

        # 3) Antes de reconstruir, alguien edita el procedimiento: cambia su huella
        documents["alta"] = converted(root, "compras/alta.txt", "Procedimiento de homologación de proveedores",
                                      "Procedimiento para dar de alta a un proveedor (revisión 2026) y revisar su homologacion.")
        print("\n3) Segunda construcción: se aplican las decisiones del proyecto (decisions=True, por defecto)")
        context = await builder.build(project, list(documents.values()), taxonomy_manifest=manifest, scan_roots=roots)
        show(context, roots)

        # 4) Sustituir una decisión: la anterior pasa al historial como `replaced`
        await store.add(ClassificationDecision(
            document_key="compras/alta.txt", source_sha256=documents["alta"].source_sha256, action="confirm",
            axes={"domains": ["gestion-proveedores"], "material_types": ["procedimiento"]}, author="luis", reason="Revisada la versión nueva"))
        print(f"\n4) Historial: {[(d.document_key, d.action, d.revoke_reason) for d in await store.revoked()]}")
        context = await builder.build(project, list(documents.values()), taxonomy_manifest=manifest, scan_roots=roots)
        print(f"  aplicadas={context.decisions_applied} desfasadas={len(context.stale_decisions)} cola={len(review_queue(context, roots=roots))}")
        print(f"  Fichero: {Path(store.path).relative_to(root).as_posix()}")


if __name__ == "__main__":
    asyncio.run(main())
```

## 3. Explicación del Código

1. **Claves de documento**: las decisiones identifican cada documento por su ruta relativa a la raíz de escaneo
   (`document_key`). El ejemplo pasa `scan_roots` a `build` y `roots` a `review_queue` con la misma raíz (`origen/`)
   para que las claves no dependan de qué documentos haya en cada construcción
2. **Huella del original**: `converted` rellena `ConversionResult.source_sha256` (en un proyecto real la pone la
   conversión o la caché). Cada `ReviewItem` trae la del documento (`item.source_sha256`) para atar la decisión a esa
   versión; sin huella, la decisión vale para cualquier versión
3. **Primera construcción**: `auditoria.txt` y `menu.txt` no alcanzan el umbral en el eje de dominios y quedan en
   `sin-clasificar`; la cola los da como `unclassified` (prioridad 1). Todavía no hay decisiones: `decisions=True` (por
   defecto) lee un `decisions.json` que aún no existe
4. **Decidir**: dos `set_axis` sobre ejes distintos del mismo documento conviven (uno por eje); `exclude` no lleva
   ejes; `confirm` lleva todos los ejes del documento. La decisión sobre `ventas/tarifas.txt` es de un documento que
   no está en la construcción
5. **Segunda construcción**: `auditoria.txt` pasa a `mejora-continua` con `classified_by="human"`; `menu.txt` sale del
   contexto (`excluded_documents`) y el dominio `sin-clasificar`, vacío, desaparece. Se aplican 3 decisiones
6. **Decisión obsoleta**: entre las dos construcciones cambió el texto de `alta.txt`, así que el `confirm` (atado a la
   huella anterior) no se aplica: queda en `stale_decisions` con `source_changed`, el documento sigue `por=rules` y la
   cola lo pone el primero (`stale_decision`, prioridad 0). La de `tarifas.txt` queda en `orphan_decisions` con
   `missing_document`; la cola no la muestra (solo lee las desfasadas)
7. **Sustituir**: un `confirm` nuevo sobre el mismo documento sustituye al anterior, que pasa al historial
   (`revoked()`) con `revoke_reason="replaced"`. En la tercera construcción se aplican las 4 y la cola queda vacía: lo
   que decidió una persona no vuelve a ella

## 4. Ejecución y Pruebas

```bash
$ python decisions_example.py
1) Primera construcción, solo reglas
  gestion-proveedores  alta.txt        material=procedimiento   por=rules
  sin-clasificar       auditoria.txt   material=registro        por=rules
  sin-clasificar       menu.txt        material=sin-clasificar  por=rules
  aplicadas=0 excluidos=[]
  desfasadas=[]
  huérfanas=[]
  Cola de revisión:
    [1] unclassified     calidad/auditoria.txt  eje=domains valor=None detalle=None
    [1] unclassified     varios/menu.txt        eje=domains valor=None detalle=None

2) Decisiones vigentes: [('calidad/auditoria.txt', 'set_axis', 'domains'), ('calidad/auditoria.txt', 'set_axis', 'material_types'), ('varios/menu.txt', 'exclude', None), ('compras/alta.txt', 'confirm', None), ('ventas/tarifas.txt', 'exclude', None)]

3) Segunda construcción: se aplican las decisiones del proyecto (decisions=True, por defecto)
  gestion-proveedores  alta.txt        material=procedimiento   por=rules
  mejora-continua      auditoria.txt   material=registro        por=human
  aplicadas=3 excluidos=['menu.txt']
  desfasadas=[('compras/alta.txt', 'source_changed')]
  huérfanas=[('ventas/tarifas.txt', 'missing_document')]
  Cola de revisión:
    [0] stale_decision   compras/alta.txt       eje=None valor=None detalle=source_changed

4) Historial: [('compras/alta.txt', 'confirm', 'replaced')]
  aplicadas=4 desfasadas=0 cola=0
  Fichero: .doc_organize/decisions.json
```

La salida es determinista: no imprime rutas temporales, huellas ni fechas. Validación sintáctica:
`python -m py_compile decisions_example.py`.

## 5. Referencias Relacionadas

- [Referencia técnica: Decisiones de personas](../api/decisions.md)
- [Documentación funcional: Revisión y calidad de la clasificación](../functional/revision_clasificacion.md)
- [Ejemplo: Construir el contexto](context-build.md)
- [Ejemplo: Evaluar la clasificación contra una referencia](evaluation-gold.md) (usa las decisiones como referencia)
- [Ejemplo: Versiones de un documento](versions.md) (la decisión `set_current_version`)
