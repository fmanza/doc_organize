# 🎯 Standards & Quality Gate — doc_organize

> Reemplaza una versión anterior ("line-length 120") de la encarnación previa de este repositorio. Valores
> verificados contra `pyproject.toml`, `pytest.ini` y `.github/workflows/tests.yml` reales (2.2.0).

## Code Style

- **Formatter**: `ruff format` (`quote-style = "double"`, `indent-style = "space"`, `line-ending = "auto"`)
- **Linter**: `ruff check` (`target-version = "py312"`, `extend-select = ["E", "W", "F", "I", "B", "C4", "UP", "N"]`,
  `ignore = ["E501"]` — línea larga permitida, `line-length = 150`). `ruff` acotado a `<0.18` en el extra `dev`.
- **Type checker**: `mypy` (`python_version = "3.12"`, `plugins = ["pydantic.mypy"]`, `warn_return_any = true`,
  `warn_unused_configs = true`, `strict = false`). `docling.*` con `follow_imports = "skip"` e `ignore_errors = true`;
  `pypdfium2` y `py3langid.*` con `ignore_missing_imports`. (El motivo original del `skip` de Docling era mantener
  compatibilidad con 3.11, que ya no se soporta; **pendiente** confirmar si sigue haciendo falta.)
- **Import sort**: `ruff` isort (`known-first-party = ["doc_organize"]`, `combine-as-imports = true`,
  `lines-between-types = 1`)
- **Python**: `>=3.12` (`requires-python`; classifiers 3.12–3.14); CI testea 3.12–3.14 en Ubuntu y Windows
  (`tests.yml`)

## Tipado

- Type hints en todas las funciones públicas (`mypy src` limpio, ver «Verificación»)
- `# type: ignore` solo con comentario explicando el porqué en la línea anterior
- Modelos de dominio: Pydantic v2 (`core/models.py`); dataclasses solo para estructuras internas o de resultado
  (p. ej. `ScanSummary` en `scan/scan_command.py`, `ContentDocument` en `dedup/content.py`)

## Testing

- `pytest` + `pytest-asyncio` (`pytest.ini` no fija `asyncio_mode`: modo `strict` por defecto, marcador
  `@pytest.mark.asyncio` explícito)
- `pytest.ini`: `--strict-markers`; marcadores `unit`, `integration`, `contract`, `slow`, `sqlite`, `flaky`;
  cobertura activada por defecto (`--cov=src`)
- `@pytest.mark.slow` para tests que ejercitan Docling real — excluibles con `-m "not slow"` (lo que hace CI)
- CI ejecuta también los doctests de `src` (`pytest --doctest-modules src`)
- Tests de arquitectura que no se relajan: `tests/unit/test_library_architecture.py` (sin FastAPI/Starlette/uvicorn/
  Jinja2/`python-multipart`, sin `doc_organize.web`/`auth`, sin extra `web`) y `tests/unit/test_ai_architecture.py`
- Sin APIs externas ni descargas reales en los tests unitarios
- Cobertura objetivo: ≥80% (la cifra real actual no se ha vuelto a medir en esta revisión: **pendiente**)
- Patrón: operaciones bloqueantes (I/O, Docling) se ejecutan vía `asyncio.to_thread()` desde código async

## Seguridad (patrones establecidos, replicar para código nuevo)

- Cualquier ruta construida a partir de un segmento elegido por el usuario pasa por
  `utils/path_utils.safe_path_join()` — nunca concatenación manual; los nombres de carpeta de salida se validan con
  `validate_output_folder_name()` (`RESERVED_OUTPUT_FOLDER_NAMES`)
- Antes de enviar texto a la IA o de publicarlo (sitio, `llms.txt`, paquete para IA) se redactan credenciales
  (`security/credentials.redact_credentials`); el Markdown no confiable se neutraliza con
  `security/untrusted_markdown.neutralize_untrusted_markdown`
- Las credenciales de IA solo llegan por `AiSettings` (inyectado o vía `settings_from_env()`); `context/` nunca las
  resuelve por su cuenta
- La deduplicación nunca borra: mueve a `duplicados/` o, en modo `copy`, registra decisiones `exclude`
- Los patrones de sesión, contraseñas, cookies y `tenant_id` de versiones anteriores ya no aplican: la librería no
  tiene autenticación desde 1.0.0 (doc_organize_web)

## Documentación

- Docstrings Google-style con ejemplo de uso en todo módulo/clase pública
- `zensical build --strict` debe pasar sin errores ni warnings de links rotos (`zensical.toml`; ver
  `.ai/DECISIONS_LOG.md` revisión 17)
- La referencia de API sale de los docstrings vía `mkdocstrings`, no se duplica a mano; la API pública (SemVer) está
  en `docs/api/publica.md`

## Verificación de este documento (2026-11-24)

```
python -m ruff check src tests   → All checks passed!
python -m mypy src                → Success: no issues found in 97 source files
python -m pytest                   → pendiente (no ejecutado en esta revisión)
zensical build --strict             → pendiente (no ejecutado en esta revisión)
```
