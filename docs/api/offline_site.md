# Sitio sin conexión (2.0)

El sitio del contexto normalmente se ve dentro de la web, que lo sirve aislado (CSP `sandbox`). Para entregarlo a quien
no tiene cuenta (un auditor, un cliente), `SiteGenerator.generate(offline=True)` construye un sitio que se abre desde
el disco (doble clic en `index.html`) y no pide nada a terceros.

```python
from doc_organize import SiteGenerator, check_site_offline

result = await SiteGenerator().generate(project, context, offline=True)
print(result.neutralized_counts)            # lo neutralizado en las páginas, por tipo
report = check_site_offline(result.site_dir)
if not report.ok:
    print("\n".join(report.problems()))
```

## Qué cambia con `offline=True`

- **Plugin `offline` de Zensical**: enlaces a ficheros (`.../pagina.html`, no a carpetas) e índice de búsqueda en
  JavaScript (`search.js`), que es lo que funciona desde `file://`.
- **Nada de terceros**: Mermaid (`mermaid@12.2.0`) y el shim `iframe-worker` (`1.0.4`) van empaquetados en la librería
  (licencia MIT; versión e integridad en `src/doc_organize/context/site_assets/README.md`) y se copian al sitio. Sin
  ellos, el tema los descargaría de unpkg.com.
- **Contenido de terceros neutralizado, siempre** (D6): ver abajo.
- **Sin originales ni conversión**: junto a cada página, `Reorganizer` deja el original y el `.json` de la
  conversión, que no se pueden redactar (el `.json` lleva el texto completo). Con `offline=True` el sitio no los
  publica (`exclude_docs` de Zensical): solo van las páginas, sus imágenes, `llms.txt` y los recursos empaquetados.
  `include_originals=True` los vuelve a incluir; `include_originals=False` los quita también del sitio normal.

Igual que la redacción de credenciales, solo cambia la copia de la carpeta reorganizada; la conversión
(`Conversión/`) y los originales no se tocan. Un `generate()` normal después quita los recursos empaquetados y la
configuración sin conexión, pero las páginas ya neutralizadas siguen así hasta que se reorganice de nuevo.

## Construir aparte (`work_dir`)

Para entregar el sitio sin cambiar el que ya se sirve (por ejemplo, desde la web), pasa una carpeta de trabajo fuera
del proyecto, vacía o que no exista:

```python
result = await SiteGenerator().generate(project, context, offline=True, llms_txt=True, work_dir=Path(tmp) / "sitio")
write_site_zip(destination, result.site_dir)  # <work_dir>/site
```

Se copia ahí la carpeta reorganizada (sin enlaces simbólicos) y en esa copia se redacta, se neutraliza y se escriben
`zensical.toml` y el sitio; el proyecto queda igual (ni páginas, ni `zensical.toml`, ni `site/`). No se admite junto
con `site_dir`. Borrar `work_dir` después es cosa de quien llama.

## Contenido no confiable (D6)

Los `.md` salen de documentos de terceros, y Zensical deja pasar tal cual el HTML que llevan. Abierto desde el disco no
hay CSP que lo aísle: un `<script>` podría leer el índice de búsqueda (todo el texto del corpus) y enviarlo fuera.
`neutralize_untrusted_markdown` deja cada página sin nada activo:

| Qué | Cómo queda |
|---|---|
| HTML fuera del código (`<script>`, `<img onerror>`, `<iframe>`, `<form>`, `<style>`...) | Escapado: se ve como texto |
| Comentarios `<!-- … -->` completos (docling emite `<!-- image -->`) | Tal cual: no ejecutan |
| Enlaces e imágenes `javascript:`, `vbscript:`, `data:` (salvo `data:image/` en imágenes), también disfrazados (`java&#9;script:`) | Solo su texto |
| Imágenes remotas (`http(s)://`, `//`) e imágenes por referencia | Un enlace «Imagen externa: …»: abrir la página no avisa a nadie |
| Listas de atributos (`{onclick=…}`, `{: style=… }`) | Escapadas |
| Bloques de código y `código en línea` | Tal cual |

Es idempotente. `SiteResult.neutralized` dice qué páginas cambiaron y `neutralized_counts`, cuánto por tipo.

**CSP en `<meta>` (D6 b): no se incluye.** El spike de M0 mostró que el tema necesita `'unsafe-inline'` en
`script-src` (lo que le quita casi todo el valor frente al HTML incrustado) y no se ha podido comprobar en Edge, Chrome
y Firefox con `file://`. La protección es la neutralización.

## Comprobar el sitio antes de entregarlo

`check_site_offline(site_dir)` revisa un `site/` ya construido:

- ningún recurso de terceros en las páginas (`<script src>`, hojas de estilo, imágenes, `iframe`, objetos); los
  enlaces `<a href>` externos sí valen, porque no se cargan solos;
- enlaces internos a ficheros que existen (un enlace a una carpeta no abre su `index.html` desde `file://`);
- el índice de búsqueda en JavaScript;
- ningún enlace `javascript:` ni atributo `on*` en el HTML.

`report.ok` es `True` si todo está bien; `report.problems()` lo explica. `report.script_references` lista, solo como
información, las URLs de terceros que hay dentro del JavaScript del tema: el tema las usa **bajo demanda** para
funciones que este sitio no activa (Pyodide y ACE para bloques de código ejecutables, la galería de imágenes, el
polyfill de `ResizeObserver` para navegadores antiguos, y Mermaid si no estuviera ya cargado).

## Empaquetar el sitio para entregarlo

`write_site_zip(destination, site_dir, *, project_name="", on_progress=None, cancel_token=None) -> SiteZipResult`
empaqueta un sitio que pasa `check_site_offline` (si no, lanza `OfflineSiteError` con los problemas y no escribe nada;
`InvalidPathError` si `destination` está dentro de `site_dir`, `FileNotFoundError` si `site_dir` no existe):

```python
import asyncio
from doc_organize import write_site_zip

zipped = await asyncio.to_thread(write_site_zip, "sitio.zip", result.site_dir, project_name=project.name)
print(zipped.sha256, zipped.zip_size_bytes)  # la huella que se da al destinatario
```

El ZIP lleva:

| Fichero | Para qué |
|---|---|
| `sitio/` | El sitio: `sitio/index.html` se abre con doble clic |
| `start_server.py` | Servidor local (Python 3.10+, sin instalar nada) en `127.0.0.1` y un puerto libre, si el navegador limita la búsqueda desde `file://` |
| `VER_SITIO.md` | Cómo abrirlo en Windows, macOS y Linux, cómo comprobar la huella y el aviso de contenido de terceros |

Es **reproducible**: orden alfabético, fecha (1980-01-01) y permisos fijos y la misma compresión, así que el mismo
`site/` da el mismo SHA-256, se escriba en una ruta o en un fichero abierto. Dos construcciones del mismo contexto dan
el mismo `site/` (comprobado con Zensical 0.1.1) y, por tanto, el mismo ZIP. Escribe en *streaming*, con progreso
(`ProgressEvent(operation="export")`) y cancelación (`CancelToken`) como `write_project_zip`; es síncrona: desde
código async, con `asyncio.to_thread`.

::: doc_organize.security.untrusted_markdown
    options:
      show_root_heading: false
      members:
        - neutralize_untrusted_markdown
        - NeutralizeResult

::: doc_organize.context.offline_site
    options:
      show_root_heading: false
      members:
        - check_site_offline
        - OfflineSiteReport
        - OfflineIssue
        - write_site_zip
        - SiteZipResult
