# 🔄 Flujo de Automatización: Docs ZIP CI/CD

Explicación completa del flujo automático de build, zip y publicación de la documentación.

---

## 📊 Diagrama de Flujo

```mermaid
graph LR
    A["💾 Push a develop/main<br/>(cambios en docs/)"] -->|Git Hook| B["🤖 GitHub Actions<br/>docs-zip-release.yml"]
    B -->|1. Checkout| C["📥 Clone repo"]
    C -->|2. Setup| D["🐍 Python 3.12<br/>+ dependencies"]
    D -->|3. Build| E["🏗️ MkDocs build<br/>→ site/"]
    E -->|4. Package| F["📦 build_docs_zip.py<br/>→ dist/*.zip"]
    F -->|5. Hash| G["🔐 SHA256<br/>→ dist/*.sha256"]
    G -->|6. Release| H["🏷️ GitHub Release<br/>docs-vX.X.X"]
    H -->|7. Publish| I["📤 Adjuntar ZIP +<br/>checksums"]
    I -->|8. Notify| J["✅ Release publicada<br/>https://github.com/.../releases"]
    J -->|9. Link| K["📥 downloads.md<br/>actualizada"]
```

---

## ⏱️ Cronología Típica

### 1️⃣ **Cambios en Documentación** (5 min antes)

```bash
# Developer
git checkout develop
# Editar documentación
vim docs/functional/managers-sync.md

git add docs/
git commit -m "docs: actualizar guía de managers"
git push origin develop

# ✅ Push completado
```

### 2️⃣ **GitHub Actions se Dispara** (0 seg)

**Evento**: `on: push` → rama `develop` + cambios en `docs/`

```yaml
# .github/workflows/docs-zip-release.yml
on:
  push:
    branches: [main, develop]
    paths:
      - 'docs/**'
      - 'mkdocs.yml'
      - 'pyproject.toml'
      - '.github/workflows/docs-zip-release.yml'
```

**Status en GitHub**: 🟡 Running

---

### 3️⃣ **Build Documentation** (30-60 seg)

```bash
# Workflow Steps:
✓ Checkout code
✓ Setup Python 3.12
✓ Install dependencies (mkdocs, mkdocs-material, etc.)
✓ mkdocs build --strict
  ├─ Parse 150+ markdown files
  ├─ Render Mermaid diagrams
  ├─ Generate search index
  └─ Output: site/ (~10 MB uncompressed)
```

**Status**: 🟡 Building

---

### 4️⃣ **Generate ZIP + Checksums** (10-30 seg)

```bash
# Script: scripts/build_docs_zip.py
python scripts/build_docs_zip.py --builder mkdocs

# Output:
dist/
├── doc_organize-docs-0.10.0.zip         (2.45 MB)
├── doc_organize-docs-0.10.0.zip.sha256  (100 bytes)
└── CHECKSUMS.txt                     (200 bytes)

# Log:
[build_docs_zip] Built with builder: mkdocs
[build_docs_zip] Created: dist/doc_organize-docs-0.10.0.zip
[build_docs_zip] 🔐 SHA256: abc123def456...
[build_docs_zip] 📄 Checksum saved to: doc_organize-docs-0.10.0.zip.sha256
```

**Status**: 🟡 Packaging

---

### 5️⃣ **Create GitHub Release** (5-10 seg)

**Action**: `ncipollo/release-action@v1`

```yaml
tag: "docs-v0.10.0"
name: "📚 Documentation Offline v0.10.0"
artifacts:
  - dist/doc_organize-docs-0.10.0.zip
  - dist/doc_organize-docs-0.10.0.zip.sha256
  - dist/CHECKSUMS.txt
```

**Release Body** (auto-generado):

```markdown
## 📚 Documentation Offline Package

**Version**: 0.10.0  
**Date**: 2026-06-06T14:30:00Z  
**Commit**: a1b2c3d4...

### 📦 Contents
- ✅ Complete HTML documentation with search
- ✅ Mermaid diagrams (rendered)
- ✅ Code examples and API reference
- ✅ Offline search capability
- ✅ Responsive design (mobile-friendly)

### 🔐 Integrity Verification
**SHA256**: `abc123def456...`

### 🚀 How to Use
1. Download the ZIP file
2. Extract: `unzip doc_organize-docs-0.10.0.zip`
3. Open `index.html` in your browser
```

**Status**: 🟡 Publishing

---

