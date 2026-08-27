# ⚙️ Runtime & Environment - doc_organize

## Development Environment

### Prerequisites

- Python ≥3.12
- pip, virtualenv (o conda)
- Git
- (Opcional) Docker Compose — para tests de integración con BD reales

### Setup

```bash
git clone <repo>
cd doc_organize
python -m venv venv
source venv/bin/activate       # Linux/Mac
# venv\Scripts\activate        # Windows
pip install -e ".[dev]"
pip install -e ".[docs]"       # Para mkdocs build
```

### Project Root

| Ruta | Propósito |
|---|---|
| `src/doc_organize/` | Código fuente (namespace package) |
| `tests/` | Tests pytest (discovery automático) |
| `scripts/` | Utilidades: `build_docs_zip.py`, `check_env.py` |
| `docs/` | Documentación MkDocs (fuente) |
| `site/` | Salida de build (git-ignored) |
| `dist/` | ZIP offline + checksums |
| `.ai/` | Contexto persistente para IAs |
| `.github/` | Workflows, agents, prompts, instrucciones |
| `.claude/` | Settings de Claude Code (hooks, commands) |

## Essential Commands

```bash
# Tests
python -m pytest
python -m pytest -v --cov=src/doc_organize --cov-report=html

# Lint y formato
python -m ruff check src tests
python -m ruff format src tests

# Type-checking
python -m mypy src

# Build del paquete
python -m build

# Documentación
python -m mkdocs build --strict   # Build completo
python -m mkdocs serve            # Preview local en http://127.0.0.1:8000
zensical build                    # Alternativa (mismo mkdocs.yml)
zensical serve

# Distribución offline
python scripts/build_docs_zip.py  # Genera dist/doc_organize-docs-{version}.zip + SHA256

# Verificación del entorno
python scripts/check_env.py
```

## Database Testing

- **SQLite in-memory** (`":memory:"`): BD por defecto en todos los tests unitarios
- **Docker Compose**: `docker-compose.yml` con MariaDB, PostgreSQL (tests de integración opcionales)
- **Test isolation**: Cada test abre su propia conexión; sin estado compartido entre tests
- **Markers**: `@pytest.mark.asyncio` para tests async; `@pytest.mark.integration` para tests con BD reales

## Async Runtime

- **Event loop:** `asyncio.new_event_loop()` (aislamiento por test)
- **Marker:** `@pytest.mark.asyncio` configurado vía `pytest-asyncio`
- **Timeout:** 30 s por defecto (configurable en `pytest.ini`)

## CI/CD

- **`.github/workflows/`**: GitHub Actions — test, lint, mypy, coverage, docs build/deploy, docs-zip-release
- **Branches**: `main` (estable), `develop` (integración), `feature/*` (trabajo en curso)
- **Gate de merge**: ≥90% coverage + all checks pass + `mkdocs build --strict` limpio
- **Docs publish**: `github-pages` en cada push a `main` con cambios en `docs/`
- **ZIP release**: Workflow `docs-zip-release.yml` publica release `docs-vX.Y.Z` automáticamente

## Configuración de Claude Code

Ver `CLAUDE.md` para:
- Slash commands disponibles (`/new-feature`, `/hotfix`, etc.)
- Hooks PostToolUse (ruff → mypy → pytest)
- Flujos estructurados por fases

## Dependencias principales

| Dependencia | Versión mínima | Rol |
|---|---|---|
| `sqlalchemy` | ≥2.0.46 | Abstracción de engine y SQL |
| `pandas` | ≥3.0.0 | DataFrames para operaciones bulk |
| `openpyxl` | ≥3.1.5 | Generación de Excel |
| `python-docx` | ≥1.2.0 | Generación de Word |
| `oracledb` | ≥3.4.0 | Driver Oracle sync/async |
| `jinja2` | ≥3.0.0 | Templates HTML para doc/ y comparar/reporters/ |
| `util` | git+develop | Medición de tiempos (`medir_tiempo`) |

### Dependencias opcionales

```bash
pip install -e ".[analysis]"   # graphviz≥0.20 (grafos de relaciones)
pip install -e ".[doc-svg]"    # cairosvg≥2.7 (SVG→PNG en doc/)
pip install -e ".[docs]"       # zensical + mkdocs-material + mkdocstrings[python]
pip install -e ".[dev]"        # pytest + ruff + mypy + build + tipos
```
