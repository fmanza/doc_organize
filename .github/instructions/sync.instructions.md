---
applyTo: "CHANGELOG.md,docs/**,COMPATIBILITY.md,.ai/**"
---
# Sincronización de versiones — CHANGELOG y COMPATIBILITY

> **TL;DR** — Antes de cerrar una versión, verifica que CHANGELOG.md, docs/ y COMPATIBILITY.md
> estén sincronizados. Ejecuta `mkdocs build` sin errores.

---

## Cuándo aplicar estas reglas

Aplica este checklist en la fase **VERSION** de cualquier flujo:

- `feat:` que añade API pública nueva
- `fix:` que cambia comportamiento observable
- `refactor:` con renombramiento de símbolos exportados
- Cierre de sprint o release (slash command `/version-closure`)

---

## Checklist de sincronización obligatorio

### 1. CHANGELOG.md (raíz del repositorio)

- [ ] La versión nueva tiene entrada bajo `## [X.Y.Z] — YYYY-MM-DD`
- [ ] Secciones presentes según cambios: `Added`, `Changed`, `Fixed`, `Removed`, `Deprecated`
- [ ] Cada ítem referencia el módulo afectado: `scanner/`, `converter/`, `dedup/`, `cache/`
- [ ] No hay entradas bajo `Unreleased` que deban estar en la versión cerrada

### 2. docs/CHANGELOG.md (si existe copia en docs/)

- [ ] Contenido idéntico al CHANGELOG.md raíz
- [ ] Si hay divergencia, prevalece el CHANGELOG.md raíz; actualiza docs/CHANGELOG.md

### 3. COMPATIBILITY.md / .ai/COMPATIBILITY.md

- [ ] Versión nueva añadida con columnas: `Versión | Python | Dependencias clave | Estado`
- [ ] Marcada como `✅ Activa` si es la release más reciente
- [ ] Versiones anteriores marcadas como `⚠️ Legacy` o `❌ EOL` según corresponda
- [ ] Si existe `.ai/COMPATIBILITY.md`, sincronizado con `docs/COMPATIBILITY.md`

### 4. pyproject.toml

- [ ] `version = "X.Y.Z"` actualizado y coincide con el CHANGELOG.md
- [ ] `requires-python = ">=3.11"` sin modificar (no incrementar sin decisión explícita)

### 5. MkDocs

- [ ] `mkdocs build` pasa sin errores ni warnings de links rotos
- [ ] Si se crearon páginas nuevas, están en `mkdocs.yml` bajo `nav:`
- [ ] Si se eliminaron páginas, se retiraron de `mkdocs.yml`

---

## Formato de entrada CHANGELOG

```markdown
## [0.2.0] — 2026-05-14

### Added
- `converter/ocr_scheduler.py`: soporte de OCR con motor acelerado por GPU (`use_gpu=True`)

### Fixed
- `dedup/deduplication.py`: corregida colisión de nombres al mover duplicados a `duplicados/`

### Changed
- CLI: `python -m doc_organize scan` ahora acepta `--use-cache`
```

---

## Reglas de versionado (SemVer)

| Tipo de cambio | Incremento |
|---|---|
| API pública nueva sin breaking changes | `MINOR` (0.X.0) |
| Breaking change en API pública | `MAJOR` (X.0.0) |
| Bugfix sin cambio de API | `PATCH` (0.0.X) |
| Cambio solo en docs o tests | `PATCH` (0.0.X) |

---

### 6. `.ai/sessions/*/TRACEABILITY.md` (cierre de sesión)

- [ ] Sección `## Directrices para Futuras IAs` presente y poblada (no vacía, no solo `-`)
- [ ] Cada directriz tiene el formato `**[área]**: <hecho verificable>`
- [ ] Veredicto final es `CLOSED` (o `GO` / `GO_CONDICIONAL` si la sesión queda abierta)

---

## Comando de validación final

```bash
mkdocs build --strict
```

El flag `--strict` convierte warnings en errores, garantizando que no queden links rotos
ni referencias a páginas inexistentes en `mkdocs.yml`.

---

*Actualizado: 2026-05-22*
