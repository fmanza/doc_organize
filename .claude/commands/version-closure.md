# version_closure

Cierre de versión o sesión de trabajo.

## Cuándo usar
- Cierras una feature, hotfix o bloque coherente de cambios
- Estás listo para mergear/release con commit message + changelog

## Inputs requeridos (OBLIGATORIO completar TODOS)

- [ ] **Cambios resumidos**: Qué se implementó (feature, fix, refactor, etc.)
- [ ] **Versión objetivo**: (ej. v0.6.7, v0.7.0)
- [ ] **Archivos modificados**: Módulos/componentes que cambiaron

## Formato de commit

Usar Conventional Commits: `feat:`, `fix:`, `refactor:`, `docs:`, `chore:`, `test:`.
Para releases usar: `release: v<X.Y.Z> - <descripción breve>`.

## Devuelve en este orden

### Commit message
- Formato convencional
- Referencia a los cambios principales incluidos

### Changelog
- Cambios por módulo (new_feature / fix / refactor / docs / chore)
- Indicar archivos o clases afectadas

### Impacto en API pública
- Cambios de firma, parámetros o comportamiento observable
- Deprecaciones introducidas o eliminadas

### Migraciones
- Cambios de esquema, configuración o contratos que requieren acción del consumidor

### Compatibilidad
- Motores afectados
- Versiones Python (rango soportado: 3.12–3.14)

### Rollback
- Pasos concretos para revertir
- Riesgos del rollback

### Checklist final
- [ ] `ruff check src tests` sin errores
- [ ] `mypy src` sin errores
- [ ] `pytest` verde
- [ ] `python -m build` exitoso
- [ ] Versión actualizada en `pyproject.toml`
- [ ] CHANGELOG.md actualizado

### Pruebas ejecutadas o sugeridas
- Lista de pruebas críticas para validar el cierre

## Ejemplo de entrada

```
Cambios: Tres features en doc/render_markdown.py, un fix en html_generator.py, un refactor en metadata/

Versión: v0.6.7

Archivos: src/doc_organize/doc/, src/doc_organize/metadata/
```

## Ejemplo de salida esperada (VERSION)

```markdown
## VERSION CLOSURE

### Commit message
```
feat(doc): add Mermaid export to Markdown renderer

- Implementa `enable_mermaid` parameter
- Fix HTML icon loss in offline exports
- Refactor metadata builder for clarity
```

### Changelog
- **feat**: Mermaid diagram export in Markdown renderer
- **fix**: HTML icons now embedded as base64 for offline compatibility
- **refactor**: metadata builder separates concerns (SRP)

### Impacto API
- Nuevo parámetro: `render_markdown(..., enable_mermaid=False)`
- Sin cambios breaking

### Rollback
- `git revert <commit>`

### Checklist
- [x] ruff check pasa
- [x] mypy src pasa
- [x] pytest pasa
- [x] build exitoso
- [x] pyproject.toml versión actualizada a 0.6.7
- [x] CHANGELOG.md actualizado
```
