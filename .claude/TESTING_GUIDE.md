# TESTING_GUIDE.md

**Versionado**: v0.10.0
**Propósito**: Patrones and best practices para escribir tests deterministas y reutilizables en doc_organize

> Usa este archivo como referencia al escribir tests como parte de IMPLEMENT, `/audit-code`, o `/new-feature`.

---

## Principios Generales

### 1. Determinismo
Todo test debe producir **exactamente el mismo resultado** dado el mismo código, sin:
- Timestamps aleatorios o UUIDs
- Dependencias en orden de filas de BD
- Mock dependencies que varían por sesión

### 2. Aislamiento
Cada test es independiente:
- Setup propio (fixture)
- Teardown propio (cleanup)
- Sin estado compartido con otros tests
- Parallelizable (caso ideal)

### 3. Rapidez
Tests deben ser rápidos para feedback immediate:
- Unitarios: < 50ms
- Integración: < 5s
- End-to-end: < 30s
- Evitar sleep, network calls, DB queries lentas

### 4. Legibilidad
Test code es documentación:
- Nombre descriptivo: `test_connection_pool_recycles_after_timeout()`
- Arrange-Act-Assert pattern
- Comments para lógica no obvia

---

## Fixtures Comunes por Módulo

### Fixtures Globales (conftest.py)

```python
# tests/conftest.py — patrón real, ver el fichero completo en el repo
import pytest

@pytest.fixture
def native_pdf(tmp_path: Path) -> Path:
    """PDF con una capa de texto real embebida (via matplotlib)."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    path = tmp_path / "native.pdf"
    fig = plt.figure(figsize=(8.27, 11.69))
    fig.text(0.1, 0.7, "Documento de prueba", fontsize=14)
    fig.savefig(path, format="pdf")
    plt.close(fig)
    return path

@pytest.fixture
def scanned_pdf(tmp_path: Path) -> Path:
    """PDF sin capa de texto (imagen renderizada) — dispara detección de OCR."""
    from PIL import Image, ImageDraw
    path = tmp_path / "scanned.pdf"
    img = Image.new("RGB", (1240, 1754), color="white")
    ImageDraw.Draw(img).text((80, 200), "Documento escaneado", fill="black")
    img.save(path, "PDF", resolution=150.0)
    return path
```

**Guía:**
- Fixtures de documentos reales (no mocks) para los tests `@pytest.mark.slow` que ejercitan Docling
- `tmp_path` de pytest para aislamiento — nunca escribir en el repo real
- Nombre debe empezar por `test_` o usar el marker apropiado (`slow`, `asyncio`)

### Fixtures por Módulo: scanner/ y converter/

```python
# tests/unit/conftest.py (o al inicio del fichero de test)
import pytest
from doc_organize.scanner import DocumentScanner
from doc_organize.converter import DocumentConverter

@pytest.fixture
async def scanner():
    async with DocumentScanner() as s:
        yield s

@pytest.fixture
async def converter():
    async with DocumentConverter() as c:
        yield c
```

### Fixtures por Módulo: auth/

```python
from doc_organize.auth import AuthStore

@pytest.fixture
async def auth_store(tmp_path):
    async with AuthStore(tmp_path / "auth.db") as store:
        yield store

# Uso: crear un tenant+usuario real (SQLite en tmp_path, no un mock)
async def test_authenticate_succeeds(auth_store):
    tenant = await auth_store.create_tenant("Acme Corp")
    await auth_store.create_user(tenant.id, "alice", "s3cr3t-password")
    user = await auth_store.authenticate(tenant.id, "alice", "s3cr3t-password")
    assert user is not None
```

---

## Patrón: Snapshot Testing

Use snapshots para validar salidas complejas (Markdown, JSON) sin hardcoding expected output.

### Setup

```bash
# Install plugin
pip install pytest-snapshot

# Crear snapshot first time
python -m pytest tests/unit/test_converter.py::test_convert_native_pdf --snapshot-update

# Subs snapshots stored en tests/doc/__snapshots__/
```

### Ejemplo: Render Markdown

```python
# tests/doc/test_render_markdown.py
import pytest
from doc_organize.doc.render import MarkdownRenderer

def test_markdown_render_schema(sample_document_data, snapshot):
    """Validate Markdown output matches snapshot."""
    renderer = MarkdownRenderer()
    output = renderer.render(sample_document_data)

    # Snapshot auto-compares output vs __snapshots__/test_render_markdown.ambr
    assert output == snapshot
```

