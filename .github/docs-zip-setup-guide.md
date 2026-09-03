# 📦 Descarga de Documentación como ZIP

> **⚠️ Nota de verificación (2026-08-28, corregida 2026-09-03)**: la nota original de esta fecha
> afirmaba que `scripts/build_docs_zip.py` no existía en el repo y que la funcionalidad de ZIP de
> release nunca se completó — **eso ya no es cierto**: el script existe (342 líneas), tiene 13 tests
> en verde (`tests/unit/test_build_docs_zip.py`) y `.github/workflows/docs-zip-release.yml` lo invoca
> con éxito en cada push a `main`/`develop` que toque `docs/` (verificado en la sesión de
> maturity-assessment 2026-09-03). `.github/workflows/docs-release.yml` (el basado en tags `v*`, la
> otra referencia de esta nota) se **retiró** en esa misma sesión por redundante — usa solo
> `docs-zip-release.yml`. Las referencias a "Zensical" y a `python scripts/build_docs_zip.py` **sin**
> `--builder mkdocs` en los ejemplos de más abajo siguen sin actualizar (el script real exige ese
> flag) — el resto de esta guía (Quick Start, estructura de archivos) sigue sin revisar en detalle,
> trátala con cautela hasta que se audite completa.

Esta guía explica cómo generar y distribuir la documentación de doc_organize como ZIP, con **mkdocs**.

---

## 🚀 Quick Start

### 1. Build + Generar ZIP (Local)

```bash
# Opción A: Zensical (recomendado) + ZIP
zensical build
python scripts/build_docs_zip.py

# Opción B: MkDocs Material + ZIP (recíproco)
mkdocs build
python scripts/build_docs_zip.py

# Opción C: Todo en una línea (VS Code Task)
# Terminal → Run Task → "docs: build + zip"
```

**Resultado**: `dist/doc_organize-docs-{version}-{date}.zip` (~2-3 MB)

---

## 📂 Estructura de Archivos

```
doc_organize/
├── mkdocs.yml                 # Configuración compartida (mkdocs + zensical)
├── docs_build_plugin.py       # Plugin Python para generar ZIP automático
├── scripts/
│   └── build_docs_zip.py      # Script para generar ZIP (alternativa)
├── .vscode/
│   └── tasks.json             # Tasks de VS Code
├── site/                      # Build output (generado por mkdocs/zensical)
└── dist/
    └── doc_organize-docs-*.zip   # ZIP final (generado por plugin o script)
```

---

## ⚙️ Configuración en mkdocs.yml

El plugin se activa automáticamente después de cada build de mkdocs:

```yaml
plugins:
  - search:
      lang: es
  - documentation_zip       # ← Plugin para generar ZIP
  - mkdocstrings:
      handlers:
        python:
          paths: [src]
```

**Compatible con**:
- ✅ `zensical build` (lee mkdocs.yml, no ejecuta plugins de mkdocs nativamente, pero el script sigue funcionando)
- ✅ `mkdocs build` (ejecuta el plugin automáticamente)

---

## 📜 Script `build_docs_zip.py`

Genera ZIP de forma **independiente** después de cualquier build:

```bash
# Uso básico (lee site/, genera dist/)
python scripts/build_docs_zip.py

# Opciones
python scripts/build_docs_zip.py --builder zensical  # Especificar builder
python scripts/build_docs_zip.py --no-build          # Solo zip (no rebuild)
python scripts/build_docs_zip.py --output-dir /tmp   # Output personalizado

# Comando completo (build + zip)
zensical build && python scripts/build_docs_zip.py
```

**Salida esperada**:
```
[build_docs_zip] Built with builder: zensical
[build_docs_zip] Created: dist/doc_organize-docs-0.10.0-20260604.zip
[build_docs_zip] Files: 150+
```

---

## 🔧 VS Code Tasks

En `.vscode/tasks.json` se incluyen 4 tareas:

### `docs: build (zensical)`
- Ejecuta: `zensical build --strict`
- Output: `site/`

### `docs: serve (zensical)`
- Ejecuta: `zensical serve --open`
- Server local con hot-reload

### `docs: build + zip`
- Ejecuta: `zensical build` + `python scripts/build_docs_zip.py`
- Output: `site/` + `dist/doc_organize-docs-*.zip`
- **Recomendado para distribución local**

