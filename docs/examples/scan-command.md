# Ejemplo: Escanear y Convertir con ScanCommand

**Objetivo**: Demostrar cómo escanear una carpeta con `ScanCommand`, seguir el progreso y leer el `ScanSummary`.

## 1. Contexto del Ejemplo

`ScanCommand` es la orquestación que usan el CLI y doc_organize_web: valida las carpetas, recorre los documentos,
compara con la caché y convierte con Docling lo nuevo o modificado. Las opciones van en un `ScanOptions` y el progreso
llega a `on_progress` como `ProgressEvent`. El ejemplo escanea la misma carpeta tres veces para ver cómo la caché evita
reconvertir lo que no ha cambiado.

### Requisitos

- Python 3.12+
- `doc_organize` instalado (Docling es dependencia del paquete base)

El ejemplo crea dos HTML en un directorio temporal y escanea con `use_ocr=False`: el pipeline de HTML de Docling no
usa modelos, así que no descarga nada ni necesita red. Un PDF o una imagen sí cargan los modelos de Docling (ver
[Converter](converter-convert.md)). El `.md` que también se crea no es una extensión soportada y no se escanea.

## 2. Implementación de Referencia

```python
import asyncio
import tempfile
from pathlib import Path

from doc_organize import ProgressEvent, ScanCommand, ScanOptions, ScanSummary


def show(summary: ScanSummary) -> None:
    print(f"  escaneados={summary.scanned} nuevos={summary.new} modificados={summary.modified} "
          f"sin_cambios={summary.unchanged} convertidos={summary.converted} errores={summary.conversion_errors} "
          f"ocr={summary.ocr_required} parado={summary.stopped_reason}")


async def main() -> None:
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp = Path(tmp_dir).resolve()
        source = tmp / "origen"
        (source / "actas").mkdir(parents=True)
        (source / "actas" / "enero.html").write_text("<h1>Acta de enero</h1><p>Se aprueba el presupuesto.</p>", encoding="utf-8")
        (source / "actas" / "febrero.html").write_text("<h1>Acta de febrero</h1><p>Se revisan contratos.</p>", encoding="utf-8")
        (source / "notas.md").write_text("# Notas\n", encoding="utf-8")  # Extensión no soportada: no se escanea
        state = tmp / "estado"  # Caché y carpetas validadas
        output_dir = tmp / "Conversión"
        cache_db, folders_json = state / "cache.db", state / "folders.json"

        in_progress: list[str] = []

        def on_progress(event: ProgressEvent) -> None:
            if event.current:  # Documento que empieza: el orden entre documentos no está garantizado
                in_progress.append(Path(event.current).relative_to(source).as_posix())
            else:
                print(f"  [{event.operation}] {event.phase}: {event.processed}/{event.total}")

        options = ScanOptions(use_ocr=False)  # HTML no necesita OCR ni modelos de Docling
        command = ScanCommand()

        print("Primer escaneo:")
        summary = await command.run([str(source)], output_dir, cache_db, folders_json,
                                    options=options, on_progress=on_progress)
        show(summary)
        print("  documentos en curso:", sorted(in_progress))
        print(" ", sorted(p.relative_to(output_dir).as_posix() for p in output_dir.rglob("*") if p.is_file()))

        print("Segundo escaneo (sin cambios):")
        show(await command.run([str(source)], output_dir, cache_db, folders_json, options=options))

        (source / "actas" / "febrero.html").write_text("<h1>Acta de febrero</h1><p>Contratos firmados.</p>", encoding="utf-8")
        print("Tercer escaneo (febrero.html modificado):")
        summary = await command.run([str(source)], output_dir, cache_db, folders_json, options=options)
        show(summary)
        print(summary.render().splitlines()[0])


if __name__ == "__main__":
    asyncio.run(main())
```

## 3. Explicación del Código

1. **Opciones**: `ScanOptions(use_ocr=False)` es un modelo inmutable; se pasa como `options=` y entonces no se pueden
   pasar también los indicadores sueltos (`use_ocr`, `use_gpu`…): mezclarlos lanza `TypeError`
2. **Rutas**: `run()` recibe las carpetas a escanear, la carpeta de salida, la caché (`cache_db`) y el JSON de carpetas
   validadas (`folders_json`); en un proyecto salen de `ProjectLayout` (`layout.conversion_dir`, `layout.cache_db`,
   `layout.folders_json`)
3. **Progreso**: `on_progress` recibe un `ProgressEvent` por evento del escaneo: fase `started`, `conversion` (con
   `total` = documentos a convertir, `processed` = convertidos y `current` = el documento que empieza) y `done`. Un
   fallo del callback se registra y no para el escaneo. El orden entre documentos no está garantizado, por eso el
   ejemplo los ordena antes de imprimirlos. El `done` final llega con `processed=0` y `total=None`: el resumen está en
   el valor que devuelve `run()`
4. **Resultado**: `run()` devuelve el `ScanSummary` del evento `COMPLETED` (si se cancela con un `CancelToken`, lanza
   `OperationCancelledError`). `stopped_reason` es `None` cuando el escaneo terminó todo (no se pasó `max_documents`)
5. **Salida**: Cada documento deja un `.md` y un `.json` bajo la carpeta de salida, replicando su ruta relativa a la
   carpeta escaneada (`actas/`)
6. **Caché**: El segundo escaneo encuentra los dos documentos `sin_cambios` y no convierte nada; al modificar
   `febrero.html`, el tercero solo reconvierte ese
7. **Texto para el usuario**: `summary.render()` da el resumen que imprime el CLI (aquí solo su primera línea; las
   últimas llevan tiempos)

Para ver cada `ScanEvent` en lugar del resumen, `run_streaming()` acepta los mismos argumentos y emite `STARTED`,
`SCANNED`, `FILE_STARTED`/`FILE_CONVERTED` por documento y `COMPLETED`.

## 4. Ejecución y Pruebas

```bash
$ python scan_example.py
Primer escaneo:
  [scan] started: 0/None
  [scan] conversion: 0/2
  [scan] conversion: 1/2
  [scan] conversion: 2/2
  [scan] done: 0/None
  escaneados=2 nuevos=2 modificados=0 sin_cambios=0 convertidos=2 errores=0 ocr=0 parado=None
  documentos en curso: ['actas/enero.html', 'actas/febrero.html']
  ['actas/enero.json', 'actas/enero.md', 'actas/febrero.json', 'actas/febrero.md']
Segundo escaneo (sin cambios):
  escaneados=2 nuevos=0 modificados=0 sin_cambios=2 convertidos=0 errores=0 ocr=0 parado=None
Tercer escaneo (febrero.html modificado):
  escaneados=2 nuevos=0 modificados=1 sin_cambios=1 convertidos=1 errores=0 ocr=0 parado=None
Documentos escaneados: 2
```

La primera importación de Docling tarda (en torno a medio minuto en frío). Validación sintáctica:
`python -m py_compile scan_example.py`.

## 5. Referencias Relacionadas

- [Referencia técnica: Escaneo](../api/scan.md)
- [Documentación funcional: Escáner](../functional/scanner.md)
- [Ejemplo: Escanear documentos](scanner-scan.md)
- [Ejemplo: Convertir documentos a Markdown](converter-convert.md)
- [Ejemplo: Detectar cambios con caché](cache-changes.md)
