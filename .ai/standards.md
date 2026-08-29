# 🎯 Standards & Quality Gate — doc_organize

> Reemplaza una versión anterior ("line-length 120", "Python ≥3.12") de la encarnación previa de
> este repositorio. Valores verificados contra `pyproject.toml` real.

## Code Style

- **Formatter**: `ruff format` (`quote-style = "double"`, `indent-style = "space"`)
- **Linter**: `ruff check` (`extend-select = ["E", "W", "F", "I", "B", "C4", "UP", "N"]`,
  `ignore = ["E501"]` — línea larga permitida, `line-length = 150`)
- **Type checker**: `mypy` (`python_version = "3.11"`, `plugins = ["pydantic.mypy"]`,
  `warn_return_any = true`, `strict = false`). `docling.*` con `follow_imports = "skip"`
  deliberadamente — sus stubs (vía `scipy-stubs`) usan sintaxis de Python 3.12+ que rompería el
  type-check de código compatible con 3.11.
- **Import sort**: `ruff` isort (`known-first-party = ["doc_organize"]`,
  `combine-as-imports = true`)
- **Python**: `>=3.11` (declarado en `requires-python` y en `classifiers` hasta 3.14); CI testea
  3.11–3.14 en Ubuntu y Windows (`tests.yml`)

## Tipado

- Type hints en el 100% de funciones públicas (verificado: `mypy src` limpio en 40 ficheros)
- `# type: ignore` solo con comentario explicando el porqué en la línea anterior (no texto libre
  tras el código en la misma línea — confunde a herramientas de análisis de suppression comments)
- Modelos de dominio: Pydantic v2 (`core/models.py`), no dataclasses salvo estructuras internas de
  uso exclusivamente local (p.ej. `ScanSummary` en `scan/scan_command.py`)

## Testing

- `pytest` + `pytest-asyncio` (modo `strict`, marcador `@pytest.mark.asyncio` explícito)
- `@pytest.mark.slow` para tests que ejercitan Docling real (conversión/OCR) — excluibles con
  `-k "not slow"` para iteración rápida
- Cobertura objetivo: ≥80% (real actual: 97%)
- Patrón establecido: operaciones síncronas/bloqueantes (I/O, `hashlib.scrypt`, `getpass`) se
  ejecutan vía `asyncio.to_thread()` desde código async — nunca bloquean el event loop directamente

## Seguridad (patrones ya establecidos, replicar para código nuevo)

- Cualquier construcción de ruta a partir de un segmento elegido por el usuario pasa por
  `utils/path_utils.safe_path_join()` — nunca concatenación manual
- Cualquier valor que llegue del cliente y determine qué recurso se lee/mueve/borra se valida contra
  un conjunto calculado en el servidor — nunca se confía en el valor crudo (ver
  `web/routes/duplicates.py::_group_key()` como patrón de referencia)
- `tenant_id` siempre resuelto server-side desde la sesión, nunca de un parámetro de query/body
- Contraseñas: `hashlib.scrypt` (parámetros OWASP) + salt aleatorio por usuario, comparación con
  `secrets.compare_digest` — nunca `==` directo ni almacenamiento en claro
- Cookies de sesión: `HttpOnly` + `SameSite=Strict` siempre; `Secure` solo si hay TLS real (nunca
  por defecto, para no dar una falsa sensación de seguridad)

## Documentación

- Docstrings Google-style con ejemplo de uso en todo módulo público
- `mkdocs build --strict` debe pasar sin errores ni warnings de links rotos — comando de validación
  real (ver `.github/instructions/sync.instructions.md`); **no** `zensical build` (binario no
  declarado como dependencia en este proyecto)
- `docs/api/index.md` genera referencia desde los docstrings vía `mkdocstrings`, no se duplica a mano

## Verificación de este documento

```
python -m ruff check src tests   → All checks passed
python -m mypy src                → Success: no issues found in 40 source files
python -m pytest                   → 182 passed, 97% cobertura
mkdocs build --strict               → exit 0
```
