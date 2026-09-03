# Instalación

## Requisitos

- Python 3.11 o superior.

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

⚠️ **Este comando por sí solo instala el build de `torch` CPU-only.** El extra
`ocr-gpu` de `pyproject.toml` no fija una versión CUDA de `torch` a propósito
(para no atar el paquete a una versión de CUDA concreta) — `pip install torch`
sin más resuelve siempre contra PyPI, que solo publica el wheel CPU. Para el
build con CUDA hace falta el índice propio de PyTorch, indicando la etiqueta
`cuXXX` que corresponda a tus drivers NVIDIA (comprueba la versión de CUDA
soportada con `nvidia-smi`, y la etiqueta exacta en
[pytorch.org/get-started](https://pytorch.org/get-started/locally/)):

```bash
pip install --force-reinstall torch --index-url https://download.pytorch.org/whl/cuXXX
```

Ejecuta esto **dentro del mismo entorno virtual que arranca el servidor web**
(`python -m doc_organize web`) — si lo instalaste en otro Python del sistema,
`torch.cuda.is_available()` seguirá devolviendo `False` en el proceso real del
servidor aunque en ese otro entorno funcione. La página de Escaneo detecta y
muestra este estado automáticamente (ver
[Resolución de problemas](troubleshooting.md#el-menu-escaneo-dice-gpu-no-activa-aunque-ya-la-instale-y-funciona)
si el mensaje no coincide con lo que esperas).

## Formato extendido: audio/vídeo (opcional)

```bash
pip install doc_organize[av]
```

Añade el backend de transcripción (Whisper, vía `docling[asr]`) necesario para
convertir audio y vídeo con `--include-audio-video`. `.txt` no necesita este
extra ni ningún flag — es una extensión genérica que docling ya soporta,
incluida en `SUPPORTED_EXTENSIONS` sin opt-in.

⚠️ Además del extra de Python, el vídeo requiere el binario **`ffmpeg`** en el
`PATH` del sistema (no se instala vía `pip`) — instálalo con el gestor de
paquetes de tu sistema operativo y comprueba `ffmpeg -version`. Sin ambos
requisitos, `--include-audio-video` se rechaza con un mensaje explícito antes
de escanear (ver
[Resolución de problemas](troubleshooting.md#scan-include-audio-video-falla-antes-de-escanear-nada)).

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
