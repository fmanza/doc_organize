# Ejemplo: Paquete para IA

**Objetivo**: Demostrar cómo `write_ai_context_bundle` empaqueta un contexto para subirlo a un chat o agente de IA, qué
ficheros lleva y cómo `render_llms_txt` genera el mismo índice para otro destino.

## 1. Contexto del Ejemplo

A partir de un contexto ya construido, `write_ai_context_bundle` escribe un ZIP con `llms.txt` (índice), un `.md` por
documento con su ficha en front matter, un `context.json` reducido y, si se pide, `llms-full.txt`. Por defecto redacta
credenciales de títulos, descripciones y textos.

El contexto se construye como en [Construir el contexto](context-build.md), con dos documentos, uno de ellos con una
contraseña en el texto, y `persist=False` (no hace falta guardarlo para empaquetarlo).

### Requisitos

- Python 3.11+
- `doc_organize[context]` instalado (PyYAML: manifiesto y front matter de cada documento)

Los ficheros se crean en un directorio temporal; no se llama a ningún servicio externo.

## 2. Implementación de Referencia

```python
import asyncio
import json
import tempfile
import zipfile
from pathlib import Path

from doc_organize import (
    ContextBuilder,
    ConversionResult,
    Project,
    parse_taxonomy_template,
    render_llms_txt,
    write_ai_context_bundle,
)

MANIFEST = """\
---
schema: 2
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
    """Original en `origen/` y su `.md` + `.json` en `Conversión/`, como en el ejemplo de construir el contexto."""
    source = root / "origen" / relative
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text(text, encoding="utf-8")
    markdown = root / "Conversión" / f"{Path(relative).stem}.md"
    markdown.parent.mkdir(parents=True, exist_ok=True)
    markdown.write_text(f"# {title}\n\n{text}\n", encoding="utf-8")
    json_path = markdown.with_suffix(".json")
    json_path.write_text(json.dumps({"title": title, "chunks": [{"text": text}]}, ensure_ascii=False), encoding="utf-8")
    return ConversionResult(source_path=str(source), markdown_path=str(markdown), json_path=str(json_path), success=True)


async def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp).resolve()
        project = Project(name="Demo", root_path=str(root), created_at="2026-01-01T00:00:00+00:00")
        documents = [
            converted(root, "compras/alta.txt", "Procedimiento de homologación de proveedores",
                      "Alta de un proveedor y revisión anual de su homologacion.\n\n"
                      "Acceso al portal de compras: password=Sup3rS3creta!"),  # Una credencial en el texto
            converted(root, "calidad/nc-2026-04.txt", "Registro de no conformidad 04",
                      "Registro de la no conformidad detectada y de la accion correctiva acordada."),
        ]
        context = await ContextBuilder().build(
            project, documents, taxonomy_manifest=parse_taxonomy_template(MANIFEST), decisions=False, persist=False
        )

        # Paquete para IA: síncrono (zipfile); desde async, en un hilo
        bundle = root / "contexto_ia.zip"
        stats = await asyncio.to_thread(write_ai_context_bundle, bundle, project, context, max_full_chars=10_000)
        print(f"Ficheros: {stats.file_count}, documentos: {stats.documents}, "
              f"con credenciales redactadas: {stats.redacted_documents}, llms-full cortado: {stats.full_text_truncated}")
        with zipfile.ZipFile(bundle) as archive:
            for name in archive.namelist():
                print(f"  {name}")
            print("--- llms.txt")
            print(archive.read("llms.txt").decode("utf-8"), end="")
            alta = next(n for n in archive.namelist() if n.endswith("alta.md"))
            print(f"--- {alta}")
            print(archive.read(alta).decode("utf-8"), end="")

        # El mismo índice para otro destino: aquí, enlaces a las páginas .html de un sitio
        print("--- render_llms_txt para un sitio")
        print(render_llms_txt(project.name, context, lambda md: md.removesuffix(".md") + ".html",
                              project_root=project.root_path), end="")


if __name__ == "__main__":
    asyncio.run(main())
```

## 3. Explicación del Código

1. **Síncrona**: `write_ai_context_bundle` usa `zipfile` y escribe en *streaming*; desde código async se llama con
   `asyncio.to_thread`. `destination` puede ser una ruta (si falla o se cancela, el fichero parcial se borra) o un
   fichero binario abierto
2. **Contenido**: `llms.txt`, un `documentos/<dominio>/<tipo>/<carpeta>/<doc>.md` por documento (las rutas de la carpeta
   reorganizada), `context.json` y, por pasar `max_full_chars`, `llms-full.txt` con todo el texto hasta ese tope
3. **Ficha de cada documento**: el front matter YAML lleva `title`, `domain`, `material_type`, `axes`, `classified_by` y
   `source`, la ruta del original **relativa** a la raíz común (`compras/alta.txt`), nunca la absoluta. `source_sha256`,
   `version`, `description` y `keywords` solo aparecen si el documento los tiene
4. **Redacción**: con `redact=True` (por defecto) la contraseña del texto sale como `«REDACTADO»` y el documento cuenta en
   `stats.redacted_documents`. Con `redact=False` saldría el valor secreto
5. **`llms.txt`**: una sección por dominio y una línea por documento con su enlace y su descripción o, sin ella, el
   nombre de su tipo de material
6. **`render_llms_txt`**: genera ese índice para cualquier destino; `link` convierte la ruta del `.md` en la carpeta
   reorganizada en el enlace del destino. `SiteGenerator.generate(llms_txt=True)` lo usa para el sitio
7. **Reproducible**: mismo contexto y textos, mismo SHA-256 (`stats.sha256`). El ejemplo no lo imprime porque
   `context.json` lleva la fecha de construcción del contexto, que cambia en cada ejecución

## 4. Ejecución y Pruebas

```bash
$ python ai_bundle_example.py
Ficheros: 5, documentos: 2, con credenciales redactadas: 1, llms-full cortado: False
  llms.txt
  documentos/gestion-proveedores/procedimiento/alta/alta.md
  documentos/mejora-continua/registro/nc-2026-04/nc-2026-04.md
  context.json
  llms-full.txt
--- llms.txt
# Demo

> Documentación organizada del proyecto Demo: 2 documentos en 2 dominios.

## Gestión de Proveedores

- [Procedimiento de homologación de proveedores](documentos/gestion-proveedores/procedimiento/alta/alta.md): Procedimiento

## Mejora Continua

- [Registro de no conformidad 04](documentos/mejora-continua/registro/nc-2026-04/nc-2026-04.md): Registro
--- documentos/gestion-proveedores/procedimiento/alta/alta.md
---
title: Procedimiento de homologación de proveedores
domain: gestion-proveedores
material_type: procedimiento
axes:
  domains:
  - gestion-proveedores
  material_types:
  - procedimiento
classified_by: rules
source: compras/alta.txt
---

# Procedimiento de homologación de proveedores

Alta de un proveedor y revisión anual de su homologacion.

Acceso al portal de compras: password=«REDACTADO»
--- render_llms_txt para un sitio
# Demo

> Documentación organizada del proyecto Demo: 2 documentos en 2 dominios.

## Gestión de Proveedores

- [Procedimiento de homologación de proveedores](gestion-proveedores/procedimiento/alta/alta.html): Procedimiento

## Mejora Continua

- [Registro de no conformidad 04](mejora-continua/registro/nc-2026-04/nc-2026-04.html): Registro
```

## 5. Referencias Relacionadas

- [Referencia técnica: Paquete para IA](../api/ai_bundle.md)
- [Documentación funcional: Exportación](../functional/export.md)
- [Ejemplo: Construir el contexto](context-build.md)
