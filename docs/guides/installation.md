# Instalación

## Requisitos

- Python 3.12 o superior.

## Núcleo (CLI)

```bash
pip install doc_organize
```

Instala el CLI y todo lo necesario para escanear, convertir, deduplicar y cachear
documentos, **incluido OCR en CPU** (vía el extra `docling[rapidocr]`, que forma
parte de las dependencias obligatorias — no hace falta ningún paso adicional para
que el OCR funcione).

⚠️ **Linux mínimo (contenedores `slim`/`alpine`, distros mínimas)**: RapidOCR usa
ONNX Runtime, que enlaza en tiempo de ejecución con `libgomp.so.1` (OpenMP). Las
imágenes base completas de Ubuntu/Debian ya lo traen, pero las variantes `slim` o
`alpine` no — si `import` falla con
`libgomp.so.1: cannot open shared object file`, instálalo con el gestor de
paquetes de la distro (p.ej. `apt-get install -y libgomp1` en Debian/Ubuntu; ver
[Resolución de problemas](troubleshooting.md#libgompso1-no-encontrado-en-linux-minimocontenedores)).

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

Añade `torch`/`torchvision`/`opencv-python`/`easyocr` para usar el motor OCR acelerado por
GPU (EasyOCR) en vez del motor por defecto en CPU (RapidOCR). Es una optimización
opcional: el OCR funciona igual de correcto sin GPU, solo más lento en documentos
grandes.

**Requiere GPU NVIDIA (CUDA)** — EasyOCR se acelera vía CUDA, disponible en
Windows y Linux con hardware NVIDIA. En macOS no existe esta ruta (ver nota al
final de esta sección).

⚠️ **Este comando por sí solo instala el build de `torch` CPU-only.** El extra
`ocr-gpu` de `pyproject.toml` no fija una versión CUDA de `torch` a propósito
(para no atar el paquete a una versión de CUDA concreta) — `pip install torch`
sin más resuelve siempre contra PyPI, que solo publica el wheel CPU. Para el
build con CUDA hace falta el índice propio de PyTorch, indicando la etiqueta
`cuXXX` que corresponda a tus drivers NVIDIA (comprueba la versión de CUDA
soportada con `nvidia-smi`, y la etiqueta exacta en
[pytorch.org/get-started](https://pytorch.org/get-started/locally/)):

### Windows / Linux (NVIDIA + CUDA)

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

⚠️ **Linux + `opencv-python`**: el paquete `opencv-python` (incluido en el extra
`ocr-gpu`) enlaza con librerías gráficas del sistema (`libGL`). En servidores o
contenedores sin entorno gráfico, `import cv2` puede fallar con
`ImportError: libGL.so.1: cannot open shared object file`. Instala la librería
del sistema (`apt-get install -y libgl1` en Debian/Ubuntu) o, si no necesitas
funciones de GUI de OpenCV, sustituye la dependencia por
`opencv-python-headless` (ver
[Resolución de problemas](troubleshooting.md#importerror-libglso1-al-usar-ocr-gpu-en-linuxdocker)).

### macOS

No hay build de `torch` con CUDA para macOS (Apple no fabrica GPUs NVIDIA). El
extra `ocr-gpu` instala igualmente `torch`/`torchvision`/`opencv-python`, pero
`torch.cuda.is_available()` siempre será `False` — el motor seguirá cayendo a
EasyOCR en CPU, sin ninguna ganancia frente a RapidOCR. PyTorch sí soporta la
GPU de Apple Silicon vía el backend Metal (`mps`), pero **EasyOCR no tiene
soporte fiable de `mps`** a fecha de esta revisión (comprobar el estado actual
en el repositorio de EasyOCR antes de asumir lo contrario). **Recomendación**:
en macOS, no instales el extra `ocr-gpu` — usa el motor por defecto en CPU
(RapidOCR), ya incluido en el núcleo sin pasos adicionales.

## Formato extendido: audio/vídeo (opcional)

```bash
pip install doc_organize[av]
```

Añade el backend de transcripción (Whisper, vía `docling[asr]`) necesario para
convertir audio y vídeo con `--include-audio-video`. `.txt` no necesita este
extra ni ningún flag — es una extensión genérica que docling ya soporta,
incluida en `SUPPORTED_EXTENSIONS` sin opt-in.

⚠️ **Requiere Python 3.12–3.13.** El extra `[av]` arrastra `numba`/`llvmlite`
(dependencias de Whisper) que, a fecha de esta revisión, todavía no publican
wheels precompilados para Python 3.14 — `pip install doc_organize[av]` falla
en ese intérprete al intentar resolver esas dependencias. No es un fallo de
`doc_organize` (revisa el código: `av_detector.py` no importa ni depende de
`numba`); si necesitas audio/vídeo, crea el entorno virtual con Python 3.12
o 3.13. Si no lo necesitas, simplemente no instales `[av]` ni actives
`--include-audio-video` — el resto de la librería (scan, convert, dedup,
cache, OCR) funciona sin restricción en Python 3.14 (ver
[Resolución de problemas](troubleshooting.md#pip-install-av-falla-por-numballvmlite-en-python-314)).

Además del extra de Python, el vídeo (y la transcripción de cualquier
audio/vídeo) requiere el binario **`ffmpeg`** en el `PATH` del sistema — no se
instala vía `pip`, hay que instalarlo con el gestor de paquetes del sistema
operativo:

### Windows

```powershell
winget install Gyan.FFmpeg
```

Alternativas si no usas `winget`: Chocolatey (`choco install ffmpeg-full`) o
Scoop (`scoop install main/ffmpeg`). Tras instalar, abre una **terminal nueva**
para que recoja el `PATH` actualizado.

### Linux

```bash
sudo apt install ffmpeg          # Debian/Ubuntu
sudo dnf install ffmpeg-free     # Fedora (el paquete "ffmpeg" a secas requiere RPM Fusion)
sudo pacman -S ffmpeg            # Arch
```

### macOS

```bash
brew install ffmpeg
```

Si no tienes Homebrew instalado, sigue las instrucciones en
[brew.sh](https://brew.sh) antes de ejecutar el comando anterior.

### Verificar la instalación (cualquier SO)

```bash
ffmpeg -version
```

Sin `ffmpeg` en el `PATH` y sin el extra `[av]` instalado (en un intérprete
compatible), `--include-audio-video` se rechaza con un mensaje explícito antes
de escanear (ver
[Resolución de problemas](troubleshooting.md#scan-include-audio-video-falla-antes-de-escanear-nada)).

## Excel legado (.xls): LibreOffice (opcional)

`.xls` (el formato binario de Excel anterior a `.xlsx`) forma parte de
`SUPPORTED_EXTENSIONS` sin ningún extra de Python ni flag — se escanea siempre,
igual que `.xlsx`. Pero Docling necesita convertirlo primero a `.xlsx` con
**LibreOffice**, que no se instala vía `pip`: hay que instalarlo con el gestor
de paquetes del sistema operativo y dejarlo accesible en el `PATH` como
`soffice` (o `libreoffice`).

### Windows

```powershell
winget install TheDocumentFoundation.LibreOffice
```

Alternativa si no usas `winget`: Chocolatey (`choco install libreoffice-fresh`),
o descarga directa desde [libreoffice.org](https://www.libreoffice.org/download/download/).
Tras instalar, abre una **terminal nueva** para que recoja el `PATH`
actualizado — si sigue sin detectarse, añade manualmente la carpeta
`Program Files\LibreOffice\program` al `PATH` del sistema.

### Linux

```bash
sudo apt install libreoffice        # Debian/Ubuntu
sudo dnf install libreoffice        # Fedora
sudo pacman -S libreoffice-fresh    # Arch
```

### macOS

```bash
brew install --cask libreoffice
```

### Verificar la instalación (cualquier SO)

```bash
soffice --version
```

Sin LibreOffice en el `PATH`, un `.xls` concreto falla con un mensaje
explícito indicando qué instalar, sin gastar los reintentos automáticos del
escaneo (ver
[Resolución de problemas](troubleshooting.md#un-xls-falla-con-libreoffice-is-required)) —
el resto de formatos (`.xlsx`, `.pdf`, `.docx`, etc.) no se ven afectados.

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
