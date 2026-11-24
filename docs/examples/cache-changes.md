# Ejemplo: Detectar Cambios con Caché

**Objetivo**: Demostrar cómo usar `CacheManager` para detectar documentos nuevos, modificados e inalterados.

## 1. Contexto del Ejemplo

El caché registra SHA-256 de cada documento. Comparando caché actual con documentos recién escaneados, se detectan cambios sin tener que reconvertir todo.

### Requisitos

- Python 3.11+
- `doc_organize` instalado

La base de datos SQLite de la caché se crea en un directorio temporal; los documentos escaneados se simulan con `DocumentMetadata`.

## 2. Implementación de Referencia

```python
import asyncio
import tempfile
from pathlib import Path

from doc_organize.cache import CacheManager
from doc_organize.core.models import CacheEntry, ConversionStatus, DocumentMetadata, DocumentStatus


def doc(name: str, sha: str, modified: float) -> DocumentMetadata:
    return DocumentMetadata(
        full_path=f"/repo/{name}",  # Clave de la caché: ruta absoluta del original
        display_name=name,
        extension="pdf",
        size_bytes=1000,
        modified_time=modified,  # Timestamp Unix
        sha256_hash=sha,
    )


async def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        cache_db = Path(tmp) / "cache.db"

        async with CacheManager(cache_db) as cache_mgr:
            # Escaneo anterior: doc1 y doc3 ya estaban en caché
            await cache_mgr.save_entries([
                CacheEntry(file_path="/repo/doc1.pdf", sha256_hash="a" * 64, timestamp=1.0, status=DocumentStatus.NEW),
                CacheEntry(file_path="/repo/doc3.pdf", sha256_hash="c" * 64, timestamp=3.0, status=DocumentStatus.NEW),
            ])

            # Escaneo actual (simulado): doc2 es nuevo y doc3 cambió de contenido
            current_docs = [doc("doc1.pdf", "a" * 64, 1.0), doc("doc2.pdf", "b" * 64, 2.0), doc("doc3.pdf", "d" * 64, 4.0)]

            cache = await cache_mgr.load_cache()
            print(f"Entradas en caché: {len(cache)}")

            # Síncrono: compara en memoria y devuelve rutas
            new, modified, unchanged = cache_mgr.get_changes(cache, current_docs)
            print(f"Nuevos: {new}")
            print(f"Modificados: {modified}")
            print(f"Sin cambios: {unchanged}")

            # Guardar el estado actual (upsert por ruta)
            status = {**dict.fromkeys(new, DocumentStatus.NEW), **dict.fromkeys(modified, DocumentStatus.MODIFIED)}
            await cache_mgr.save_entries([
                CacheEntry(
                    file_path=d.full_path,
                    sha256_hash=d.sha256_hash,
                    timestamp=d.modified_time,
                    status=status.get(d.full_path, DocumentStatus.UNCHANGED),
                    conversion_status=ConversionStatus.PENDING,
                    size_bytes=d.size_bytes,
                )
                for d in current_docs
            ])
            print(f"Entradas tras guardar: {len(await cache_mgr.load_cache())}")


if __name__ == "__main__":
    asyncio.run(main())
```

## 3. Explicación del Código

1. **Apertura**: `async with CacheManager(db_path)` abre `cache.db` (modo WAL) y crea la tabla si no existe
2. **Carga**: `load_cache()` devuelve un `dict` ruta → `CacheEntry`
3. **Comparación**: `get_changes()` es síncrono y compara el SHA-256 por ruta (O(1) por documento); devuelve tres listas de **rutas** (`new`, `modified`, `unchanged`)
4. **Decisión**: Se procesan solo nuevos y modificados
5. **Persistencia**: `save_entries()` hace un upsert transaccional por `file_path`; guardar `size_bytes` permite reutilizar el hash en el siguiente escaneo (`known_entries`) y buscar duplicados desde la caché (`DocumentMetadata.from_cache_entry`)

## 4. Ejecución y Pruebas

```bash
$ python cache_example.py
Entradas en caché: 2
Nuevos: ['/repo/doc2.pdf']
Modificados: ['/repo/doc3.pdf']
Sin cambios: ['/repo/doc1.pdf']
Entradas tras guardar: 3
```

Validación sintáctica: `python -m py_compile cache_example.py`.

## 5. Referencias Relacionadas

- [Documentación funcional: Cache](../functional/cache.md)
- [Referencia técnica: Cache](../api/cache.md)
- [Ejemplo: Escanear documentos](scanner-scan.md)
