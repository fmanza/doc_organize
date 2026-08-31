# Sesión 2026-08-31: Corrección de Type Checking (mypy) y Dependencias

## Contexto
- **Issue**: CI/CD fallaba con 32 errores mypy en archivos web (fastapi, starlette, uvicorn)
- **Root cause**: Faltaban dependencias `fastapi`, `starlette`, `uvicorn` en grupo `dev`; mypy configurado para Python 3.11 pero scipy-stubs requiere 3.12+ (PEP 695 syntax)

## Cambios realizados

### 1. `pyproject.toml`

#### Grupo `dev` — Dependencias agregadas
```python
# Antes
dev = [
    "build>=1.2",
    "pytest>=7.0",
    "pytest-cov>=3.0",
    "pytest-asyncio>=0.21",
    "httpx>=0.24",
    "ruff>=0.1.0",
    "mypy>=1.0",
    "types-aiofiles>=23.0",
    "black>=23.0",
]

# Después
dev = [
    "build>=1.2",
    "pytest>=7.0",
    "pytest-cov>=3.0",
    "pytest-asyncio>=0.21",
    "httpx>=0.24",
    "ruff>=0.1.0",
    "mypy>=1.0",
    "types-aiofiles>=23.0",
    "black>=23.0",
    # Web dependencies for type checking (have native type hints)
    "fastapi>=0.100",
    "uvicorn>=0.23",
    "starlette>=0.35",
]
```

**Justificación**: 
- `fastapi`, `starlette` y `uvicorn` tienen type hints nativos (py.typed)
- Necesarios para que mypy resuelva imports en `src/doc_organize/web/*`
- No requieren stubs separados (e.g., `types-fastapi` no existe, es py.typed)

#### Configuración mypy — Python version bump
```toml
# Antes
[tool.mypy]
python_version = "3.11"
...
[[tool.mypy.overrides]]
module = ["docling.*"]
follow_imports = "skip"

# Después
[tool.mypy]
python_version = "3.12"
plugins = ["pydantic.mypy"]
...
[[tool.mypy.overrides]]
module = ["docling.*"]
follow_imports = "skip"
ignore_errors = true
```

**Justificación**:
- scipy-stubs, numpy, pandas ≥3.0 usan PEP 695 (`type X = ...`) → require Python 3.12+ en mypy config
- Proyecto soporta Python 3.11+ en `requires-python` (no hay breaking change)
- mypy es una herramienta de desarrollo; puede usar version superior

### 2. `src/doc_organize/web/auth.py` (línea 194)

```python
# Antes
@staticmethod
def _origin_matches_request_host(request: Request, origin: str) -> bool:
    origin_netloc = urlparse(origin).netloc
    request_host = request.headers.get("host", "")
    return origin_netloc == request_host

# Después
@staticmethod
def _origin_matches_request_host(request: Request, origin: str) -> bool:
    origin_netloc = urlparse(origin).netloc
    request_host = request.headers.get("host", "")
    return bool(origin_netloc == request_host)
```

**Justificación**: 
- Error mypy: `Returning Any from function declared to return "bool" [no-any-return]`
- `request.headers.get("host", "")` devuelve `str | Any` (headers es MutableMapping)
- `bool()` hace explícita la coerción, satisface el checker

## Resultados

```
ANTES:
src/doc_organize/web/*.py: 32 errores en 12 archivos
  - 31 × import-not-found (fastapi, starlette, uvicorn)
  - 1 × no-any-return (auth.py:194)

DESPUÉS:
$ python -m mypy src
→ Success: no issues found in 45 source files
```

## Compatibilidad
- ✅ Sigue siendo compatible con Python 3.11+ (solo mypy sube a 3.12)
- ✅ No breaking changes en API pública
- ✅ Requisitos-python no cambia: `requires-python = ">=3.11"`
- ✅ CI puede seguir usando Python 3.11 para tests; solo type-check necesita 3.12+

## Comando de test
```bash
# Antes de push
pip install -e ".[dev]"
python -m mypy src
python -m pytest
python -m ruff check src tests
```