### 6️⃣ **Workflow Completo** (Total: ~2 min)

```
✅ All steps completed successfully
✅ Artifacts uploaded
✅ Release created: https://github.com/fmanza/doc_organize/releases/tag/docs-v0.10.0
```

**Status**: 🟢 Success

---

## 📥 Descarga Automática (Post-Release)

### Opción 1: GitHub Releases (Manual)

1. Ir a: https://github.com/fmanza/doc_organize/releases
2. Encontrar release con etiqueta `docs-vX.X.X`
3. Descargar ZIP desde "Assets"

### Opción 2: Enlace Directo (Automático)

URL pattern (construida automáticamente):
```
https://github.com/fmanza/doc_organize/releases/download/docs-v{VERSION}/doc_organize-docs-{VERSION}.zip
```

Ejemplo:
```
https://github.com/fmanza/doc_organize/releases/download/docs-v0.10.0/doc_organize-docs-0.10.0.zip
```

### Opción 3: Página de Descargas (Integrada)

- Página: https://fmanza.github.io/doc_organize/downloads/
- Se puede actualizar con el enlace posterior a release
- Muestra SHA256 para validación

---

## 🔐 Validación de Integridad (Post-Descarga)

### Flujo Típico del Usuario

```bash
# 1. Descargar desde GitHub Release
wget https://github.com/fmanza/doc_organize/releases/download/docs-v0.10.0/doc_organize-docs-0.10.0.zip
wget https://github.com/fmanza/doc_organize/releases/download/docs-v0.10.0/doc_organize-docs-0.10.0.zip.sha256

# 2. Validar SHA256 (Linux/Mac)
sha256sum -c doc_organize-docs-0.10.0.zip.sha256
# Output: doc_organize-docs-0.10.0.zip: OK ✅

# 3. Extraer ZIP
unzip doc_organize-docs-0.10.0.zip

# 4. Abrir en navegador
open index.html  # Mac
xdg-open index.html  # Linux
start index.html  # Windows PowerShell

# 5. Usar
# - Buscar documentación con Cmd+F (búsqueda en página)
# - O usar el campo de búsqueda global (requiere JavaScript)
# - Navegar con el menú lateral
```

---

## 📊 Archivos Generados en CI/CD

| Archivo | Tamaño | Generado Por | Propósito |
|---|---|---|---|
| `site/` (temp) | ~10 MB | `mkdocs build --strict` | Build intermedio |
| `dist/*.zip` | ~2.5 MB | `build_docs_zip.py` | ZIP final distribuible |
| `dist/*.sha256` | ~100 B | `build_docs_zip.py` | Hash SHA256 |
| `dist/CHECKSUMS.txt` | ~200 B | `build_docs_zip.py` | Histórico de hashes |

**Almacenamiento**:
- GitHub Release Assets (permanente)
- GitHub Actions Artifacts (temporal, 30 días)

---

## 🚀 Triggers del Workflow

### Automático (Recomendado)

```bash
# Push a develop/main con cambios en docs/
git push origin develop
# → Workflow se dispara automáticamente
```

### Manual (desde GitHub UI)

1. Ir a: **GitHub → Actions → "📦 Build & Publish Docs ZIP"**
2. Hacer clic en: **"Run workflow"**
3. Rama: `develop` o `main`
4. Confirmar: **"Run workflow"**

---

## 📋 Checklist del CI/CD

- [x] Workflow configurado: `.github/workflows/docs-zip-release.yml`
- [x] Permisos: `permissions.contents: write`
- [x] Python 3.12 con dependencias docs
- [x] Script build_docs_zip.py con SHA256
- [x] Generación de checksums (.sha256, CHECKSUMS.txt)
- [x] GitHub Release con artifacts adjuntos
- [x] Release body con instrucciones
- [x] Página de descargas: docs/downloads.md
- [x] Tags automáticos: `docs-vX.X.X`

---

## 🔗 Archivos Relacionados

- [.github/workflows/docs-zip-release.yml](.github/workflows/docs-zip-release.yml) — Workflow
- [DOCS_ZIP_WORKFLOW.md](DOCS_ZIP_WORKFLOW.md) — Guía del workflow
- [../scripts/build_docs_zip.py](../scripts/build_docs_zip.py) — Script
- [../docs/downloads.md](../docs/downloads.md) — Página de descargas
- [../mkdocs.yml](../mkdocs.yml) — Configuración

---

*Última actualización: 2026-06-06*