### `docs: zip only`
- Ejecuta: `python scripts/build_docs_zip.py`
- Usa `site/` existente (no rebuilds)

**Invocar**:
- Ctrl+Shift+P → "Run Task" → seleccionar tarea
- O: Terminal → Run Task

---

## 🔄 Integración en CI/CD

### GitHub Actions

```yaml
# .github/workflows/docs.yml
name: Build & Publish Docs

on:
  push:
    branches:
      - main
      - develop

jobs:
  docs:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      
      - uses: actions/setup-python@v4
        with:
          python-version: "3.12"
      
      # Build docs + ZIP
      - name: Build documentation
        run: |
          pip install -e ".[docs]"
          zensical build --strict
          python scripts/build_docs_zip.py
      
      # Publicar en GitHub Pages
      - name: Deploy to GitHub Pages
        uses: peaceiris/actions-gh-pages@v3
        with:
          github_token: ${{ secrets.GITHUB_TOKEN }}
          publish_dir: ./site
      
      # Subir ZIP como artifact
      - name: Upload ZIP as release artifact
        uses: actions/upload-artifact@v3
        with:
          name: documentation-zip
          path: dist/doc_organize-docs-*.zip
          retention-days: 30
```

---

## 📋 Contenido del ZIP

```
doc_organize-docs-0.10.0-20260604.zip
├── index.html
├── INSTALLATION.html
├── css/
│   ├── material.css
│   ├── mermaid.css
│   └── nav.css
├── js/
│   ├── mermaid.js
│   ├── search.js
│   └── instant.js
├── assets/
│   └── images/
├── api/
│   ├── managers-sync.html
│   ├── bulk-crud.html
│   └── ...
├── functional/
│   ├── managers-sync.html
│   ├── bulk-operations.html
│   └── ...
├── examples/
│   ├── bulk-insert-csv.html
│   └── ...
└── search/
    └── search_index.json
```

**Características**:
- ✅ HTML completo con CSS/JS
- ✅ Búsqueda offline (search_index.json)
- ✅ Diagramas Mermaid renderizados
- ✅ Navegación interactiva
- ✅ Responsive (funciona en móvil)

---

## 🌐 Distribución

### Opción 1: GitHub Releases

Adjunta el ZIP a cada release:

```bash
# Crear release con ZIP
gh release create v0.10.0 \
  --title "v0.10.0: Release" \
  --notes "Incluye documentación offline" \
  dist/doc_organize-docs-*.zip
```

### Opción 2: PyPI (en future)

```toml
# pyproject.toml (future enhancement)
[project.urls]
"Offline Docs" = "https://github.com/fmanza/doc_organize/releases/download/v0.10.0/doc_organize-docs-0.10.0.zip"
```

### Opción 3: Website personalizado

Servir desde GitHub Pages con listado:

```html
<!-- docs/downloads.html -->
<h1>Descargas</h1>
<a href="../doc_organize-docs-latest.zip">Documentación Offline (ZIP)</a>
```

---

## 🔗 Enlaces Relacionados

- [ZENICAL.md](../../ZENICAL.md) — Configuración de Zensical
- [mkdocs.yml](../../mkdocs.yml) — Navegación y plugins
- [scripts/build_docs_zip.py](../../scripts/build_docs_zip.py) — Script de generación
- [docs_build_plugin.py](../../docs_build_plugin.py) — Plugin de mkdocs

---

## ❓ FAQ

**P: ¿El ZIP es compatible con zensical y mkdocs?**
R: Sí. El script funciona con cualquier build HTML. Zensical no ejecuta plugins nativamente, pero el script se invoca por separado.

**P: ¿Puedo servir el ZIP en GitHub Pages?**
R: Sí. Publícalo en `site/docs.zip` después del build.

**P: ¿Qué tamaño tiene el ZIP?**
R: ~2-3 MB (comprimido). La documentación HTML sin comprimir es ~8-10 MB.

**P: ¿Incluye búsqueda offline?**
R: Sí. El `search_index.json` se incluye en el ZIP.

**P: ¿Cómo actualizar el ZIP?**
R: Ejecuta `python scripts/build_docs_zip.py` después de cualquier build.

---

*Actualizado: 2026-06-04*
