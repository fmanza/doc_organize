# 🤖 Workflow: Docs ZIP Release

Automatización para generar y publicar la documentación en ZIP en GitHub Releases.

---

## 📋 Descripción

El workflow **`docs-zip-release.yml`** se dispara automáticamente cuando:

1. **Push a `main` o `develop`** — Si hay cambios en documentación
2. **Manualmente** — Desde la pestaña "Actions" en GitHub UI

**Tareas**:
- 🏗️ Build documentación con Zensical
- 📚 Generar ZIP comprimido
- 🔐 Calcular SHA256 para integridad
- 📤 Crear/actualizar GitHub Release
- 📎 Adjuntar ZIP + checksums

---

## 🚀 Uso

### Automático (Recomendado)

El workflow se dispara automáticamente:

```bash
# Cambiar documentación en branch develop
git add docs/
git commit -m "docs: actualizar guía"
git push origin develop

# ✅ Workflow ejecutado automáticamente
# 📦 Release generada en: https://github.com/fmanza/doc_organize/releases
```

### Manual desde GitHub UI

1. Ir a: **GitHub → Actions → "📦 Build & Publish Docs ZIP"**
2. Hacer clic en: **"Run workflow"**
3. Seleccionar rama: `main` o `develop`
4. Confirmar: **"Run workflow"**

---

## 📊 Salida del Workflow

```
✅ Steps completados:

1. Checkout code
   └─ Repository clonado (develop branch)

2. Setup Python 3.12
   └─ Python 3.12 + cache de pip

3. Install dependencies
   └─ mkdocs, zensical, mkdocstrings

4. Build documentation
   └─ zensical build --strict
   └─ ✅ 150+ archivos HTML generados

5. Generate ZIP + Checksums
   └─ dist/doc_organize-docs-0.10.0.zip (2.45 MB)
   └─ dist/doc_organize-docs-0.10.0.zip.sha256
   └─ dist/CHECKSUMS.txt

6. Display checksums
   └─ SHA256: abc123def456...

7. Create GitHub Release
   └─ Tag: docs-v0.10.0
   └─ Release: "📚 Documentation Offline v0.10.0"
   └─ Artifacts: ZIP + checksums adjuntos

✅ Release publicada:
   https://github.com/fmanza/doc_organize/releases/tag/docs-v0.10.0
```

---

## 📦 Archivos Generados

| Archivo | Tamaño | Propósito |
|---|---|---|
| `doc_organize-docs-{version}.zip` | ~2-3 MB | ZIP de documentación comprimida |
| `doc_organize-docs-{version}.zip.sha256` | ~100 bytes | SHA256 para validar integridad |
| `CHECKSUMS.txt` | ~200 bytes | Historial de checksums (append) |

**Ubicación**: En la **GitHub Release** de cada versión

---

## 🔐 Validar Integridad

### En GitHub

1. Descargar ZIP desde: https://github.com/fmanza/doc_organize/releases
2. Descargar `.sha256` adjunto a la misma release
3. Ejecutar en terminal:

```bash
# Descargar desde release
wget https://github.com/fmanza/doc_organize/releases/download/docs-v0.10.0/doc_organize-docs-0.10.0.zip
wget https://github.com/fmanza/doc_organize/releases/download/docs-v0.10.0/doc_organize-docs-0.10.0.zip.sha256

# Validar (Linux/Mac)
sha256sum -c doc_organize-docs-0.10.0.zip.sha256
# Output: doc_organize-docs-0.10.0.zip: OK ✅

# Validar (Windows PowerShell)
(Get-FileHash doc_organize-docs-0.10.0.zip -Algorithm SHA256).Hash
```

### En el navegador (GitHub Release)

1. Abrir release en GitHub
2. Copiar SHA256 del body de la release
3. Comparar con el de tu archivo descargado

---

## 🔧 Configuración del Workflow

### Triggers (Cuándo se ejecuta)

```yaml
on:
  push:
    branches: [main, develop]
    paths:
      - 'docs/**'
      - 'zensical.toml'
      - 'pyproject.toml'
      - '.github/workflows/docs-zip-release.yml'
  workflow_dispatch:  # Manual desde GitHub UI
```

**Explicación**:
- ✅ Se ejecuta en **push a main/develop**
- ✅ **Solo si hay cambios** en docs/, zensical.toml, etc.
- ✅ Se puede **ejecutar manualmente** sin cambios

### Permisos Necesarios

```yaml
permissions:
  contents: write  # Necesario para crear releases
```

Este workflow necesita permiso de **escritura** para crear GitHub Releases.

**Verificar en GitHub**:
- Settings → Actions → General → Workflow permissions
- Seleccionar: "Read and write permissions" ✅

---

## 🐛 Troubleshooting

### El workflow no se ejecuta

**Causa**: Cambios en rama no configurada o permisos insuficientes

**Solución**:
1. Verificar que cambios están en `docs/`, `zensical.toml`, etc.
2. Ir a Settings → Actions → General
3. Seleccionar "Read and write permissions" ✅

### La release no se crea

**Causa**: Token de GitHub o permisos insuficientes

**Solución**:
1. Verificar que `permissions.contents: write` está en el workflow
2. Si es fork privado, configurar:
   - Settings → Actions → General → "Create and approve pull requests" ✅

### SHA256 no coincide

**Causa**: Archivo corrupto o descarga incompleta

**Solución**:
1. Descargar ZIP nuevamente
2. Ejecutar `sha256sum -c *.sha256` nuevamente
3. Si el problema persiste, reportar issue

---

## 📊 Monitoreo

### Historial de Workflows

Ver en GitHub: **Actions → "📦 Build & Publish Docs ZIP"**

Cada ejecución muestra:
- ✅ Estado (success/failure)
- ⏱️ Duración (~1-2 minutos)
- 📦 Artifacts generados
- 📋 Logs detallados

### Releases Publicadas

Ver en GitHub: **Releases → Releases** (con etiqueta `docs-v*`)

Cada release incluye:
- 📝 Body con instrucciones
- 📎 ZIP + checksums
- 📌 Commit y fecha asociada

---

## 🔄 Próximas Mejoras (Opcionales)

- [ ] Publicar ZIP en PyPI como documentación adicional
- [ ] Notificar automáticamente en Slack/Discord
- [ ] Incluir cambios de documentación en CHANGELOG
- [ ] Generar índice HTML de versiones anteriores
- [ ] Comprimir con `brotli` para menor tamaño

---

## 🔗 Enlaces Relacionados

- [docs-zip-release.yml](.github/workflows/docs-zip-release.yml) — Workflow completo
- [build_docs_zip.py](../scripts/build_docs_zip.py) — Script de generación
- [downloads.md](../docs/downloads.md) — Página de descargas
- [docs-zip-setup-guide.md](docs-zip-setup-guide.md) — Setup y CI/CD

---

*Última actualización: 2026-06-06*
