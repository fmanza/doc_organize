# doc_organize

> Sistema de extracción de contenido de documentos en Markdown y JSON documentación y organización.

## 🚀 Descripción

Proyecto desarrollado como parte de la arquitectura modular de utilidades IA.

## 📋 Requisitos

- Python 3.10+
- pip o conda

## 🔧 Instalación

### Desarrollo

```bash
# Crear entorno virtual
python -m venv .venv
source .venv/bin/activate  # En Windows: .venv\\Scripts\\activate

# Instalar con dependencias de desarrollo
pip install -e ".[dev,docs]"
```

### Producción

```bash
pip install doc_organize
```

## 📚 Uso Básico

```python
from doc_organize import MyService

service = MyService()
result = service.do_something()
```

## 🧪 Testing

```bash
# Ejecutar todos los tests
python -m pytest

# Con cobertura
python -m pytest --cov=src

# Tests específicos
python -m pytest tests/unit/test_module.py::TestClass::test_method
```

## 🔍 Linting y Type Checking

```bash
# Linting con ruff
python -m ruff check src tests

# Formateo automático
python -m ruff format src tests

# Type checking con mypy
python -m mypy src
```

## 📖 Documentación

```bash
# Servir documentación localmente
mkdocs serve

# Generar documentación estática
mkdocs build
```

## 🏗️ Estructura del Proyecto

```
doc_organize/
├── src/
│   └── doc_organize/
│       ├── __init__.py
│       ├── core/
│       │   └── __init__.py
│       └── utils/
│           └── __init__.py
├── tests/
│   ├── unit/
│   ├── integration/
│   └── conftest.py
├── docs/
│   └── examples/
├── .github/
│   └── copilot-instructions.md   ← instrucciones para GitHub Copilot
├── .claude/
│   └── settings.json             ← configuración para Claude Code
├── AGENTS.md                      ← instrucciones para Codex
├── pyproject.toml
├── README.md
├── CLAUDE.md
└── doc_organize.code-workspace
```

## 🤖 IA y Desarrollo

### Claude Code

Este proyecto está configurado para trabajar con Claude Code.

### Codex en VS Code

Este proyecto incluye `AGENTS.md` para orientar a Codex. En VS Code, instala la extensión `OpenAI.chatgpt`, abre el workspace y trabaja desde el panel de Codex.

### Comandos Disponibles

- `/new-feature` — Nueva funcionalidad
- `/hotfix` — Corrección de bug
- `/refactor` — Refactoring
- `/audit-code` — Auditoría técnica
- `/security-review` — Revisión de seguridad

## 📝 Convenciones

### Commits

Usar [Conventional Commits](https://www.conventionalcommits.org/):

```
feat:     nueva funcionalidad
fix:      corrección de bug
refactor: cambio sin impacto funcional
test:     solo tests
docs:     solo documentación
chore:    mantenimiento
```

## 📧 Contacto

Autor: Paco Manzano
Email: fmanzano.trabajo@gmail.com

## 📄 Licencia

MIT License. Ver LICENSE para más detalles.

---

*Generado con Project Generator v3*
