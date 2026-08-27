# Instrucciones para Claude Code — doc_organize

Este fichero proporciona guía a Claude Code cuando trabaja con código de doc_organize.

---

## ⚠️ Notas importantes

**Lee primero**: [`.github/SHARED_INSTRUCTIONS.md`](.github/SHARED_INSTRUCTIONS.md) para arquitectura, SOLID, patrones y políticas comunes.

Esta página contiene **solo especificidades de doc_organize**.

---

## Slash commands disponibles

Usa estos comandos para activar flujos estructurados:

- `/new-feature` — nueva funcionalidad (PLAN → AUDIT_PLAN → IMPLEMENT → AUDIT_CODE → VERSION)
- `/hotfix` — corrección acotada de bug
- `/refactor` — refactor sin cambios funcionales
- `/audit-code` — auditoría técnica independiente
- `/security-review` — revisión de seguridad

---

## Configuración de Claude Code

### Hooks y PostToolUse

Lee [`.claude/README.md`](.claude/README.md) para:
- `settings.json` — configuración de hooks (ruff, mypy, pytest)
- `settings.local.json` — personalización local

### Comandos de desarrollo

```bash
python -m ruff check src tests       # lint
python -m ruff format src tests      # format
python -m mypy src                   # type-check
python -m pytest                     # todos los tests
python -m build                      # build package
mkdocs serve                         # documentación local (http://127.0.0.1:8000)
mkdocs build                         # genera sitio estático en /site
```

---

## Formato de commits

Usar [Conventional Commits](https://www.conventionalcommits.org/):

```
feat:     nueva funcionalidad
fix:      corrección de bug
refactor: cambio sin impacto funcional
test:     solo tests
docs:     solo documentación
chore:    mantenimiento
```

---

## Documentación Obligatoria

### Cuándo es CRÍTICA

- ✅ Nueva clase pública → docstring + ejemplo
- ✅ Cambio de API pública → actualizar guías
- ✅ Refactor con breaking changes → guía de migración

### MkDocs — cuándo actualizar

- ✅ Módulo o clase pública nueva → añadir entry en `mkdocs.yml` bajo `nav:`
- ✅ Antes de cerrar una versión → `mkdocs build` debe pasar sin errores ni warnings de links rotos
- ✅ Verificar localmente con `mkdocs serve` antes de publicar

**Bloquea PR/release**: `mkdocs build` falla o tiene links rotos.

### Estándares de Docstrings (Google-style)

```python
class MyService:
    """Descripción breve (1-2 líneas).

    Descripción detallada si es necesario.

    Attributes:
        attr1 (str): Descripción

    Example:
        >>> service = MyService()
        >>> result = service.do_something()
        >>> print(result)
        'expected'
    """
```

---

*Actualizado: 2026-04-27*
