# ⚙️ Runtime & Environment — doc_organize

> Reemplaza una versión anterior ("Python ≥3.12", "Docker Compose para tests con BD reales") de la
> encarnación previa de este repositorio (una librería de motores de base de datos).

## Requisitos

- Python **≥3.11** (`pyproject.toml`: `requires-python`; classifiers declaran 3.11–3.14)
- Sin Docker ni servicios externos: los tests no dependen de bases de datos reales.

## Setup de desarrollo

```bash
git clone <repo>
cd doc_organize
python -m venv .venv
source .venv/bin/activate        # Linux/macOS
# .venv\Scripts\activate          # Windows

pip install -e ".[dev,web,docs]"
```

- `dev`: pytest, ruff, mypy y el resto de herramientas de calidad.
- `web`: FastAPI/Uvicorn/Jinja2 + `cryptography` (Fernet, cifrado de credenciales de IA en
  `/admin/configuracion-ia`) — necesario para correr `tests/unit/test_web_*.py`.
- `docs`: mkdocs + mkdocs-material + mkdocstrings — necesario para `mkdocs build`.
- `ai`: `httpx` — clientes de IA (`ai/`, LiteLLM Proxy/GitHub Copilot Pro).
- `context`: `pyyaml` — front matter de `taxonomy_manifest.md` y plantillas compartidas (`context/`).

El núcleo (`pip install doc_organize` sin extras) **no** instala `fastapi`/`uvicorn`/`jinja2` —
verificado, es una condición de seguridad/tamaño explícita (`§11` del PLAN).

## Comandos habituales

```bash
python -m ruff check src tests       # lint
python -m ruff format src tests      # formato
python -m mypy src                   # type-check
python -m pytest                     # todos los tests
python -m pytest -k "not slow"       # sin los tests de integración con Docling real (más lentos)
python -m pytest --cov=src           # con cobertura
mkdocs serve                         # documentación local (http://127.0.0.1:8000)
mkdocs build --strict                # sitio estático en ./site — comando de validación real de CI
```

## CLI de la aplicación (no confundir con los comandos de desarrollo de arriba)

```bash
python -m doc_organize project create "Mi Proyecto" --location /ruta/a/workspaces
python -m doc_organize project list
python -m doc_organize scan --project "Mi Proyecto" --paths /ruta/a/documentos [--use-ocr] [--use-gpu]  # ya no deduplica
python -m doc_organize deduplicate --project "Mi Proyecto" --paths /ruta/a/documentos  # accion aparte, a peticion del usuario
python -m doc_organize web [--host 0.0.0.0] [--port 8000]
# El tenant "default" y su usuario admin/admin se crean de fábrica al abrir auth.db por primera
# vez (rediseño Tenant/Role/User, 2026-09-11) -- no hace falta lo de abajo para arrancar en
# no-loopback, salvo que quieras un tenant propio en vez del de fábrica:
python -m doc_organize tenant create "Mi Organización"
python -m doc_organize user create alice --tenant mi-organizacion   # contraseña vía prompt interactivo
python -m doc_organize user set-instance-admin alice --tenant mi-organizacion  # is_instance_admin
```

## CI real (`.github/workflows/`)

- `tests.yml`: matriz `os: [ubuntu-latest, windows-latest]` × `python-version: [3.11, 3.12,
  3.13, 3.14]` — `ruff check`, `mypy src`, `pytest --cov`.
- `docs.yml`: `pip install -e ".[docs]"` + `mkdocs build --strict` (no `zensical` — ese binario no
  es una dependencia declarada; ver `.ai/DECISIONS_LOG.md` revisión 12 para el porqué).

## Variables de entorno

Ninguna es obligatoria para el uso local (loopback). No existe `DOC_ORGANIZE_API_TOKEN` (retirado en
la revisión 8 — autenticación es multi-usuario, no un token compartido). Para exponer la web fuera
de loopback, ya no hace falta provisionar nada por CLI de antemano (rediseño Tenant/Role/User,
2026-09-11): `AuthStore` crea de fábrica el tenant `default` + usuario `admin`/`admin` al primer
arranque — pero esa cuenta no puede completar el login en modo no-loopback mientras conserve la
contraseña de fábrica (cámbiala desde loopback primero, ver `docs/functional/access.md`).
`DOC_ORGANIZE_SECRETS_KEY` (32 bytes en base64 urlsafe) es opcional: sin ella, el panel
`/admin/configuracion-ia` sigue funcionando en modo "solo campos no-secretos".
