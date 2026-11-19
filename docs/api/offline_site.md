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

Igual que la redacción de credenciales, solo cambia la copia de la carpeta reorganizada; la conversión
(`Conversión/`) y los originales no se tocan. Un `generate()` normal después quita los recursos empaquetados y la
configuración sin conexión, pero las páginas ya neutralizadas siguen así hasta que se reorganice de nuevo.

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
