# Ejemplo: Exportar un Proyecto a ZIP y Excel

**Objetivo**: Demostrar cómo calcular y escribir el ZIP de un proyecto y el Excel de su caché.

## 1. Contexto del Ejemplo

`doc_organize.export` empaqueta lo que un proyecto ya tiene: `preview_project_zip` dice cuántos ficheros y bytes
llevaría el ZIP sin escribirlo, `write_project_zip` lo escribe (conversiones, instantánea de la caché e informe de
duplicados) y `write_cache_xlsx` vuelca la caché a Excel. Las entradas se leen de una o varias cachés con
`load_cache_entries`.

### Requisitos

- Python 3.12+
- `doc_organize` instalado; para el Excel, el extra `export` (`pip install doc_organize[export]`, instala `openpyxl`).
  El ZIP no lo necesita

El ejemplo prepara a mano un proyecto pequeño en un directorio temporal (dos entradas de caché guardadas con
`CacheManager`, una conversión y un `DEDUP_REPORT.json`), así que no carga Docling ni usa la red. En uso real, esos
ficheros los deja `ScanCommand` (ver [Escanear y convertir con ScanCommand](scan-command.md)).

## 2. Implementación de Referencia

```python
import asyncio
import hashlib
import json
import tempfile
import zipfile
from pathlib import Path

from doc_organize import (
    CacheEntry,
    CacheManager,
    ConversionStatus,
    DocumentStatus,
    MissingDependencyError,
    ProgressEvent,
    ProjectLayout,
    load_cache_entries,
    preview_project_zip,
    write_cache_xlsx,
    write_project_zip,
)


def entry(source: Path, content: bytes, status: ConversionStatus) -> CacheEntry:
    return CacheEntry(file_path=str(source), sha256_hash=hashlib.sha256(content).hexdigest(), timestamp=1_700_000_000.0,
                      status=DocumentStatus.NEW, conversion_status=status, size_bytes=len(content))


async def main() -> None:
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp = Path(tmp_dir).resolve()
        layout = ProjectLayout(tmp / "Proyecto", state_root=tmp / "estado")
        source = tmp / "origen"

        # Un proyecto pequeño ya escaneado: dos conversiones, su caché y un informe de duplicados
        (layout.conversion_dir / "actas").mkdir(parents=True)
        (layout.conversion_dir / "actas" / "enero.md").write_text("# Acta de enero\n", encoding="utf-8")
        (layout.conversion_dir / "actas" / "enero.json").write_text("{}", encoding="utf-8")
        layout.dedup_report.parent.mkdir(parents=True)
        layout.dedup_report.write_text("{}", encoding="utf-8")
        async with CacheManager(layout.cache_db) as cache:
            await cache.save_entries([
                entry(source / "actas" / "enero.html", b"<h1>Acta de enero</h1>", ConversionStatus.SUCCESS),
                entry(source / "escaneo.pdf", b"%PDF-1.7", ConversionStatus.OCR_PENDING),
            ])

        entries = await load_cache_entries([layout.cache_db])
        preview = await asyncio.to_thread(preview_project_zip, entries, layout=layout)
        print(f"Vista previa: {preview.file_count} ficheros")

        def on_progress(event: ProgressEvent) -> None:
            print(f"  [{event.operation}] {event.phase}: {event.processed}/{event.total} {event.current or '-'}")

        destination = tmp / "proyecto.zip"
        stats = await asyncio.to_thread(write_project_zip, destination, entries, layout=layout, on_progress=on_progress)
        print(f"ZIP: {stats.file_count} ficheros, mismos bytes que la vista previa: {stats.total_size_bytes == preview.total_size_bytes}")
        with zipfile.ZipFile(destination) as archive:
            print(f"  {archive.namelist()}")
            snapshot = json.loads(archive.read("cache_export.json"))
        print(f"  cache_export.json: {[Path(e['file_path']).name for e in snapshot['entries']]}")

        try:
            rows = await asyncio.to_thread(write_cache_xlsx, tmp / "cache.xlsx", entries)
        except MissingDependencyError as exc:  # Sin el extra `export` (openpyxl)
            print(f"Excel no disponible: instala doc_organize[{exc.extra}]")
        else:
            from openpyxl import load_workbook

            workbook = load_workbook(tmp / "cache.xlsx", read_only=True)
            sheet = workbook.active
            header = next(sheet.iter_rows(max_row=1, values_only=True))
            workbook.close()  # El modo read_only deja el fichero abierto hasta cerrarlo
            print(f"Excel: {rows} filas en la hoja {sheet.title!r}; columnas: {list(header)}")


if __name__ == "__main__":
    asyncio.run(main())
```

