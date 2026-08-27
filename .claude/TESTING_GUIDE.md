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
# tests/conftest.py
import pytest

@pytest.fixture(scope="session")
def temp_sqlite_db(tmp_path_factory):
    """SQLite in-memory test database, reusable per session."""
    import sqlite3
    db_path = tmp_path_factory.mktemp("db") / "test.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute("""
        CREATE TABLE test_table (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            value INTEGER
        )
    """)
    conn.commit()
    yield conn
    conn.close()

@pytest.fixture
def mock_logger(mocker):
    """Mock logger for inspecting log calls."""
    return mocker.patch("doc_organize.logger")

@pytest.fixture
def deterministic_timestamp():
    """Fixed timestamp for reproducible tests."""
    return "2026-04-10T12:00:00Z"
```

**Guía:**
- Use `scope="session"` si BD no cambia entre tests (rapidez)
- Use `scope="function"` si BD necesita reset (aislamiento)
- Name must start with `test_` o usar pytest marker

### Fixtures por Módulo: metadata/

```python
# tests/metadata/conftest.py
import pytest
from doc_organize.metadata import SchemaIntrospector

@pytest.fixture
def postgres_introspector(mocker):
    """Mocked PostgreSQL introspector."""
    mock_conn = mocker.Mock()
    mock_conn.execute.return_value = [
        ("schema1", "table1", "id", "INTEGER", False),
        ("schema1", "table1", "name", "VARCHAR", True),
    ]
    return SchemaIntrospector(mock_conn, dialect="postgres")

@pytest.fixture
def test_schema():
    """Deterministic schema structure for tests."""
    return {
        "name": "test_schema",
        "tables": [
            {
                "name": "users",
                "columns": [
                    {"name": "id", "type": "INTEGER", "pk": True},
                    {"name": "email", "type": "VARCHAR", "pk": False},
                ]
            }
        ]
    }
```

### Fixtures por Módulo: connection/

```python
# tests/connection/conftest.py
import pytest
from doc_organize.connection import PoolFactory

@pytest.fixture
def mock_pool(mocker):
    """Mocked connection pool."""
    pool = mocker.Mock()
    pool.get.return_value = mocker.Mock()  # mock connection
    pool.close.return_value = None
    return pool

@pytest.fixture
def pool_factory(mocker):
    """Factory for test pools."""
    return PoolFactory(
        engine_type="sqlite",
        params={"path": ":memory:"}  # in-memory always deterministic
    )
```

### Fixtures por Módulo: doc/render/

```python
# tests/doc/conftest.py
import pytest
from pathlib import Path

@pytest.fixture
def template_dir():
    """Directory with Jinja2 templates for rendering."""
    return Path(__file__).parent / "fixtures" / "templates"

@pytest.fixture
def sample_document_data():
    """Deterministic document data for rendering tests."""
    return {
        "title": "Test Database Documentation",
        "tables": [
            {
                "name": "employees",
                "columns": [
                    {"name": "id", "type": "INT"},
                    {"name": "salary", "type": "DECIMAL"}
                ]
            }
        ],
        "generated_date": "2026-04-10T12:00:00Z"  # Fixed, not now()
    }
```

---

## Patrón: Snapshot Testing

Use snapshots para validar salidas complejas (Markdown, HTML, Word) sin hardcoding expected output.

### Setup

```bash
# Install plugin
pip install pytest-snapshot

# Crear snapshot first time
python -m pytest tests/doc/test_render.py::test_markdown_render --snapshot-update

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

## MySQL Variables Testing (v0.10.0+)

### Patrón: Mocking `connection.execute()` para ReturnValue Iterator

`MySQLVariableValidator` y pruebas de packet size calculation requieren mocking de `connection.execute()`
que retorna un Iterator (tipo `ResultProxy` de SQLAlchemy). Los mocks ingenuos fallan si devuelven
listas o `None` en lugar de iterables.

### Antipattern: Mock Incorrecto

```python
# ❌ INCORRECTO — Devuelve lista, no Iterator
connection.execute.return_value = [
    {"max_allowed_packet": 16777216},
]
# TypeError: validator intenta iterar pero recibe list (que sí es iterable pero mock no es ResultProxy)

# ❌ INCORRECTO — Devuelve None
connection.execute.return_value = None
# TypeError: 'NoneType' object is not iterable
```

### Patrón Correcto: MagicMock con `__iter__`

```python
from unittest.mock import MagicMock

@pytest.fixture
def mock_mysql_connection(mocker):
    """Mock MySQL connection que retorna Iterator via execute()."""
    connection = MagicMock()

    # Configura execute() para retornar iterator simulado
    def side_effect_execute(*args, **kwargs):
        # Simula SHOW VARIABLES para múltiples variables
        if "max_allowed_packet" in str(args):
            mock_result = MagicMock()
            mock_result.__iter__ = MagicMock(return_value=iter([
                {"max_allowed_packet": 16777216}
            ]))
            return mock_result
        elif "innodb_buffer_pool_size" in str(args):
            mock_result = MagicMock()
            mock_result.__iter__ = MagicMock(return_value=iter([
                {"innodb_buffer_pool_size": 1073741824}
            ]))
            return mock_result
        return iter([])  # Fallback

    connection.execute.side_effect = side_effect_execute
    return connection

# Uso en test
def test_mysql_variables_read(mock_mysql_connection):
    from doc_organize.connection.mariadb import MySQLVariableValidator

    validator = MySQLVariableValidator(mock_mysql_connection)
    variables = validator.read_variables()

    assert variables["max_allowed_packet"] == 16777216
    assert variables["innodb_buffer_pool_size"] == 1073741824
```

### Patrón Alternativo: `side_effect` con Iterators Directo

```python
from unittest.mock import MagicMock

@pytest.fixture
def mock_connection_with_side_effect(mocker):
    """Mock simplificado usando side_effect."""
    connection = MagicMock()

    # Secuencia de iterators para múltiples llamadas a execute()
    connection.execute.side_effect = [
        iter([{"max_allowed_packet": 16777216}]),
        iter([{"innodb_buffer_pool_size": 1073741824}]),
    ]
    return connection

def test_validator_with_direct_side_effect(mock_connection_with_side_effect):
    from doc_organize.connection.mariadb import MySQLVariableValidator

    validator = MySQLVariableValidator(mock_connection_with_side_effect)
    vars1 = validator.read_variables()  # Consume primer iterator
    vars2 = validator.read_variables()  # Consume segundo iterator
```

### Testing Heurística de Packet Size

`MySQLMultiRowInsertStrategy.get_min_max_allowed_packet()` calcula valores basados en
`max_rows_per_statement` y `avg_row_bytes`. Los tests validan power-of-2 y límites.

```python
@pytest.mark.parametrize("max_rows,avg_row_bytes,expected_min", [
    (1000, 2000, 64 * 1048576),      # Típico → 64 MB mínimo
    (10000, 1000, 128 * 1048576),    # Grande → 128 MB
    (100000, 2000, 256 * 1048576),   # Muy grande → 256 MB máximo
])
def test_packet_size_is_power_of_two(max_rows, avg_row_bytes, expected_min):
    from doc_organize.bulk._execution.batch import MySQLMultiRowInsertStrategy

    strategy = MySQLMultiRowInsertStrategy(max_rows_per_statement=max_rows)
    packet_size = strategy.get_min_max_allowed_packet(avg_row_bytes=avg_row_bytes)

    # Valida power-of-2: 64 MB, 128 MB, o 256 MB
    assert packet_size in [64 * 1048576, 128 * 1048576, 256 * 1048576]
    # Valida >= mínimo recomendado
    assert packet_size >= 64 * 1048576
    assert packet_size <= 256 * 1048576
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
def test_postgres_connection():
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
@pytest.mark.parametrize("motor,expected_dialect", [
    ("postgres", "postgresql"),
    ("mysql", "mysql"),
    ("sqlite", "sqlite"),
])
def test_dialect_resolution(motor, expected_dialect):
    assert get_dialect(motor) == expected_dialect

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
def db_connection(request):
    """Yield different connections based on marker."""
    if "sqlite" in request.keywords:
        return connect_sqlite(":memory:")
    elif "postgres" in request.keywords:
        return connect_postgres("test")

@pytest.mark.sqlite
def test_query_on_sqlite(db_connection):
    ...

@pytest.mark.postgres
def test_query_on_postgres(db_connection):
    ...
```

---

## Sync/Async Contract Validation

Util_bbdd tiene métodos sync y async que deben ser equivalentes. Valida con DRY pattern:

```python
# tests/test_manager_contracts.py
import pytest
import asyncio
from doc_organize import SyncDatabaseManager, AsyncDatabaseManager

class TestManagerContracts:
    """Validate sync/async managers have same behavior."""

    def test_sync_async_schema_fetch_equivalent(self):
        """Both sync and async return identical schema."""
        sync_mgr = SyncDatabaseManager(sqlite_config)
        async_mgr = AsyncDatabaseManager(sqlite_config)

        # Fetch with sync
        sync_schema = sync_mgr.get_schema("main")

        # Fetch with async
        async_schema = asyncio.run(async_mgr.get_schema("main"))

        # Must be identical
        assert sync_schema == async_schema

    @pytest.mark.parametrize("table_name", [
        "metadata_table",
        "edge_case_table_with_unicode_ñ",
        "table_with_long_name_" + "x" * 50,
    ])
    def test_sync_async_table_columns_equal(self, table_name):
        """Columns retrieved must be identical."""
        sync_cols = sync_mgr.get_table_columns(table_name)
        async_cols = asyncio.run(async_mgr.get_table_columns(table_name))
        assert sync_cols == async_cols
```

---

## Cobertura Esperada por Tipo de Cambio

| Tipo | Cobertura | Regla | Ejemplo |
|------|-----------|-------|---------|
| **new_feature** | 80%+ | Lógica principal covered, ok si edge cases pending | Feature: Oracle 11g support → 80% cobertura |
| **hotfix** | 100% del path afectado | Cada línea del bug fix tiene test | Bug: NoneType in connection → 100% cobertura |
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
