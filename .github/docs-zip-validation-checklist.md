# ✅ Checklist: Descarga de Documentación ZIP

Validación de la integración de descarga ZIP en doc_organize (mkdocs + zensical).

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