## 3. Explicación del Código

1. **Rutas**: `ProjectLayout(output_root, state_root=...)` da todas las rutas del proyecto: `conversion_dir`
   (`Proyecto/Conversión`), `cache_db` y `dedup_report` (en el estado, `estado/duplicados/DEDUP_REPORT.json`)
2. **Entradas**: `load_cache_entries` lee una o varias `cache.db` (las que no existen se omiten; si una ruta está en
   dos, gana la última) y devuelve `CacheEntry` sin orden garantizado; las funciones de exportación las ordenan por
   `file_path`
3. **Vista previa**: `preview_project_zip` cuenta ficheros y bytes de lo que escribiría `write_project_zip` con los
   mismos argumentos, sin escribir nada. `layout` y `conversion_dir`/`dedup_report` son excluyentes (`ValueError`)
4. **ZIP**: `write_project_zip` mete `Conversión/` en orden alfabético, `cache_export.json` (la instantánea de la
   caché, con `export_timestamp`) y `duplicados/DEDUP_REPORT.json` si existe. Devuelve `ExportStats`
   (`file_count`, `total_size_bytes`). El ejemplo no imprime los bytes porque dependen de la longitud de las rutas
   absolutas del directorio temporal; solo comprueba que coinciden con la vista previa
5. **Progreso**: `on_progress` recibe `ProgressEvent(operation="export")`: `started`, un `export` por fichero del ZIP
   (`current` = nombre dentro del archivo) y `done`
6. **Síncronas**: Las escrituras son síncronas; desde código async se llaman con `asyncio.to_thread` (el `CancelToken`,
   si se pasa, es seguro entre hilos)
7. **Excel**: `write_cache_xlsx` escribe la hoja `Cache` y devuelve las filas de datos; sin `openpyxl` lanza
   `MissingDependencyError` con `extra="export"`. El ejemplo lo relee con `openpyxl` en modo `read_only` y lo cierra
   (en Windows, un libro sin cerrar impide borrar el directorio temporal)

## 4. Ejecución y Pruebas

```bash
$ python export_example.py
Vista previa: 4 ficheros
  [export] started: 0/4 -
  [export] export: 1/4 Conversión/actas/enero.json
  [export] export: 2/4 Conversión/actas/enero.md
  [export] export: 3/4 cache_export.json
  [export] export: 4/4 duplicados/DEDUP_REPORT.json
  [export] done: 4/4 -
ZIP: 4 ficheros, mismos bytes que la vista previa: True
  ['Conversión/actas/enero.json', 'Conversión/actas/enero.md', 'cache_export.json', 'duplicados/DEDUP_REPORT.json']
  cache_export.json: ['enero.html', 'escaneo.pdf']
Excel: 2 filas en la hoja 'Cache'; columnas: ['Archivo', 'Carpeta', 'Ruta completa', 'Hash SHA-256', 'Estado', 'Conversión', 'Última actualización (UTC)']
```

Sin el extra `export`, la última línea es `Excel no disponible: instala doc_organize[export]`. Validación sintáctica:
`python -m py_compile export_example.py`.

## 5. Referencias Relacionadas

- [Referencia técnica: Exportación](../api/export.md)
- [Documentación funcional: Exportación](../functional/export.md)
- [Ejemplo: Escanear y convertir con ScanCommand](scan-command.md)
- [Ejemplo: Detectar cambios con caché](cache-changes.md)
