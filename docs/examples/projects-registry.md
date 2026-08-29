# Ejemplo: Crear y Listar Proyectos

**Objetivo**: Demostrar cómo crear y gestionar proyectos locales.

## Contexto

El `ProjectRegistry` mantiene un registro central (`~/.doc_organize/projects.json`) de proyectos, cada uno con su propia carpeta y configuración.

## Requisitos

- Python 3.11+
- `doc_organize` instalado
- Permisos de escritura en `~/.doc_organize/`

## Código

```python
from pathlib import Path
from doc_organize.projects import ProjectRegistry

async def main():
    # Ubicación base para proyectos
    base_location = Path.home() / "Documentos" / "doc_organize_projects"
    base_location.mkdir(parents=True, exist_ok=True)
    
    async with ProjectRegistry() as registry:
        # Crear proyectos
        print("📁 Creando proyectos...")
        
        p1 = await registry.create_project(
            name="proyecto_importante",
            base_location=base_location,
            tenant_id="default"
        )
        print(f"  ✅ {p1.name} → {p1.root_path}")
        
        p2 = await registry.create_project(
            name="research_2024",
            base_location=base_location,
            tenant_id="default"
        )
        print(f"  ✅ {p2.name} → {p2.root_path}")
        
        # Listar proyectos
        print("\n📋 Proyectos registrados:")
        projects = await registry.list_projects(tenant_id="default")
        for proj in projects:
            print(f"  • {proj.name}")
            print(f"    Ubicación: {proj.root_path}")
            print(f"    Creado: {proj.created_at}")
        
        # Recuperar proyecto específico
        print("\n🔍 Recuperando proyecto...")
        proj = await registry.get_project("proyecto_importante", tenant_id="default")
        print(f"  Nombre: {proj.name}")
        print(f"  Ruta: {proj.root_path}")
        print(f"  Tenant: {proj.tenant_id}")

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
```

## Ejecución

```bash
$ python examples/projects_example.py
📁 Creando proyectos...
  ✅ proyecto_importante → /home/user/Documentos/doc_organize_projects/proyecto_importante
  ✅ research_2024 → /home/user/Documentos/doc_organize_projects/research_2024

📋 Proyectos registrados:
  • proyecto_importante
    Ubicación: /home/user/Documentos/doc_organize_projects/proyecto_importante
    Creado: 2024-08-29 10:30:00
  • research_2024
    Ubicación: /home/user/Documentos/doc_organize_projects/research_2024
    Creado: 2024-08-29 10:35:00

🔍 Recuperando proyecto...
  Nombre: proyecto_importante
  Ruta: /home/user/Documentos/doc_organize_projects/proyecto_importante
  Tenant: default
```

## Explicación

1. **Creación**: Se valida nombre, se crea carpeta + `project.json`
2. **Registro**: Se añade entrada a `~/.doc_organize/projects.json`
3. **Rollback**: Si falla, se limpia carpeta creada automáticamente
4. **Listado**: Se leen proyectos del registro (sin verificar existencia física)
5. **Recuperación**: Se busca proyecto por nombre (case-insensitive)

## Estructura de Carpetas

```
~/.doc_organize/
  ├── projects.json                (registro central)
  └── (gestionado por user)

~/Documentos/doc_organize_projects/
  ├── proyecto_importante/
  │   ├── project.json            (config del proyecto)
  │   ├── cache.db                (caché local, opcional)
  │   ├── duplicates/             (carpeta de duplicados)
  │   └── output/                 (documentos convertidos)
  │
  └── research_2024/
      ├── project.json
      └── (estructura similar)
```

## Referencias

- [Documentación funcional: Projects](../functional/projects.md)
- [Referencia técnica: Projects](../api/projects.md)
- [Validadores — Validación de nombres](../api/validators.md)
