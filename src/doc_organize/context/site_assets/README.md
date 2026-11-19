# Recursos del sitio sin conexión (2.0.0, F3)

Copiados tal cual del registro de npm para que el sitio sin conexión no pida nada a terceros. `SiteGenerator.generate(
offline=True)` los copia al sitio; no se usan en el sitio normal.

| Fichero | Paquete npm | Licencia | Integridad del tarball (npm) |
|---|---|---|---|
| `vendor/mermaid/mermaid.min.js` (`dist/mermaid.min.js`) | `mermaid@12.2.0` | MIT (`vendor/mermaid/LICENSE`) | `sha512-w7nr/SFrLO7BaVTs3dQTvYSV6nYSBj0Yy9DjBhsIJtAcHqRzXSq4Pg32ujHZ/AdWsAMNEvvhbm5dt9E2tOiHzw==` |
| `vendor/iframe-worker/shim.js` (`shim/index.js`) | `iframe-worker@1.0.4` | MIT (`vendor/iframe-worker/LICENSE`) | `sha512-roeaaI+Lg1LJNfgpCjoRe/+WzEjy9+Z08LoEvu85MCPbBjwm+qXz8Ag5U05lHa6V1CysZyGzE0SOkAtSUA5q7Q==` |

El tema de Zensical (`zensical-ui`) usa `window.mermaid` si existe y, si no, lo descarga de `unpkg.com/mermaid@12`;
cargar `mermaid.min.js` con `extra_javascript` lo evita. El plugin `offline` añade
`https://unpkg.com/iframe-worker/shim` salvo que ya haya un polyfill cuya ruta contenga `iframe-worker` (spike de M0).

Para actualizar: descargar el tarball de `https://registry.npmjs.org/<paquete>/-/<paquete>-<versión>.tgz`, comprobar su
`dist.integrity`, copiar los ficheros y actualizar esta tabla y los SHA-256 de `tests/unit/test_site_offline.py`.
