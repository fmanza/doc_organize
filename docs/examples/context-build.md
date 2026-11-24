# Ejemplo: Construir el Contexto

**Objetivo**: Demostrar cómo `ContextBuilder.build` clasifica por reglas unos documentos ya convertidos con un manifiesto
de taxonomía pequeño, y qué queda en dominios y qué sin clasificar.

## 1. Contexto del Ejemplo

`ContextBuilder` no convierte nada: recibe los `ConversionResult` de documentos ya convertidos y lee de cada `.json` de
conversión solo `title` y el texto de `chunks`. Por eso el ejemplo no necesita Docling: escribe a mano lo que dejaría
`DocumentConverter` (un original, su `.md` y su `.json`) y construye el contexto solo con reglas, sin IA.

Con manifiesto, cada documento con sus tres artefactos se clasifica en todos los ejes; el eje que no alcanza el umbral
(`threshold`, 0,5 por defecto) queda en el valor `sin-clasificar`. Solo un documento al que le falta algún artefacto va a
`unclassified_documents`.

### Requisitos

- Python 3.11+
- `doc_organize[context]` instalado (PyYAML, para leer el manifiesto)

Los ficheros se crean en un directorio temporal; no se llama a ningún servicio externo.

## 2. Implementación de Referencia

```python
import asyncio
import json
import tempfile
from pathlib import Path

from doc_organize import ContextBuilder, ConversionResult, Project, parse_taxonomy_template

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
# Notas libres: no se parsean
"""


def converted(root: Path, relative: str, title: str | None, text: str | None) -> ConversionResult:
    """Un original en `origen/` y, si hay `text`, su `.md` + `.json` en `Conversión/`, como los deja `DocumentConverter`."""
    source = root / "origen" / relative
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text(text or "", encoding="utf-8")
    stem = Path(relative).stem
    markdown = root / "Conversión" / f"{stem}.md"
    json_path = root / "Conversión" / f"{stem}.json"
    if text is not None:
        markdown.parent.mkdir(parents=True, exist_ok=True)
        markdown.write_text(f"# {title}\n\n{text}\n", encoding="utf-8")
        # Lo único que leen las reglas del `.json`: `title` y el texto de `chunks`
        json_path.write_text(json.dumps({"title": title, "chunks": [{"text": text}]}, ensure_ascii=False), encoding="utf-8")
    return ConversionResult(source_path=str(source), markdown_path=str(markdown), json_path=str(json_path), success=True)


async def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp).resolve()
        project = Project(name="Demo", root_path=str(root), created_at="2026-01-01T00:00:00+00:00")
        documents = [
            converted(root, "compras/alta.txt", "Procedimiento de homologación de proveedores",
                      "Procedimiento para dar de alta a un proveedor y revisar su homologacion anual."),
            converted(root, "calidad/nc-2026-04.txt", "Registro de no conformidad 04",
                      "Registro de la no conformidad detectada y de la accion correctiva acordada."),
            converted(root, "varios/menu.txt", "Menú de la cafetería", "Lunes: lentejas. Martes: paella."),
            converted(root, "varios/escaneo.txt", None, None),  # Conversión incompleta: sin `.md` ni `.json`
        ]

        manifest = parse_taxonomy_template(MANIFEST)
        context = await ContextBuilder().build(project, documents, taxonomy_manifest=manifest, decisions=False)

        print(f"Ejes: {[axis.key for axis in context.taxonomy_axes]}")
        for domain in context.domains:
            print(f"Dominio {domain.slug} ({domain.name}, {domain.status.value}):")
            for document in domain.documents:
                print(f"  {Path(document.source_path).name}: material={document.material_type} "
                      f"confianza={document.confidence:.2f} por={document.classified_by}")
        print(f"Sin clasificar: {[Path(p).name for p in context.unclassified_documents]}")
        print(f"Motivo: {[d.reason for d in context.unclassified_details]}")
        print(f"IA: scope={context.ai_stats.scope}, enviados={context.ai_stats.classification.sent}")
        print(f"Persistido: {sorted(p.relative_to(root).as_posix() for p in root.rglob('*') if p.is_file() and 'origen' not in p.parts and 'Conversión' not in p.parts)}")


if __name__ == "__main__":
    asyncio.run(main())
```

