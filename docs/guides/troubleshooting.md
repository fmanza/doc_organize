# Resolución de problemas

## `python -m doc_organize web` falla con "instala doc_organize[web]"

No tienes instalado el extra `web`. `pip install doc_organize[web]`.

## `libgomp.so.1` no encontrado en Linux mínimo/contenedores

RapidOCR (motor OCR por defecto, incluido en el núcleo) usa ONNX Runtime, que
enlaza en tiempo de ejecución con `libgomp.so.1` (OpenMP de GCC). Las imágenes
completas de Ubuntu/Debian ya lo incluyen, pero variantes `slim`/`alpine` o
distros mínimas no. Instala el paquete del sistema:

```bash
apt-get install -y libgomp1    # Debian/Ubuntu
# equivalente en otras distros: busca el paquete "libgomp" con tu gestor
```

Ver también [Instalación → Núcleo (CLI)](installation.md#nucleo-cli).

## Un documento escaneado nunca sale de "OCR pendiente"

`--use-ocr` reprocesa en la misma ejecución los documentos detectados como
`ocr_required`. Si escaneaste sin `--use-ocr`, esos documentos quedan marcados
`OCR_PENDING` en el caché — vuelve a ejecutar `scan` con `--use-ocr` (no hace
falta re-escanear las carpetas de origen; el caché ya los tiene identificados).

## OCR muy lento en documentos grandes

El motor por defecto (RapidOCR) corre en CPU. Si tienes GPU disponible, instala
el extra `ocr-gpu` y añade `--use-gpu` (junto con `--use-ocr`) para usar EasyOCR
acelerado por CUDA.

## El menú Escaneo dice "GPU no activa" aunque ya la instalé y funciona

Primero, comprueba el estado real desde el mismo entorno donde corre el
servidor (no desde otra terminal/Python que tengas a mano):

```bash
# reemplaza .venv por el entorno virtual real de tu instalación
.venv\Scripts\python -c "from doc_organize.utils.gpu_detector import detect_gpu_status; print(detect_gpu_status())"
```

**Causa más común: `torch` CPU-only en el entorno del servidor.**
`pip install doc_organize[web,ocr-gpu]` (o `pip install torch` a secas) instala
por defecto el build **CPU-only** de PyTorch — PyPI no publica los builds con
CUDA bajo el nombre normal del paquete. Es fácil comprobarlo y confundirse
porque `import torch` funciona igual de bien con o sin CUDA: solo
`torch.cuda.is_available()` delata la diferencia.

```bash
.venv\Scripts\python -c "import torch; print(torch.__version__, torch.version.cuda)"
```

Si `torch.version.cuda` sale `None` (o la versión no lleva sufijo `+cuXXX`),
reinstala `torch` en **ese mismo entorno** apuntando al índice de PyTorch (ver
[Instalación → Aceleración GPU](installation.md#aceleracion-gpu-para-ocr-opcional)
para el comando exacto con la etiqueta CUDA correcta). Es habitual tener, sin
darse cuenta, `torch` con CUDA instalado en *otro* Python del sistema (uno
distinto al que arranca `doc_organize web`) — comprobar `torch.cuda.is_available()`
ahí no dice nada sobre el entorno real del servidor.

**Causa secundaria: caché por proceso.** `detect_gpu_status()`
(`utils/gpu_detector.py`) cachea su resultado una vez por proceso servidor
(`functools.lru_cache`), para no reimportar `torch` ni reinicializar CUDA en
cada carga de página. Si acabas de arreglar el build de `torch` (o instalar
drivers) con el servidor ya arrancado, reinicia el proceso
(`python -m doc_organize web`) — el nuevo proceso vuelve a detectar el entorno
desde cero. Un reinicio **no** soluciona la causa más común de arriba, solo
esta.

## `ImportError: libGL.so.1` al usar `ocr-gpu` en Linux/Docker

`opencv-python` (parte del extra `ocr-gpu`, necesario para EasyOCR) enlaza con
librerías gráficas del sistema. En servidores o imágenes de contenedor sin
entorno gráfico, `import cv2` falla con
`libGL.so.1: cannot open shared object file`. Dos soluciones:

```bash
# Opción 1: instalar la librería del sistema
apt-get install -y libgl1        # Debian/Ubuntu

# Opción 2: si no necesitas funciones de GUI de OpenCV
pip uninstall opencv-python
pip install opencv-python-headless
```

Ver también [Instalación → Aceleración GPU](installation.md#aceleracion-gpu-para-ocr-opcional).

## `pip install .[av]` falla por `numba`/`llvmlite` en Python 3.14

El extra `[av]` arrastra Whisper (`docling[asr]`), y Whisper depende de
`numba`/`llvmlite`. A fecha de esta revisión, esas dos librerías todavía no
publican wheels precompilados para Python 3.14, así que `pip` falla al
resolver la instalación en ese intérprete.

**No es un bug de `doc_organize`** — revisa `src/doc_organize/utils/av_detector.py`:
no importa ni depende de `numba` en ningún punto, solo comprueba
`find_spec("whisper")` y `shutil.which("ffmpeg")`. Es un problema de
resolución de dependencias de `pip`/Whisper en un intérprete todavía no
soportado por esas librerías, no de la lógica de `doc_organize`.

Soluciones (de entorno, no de código):

1. Crea el entorno virtual con **Python 3.11, 3.12 o 3.13** e instala `[av]`
   ahí — el resto del proyecto no impone esta restricción, solo este extra.
2. Si no necesitas transcribir audio/vídeo, no instales `[av]` ni actives
   `--include-audio-video` (CLI) / el checkbox equivalente (web). El resto de
   `doc_organize` (scan, convert, dedup, cache, OCR) funciona sin restricción
   en Python 3.14.

Ver también [Instalación → Formato extendido: audio/vídeo](installation.md#formato-extendido-audiovideo-opcional).

## `scan --include-audio-video` falla antes de escanear nada

Es el pre-check de `detect_av_status()` (`utils/av_detector.py`, mismo patrón
que `detect_gpu_status()`): sin el backend de transcripción (extra `[av]`) o
sin el binario `ffmpeg` en el `PATH`, la conversión de audio/vídeo fallaría
garantizado en cada fichero — así que el CLI rechaza `--include-audio-video`
entero, con un mensaje que dice exactamente qué falta, antes de tocar la
caché. `.txt` no se ve afectado por este pre-check: se escanea siempre, sin
depender de este flag ni del extra `[av]`. Instala lo que falte:

```bash
pip install doc_organize[av]
# y verifica que 'ffmpeg' está en el PATH:
ffmpeg -version
```

En la interfaz web el checkbox equivalente ("Incluir audio/vídeo") aparece
deshabilitado con el mismo mensaje en el tooltip, en vez de fallar al enviar
el formulario.

## Rutas de salida muy largas o error de ruta en Windows

`DocumentConverter` replica la ruta **absoluta completa** del documento de origen
bajo `Conversión/` (no solo el nombre de archivo). Con carpetas de entrada muy
anidadas, la ruta de salida resultante puede acercarse al límite clásico de 260
caracteres de Windows. Es una limitación conocida — evita escanear jerarquías de
entrada extremadamente profundas hasta que se aborde (ver el PLAN de la Fase 1,
`§14.2`, para el análisis de una corrección propuesta).

## No puedo iniciar sesión en la web (host no-loopback)

Comprueba, en este orden:

1. ¿Estás usando `tenant_id="default"`, `username="admin"` y la contraseña de
   fábrica (`admin`)? Ese login se rechaza a propósito (`403` explícito) en
   modo no-loopback mientras esa contraseña siga sin cambiar — cambia la
   contraseña arrancando el servidor en modo loopback primero (`python -m
   doc_organize web`, sin `--host`), entra ahí, y solo entonces expón el host.
   No hace falta provisionar nada por CLI antes: ese tenant/usuario ya existen
   de fábrica.
2. ¿El `tenant_id`/usuario/contraseña son exactos? El formulario devuelve el mismo
   mensaje de error genérico tanto si el tenant no existe, el usuario está
   bloqueado, o la contraseña es incorrecta (deliberado, evita revelar cuál de
   esos motivos fue).
3. ¿El navegador acepta cookies de este origen? La sesión depende de la cookie
   `doc_organize_session` (`HttpOnly`, `SameSite=Strict`).

Ver [Acceso a la Aplicación](../functional/access.md) para el detalle completo.

## Cerrar sesión en una pestaña me desconecta de las demás

No debería — el logout es selectivo: solo invalida la sesión de la pestaña/
dispositivo desde la que se pide. Si observas lo contrario, es un bug; abre un
issue con los pasos para reproducirlo.

## `mkdocs build` falla por links rotos

Añadiste una página nueva a `docs/` sin registrarla en `nav:` de `mkdocs.yml` (o
al revés). `mkdocs build` valida todos los enlaces internos — corrige el `nav:`
o la ruta del fichero referenciado.
