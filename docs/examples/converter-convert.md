# Ejemplo: Convertir Documentos a Markdown

**Objetivo**: Demostrar cómo convertir documentos a Markdown y JSON.

## 1. Contexto del Ejemplo

El `DocumentConverter` usa Docling para transformar PDF, DOCX, HTML, etc. a Markdown legible + JSON estructurado (troceado por secciones, pensado para IA).

### Requisitos

- Python 3.11+
- `doc_organize` instalado (Docling es dependencia del paquete base)
- Documentos escaneados (con `DocumentMetadata`)

El ejemplo convierte un HTML creado en un directorio temporal: el pipeline de HTML de Docling no usa modelos, así que no descarga nada. Un PDF o una imagen sí cargan los modelos de Docling (se descargan la primera vez, salvo `artifacts_path`).

## 2. Implementación de Referencia

```python
import asyncio
import tempfile
from pathlib import Path

from doc_organize.converter import DocumentConverter
from doc_organize.scanner import DocumentScanner


async def main() -> None:
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp = Path(tmp_dir).resolve()
        source_root = tmp / "Documents"
        output_dir = tmp / "Conversión"
        (source_root / "informes").mkdir(parents=True)
        (source_root / "informes" / "report.html").write_text(
            "<h1>Informe</h1><p>Resultados del trimestre.</p>", encoding="utf-8"
        )

        async with DocumentScanner() as scanner:
            doc = (await scanner.scan_folders([str(source_root)])).documents[0]

        async with DocumentConverter() as converter:
            result = await converter.convert_document(
                source_doc=doc,
                output_dir=output_dir,
                use_ocr=False,  # Primera pasada sin OCR
                scan_roots=[str(source_root)],  # Replica informes/ bajo output_dir
            )

        print(f"Éxito: {result.success}")
        print(f"OCR requerido: {result.ocr_required}")
        if result.success:
            print(f"Markdown: {Path(result.markdown_path).relative_to(tmp).as_posix()}")
            print(f"JSON: {Path(result.json_path).relative_to(tmp).as_posix()}")
            print(Path(result.markdown_path).read_text(encoding="utf-8").strip())
        else:
            print(f"Error: {result.error}")


if __name__ == "__main__":
    asyncio.run(main())
```

## 3. Explicación del Código

1. **Creación**: `DocumentConverter` se usa como context manager asíncrono (`async with`); fuera de él, `convert_document()` falla
2. **Conversión**: Se convierte el documento a `.md` + `.json` bajo `output_dir`, replicando su ruta relativa a `scan_roots` (sin `scan_roots`, la salida se aplana a `output_dir/<stem>`)
3. **Detección OCR**: Si es PDF/imagen y `parse_score=NaN`, marca `ocr_required=True` (el resto de formatos nunca lo requieren)
4. **Errores**: Un fallo de conversión no se lanza: vuelve en `ConversionResult` con `success=False` y `error`, para no abortar un lote
5. **Retorno**: `ConversionResult` con rutas de salida y `duration_seconds`
6. **OCR diferido**: Si es necesario, se llama a `OCRScheduler` en una segunda pasada

## 4. Ejecución y Pruebas

```bash
$ python converter_example.py
Éxito: True
OCR requerido: False
Markdown: Conversión/informes/report.md
JSON: Conversión/informes/report.json
# Informe

Resultados del trimestre.
```

La primera importación de Docling tarda (en torno a un minuto en frío). Validación sintáctica:
`python -m py_compile converter_example.py`.

## 5. Referencias Relacionadas

- [Documentación funcional: Converter](../functional/converter.md)
- [Referencia técnica: Converter](../api/converter.md)
- [Ejemplo: Escanear documentos](scanner-scan.md)
