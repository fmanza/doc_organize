# PLAN: Integración de `build_docs_zip.py` en CI/CD

## 1. Estado Actual

### Archivos Existentes
- ✅ `.github/scripts/build_docs_zip.py` — Script de empaquetado (completo, funcional)
- ✅ `.github/workflows/docs-zip-release.yml` — Workflow actualmente **simplificado** (sin ZIP)
- ✅ `pyproject.toml` — Incluye dependencies necesarias (mkdocs, material, etc.)

### Restricción Actual en Workflow
- ⏸️ Steps de ZIP/Release están **comentados** (razón: script no existía)
- ⏸️ Workflow solo construye docs con MkDocs
- ⏸️ No genera ZIP, SHA256, ni GitHub Release

---

## 2. PLAN: Integración Completa

### 2.1 Pre-requisitos a Verificar

| Ítem | Status | Nota |
|------|--------|------|
| Script `build_docs_zip.py` existe | ✅ Sí | `.github/scripts/build_docs_zip.py` |
| Script es executable | ⓘ TBD | Verificar permisos en git |
| Workflow path correcto | ⚠️ **ISSUE** | Workflow usa `scripts/` pero script está en `.github/scripts/` |
| `ZIP_PREFIX` variable | ⚠️ **ISSUE** | Dice `doc_calidad-docs`, debería ser `doc_organize-docs` |
| Dependencias instaladas | ✅ Sí | mkdocs, etc. ya en `[docs]` group |
| Directorio `dist/` | ⓘ TBD | Se crea automáticamente por script |

### 2.2 Tareas de Integración

#### **TAREA 1: Corregir nombre del ZIP**
```python
# Actual (INCORRECTO)
ZIP_PREFIX = "doc_calidad-docs"

# Debe ser
ZIP_PREFIX = "doc_organize-docs"
```
**Impacto:** GitHub Release busca `doc_organize-docs-*.zip` por patrón.

---

#### **TAREA 2: Resolver path inconsistencia**
**Opción A (Recomendada):** Mover script a `scripts/` (raíz del proyecto)
```bash
mv .github/scripts/build_docs_zip.py scripts/build_docs_zip.py
# Actualizar referencias en cualquier documentation
```

**Opción B:** Actualizar workflow para usar path `.github/scripts/`
```yaml
- name: '📚 Generate ZIP + Checksums'
  run: |
    python .github/scripts/build_docs_zip.py --builder mkdocs
```

**Decisión:** ⓘ Pendiente de input usuario (recomendación: Opción A → `scripts/` es convención estándar)

---

#### **TAREA 3: Descomentar y restaurar workflow steps**
**Archivo:** `.github/workflows/docs-zip-release.yml`

**Steps a restaurar (actualmente comentados):**
1. `📚 Generate ZIP + Checksums` → invoca `build_docs_zip.py`
2. `🔐 Display checksums for verification` → muestra SHA256
3. `📤 Upload ZIP as artifact` → guarda en GitHub Artifacts
4. `📋 Extract version and prepare release` → extrae version de `pyproject.toml`
5. `🏷️ Create or update GitHub Release` → publica en Releases

**Forma de cambio:**
- Descomentar los 5 steps (actualmente en comentario `# - name: ...`)
- Adaptar indentación YAML si es necesario
- Validar YAML syntax antes de commit

---

#### **TAREA 4: Validar compatibilidad de script**

**Validaciones necesarias:**
1. ¿Script requiere dependencias adicionales? (revisa `import` statements)
   - ✅ Solo módulos stdlib: `argparse`, `hashlib`, `shutil`, `subprocess`, `sys`, `tomllib`, `datetime`, `pathlib`
   - ✅ Sin dependencias externas adicionales

2. ¿Script funciona en Windows y Linux?
   - ✅ `Path()` es cross-platform
   - ✅ `shutil.make_archive()` es cross-platform
   - ⚠️ `subprocess.run()` hereda env vars — validar que funciona con GitHub Actions

