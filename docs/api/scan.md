# Escaneo — Referencia Técnica

`ScanCommand` orquesta escaneo, caché y conversión (Nivel 3). Lo comparten el CLI y
[doc_organize_web](https://github.com/fmanza/doc_organize_web). Las opciones van en `ScanOptions`.

## ScanCommand

```python
class ScanCommand:
    async def run(
        self,
        paths: list[str],
        output_dir: Path,
        cache_db: Path,
        folders_json: Path,
        use_ocr: bool | None = None,
        use_gpu: bool | None = None,
        force: bool = False,
        include_audio_video: bool = False,
        extract_images: bool = False,
        use_picture_description: bool = False,
        error_log_path: Path | None = None,
        history_log_path: Path | None = None,
        *,
        options: ScanOptions | None = None,
        on_progress: ProgressCallback | None = None,
        cancel_token: CancelToken | None = None,
    ) -> ScanSummary

    async def run_streaming(...)  # mismos argumentos que run
        -> AsyncIterator[ScanEvent]

    async def deduplicate_streaming(
        self,
        paths: list[str],
        duplicates_dir: Path,
        folders_json: Path,
        *,
        report_dir: Path | None = None,
        mode: DedupMode = "move",
        relative_to: Path | None = None,
        on_progress: ProgressCallback | None = None,
        cancel_token: CancelToken | None = None,
        io_retries: int = 0,              # 1.1.0
        io_retry_backoff_s: float = 1.0,  # 1.1.0
    ) -> AsyncIterator[DedupEvent]
```

`run` consume `run_streaming` y devuelve el resumen del evento `COMPLETED`. Si el escaneo se cancela, lanza
`OperationCancelledError`. Los indicadores sueltos (`use_ocr`, `use_gpu`…) y `options` son excluyentes: pasa uno u
otro.

`run_streaming` emite `STARTED`, `SCANNED`, un `FILE_STARTED`/`FILE_CONVERTED` por documento y, con OCR,
`OCR_STARTED` y un `OCR_FILE_STARTED`/`OCR_PROCESSED` por documento. Termina con `COMPLETED` (resumen) o con
`CANCELLED`.

## ScanOptions

Modelo inmutable (`frozen`, `extra="forbid"`). Con los valores por defecto, un escaneo de 1.1.0 se comporta como uno
de 1.0.

| Campo | Tipo | Defecto | Descripción |
|---|---|---|---|
| `use_ocr` | `bool` | `True` | Aplicar OCR a imágenes y PDF escaneados (segunda pasada) |
| `use_gpu` | `bool` | `False` | Motor de OCR con GPU (EasyOCR) si está disponible |
| `force` | `bool` | `False` | Ignorar la caché y reconvertirlo todo |
| `include_audio_video` | `bool` | `False` | Incluir audio y vídeo (extra `av`) |
| `extract_images` | `bool` | `False` | Extraer las imágenes de los documentos |
| `use_picture_description` | `bool` | `False` | Describir las imágenes con un modelo de visión |
| `cache_save_every` | `int ≥ 0` | `20` | Guardar la caché cada N documentos convertidos (0: no) |
| `cache_save_seconds` | `float ≥ 0` | `30.0` | Guardar la caché cada X segundos de conversión (0: no) |
| `artifacts_path` | `Path \| None` | `None` | Carpeta de modelos de Docling |
| `allow_model_downloads` | `bool` | `True` | Permitir que Docling descargue modelos |
| `root_name_in_output` | `bool` | `False` | Incluir el nombre de la carpeta escaneada en la ruta de salida |
| `json_source_path` | `"relative" \| "absolute"` | `"relative"` | `source_path` del JSON de cada documento |
| `max_documents` | `int ≥ 1 \| None` | `None` | **1.1.0.** Parar de forma ordenada tras N conversiones de Docling |
| `document_timeout_s` | `float > 0 \| None` | `None` | **1.1.0.** Segundos máximos por documento y pasada |
| `io_retries` | `int ≥ 0` | `0` | **1.1.0.** Reintentos ante errores de E/S transitorios |
| `io_retry_backoff_s` | `float ≥ 0` | `1.0` | **1.1.0.** Espera antes del primer reintento; se duplica en cada uno |
| `reuse_unchanged_hashes` | `bool` | `False` | **1.1.0.** Reutilizar el hash de la caché si coinciden tamaño y fecha |

### Escaneos por tramos (`max_documents`, G38)

Cada conversión de Docling cuenta una vez: la primera pasada de un documento y su pasada de OCR cuentan por separado.
Al llegar al límite, el escaneo:

1. no empieza el siguiente documento (el que está en curso termina);
2. guarda la caché y el informe de errores;
3. termina con `COMPLETED`, con `stopped_reason="max_documents"` y `remaining` en el resumen.

`remaining` son las conversiones pendientes: documentos sin convertir más candidatos de OCR sin procesar. Lo
convertido queda en la caché y los candidatos de OCR quedan `ocr_pending`, así que la llamada siguiente, con los mismos
argumentos, solo hace lo que falta. El escaneo se ha completado cuando `stopped_reason` es `None`.

```python
options = ScanOptions(use_ocr=True, max_documents=200)
while True:
    summary = await ScanCommand().run(paths, output_dir, cache_db, folders_json, options=options)
    if summary.stopped_reason is None:
        break
```

Si cada tramo se lanza en un proceso nuevo (como el worker de doc_organize_web), la memoria de cada tramo se devuelve
al sistema al terminar ese proceso. Ver [Memoria en escaneos largos](../guides/troubleshooting.md#memoria-en-escaneos-largos).

### Cancelación (`cancel_token`)

El escaneo para **entre documentos**, también en la fase de OCR desde 1.1.0. El documento en curso termina. Lo ya
convertido, y lo ya procesado con OCR, se guarda en la caché; el resto de candidatos de OCR sigue `ocr_pending`. El
último evento es `CANCELLED`. Hasta 1.0.1, cancelar durante el OCR descartaba los documentos ya procesados en ese lote.

### Carpetas de red (`io_retries`, `document_timeout_s`, `reuse_unchanged_hashes`, G11)

- **Reintentos**: listar una carpeta, leer los metadatos de un fichero y calcular su hash se repiten hasta
  `io_retries` veces ante un `OSError` transitorio. Se espera `io_retry_backoff_s`, luego el doble, y así
  sucesivamente. No se reintentan los errores que no cambian al repetir: `FileNotFoundError`, `NotADirectoryError`,
  `IsADirectoryError` y `FileExistsError`. Un fichero que agota los reintentos:
    - no aborta la carpeta: queda fuera de este escaneo;
    - aparece en el aviso del evento `SCANNED`, en `ScanSummary.io_errors` y en el `ScanErrorReport` (`error_log_path`);
    - no se da por eliminado: con `force`, ni se borra su salida ni se pierde su entrada de caché.

  Un fichero que desaparece durante el escaneo se omite sin más, como en 1.0.
- **Timeout por documento**: el documento que tarda más de `document_timeout_s` queda en `ERROR` con la causa
  («Superado el tiempo máximo de conversión por documento») y el escaneo sigue con el siguiente. El hilo de Docling no
  se puede interrumpir: sigue hasta terminar en segundo plano y su resultado se descarta. El convertidor de ese modo se
  descarta también y el siguiente documento vuelve a cargar los modelos, así que hay un pico de memoria temporal.
- **Sin rehashear lo que no cambia**: con `reuse_unchanged_hashes=True`, un fichero cuya caché tiene el mismo
  `size_bytes` y la misma fecha de modificación (`timestamp`) reutiliza su hash sin leerlo. No detecta un cambio que
  conserve tamaño y fecha. Las entradas anteriores a 1.1.0 no tienen tamaño y se rehashean una vez. Con `force` se
  rehashea todo.
- **Enlaces**: los enlaces simbólicos, y desde 1.1.0 las *junctions* de Windows, no se siguen. Solo se resuelve la
  carpeta raíz indicada.

## ScanSummary

```python
@dataclass
class ScanSummary:
    scanned: int
    new: int
    modified: int
    unchanged: int
    converted: int
    conversion_errors: int
    ocr_required: int
    ocr_processed: int
    error_retries: int
    error_retries_capped: int
    duration_seconds: float
    discovery_duration_seconds: float
    total_conversion_seconds: float
    io_errors: int = 0                # 1.1.0: ficheros que no se pudieron leer (G11)
    remaining: int = 0                # 1.1.0: conversiones pendientes por max_documents (G38)
    stopped_reason: str | None = None # 1.1.0: "max_documents" o None
```

El evento `COMPLETED` lleva estos campos en `data` (`dataclasses.asdict`). Los tres campos nuevos se añaden siempre,
con sus valores por defecto si no aplican.
