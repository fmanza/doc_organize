# Ejemplo: Escanear Documentos

**Objetivo**: Demostrar cómo escanear documentos en carpetas y calcular sus hashes.

## 1. Contexto del Ejemplo

El `DocumentScanner` descubre todos los documentos (respetando extensiones soportadas), calcula SHA-256 y construye un árbol de directorios.

### Requisitos

- Python 3.11+
- `doc_organize` instalado

El ejemplo crea sus documentos en un directorio temporal: se ejecuta tal cual y la salida es siempre la misma.

## 2. Implementación de Referencia

```python
import asyncio
import tempfile
from pathlib import Path

from doc_organize.scanner import DocumentScanner


async def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "Documents"
        (root / "informes").mkdir(parents=True)
        (root / "informes" / "report.txt").write_text("Informe trimestral", encoding="utf-8")
        (root / "notas.html").write_text("<h1>Notas de la reunión</h1>", encoding="utf-8")
        (root / "programa.exe").write_bytes(b"MZ")  # Extensión no soportada: se ignora

        async with DocumentScanner() as scanner:
            result = await scanner.scan_folders([str(root)])

        print(f"Total documentos: {len(result.documents)}")
        print(f"Resumen: {dict(sorted(result.summary.items()))}")
        print(f"Carpetas ilegibles: {result.unreadable_dirs}")
        for doc in sorted(result.documents, key=lambda d: d.display_name):
            print(f"  {doc.display_name} ({doc.size_bytes} bytes) SHA-256: {doc.sha256_hash[:16]}...")


if __name__ == "__main__":
    asyncio.run(main())
```

## 3. Explicación del Código

1. **Creación**: `DocumentScanner` se usa como context manager asíncrono (`async with`)
2. **Escaneo**: `scan_folders()` recorre las carpetas recursivamente en un hilo aparte; deben existir (valídalas antes con `FolderValidator`)
3. **Filtro**: Solo entran las extensiones de `SUPPORTED_EXTENSIONS` (`.exe` se ignora; audio y vídeo, con `include_audio_video=True`)
4. **Hashing**: Calcula el SHA-256 de cada documento de forma concurrente (acotada por `max_concurrent_hashes`)
5. **Retorno**: `ScanResult` con `documents`, `summary` (conteo por extensión), `tree`, `scan_duration_seconds` y lo que no se pudo leer (`unreadable_dirs`, `unreadable_files`)

## 4. Ejecución y Pruebas

```bash
$ python scanner_example.py
Total documentos: 2
Resumen: {'html': 1, 'txt': 1}
Carpetas ilegibles: []
  notas.html (29 bytes) SHA-256: eb0be6fac3c305dd...
  report.txt (18 bytes) SHA-256: 9a47508fd6bdb936...
```

Validación sintáctica: `python -m py_compile scanner_example.py`.

## 5. Referencias Relacionadas

- [Documentación funcional: Scanner](../functional/scanner.md)
- [Referencia técnica: Scanner](../api/scanner.md)
- [Ejemplo: Validar carpetas antes de escanear](validators-scan.md)
- [Ejemplo: Detectar cambios con caché](cache-changes.md)
