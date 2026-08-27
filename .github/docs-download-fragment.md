<!-- Fragmento para docs/index.md o como partial personalizado -->
<!-- Agregar esto en la documentación para enlazar a descargas -->

## 📥 Descargar Documentación

Puedes descargar toda la documentación como ZIP para acceso offline:

- 📦 [Documentación Offline (ZIP)](#descargas) — Compatible con cualquier navegador
- 🔗 [Última versión disponible](#) — Generada automáticamente en cada build

### Generación del ZIP

El ZIP se genera automáticamente después de cada build:

```bash
# Con Zensical (recomendado)
zensical build
python scripts/build_docs_zip.py

# O con MkDocs Material (recíproco)
mkdocs build
python scripts/build_docs_zip.py
```

**Ubicación**: `dist/doc_organize-docs-{version}-{date}.zip`
**Tamaño**: ~2-3 MB (documentación completa + ejemplos)
**Contenido**: HTML, CSS, JS, búsqueda, diagramas Mermaid
