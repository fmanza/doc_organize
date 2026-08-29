# Ejemplo: Convertir Documentos a Markdown

**Objetivo**: Demostrar cómo convertir documentos a Markdown y JSON.

## Contexto

El `DocumentConverter` usa Docling para transformar PDF, DOCX, etc. a Markdown legible + JSON estructurado.

## Requisitos

- Python 3.11+
- `doc_organize[converter]` instalado (incluye Docling)
- Documentos escaneados (con `DocumentMetadata`)

## Código

```python
from pathlib import Path
from doc_organize.converter import DocumentConverter
from doc_organize.core.models import DocumentMetadata
from datetime import datetime

async def main():
    output_dir = Path("/tmp/doc_organize/output")
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Simular documento escaneado
    doc = DocumentMetadata(
        full_path=Path("/home/user/Documents/report.pdf"),
        display_name="report.pdf",
        extension="pdf",
        size_bytes=2450123,
        modified_time=datetime.now(),
        sha256_hash="a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6"
    )
    
    async with DocumentConverter() as converter:
        result = await converter.convert_document(
            source_doc=doc,
            output_dir=output_dir,
            use_ocr=False,  # Primera pasada sin OCR
            use_gpu=False
        )
        
        print(f"Éxito: {result.success}")
        print(f"OCR requerido: {result.ocr_required}")
        print(f"Duración: {result.duration_seconds:.2f}s")
        
        if result.success:
            print(f"Markdown: {result.markdown_path}")
            print(f"JSON: {result.json_path}")
        else:
            print(f"Error: {result.error}")

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
```

## Ejecución

```bash
$ python examples/converter_example.py
Éxito: True
OCR requerido: False
Duración: 2.34s
Markdown: /tmp/doc_organize/output/report.md
JSON: /tmp/doc_organize/output/report.json
```

## Explicación

1. **Creación**: Se crea instancia de `DocumentConverter` (context manager)
2. **Conversión**: Se convierte documento a Markdown + JSON
3. **Detección OCR**: Si `parse_score=NaN`, marca `ocr_required=True`
4. **Retorno**: `ConversionResult` con rutas de salida
5. **OCR diferido**: Si necesario, llamar a `OCRScheduler` en segunda pasada

## Referencias

- [Documentación funcional: Converter](../functional/converter.md)
- [Referencia técnica: Converter](../api/converter.md)
- [Scanner — Escaneo de documentos](../api/scanner.md)
