# Ejemplo: Detectar Cambios con Caché

**Objetivo**: Demostrar cómo usar `CacheManager` para detectar documentos nuevos, modificados e inalterados.

## Contexto

El caché registra SHA-256 de cada documento. Comparando caché actual con documentos recién escaneados, se detectan cambios sin tener que reconvertir todo.

## Requisitos

- Python 3.11+
- `doc_organize` instalado
- Base de datos SQLite para caché

## Código

```python
from pathlib import Path
from doc_organize.cache import CacheManager
from doc_organize.core.models import DocumentMetadata, DocumentStatus, ConversionStatus
from datetime import datetime

async def main():
    cache_db = Path("/tmp/doc_organize/cache.db")
    
    # Documentos escaneados (simulados)
    current_docs = [
        DocumentMetadata(
            full_path=Path("/repo/doc1.pdf"),
            display_name="doc1.pdf",
            extension="pdf",
            size_bytes=1000,
            modified_time=datetime(2024, 1, 1),
            sha256_hash="a1b2c3d4e5f6"
        ),
        DocumentMetadata(
            full_path=Path("/repo/doc2.pdf"),
            display_name="doc2.pdf",
            extension="pdf",
            size_bytes=2000,
            modified_time=datetime(2024, 1, 2),
            sha256_hash="xyz789abc123"  # Nuevo
        ),
        DocumentMetadata(
            full_path=Path("/repo/doc3.pdf"),
            display_name="doc3.pdf",
            extension="pdf",
            size_bytes=3000,
            modified_time=datetime(2024, 1, 3),
            sha256_hash="modified_hash"  # Modificado (distinto hash)
        ),
    ]
    
    async with CacheManager(db_path=cache_db) as cache_mgr:
        # Cargar caché existente
        cache = await cache_mgr.load_cache()
        print(f"Entradas en caché: {len(cache)}")
        
        # Detectar cambios
        new, modified, unchanged = cache_mgr.get_changes(cache, current_docs)
        
        print(f"\n📊 Clasificación:")
        print(f"  Nuevos: {len(new)}")
        for doc in new:
            print(f"    ✨ {doc.display_name}")
        
        print(f"  Modificados: {len(modified)}")
        for doc in modified:
            print(f"    🔄 {doc.display_name}")
        
        print(f"  Sin cambios: {len(unchanged)}")
        for doc in unchanged:
            print(f"    ✓ {doc.display_name}")
        
        # Guardar caché actualizado
        from doc_organize.core.models import CacheEntry
        entries = [
            CacheEntry(
                file_path=str(doc.full_path),
                sha256_hash=doc.sha256_hash,
                timestamp=doc.modified_time.timestamp(),
                status=DocumentStatus.new if doc in new else DocumentStatus.unchanged,
                conversion_status=ConversionStatus.pending
            )
            for doc in current_docs
        ]
        await cache_mgr.save_entries(entries)
        print("\n✅ Caché actualizado")

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
```

## Ejecución

```bash
$ python examples/cache_example.py
Entradas en caché: 2

📊 Clasificación:
  Nuevos: 1
    ✨ doc2.pdf
  Modificados: 1
    🔄 doc3.pdf
  Sin cambios: 1
    ✓ doc1.pdf

✅ Caché actualizado
```

## Explicación

1. **Carga**: Se leen todas las entradas del caché en memoria
2. **Comparación**: Se compara SHA-256 actual vs. caché (O(1) por documento)
3. **Clasificación**: Se categorizan en new, modified, unchanged
4. **Decisión**: Se procesan solo nuevos y modificados (eficiencia)
5. **Persistencia**: Se guarda caché actualizado en SQLite

## Referencias

- [Documentación funcional: Cache](../functional/cache.md)
- [Referencia técnica: Cache](../api/cache.md)
- [Scanner — Escaneo de documentos](../api/scanner.md)
