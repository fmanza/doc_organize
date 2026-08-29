# Ejemplo: Escanear Documentos

**Objetivo**: Demostrar cómo escanear documentos en carpetas y calcular sus hashes.

## Contexto

El `DocumentScanner` descubre todos los documentos (respetando extensiones soportadas), calcula SHA-256 y construye un árbol de directorios.

## Requisitos

- Python 3.11+
- `doc_organize` instalado
- Carpetas con documentos (PDF, DOCX, XLSX, PPTX, PNG, JPG, etc.)

## Código

```python
from pathlib import Path
from doc_organize.scanner import DocumentScanner

async def main():
    scanner = DocumentScanner()
    
    paths = [Path("/home/user/Documents")]
    
    # Escanear
    result = await scanner.scan(paths)
    
    print(f"Total documentos: {len(result.documents)}")
    print(f"Resumen: {result.summary}")
    print(f"Duración: {result.scan_duration_seconds:.2f}s")
    
    # Primeros 5 documentos
    for doc in result.documents[:5]:
        print(f"  📄 {doc.display_name} ({doc.size_bytes:,} bytes)")
        print(f"     SHA-256: {doc.sha256_hash[:16]}...")

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
```

## Ejecución

```bash
$ python examples/scanner_example.py
Total documentos: 42
Resumen: {'soportados': 42, 'ignorados': 3, 'errores': 0}
Duración: 1.23s
  📄 report.pdf (2,450,123 bytes)
     SHA-256: a1b2c3d4e5f6g7h8...
  📄 budget.xlsx (125,456 bytes)
     SHA-256: f9e8d7c6b5a4932e...
  📄 presentation.pptx (3,891,200 bytes)
     SHA-256: 1a2b3c4d5e6f7g8h...
  📄 photo1.jpg (892,456 bytes)
     SHA-256: x9y8z7w6v5u4t3s2...
  📄 photo2.jpg (912,123 bytes)
     SHA-256: a8b7c6d5e4f3g2h1...
```

## Explicación

1. **Creación**: Se crea instancia de `DocumentScanner`
2. **Escaneo**: Se escanean carpetas recursivamente
3. **Hashing**: Calcula SHA-256 concurrente de cada documento
4. **Árbol**: Construye estructura jerárquica de directorios
5. **Retorno**: `ScanResult` con lista de documentos + resumen + árbol

## Referencias

- [Documentación funcional: Scanner](../functional/scanner.md)
- [Referencia técnica: Scanner](../api/scanner.md)
- [Validadores — Validación de carpetas](../api/validators.md)