## 3. Explicación del Código

1. **Manifiesto**: `parse_taxonomy_template` valida el front matter YAML (formato 2.0, `schema: 2`, `axes:`) como
   `TaxonomyManifest`. El eje `organizes: folder` es el de dominios y el `organizes: subfolder`, el de tipos de material;
   el cuerpo tras el front matter no se parsea
2. **Documentos convertidos**: cada `ConversionResult` apunta al original, al `.md` y al `.json`. Las reglas leen del
   `.json` el `title` y el texto de `chunks` (no el `.md`)
3. **Puntuación por reglas**: la confianza de un dominio es la fracción de sus palabras clave (las del slug más
   `keywords`) que aparecen en el título y el texto, sin distinguir tildes. `alta.txt` encuentra 3 de 4 (`proveedores`,
   `proveedor`, `homologacion`, pero no `gestion`): 0,75. `nc-2026-04.txt` encuentra 2 de 4: 0,50, justo el umbral
4. **`sin-clasificar`**: `menu.txt` tiene sus tres artefactos pero no alcanza el umbral en ningún eje: se reorganiza
   igualmente, con el valor `sin-clasificar` en los dos ejes
5. **Sin clasificar de verdad**: `escaneo.txt` no tiene `.json`; va a `unclassified_documents` y su detalle
   (`unclassified_details`) lleva el motivo `incomplete_artifacts`. La librería lo avisa en el log (WARNING «No se pudo
   leer el .json de conversión»)
6. **Sin IA**: sin `llm`, `ai_scope` queda en `"off"` y no se envía nada (`ai_stats.classification.sent == 0`).
   `decisions=False` evita leer decisiones de personas del proyecto
7. **Persistencia**: `ContextRegistry` (el de por defecto) guarda en la raíz del proyecto `context.json`,
   `domains/<slug>/{DOMAIN.md,index.json}`, `unclassified.json` y el histórico `historial_contexto/CONTEXT_HISTORY.jsonl`.
   Con `persist=False` se devuelve el contexto sin guardar nada

En un proyecto real los `ConversionResult` salen de la conversión (`DocumentConverter`) o de la caché, y el manifiesto de
`taxonomy_manifest.md` del proyecto o de una plantilla (`load_builtin_template`).

## 4. Ejecución y Pruebas

```bash
$ python context_build_example.py 2>/dev/null
Ejes: ['domains', 'material_types']
Dominio gestion-proveedores (Gestión de Proveedores, confirmado):
  alta.txt: material=procedimiento confianza=0.75 por=rules
Dominio mejora-continua (Mejora Continua, confirmado):
  nc-2026-04.txt: material=registro confianza=0.50 por=rules
Dominio sin-clasificar (Sin Clasificar, confirmado):
  menu.txt: material=sin-clasificar confianza=0.00 por=rules
Sin clasificar: ['escaneo.txt']
Motivo: ['incomplete_artifacts']
IA: scope=off, enviados=0
Persistido: ['context.json', 'domains/gestion-proveedores/DOMAIN.md', 'domains/gestion-proveedores/index.json', 'domains/mejora-continua/DOMAIN.md', 'domains/mejora-continua/index.json', 'domains/sin-clasificar/DOMAIN.md', 'domains/sin-clasificar/index.json', 'historial_contexto/CONTEXT_HISTORY.jsonl', 'unclassified.json']
```

`2>/dev/null` solo oculta el aviso del log sobre `escaneo.json`, que lleva la ruta temporal. Los dominios salen
`confirmado` porque el catálogo viene del manifiesto; sin él, los dominios descubiertos de las carpetas quedan en
borrador.

## 5. Referencias Relacionadas

- [Referencia técnica: Organización documental](../api/context.md)
- [Documentación funcional: Contexto](../functional/context.md)
- [Ejemplo: Paquete para IA](ai-bundle.md) (usa un contexto como este)
- [Ejemplo: Convertir documentos a Markdown](converter-convert.md)