3. ¿Paths absolutos vs relativos?
   - ✅ Usa `ROOT = Path(__file__).resolve().parent.parent` (correcto)
   - ✅ Soporta `--output-dir` relativo y absoluto

---

#### **TAREA 5: Documentar cambios**

**Archivos a actualizar:**
- [ ] `README.md` — Sección "Offline Documentation"
- [ ] `CHANGELOG.md` — Entrada `## [Unreleased]` con feature
- [ ] `.github/DECISIONS_LOG.md` — Registrar decisión de habilitar ZIP feature

---

### 2.3 Flujo Post-Integración

```
User: git push origin develop
  ↓
GitHub Actions Workflow Triggered
  ├─ Checkout code
  ├─ Setup Python 3.12
  ├─ Install deps (mkdocs, material-theme, etc.)
  ├─ Build docs: mkdocs build --strict
  ├─ [NEW] Generate ZIP + Checksums: python scripts/build_docs_zip.py
  ├─ [NEW] Display checksums
  ├─ [NEW] Upload artifact (30-day retention)
  ├─ [NEW] Extract version + SHA256
  ├─ [NEW] Create GitHub Release (docs-v{version})
  └─ Success notification

Artifacts:
  ├─ doc_organize-docs-{version}.zip (site/ comprimido)
  ├─ doc_organize-docs-{version}.zip.sha256
  └─ CHECKSUMS.txt (histórico)

GitHub Release:
  └─ docs-v{version} (tag, body con links, ZIP adjunto)
```

---

## 3. Matriz de Decisiones

| Decisión | Opción A | Opción B | Recomendación |
|----------|----------|----------|----------------|
| **Location de script** | `scripts/build_docs_zip.py` (raíz) | `.github/scripts/build_docs_zip.py` | **A** (convención estándar) |
| **ZIP_PREFIX** | Corregir a `doc_organize-docs` | Dejar `doc_calidad-docs` | **Corregir** (branding correcto) |
| **Workflow integración** | Full restore (all 5 steps) | Gradual (ZIP solo, sin Release) | **Full** (feature completa) |
| **Documentación** | Update README + CHANGELOG | Solo comentarios en YAML | **Update** (transparencia) |

---

## 4. Estimación de Effort

| Tarea | Complejidad | Tiempo Estimado |
|-------|------------|-----------------|
| Corregir ZIP_PREFIX | ⭐ Trivial | ~2 min |
| Mover script a `scripts/` (si Opción A) | ⭐ Trivial | ~2 min |
| Descomentar workflow steps | ⭐ Trivial | ~3 min |
| Validar YAML + testing local | ⭐⭐ Simple | ~10 min |
| Actualizar docs (README, CHANGELOG) | ⭐⭐ Simple | ~15 min |
| Commit + Push | ⭐ Trivial | ~3 min |
| **TOTAL** | — | ~35 min |

---

## 5. Riesgos Pre-Integración

- ⚠️ **ZIP_PREFIX incorrecto** → GitHub Release busca patrón incorrecto → artifacts no cargados
- ⚠️ **Path inconsistencia** → Workflow falla con "script not found" → CI/CD red
- ⚠️ **YAML no validado** → GH Actions rechaza workflow → build bloqueado
- ⚠️ **dist/ no existe** → Script falla al crear ZIP → CI/CD red

Mitigation: Validar YAML, hacer dry-run en local, verificar paths.

---

## 6. Próximos Pasos (Pending User Input)

1. **¿Confirmar decisiones?** (Location, ZIP_PREFIX, documentación)
2. **¿Autorizar IMPLEMENT?** (aplica cambios, testa, commit)
3. **¿Testing pre-commit?** (ejecutar script localmente)

**Estado:** 🔴 BLOCKED ON AUDIT_PLAN (vea abajo)
