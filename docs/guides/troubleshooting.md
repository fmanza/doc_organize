# Resolución de problemas

## `libgomp.so.1` no encontrado en Linux mínimo/contenedores

RapidOCR (motor OCR por defecto, incluido en el núcleo) usa ONNX Runtime, que
enlaza en tiempo de ejecución con `libgomp.so.1` (OpenMP de GCC). Las imágenes
completas de Ubuntu/Debian ya lo incluyen, pero variantes `slim`/`alpine` o
distros mínimas no. Instala el paquete del sistema:

```bash
apt-get install -y libgomp1    # Debian/Ubuntu
# equivalente en otras distros: busca el paquete "libgomp" con tu gestor
```

Ver también [Instalación → Núcleo (CLI)](installation.md#nucleo-cli-y-libreria).

## Un documento escaneado nunca sale de "OCR pendiente"

`--use-ocr` reprocesa en la misma ejecución los documentos detectados como
`ocr_required`. Si escaneaste sin `--use-ocr`, esos documentos quedan marcados
`OCR_PENDING` en el caché — vuelve a ejecutar `scan` con `--use-ocr` (no hace
falta re-escanear las carpetas de origen; el caché ya los tiene identificados).

## OCR muy lento en documentos grandes

El motor por defecto (RapidOCR) corre en CPU. Si tienes GPU disponible, instala
el extra `ocr-gpu` y añade `--use-gpu` (junto con `--use-ocr`) para usar EasyOCR
acelerado por CUDA.

## Memoria en escaneos largos

Un escaneo con OCR de cientos de documentos puede agotar la memoria de un proceso con límite, como un contenedor de
6 GiB. Desde 1.1.0:

- **Por tramos**: `ScanOptions(max_documents=N)` para el escaneo de forma ordenada tras N conversiones. Guarda la
  caché y deja `stopped_reason="max_documents"` y `remaining` en el resumen. Lanza cada tramo en un proceso nuevo para
  que el sistema recupere toda la memoria entre tramos (ver [Escaneo](../api/scan.md#escaneos-por-tramos-max_documents-g38)).
  Es la única medida que acota la memoria pase lo que pase dentro de Docling.
- **Liberación periódica**: durante la conversión, cada 10 documentos se recogen los ciclos de referencias
  (`gc.collect()`). En Linux con glibc, además, se devuelve al sistema la memoria libre del *heap* (`malloc_trim`). No
  hay que configurarlo. Cuesta unos 40 ms por documento repartidos, porque un `gc.collect()` con los modelos de Docling
  cargados tarda unos 0,35 s.

Medidas de 1.1.0 con `tests/integration/test_scan_memory_growth.py`. Son documentos sintéticos: una quinta parte cada
uno de PDF con texto, PDF escaneado, `.docx`, `.xlsx` y `.html`, todos con OCR. El RSS se mide cada 50 conversiones.

| Entorno | Liberación periódica | RSS a las 50 conversiones | Al terminar la primera pasada | Final (tras el OCR) |
|---|---|---|---|---|
| Linux (Docker, Python 3.12, 200 documentos) | no¹ | 1 433 MiB | 1 512 MiB | 1 822 MiB |
| Linux (Docker, Python 3.12, 200 documentos) | sí (1.1.0) | 1 035 MiB | 1 037 MiB | 814 MiB |
| Windows 11 (Python 3.14, 150 documentos) | no (1.0.1) | 2 475 MiB | 2 988 MiB | 5 332 MiB |
| Windows 11 (Python 3.14, 150 documentos) | sí (1.1.0) | 2 310 MiB | 2 690 MiB | 3 042 MiB |

¹ El código de 1.1.0 antes de añadir la liberación, que en memoria se comporta como 1.0.1. Con la liberación, el
escaneo de Linux tardó 91 s en lugar de 128 s; en Windows la primera pasada tardó unos 6 s más (24,7 s frente a 18,2 s).

Lo que se vio al aislar cada causa:

- Los `.docx` (python-docx sobre lxml) y las imágenes de página del OCR (PIL/numpy) quedan en ciclos de referencias.
  El recolector de Python se dispara por número de objetos, no por bytes, así que tarda en liberarlos. En Windows, sin
  recolección explícita, un `.docx` dejaba unos 5 MiB y un PDF escaneado unos 40 MiB por documento. En Linux el `.docx`
  crece en dientes de sierra y se estabiliza.
- En Windows, el pipeline PDF de Docling (modelo de *layout*) deja además unos 9 MiB por documento en memoria nativa.
  No se libera con `gc.collect()`, ni con un hilo único, ni creando un convertidor nuevo. En Linux no aparece. El
  remedio en Windows es partir el escaneo en tramos.
- El pico dentro de un documento crece poco con las páginas: un PDF escaneado de 40 páginas con OCR llegó a 2,9 GiB
  (1 página: 1,6 GiB).
- Cargar los modelos cuesta alrededor de 1 GiB la primera vez (primera pasada y OCR por separado). Los de la primera
  pasada se sueltan antes de cargar los del OCR.

Con documentos sintéticos no se ha reproducido el agotamiento de 6 GiB que vio doc_organize_web con 521 documentos
reales. Si vuelve a pasar, mide con tus documentos (`DOC_ORGANIZE_MEMORY_TEST=1`, ver el test) y usa `max_documents`.

## Carpetas de red: cortes, ficheros bloqueados y documentos que no terminan

- `ScanOptions(io_retries=3, io_retry_backoff_s=1.0)` repite listar, leer y hashear ante errores de E/S transitorios,
  esperando 1 s, luego 2 s y luego 4 s. El fichero que agota los reintentos no aborta la carpeta: sale en los avisos
  del evento `SCANNED`, en `ScanSummary.io_errors` y en el informe de errores, y no se da por eliminado.
  `ScanCommand.deduplicate_streaming(io_retries=...)` hace lo mismo al buscar duplicados y al copiar (`mode="copy"`).
- `ScanOptions(document_timeout_s=600)` deja en error el documento que tarde más de 10 minutos y sigue con el
  siguiente.
- `ScanOptions(reuse_unchanged_hashes=True)` no vuelve a leer los ficheros cuyo tamaño y fecha coinciden con la
  caché, así que un escaneo incremental de una carpeta de red grande no la lee entera.

Ver [Escaneo](../api/scan.md#carpetas-de-red-io_retries-document_timeout_s-reuse_unchanged_hashes-g11).

## `detect_gpu_status()` dice "GPU no activa" aunque ya la instalé y funciona

Primero, comprueba el estado real desde el mismo entorno donde corre
doc_organize (no desde otra terminal/Python que tengas a mano):

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
distinto al que ejecuta `doc_organize`) — comprobar `torch.cuda.is_available()`
ahí no dice nada sobre el entorno real del proceso.

**Causa secundaria: caché por proceso.** `detect_gpu_status()`
(`utils/gpu_detector.py`) cachea su resultado una vez por proceso servidor
(`functools.lru_cache`), para no reimportar `torch` ni reinicializar CUDA en
cada carga de página. Si acabas de arreglar el build de `torch` (o instalar
drivers) con el proceso ya arrancado, reinícialo — el nuevo proceso vuelve a detectar el entorno
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

`detect_av_status()` devuelve el mismo diagnóstico para que una interfaz (p. ej.
doc_organize_web) deshabilite la opción en vez de fallar al enviar el formulario.

## Un `.xls` falla con "LibreOffice is required"

Es el pre-check de `detect_office_status()` (`utils/office_detector.py`, mismo
patrón que `detect_av_status()`/`detect_gpu_status()`): Docling necesita
LibreOffice (binario `soffice`/`libreoffice`) en el `PATH` para convertir
Excel legado (`.xls`) a `.xlsx` antes de parsearlo, y sin él esa conversión
falla garantizado en cada fichero. A diferencia de audio/vídeo, `.xls` no es
opt-in (se escanea siempre), así que `doc_organize` no bloquea el escaneo
entero: corta la conversión de ese `.xls` concreto con el mensaje de qué
instalar, sin gastar los reintentos automáticos ni llegar a invocar Docling.
El resto de formatos (`.xlsx` incluido) no se ve afectado. Instala LibreOffice
con el gestor de paquetes de tu sistema operativo (ver
[Instalación → Excel legado: LibreOffice](installation.md#excel-legado-xls-libreoffice-opcional))
y verifica con:

```bash
soffice --version
```

## Rutas de salida muy largas o error de ruta en Windows

`DocumentConverter` replica la ruta **absoluta completa** del documento de origen
bajo `Conversión/` (no solo el nombre de archivo). Con carpetas de entrada muy
anidadas, la ruta de salida resultante puede acercarse al límite clásico de 260
caracteres de Windows. Es una limitación conocida — evita escanear jerarquías de
entrada extremadamente profundas hasta que se aborde (ver el PLAN de la Fase 1,
`§14.2`, para el análisis de una corrección propuesta).

## `zensical build --strict` falla por links rotos

Añadiste una página nueva a `docs/` sin registrarla en `nav` de `zensical.toml` (o
al revés). `zensical build --strict` valida todos los enlaces internos — corrige el `nav`
o la ruta del fichero referenciado.
