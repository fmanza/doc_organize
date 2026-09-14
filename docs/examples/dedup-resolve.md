# Ejemplo: Deduplicar Documentos

**Objetivo**: Demostrar cómo detectar y resolver duplicados.

## Contexto

El `DeduplicationManager` agrupa documentos por hash exacto (duplicados reales) y por nombre base (conflictos de versión), luego mueve los descartados a una carpeta separada.

## Requisitos

- Python 3.11+
- `doc_organize` instalado
- Documentos escaneados (con SHA-256 calculado)

## Código

```python
from pathlib import Path
from doc_organize.dedup import DeduplicationManager
from doc_organize.core.models import DocumentMetadata
from datetime import datetime

async def main():
    duplicates_dir = Path("/tmp/doc_organize/duplicates")
    duplicates_dir.mkdir(parents=True, exist_ok=True)
    
    # Simular documentos escaneados
    docs = [
        DocumentMetadata(
            full_path=Path("/repo/doc1.pdf"),
            display_name="doc1.pdf",
            extension="pdf",
            size_bytes=1000,
            modified_time=datetime(2024, 1, 1),
            sha256_hash="a1b2c3d4e5f6"  # Mismo hash
        ),
        DocumentMetadata(
            full_path=Path("/repo/backup/doc1.pdf"),
            display_name="doc1.pdf",
            extension="pdf",
            size_bytes=1000,
            modified_time=datetime(2024, 1, 2),  # Más nuevo
            sha256_hash="a1b2c3d4e5f6"  # Mismo hash = duplicado exacto
        ),
        DocumentMetadata(
            full_path=Path("/repo/doc1_v2.pdf"),
            display_name="doc1_v2.pdf",
            extension="pdf",
            size_bytes=1050,
            modified_time=datetime(2024, 1, 15),
            sha256_hash="xyz789abc123"  # Hash distinto = conflicto de versión
        ),
    ]
    
    manager = DeduplicationManager()
    
    # Fase 1: Detectar duplicados (síncrono)
    groups = manager.find_duplicates(docs)
    
    print(f"Grupos detectados: {len(groups)}")
    for group in groups:
        print(f"\n  Grupo {group.reason}:")
        print(f"    Canónico: {group.canonical_doc.display_name}")
        print(f"    Duplicados: {len(group.duplicates)}")
        for dup in group.duplicates:
            print(f"      - {dup.display_name}")
    
    # Fase 2: Resolver duplicados (async)
    report = await manager.resolve_duplicates(groups, duplicates_dir)
    
    print(f"\n📊 Reporte de deduplicación:")
    print(f"  Duplicados exactos movidos: {report.total_exact_duplicates}")
    print(f"  Conflictos de versión movidos: {report.total_version_conflicts}")
    print(f"  Carpeta destino: {report.duplicates_folder_path}")
    print(f"  Auditoría: {report.audit_json_path}")

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
```

## Ejecución

```bash
$ python examples/dedup_example.py
Grupos detectados: 2

  Grupo exact_duplicate:
    Canónico: doc1.pdf (2024-01-01)
    Duplicados: 1
      - doc1.pdf (2024-01-02)

  Grupo version_conflict:
    Canónico: doc1.pdf
    Duplicados: 1
      - doc1_v2.pdf

📊 Reporte de deduplicación:
  Duplicados exactos movidos: 1
  Conflictos de versión movidos: 1
  Carpeta destino: /tmp/doc_organize/duplicates
  Auditoría: /tmp/doc_organize/duplicates/DEDUP_REPORT.json
```

## Explicación

1. **Detección** (síncrono): Se agrupan documentos por hash y por nombre base
2. **Selección**: Se elige canónico = documento más antiguo
3. **Resolución** (async): Se mueven no-canónicos a `duplicates_dir`
4. **Auditoría**: Se escribe `DEDUP_REPORT.json` con decisiones
5. **Estructura**: Se preserva la ruta original bajo `duplicates_dir`

## Similitud aproximada de nombre (opcional)

Pasando `fuzzy_threshold` (0-100), `find_duplicates()` añade una tercera pasada sobre los
documentos que no quedaron agrupados por hash ni por versión, comparando `display_name` con
RapidFuzz:

```python
from doc_organize.core.models import DuplicateReason

groups = manager.find_duplicates(docs, fuzzy_threshold=90)

for group in groups:
    if group.reason == DuplicateReason.FUZZY_NAME_MATCH:
        print(f"Posibles duplicados por nombre: {[d.display_name for d in group.duplicates]}")
        # canonical_doc es solo una propuesta -- nunca se resuelve sin
        # confirmación explícita del usuario (ver web/routes/duplicates.py,
        # POST /api/projects/{name}/duplicates/resolve).
```

**Importante**: los grupos `FUZZY_NAME_MATCH` nunca se mueven vía `resolve_duplicates()` llamado
desde la acción masiva "Buscar duplicados" (`ScanCommand.deduplicate_streaming()`, que no pasa
`fuzzy_threshold`) — solo desde una resolución donde el usuario elige explícitamente `user_choice`
por grupo.

## Referencias

- [Documentación funcional: Deduplicación](../functional/dedup.md)
- [Referencia técnica: Deduplicación](../api/dedup.md)
- [Scanner — Escaneo de documentos](../api/scanner.md)
