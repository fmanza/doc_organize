# Ejemplo: Validar Carpetas antes de Escanear

**Objetivo**: Demostrar cómo usar `FolderValidator` para limpiar una lista de carpetas con redundancia.

## Contexto

Cuando el usuario selecciona `/repo` y `/repo/docs` (redundancia) para procesar, el validador detecta y elimina la redundancia automáticamente.

## Requisitos

- Python 3.11+
- `doc_organize` instalado

## Código

```python
from pathlib import Path
from doc_organize.validators import FolderValidator

async def main():
    validator = FolderValidator()
    
    # Lista con redundancia: /repo/docs está dentro de /repo
    paths = [
        "/home/user/Documents",
        "/home/user/Documents/archive",  # Redundante
        "/home/user/Projects",
    ]
    
    # Validar y limpiar
    result = validator.validate_folder_set(paths)
    
    print(f"Válido: {result.is_valid}")
    print(f"Carpetas limpias: {result.clean_paths}")
    for warning in result.warnings:
        print(f"  ⚠️  {warning}")

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
```

## Ejecución

```bash
$ python examples/validators_example.py
Válido: True
Carpetas limpias: ['/home/user/Documents', '/home/user/Projects']
  ⚠️  "/home/user/Documents/archive" es subcarpeta de "/home/user/Documents" y se omite.
```

## Explicación

1. **Input**: Lista con 3 rutas, 2 de ellas con redundancia
2. **Validación**: Se verifica que existan y son directorios
3. **Deduplicación**: Se detecta que `archive` ⊂ `Documents`
4. **Output**: Solo 2 carpetas (nivel superior) + lista de avisos
5. **Siguiente paso**: Pasar `clean_paths` al `DocumentScanner`

## Referencias

- [Documentación funcional: Validadores](../functional/validators.md)
- [Referencia técnica: Validadores](../api/validators.md)
- [Scanner — Escaneo de documentos](../api/scanner.md)
