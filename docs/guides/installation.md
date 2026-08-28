# Instalación

## Requisitos

- Python 3.10 o superior.

## Núcleo (CLI)

```bash
pip install doc_organize
```

Instala el CLI y todo lo necesario para escanear, convertir, deduplicar y cachear
documentos, **incluido OCR en CPU** (vía el extra `docling[rapidocr]`, que forma
parte de las dependencias obligatorias — no hace falta ningún paso adicional para
que el OCR funcione).

## Interfaz web (opcional)

```bash
pip install doc_organize[web]
```

Añade FastAPI, Uvicorn, Jinja2 y lo necesario para `python -m doc_organize web`. Sin
este extra, el subcomando `web` falla con un mensaje claro pidiendo instalarlo — el
núcleo nunca arrastra estas dependencias.

## Aceleración GPU para OCR (opcional)

```bash
pip install doc_organize[web,ocr-gpu]
```

Añade `torch`/`torchvision`/`opencv-python` para usar el motor OCR acelerado por
GPU (EasyOCR) en vez del motor por defecto en CPU (RapidOCR). Es una optimización
opcional: el OCR funciona igual de correcto sin GPU, solo más lento en documentos
grandes.

## Entorno de desarrollo

```bash
git clone <repo>
cd doc_organize
python -m venv .venv
.venv\Scripts\activate        # Windows
# source .venv/bin/activate   # Linux/macOS

pip install -e ".[dev,web,docs]"
```

- `dev`: pytest, ruff, mypy y el resto de herramientas de calidad.
- `web`: interfaz web (necesaria para correr `tests/unit/test_web_*.py`).
- `docs`: mkdocs + mkdocs-material + mkdocstrings, para compilar esta documentación.

### Comandos de desarrollo

```bash
python -m ruff check src tests       # lint
python -m ruff format src tests      # formato
python -m mypy src                   # type-check
python -m pytest                     # todos los tests
python -m pytest -k "not slow"       # sin los tests de integración con Docling real
mkdocs serve                         # documentación local (http://127.0.0.1:8000)
mkdocs build                         # sitio estático en ./site
```
