# Ejemplo: Crear y Listar Proyectos

**Objetivo**: Demostrar cómo crear y gestionar proyectos locales.

## 1. Contexto del Ejemplo

El `ProjectRegistry` mantiene un registro central (por defecto, `~/.doc_organize/projects.json`) de proyectos, cada uno con su propia carpeta y configuración.

### Requisitos

- Python 3.11+
- `doc_organize` instalado

El ejemplo usa un registro y una ubicación base temporales (`ProjectRegistry(registry_path)`): no toca el registro real del usuario.

## 2. Implementación de Referencia

```python
import asyncio
import tempfile
from pathlib import Path

from doc_organize.core.exceptions import ProjectAlreadyExistsError
from doc_organize.projects import ProjectLayout, ProjectRegistry


async def main() -> None:
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp = Path(tmp_dir).resolve()
        base_location = tmp / "doc_organize_projects"  # Carpeta padre: debe existir
        base_location.mkdir()
        # Registro propio para no tocar ~/.doc_organize/projects.json (el registro por defecto)
        registry_path = tmp / "registro" / "projects.json"

        async with ProjectRegistry(registry_path) as registry:
            for name in ("proyecto_importante", "research_2024"):
                project = await registry.create_project(name=name, base_location=base_location)
                print(f"Creado: {project.name} -> {Path(project.root_path).relative_to(tmp).as_posix()}")

            try:
                await registry.create_project(name="PROYECTO_IMPORTANTE", base_location=base_location)
            except ProjectAlreadyExistsError:
                print("Nombre repetido (sin distinguir mayúsculas): rechazado")

            print(f"Registrados: {[p.name for p in await registry.list_projects()]}")

            project = await registry.get_project("Proyecto_Importante")  # Búsqueda sin distinguir mayúsculas
            layout = ProjectLayout.for_project(project)
            print(f"Recuperado: {project.name}")
            print(f"Contenido: {sorted(p.name for p in Path(project.root_path).iterdir())}")
            print(f"Rutas: {layout.conversion_dir.name}, {layout.duplicates_dir.name}, {layout.cache_db.name}")


if __name__ == "__main__":
    asyncio.run(main())
```

## 3. Explicación del Código

1. **Creación**: Se valida el nombre (`ProjectValidator`) y que no esté repetido sin distinguir mayúsculas (`ProjectAlreadyExistsError`); se crea la carpeta + `project.json`. `base_location` debe existir
2. **Registro**: Se añade la entrada al `projects.json` del registro
3. **Rollback**: Si falla tras crear la carpeta, se borra antes de propagar el error
4. **Listado**: `list_projects()` lee el registro (sin verificar existencia física)
5. **Recuperación**: `get_project()` busca por nombre sin distinguir mayúsculas (`ProjectNotFoundError` si no existe)
6. **Rutas**: `ProjectLayout.for_project()` da las rutas del proyecto; esas carpetas y ficheros se crean al usarse, no al crear el proyecto

## 4. Ejecución y Pruebas

```bash
$ python projects_example.py
Creado: proyecto_importante -> doc_organize_projects/proyecto_importante
Creado: research_2024 -> doc_organize_projects/research_2024
Nombre repetido (sin distinguir mayúsculas): rechazado
Registrados: ['proyecto_importante', 'research_2024']
Recuperado: proyecto_importante
Contenido: ['project.json']
Rutas: Conversión, duplicados, cache.db
```

Validación sintáctica: `python -m py_compile projects_example.py`.

### Estructura de Carpetas

```
~/.doc_organize/
  └── projects.json               (registro central por defecto)

<base_location>/
  ├── proyecto_importante/
  │   ├── project.json            (se crea con el proyecto)
  │   ├── cache.db                (caché, al escanear)
  │   ├── duplicados/             (duplicados e informes de deduplicación)
  │   └── Conversión/             (Markdown y JSON convertidos)
  │
  └── research_2024/
      ├── project.json
      └── (estructura similar)
```

## 5. Referencias Relacionadas

- [Documentación funcional: Projects](../functional/projects.md)
- [Referencia técnica: Projects](../api/projects.md)
- [Referencia técnica: Validadores — validación de nombres](../api/validators.md)
