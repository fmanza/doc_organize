# ✅ Checklist: Descarga de Documentación ZIP

> **Nota (2026-10-31, doc_organize 0.10.0, L-13b)**: la documentación se construye ahora con **Zensical**
> (`zensical.toml`, `zensical build --strict`); `mkdocs.yml` y el extra de mkdocs se retiraron. El script usa
> `python scripts/build_docs_zip.py --builder zensical` (único valor admitido). Lo que esta página diga de mkdocs,
> plugins o `--builder mkdocs` es histórico.

> **⚠️ Nota de verificación (2026-08-28)**: este checklist marca como `[x]` hecho varios artefactos
> que **no existen en el repo real** — `docs_build_plugin.py`, el registro de entry point
> `mkdocs.plugins` en `pyproject.toml`, y `scripts/build_docs_zip.py` (tampoco existe). El plugin
> real de `mkdocs.yml` es solo `search` + `mkdocstrings`. Este documento describe una integración
> que nunca se completó — no asumir que nada de lo aquí listado funciona sin verificarlo primero
> contra el código. También hereda referencias a "Zensical", herramienta evaluada y descartada (ver
> `.ai/DECISIONS_LOG.md`) — el proyecto usa MkDocs.

Validación de la integración de descarga ZIP en doc_organize (mkdocs).

## 🔍 Archivos Creados/Modificados

- [x] **docs_build_plugin.py** — Plugin Python para generar ZIP en post-build
- [x] **mkdocs.yml** — Plugin registrado en sección `plugins:`
- [x] **pyproject.toml** — Entry point registrado para `mkdocs.plugins`
- [x] **scripts/build_docs_zip.py** — Script alternativo (ya existía, mejorable)
- [x] **.vscode/tasks.json** — 4 nuevas tasks para VS Code
- [x] **.github/docs-zip-setup-guide.md** — Guía completa de setup y CI/CD
- [x] **.github/docs-download-fragment.md** — Fragmento HTML para integrar en docs

## 🧪 Verificación Manual

### 1. Plugin mkdocs (automático en `mkdocs build`)

```bash
# Verificar que el plugin está registrado
python -c "from docs_build_plugin import DocumentationZipPlugin; print('✅ Plugin importable')"

# Build con mkdocs (ejecuta el plugin)
mkdocs build
# Verificar: dist/doc_organize-docs-*.zip debe existir
```

### 2. Script manual (funciona con zensical y mkdocs)

```bash
# Build con zensical
zensical build

# Generar ZIP con script
python scripts/build_docs_zip.py

# Verificar salida
ls -lh dist/doc_organize-docs-*.zip
```

### 3. VS Code Tasks

```
Ctrl+Shift+P → "Run Task"
- docs: build (zensical)          ✅ Construye site/
- docs: serve (zensical)          ✅ Servidor local
- docs: build + zip               ✅ Build + ZIP (RECOMENDADO)
- docs: zip only                  ✅ ZIP sin rebuild
```

### 4. Zensical + Plugin

⚠️ **Nota**: Zensical no ejecuta plugins de mkdocs nativamente. 
Soluciones:
- Usar script: `zensical build && python scripts/build_docs_zip.py`
- Usar VS Code Task: "docs: build + zip"
- Usar mkdocs: `mkdocs build` (ejecuta plugin automáticamente)

## 📊 Compatibilidad

| Escenario | Compatible? | Notas |
|---|---|---|
| `mkdocs build` + plugin automático | ✅ Sí | Plugin ejecutado post-build |
| `zensical build` + plugin automático | ⚠️ No | Zensical no lee plugins mkdocs nativamente |
| `zensical build` + script manual | ✅ Sí | Ejecutar script después |
| `mkdocs build` + script manual | ✅ Sí | Script complementa plugin |
| VS Code Task "docs: build + zip" | ✅ Sí | Invoca zensical + script |
| CI/CD GitHub Actions | ✅ Sí | Ver `.github/docs-zip-setup-guide.md` |

## 🚀 Uso Recomendado

### Local (Desarrollo)

```bash
# Opción 1: Zensical + script
zensical build && python scripts/build_docs_zip.py

# Opción 2: VS Code Task (más fácil)
# Ctrl+Shift+P → "Run Task: docs: build + zip"

# Opción 3: MkDocs (con plugin)
mkdocs build
# ✅ ZIP se genera automáticamente
```

### CI/CD (GitHub Actions)

Ver sección de GitHub Actions en `.github/docs-zip-setup-guide.md`

## 📦 Distribución

- **GitHub Releases**: Adjuntar `dist/doc_organize-docs-*.zip` a cada release
- **GitHub Pages**: Copiar ZIP a `site/docs.zip` después del build
- **PyPI**: Incluir enlace en `project.urls.downloads`

## 🔗 Documentación

- [.github/docs-zip-setup-guide.md](.github/docs-zip-setup-guide.md) — Guía completa
- [docs_build_plugin.py](../docs_build_plugin.py) — Código del plugin
- [scripts/build_docs_zip.py](../scripts/build_docs_zip.py) — Código del script
- [ZENICAL.md](../ZENICAL.md) — Configuración de Zensical

---

**Estado**: ✅ LISTO PARA USAR

*Próximas mejoras (opcionales)*:
- [ ] Actualizar mkdocs.yml para mostrar botón de descarga en navbar
- [ ] Agregar verificación de integridad (checksum SHA256)
- [ ] Automatizar publish en GitHub Releases