** **Excepciones de Snapshot:**

Snapshot NO debe incluir:
- Timestamps (use `datetime.now()` replacement)
- UUIDs (use fixed values)
- Absolute paths (use relative o placeholders)

```python
# INCORRECTO
output = f"Generated: {datetime.now()}"
snapshot = "Generated: 2026-04-10 12:34:56.123456"
# Cada run es distinto!

# CORRECTO
output = f"Generated: 2026-04-10T12:00:00Z"  # Fixed
snapshot = "Generated: 2026-04-10T12:00:00Z"
# Sempre igual
```

---

## Datos Deterministas

### Timestamps

```python
# DON'T
from datetime import datetime
test_date = datetime.now()  # Changes every run!

# DO
test_date = datetime.fromisoformat("2026-04-10T12:00:00Z")

# Using in fixtures
@pytest.fixture
def now_fixed():
    return datetime.fromisoformat("2026-04-10T12:00:00Z")

# Using in mocks
mocker.patch("doc_organize.datetime.now", return_value=now_fixed)
```

### Order de Filas

```python
# DON'T
rows = cursor.execute("SELECT * FROM users")
# Order is undefined!

# DO
rows = cursor.execute("SELECT * FROM users ORDER BY id ASC")
# or
rows = sorted(cursor.execute("SELECT * FROM users"), key=lambda r: r[0])
```

### Random Data

```python
# DON'T
import random
random_value = random.randint(1, 100)  # Changes every run!

# DO
# Use seed OR fixed values
random.seed(42)  # Deterministic seed
test_values = [1, 2, 3]  # Hard-coded

@pytest.fixture
def seeded_random():
    random.seed(42)
    yield random
    random.seed(None)  # Reset after
```

---

## Pytest Patterns

### Markers para Categorización

```python
# tests/conftest.py (add at top)
def pytest_configure(config):
    config.addinivalue_line(
        "markers", "slow: marks tests as slow (deselect with '-m \"not slow\"')"
    )
    config.addinivalue_line(
        "markers", "integration: marks tests requiring external services"
    )
    config.addinivalue_line(
        "markers", "async: marks async tests"
    )

# Usage
@pytest.mark.slow
def test_full_schema_introspection():
    ...

@pytest.mark.integration
def test_scan_folder_with_real_docling():
    ...

@pytest.mark.async
async def test_async_query_executor():
    ...

# CLI
python -m pytest -m "not slow"  # Skip slow tests
python -m pytest -m "integration"  # Only integration
```

### Parametrización

```python
# Good: Small, deterministic data
@pytest.mark.parametrize("extension,expected_converter", [
    (".pdf", "docling"),
    (".docx", "docling"),
    (".xlsx", "docling"),
])
def test_converter_resolution(extension, expected_converter):
    assert resolve_converter(extension) == expected_converter

# BAD: Too large, random
@pytest.mark.parametrize(
    "data",
    [generate_random_row() for _ in range(1000)]
)
def test_bulk_insert(data):
    ...  # SLOW! Random data! Hard to debug failures!
```

### Fixtures con Request (indirect parametrization)

```python
@pytest.fixture
def cache_backend(request, tmp_path):
    """Yield different cache backends based on marker."""
    if "in_memory" in request.keywords:
        return CacheManager(":memory:")
    elif "sqlite_file" in request.keywords:
        return CacheManager(tmp_path / "cache.db")

@pytest.mark.in_memory
def test_cache_roundtrip_in_memory(cache_backend):
    ...

@pytest.mark.sqlite_file
def test_cache_roundtrip_sqlite_file(cache_backend):
    ...
```

---

## Async Contract Validation

`doc_organize` es async-first (scanner, converter, cache, auth). Valida comportamiento
determinista con datos de entrada fijos:

```python
# tests/unit/test_scanner.py
import pytest

class TestScannerContract:
    """Validate scanner produces deterministic, stable output."""

    async def test_scan_folder_returns_stable_order(self, tmp_path):
        """Mismo árbol de carpetas siempre produce el mismo orden de resultados."""
        async with DocumentScanner() as scanner:
            first = [doc.path async for doc in scanner.scan(tmp_path)]
            second = [doc.path async for doc in scanner.scan(tmp_path)]
        assert first == second

    @pytest.mark.parametrize("extension", [
        ".pdf",
        ".docx",
        ".file_con_ñ_unicode.xlsx",
    ])
    async def test_scan_folder_detects_extension(self, tmp_path, extension):
        """Cada extensión soportada es detectada correctamente."""
        (tmp_path / f"doc{extension}").touch()
        async with DocumentScanner() as scanner:
            found = [doc.path async for doc in scanner.scan(tmp_path)]
        assert any(p.suffix == extension for p in found)
```

---

## Cobertura Esperada por Tipo de Cambio

| Tipo | Cobertura | Regla | Ejemplo |
|------|-----------|-------|---------|
| **new_feature** | 80%+ | Lógica principal covered, ok si edge cases pending | Feature: Duplicates Resolver → 80% cobertura |
| **hotfix** | 100% del path afectado | Cada línea del bug fix tiene test | Bug: NoneType en ScanEvent.data → 100% cobertura |
| **refactor** | Pre-cobertura = Post-cobertura | No desmejorar cobertura | Refactor: Renombrar métodos → Misma cobertura que antes |
| **audit-code** / **sec-review** | N/A (no modifica) | Solo auditoría | N/A |

### Verificar Cobertura

```bash
# Full report
python -m pytest tests/ --cov=src --cov-report=html

# Enfocado en un módulo
python -m pytest tests/metadata/ --cov=src/doc_organize/metadata --cov-report=term-missing

# Reporte combinado (pre-post)
python -m pytest tests/ --cov=src --cov-report=json-summary
# Guardar en coverage-pre.json
# Hacer cambios
# python -m pytest tests/ --cov=src --cov-report=json-summary > coverage-post.json
# diff coverage-pre.json coverage-post.json
```

---

## Debugging de Tests Fallidos

### Cuando test falla, sigue estos pasos:

1. **Ejecuta aislado**
   ```bash
   python -m pytest tests/module/test_X.py::TestClass::test_method -vv
   ```

2. **Captura salida full**
   ```bash
   python -m pytest tests/ -vv --tb=long --capture=no 2>&1 | tee debug.log
   ```

3. **Usa breakpoint**
   ```python
   def test_something():
       result = function_under_test()
       breakpoint()  # Pausa aquí, explora con `print()`, `dir()`, etc.
       assert result == expected
   ```

4. **Add logging**
   ```python
   import logging
   logger = logging.getLogger(__name__)

   def test_with_logging():
       logger.debug(f"Starting test with: {data}")
       result = process(data)
       logger.debug(f"Result: {result}")
       assert result == expected
   ```

5. **Verifica fixtures**
   - Están siendo inicializadas correctamente?
   - Scope es correcto (session vs function)?
   - Cleanup está sucediendo?

---

## Anti-patterns to Avoid

| Anti-pattern | Problema | Solución |
|---|---|---|
| `sleep(1)` in tests | Lento, no determinista | Use mocks, fixtures, deterministic waits |
| `datetime.now()` | Timestamp varía | Use fixed `datetime.fromisoformat()` |
| `random.randint()` | Resultado varía | Use `random.seed()` o hardcoded values |
| Test toca BD real | Lento, requiere setup | Use sqlite :memory: o mock |
| Test toca API externa | Lento, unreliable | Use `responses` o mock library |
| Shared state between tests | Flaky tests | Use fixtures con scope=function |
| Hardcoded paths | Fails on other machines | Use `Path(__file__).parent / "fixtures"` |

---

## Size Expectations

| Categoría | LoC | Tiempo | Scope |
|-----------|-----|--------|-------|
| Unit test | 10-30 | < 50ms | Una función |
| Integration test | 30-100 | < 5s | Módulo (p.ej. metadata) |
| End-to-end test | 50-200 | < 30s | Feature completa |
| Fixture | 5-50 | N/A | Support para tests |

---

## Referencias

- `pytest.ini` — Configuration, markers, plugins
- `tests/ ` — Existing tests as examples
- `.github/instructions/tests.instructions.md` — Broader testing policy
- TESTING_GUIDE.md (este archivo) — Quick reference patterns

---

## Versión

| Versión | Fecha | Cambios |
|---------|-------|---------|
| v0.6.7 | 10 abr 2026 | Initial: fixtures, snapshot, sync/async, debugging |
