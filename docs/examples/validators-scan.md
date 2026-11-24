# Ejemplo: Validar Carpetas antes de Escanear

**Objetivo**: Demostrar cómo usar `FolderValidator` para limpiar una lista de carpetas con redundancia.

## 1. Contexto del Ejemplo

Cuando el usuario selecciona `/repo` y `/repo/docs` (redundancia) para procesar, el validador detecta y elimina la redundancia automáticamente.

### Requisitos

- Python 3.11+
- `doc_organize` instalado

El ejemplo crea sus carpetas en un directorio temporal: se ejecuta tal cual, sin rutas del usuario.

## 2. Implementación de Referencia

```python
import tempfile
from pathlib import Path

from doc_organize.core.exceptions import InvalidPathError
from doc_organize.validators import FolderValidator


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        documents = base / "Documents"
        archive = documents / "archive"  # Redundante: cuelga de Documents
        projects = base / "Projects"
        archive.mkdir(parents=True)
        projects.mkdir()

        validator = FolderValidator()  # Síncrono: solo `stat` y comparación de rutas
        result = validator.validate_folder_set([str(documents), str(archive), str(projects)])

        print(f"Válido: {result.is_valid}")
        print(f"Carpetas limpias: {[Path(p).name for p in result.clean_paths]}")
        print(f"Avisos: {len(result.warnings)}")

        try:
            validator.validate_folder_set([str(base / "no_existe")])
        except InvalidPathError as exc:
            print(f"Error esperado: {type(exc).__name__}")


if __name__ == "__main__":
    main()
```

## 3. Explicación del Código

1. **Input**: Lista con 3 rutas; `archive` cuelga de `Documents` (redundancia)
2. **Validación**: Se comprueba que cada ruta existe y es una carpeta; si no, `InvalidPathError`
3. **Deduplicación**: Se detecta que `archive` ⊂ `Documents` y se omite, con un aviso en `warnings`
4. **Output**: `clean_paths` con las 2 carpetas de nivel superior, ya resueltas (rutas absolutas)
5. **Síncrono**: `validate_folder_set()` no es `async`: solo hace `stat` y compara rutas en memoria
6. **Siguiente paso**: Pasar `clean_paths` a `DocumentScanner.scan_folders()`

## 4. Ejecución y Pruebas

```bash
$ python validators_example.py
Válido: True
Carpetas limpias: ['Documents', 'Projects']
Avisos: 1
Error esperado: InvalidPathError
```

Validación sintáctica: `python -m py_compile validators_example.py`.

## 5. Referencias Relacionadas

- [Documentación funcional: Validadores](../functional/validators.md)
- [Referencia técnica: Validadores](../api/validators.md)
- [Ejemplo: Escanear documentos](scanner-scan.md)
