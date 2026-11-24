# ⚙️ Runtime & Environment — doc_organize

> Reemplaza una versión anterior ("Docker Compose para tests con BD reales") de la encarnación previa de este
> repositorio (una librería de motores de base de datos). Revisado contra `pyproject.toml`, `pytest.ini`,
> `.github/workflows/` y `src/` de 2.2.0.

## Requisitos

- Python **≥3.12** (`pyproject.toml`: `requires-python`; classifiers declaran 3.12–3.14)
- Sin Docker ni servicios externos para los tests: no dependen de bases de datos reales ni de un LiteLLM Proxy.
- La IA (opcional) necesita un **LiteLLM Proxy** accesible; ver `docs/guides/litellm_proxy_setup.md` y
  `deploy/litellm/`.

## Setup de desarrollo

```bash
git clone <repo>
cd doc_organize
python -m venv .venv
source .venv/bin/activate        # Linux/macOS
# .venv\Scripts\activate          # Windows

pip install -e ".[dev,docs]"     # CI de tests instala solo ".[dev]"
```

Extras declarados en `pyproject.toml`:

- `dev`: build, pytest (+cov, asyncio), httpx, ruff (`<0.18`), mypy y stubs, openpyxl, black, matplotlib (fixtures
  de PDF).
- `docs`: zensical + mkdocstrings-python — para `zensical build` de la documentación del proyecto.
- `ai`: `httpx` — `LlmClient` y clientes de uso (`ai/`).
- `context`: `pyyaml` — front matter de `taxonomy_manifest.md` y plantillas (`context/`).
- `export`: `openpyxl` — Excel de `doc_organize.export`.
- `site`: `zensical` — sitio del contexto de un proyecto (`SiteGenerator`).
- `ocr-gpu`: torch, torchvision, opencv-python, easyocr.
- `av`: `docling[asr]` — audio y vídeo.

No existe el extra `web` desde 1.0.0: el núcleo nunca instala `fastapi`/`uvicorn`/`jinja2`/`cryptography`
(`tests/unit/test_library_architecture.py`).

## Comandos habituales

```bash
python -m ruff check src tests       # lint
python -m ruff format src tests      # formato
python -m mypy src                   # type-check
python -m pytest                     # todos los tests (cobertura activada en pytest.ini)
python -m pytest -m "not slow"       # sin los tests con Docling real (más lentos), como CI
python -m pytest --doctest-modules src --no-cov -q   # doctests, como CI
python -m build                      # paquete
zensical serve                       # documentación local (http://127.0.0.1:8000)
zensical build --strict              # sitio estático en ./site — validación de CI
```

## CLI de la aplicación (no confundir con los comandos de desarrollo de arriba)

```bash
python -m doc_organize project create "Mi Proyecto" --location /ruta/a/workspaces
python -m doc_organize project list
python -m doc_organize scan --project "Mi Proyecto" --paths /ruta/a/documentos [--use-ocr] [--use-gpu] [--force]  # no deduplica
python -m doc_organize deduplicate --project "Mi Proyecto" --paths /ruta/a/documentos  # acción aparte, a petición del usuario
python -m doc_organize export zip --project "Mi Proyecto" -o proyecto.zip   # o --preview
python -m doc_organize export cache-xlsx --project "Mi Proyecto" -o cache.xlsx
python -m doc_organize export errors-xlsx --project "Mi Proyecto" -o errores.xlsx
python -m doc_organize export context-xlsx --project "Mi Proyecto" -o contexto.xlsx
```

`project` y `scan`/`deduplicate` aceptan `--registry-path` para usar otro `projects.json`. Los subcomandos `web`,
`tenant` y `user` se retiraron en 1.0.0 (la web es doc_organize_web).

## CI real (`.github/workflows/`)

- `tests.yml`: matriz `os: [ubuntu-latest, windows-latest]` × `python-version: ["3.12", "3.13", "3.14"]` —
  `pip install -e ".[dev]"`, `ruff check src/ tests/`, `mypy src`, doctests de `src`,
  `pytest tests/ -m "not slow" --cov`.
- `docs.yml`: Python 3.12, `pip install -e ".[docs]"` + `zensical build --strict`.
- Además: `release.yml`, `docs-zip-release.yml` y `doc_agents.yml` (agentes de documentación).

## Variables de entorno

Ninguna es obligatoria para el uso local.

| Variable | Uso |
|---|---|
| `DOC_ORGANIZE_LITELLM_BASE_URL` | URL del LiteLLM Proxy; sin ella, `settings_from_env()` devuelve `None` (IA desactivada) |
| `DOC_ORGANIZE_LITELLM_VIRTUAL_KEY` | Clave general; obligatoria si hay `BASE_URL` |
| `DOC_ORGANIZE_LITELLM_MODEL_<TAREA>` | Modelo por tarea (`CLASSIFY`, `ENRICH`, `TAXONOMY_DESIGN`, `AGENT`, `EMBED`, `DEDUP`); por defecto el alias `doc-organize-<tarea>` |
| `DOC_ORGANIZE_LITELLM_VIRTUAL_KEY_<TAREA>` | Clave propia de una tarea (opcional) |
| `DOC_ORGANIZE_LOG_LEVEL`, `DOC_ORGANIZE_LOG_DIR`, `DOC_ORGANIZE_ENV` | Logging (`utils/logging.py`) |
| `DOC_ORGANIZE_DATE_FORMAT`, `DOC_ORGANIZE_TIMEZONE` | Formato de fecha mostrado (`utils/date_format.py`) |
| `DOC_ORGANIZE_GITHUB_USERNAME`, `DOC_ORGANIZE_GITHUB_PAT` | Obsoletas desde 2.1.0 (`GitHubCopilotUsageClient`, se retira en 3.0) |

Las variables de IA de 1.x (`DOC_ORGANIZE_LITELLM_<CLIENTE>_BASE_URL`, `..._ENRICHMENT_MODEL`…) ya no se leen: si
alguna tiene valor, `settings_from_env()` lanza `AiConfigurationError` con la equivalencia
(`docs/guides/migracion_2_0.md`). Ya no existen `DOC_ORGANIZE_API_TOKEN` ni `DOC_ORGANIZE_SECRETS_KEY` (eran de la web
integrada, retirada en 1.0.0).
