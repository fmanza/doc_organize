# Projects — Referencia Técnica

API Reference para registro y gestión de proyectos.

## Arquitectura

```mermaid
classDiagram
    class ProjectRegistry {
        -logger: Logger
        -projects_json_path: Path
        +create_project(name: str, base_location: str|Path, tenant_id: str) Project
        +list_projects(tenant_id: str) list[Project]
        +get_project(name: str, tenant_id: str) Project
    }
    
    class Project {
        +name: str
        +root_path: Path
        +created_at: datetime
        +tenant_id: str
    }
    
    ProjectRegistry --> Project
```

## API Pública

### ProjectRegistry

```python
class ProjectRegistry:
    async def __aenter__(self) -> 'ProjectRegistry'
    async def __aexit__(self, *args) -> None
    
    async def create_project(
        self,
        name: str,
        base_location: str | Path,
        tenant_id: str = "default"
    ) -> Project
    
    async def list_projects(
        self,
        tenant_id: str = "default"
    ) -> list[Project]
    
    async def get_project(
        self,
        name: str,
        tenant_id: str = "default"
    ) -> Project
```

Context manager para gestión de proyectos (registro + disk).

#### create_project

Crea nuevo proyecto (carpeta + registro).

| Parámetro | Tipo | Descripción |
|---|---|---|
| `name` | `str` | Nombre del proyecto (validado) |
| `base_location` | `str \| Path` | Directorio padre donde crear carpeta |
| `tenant_id` | `str` | ID de tenant (por defecto: "default") |

| Retorno | Tipo | Descripción |
|---|---|---|
| | `Project` | Proyecto creado con `name`, `root_path`, `tenant_id`, `created_at` |

**Proceso**:
1. Valida nombre vía `ProjectValidator.validate_name()`
2. Verifica no existe en registro
3. Crea carpeta `base_location/<name>/`
4. Escribe `project.json` dentro
5. Registra en `~/.doc_organize/projects.json`
6. Rollback si falla en cualquier punto

**Excepciones**:
- `ProjectNameError` — Nombre inválido
- `ProjectAlreadyExistsError` — Nombre duplicado en tenant
- `ProjectError` — Errores de I/O

---

#### list_projects

Lista proyectos de un tenant.

| Parámetro | Tipo | Descripción |
|---|---|---|
| `tenant_id` | `str` | ID de tenant |

| Retorno | Tipo | Descripción |
|---|---|---|
| | `list[Project]` | Proyectos registrados (sin verificar existencia física) |

**Nota**: No verifica que las carpetas existan en disco.

---

#### get_project

Recupera proyecto por nombre.

| Parámetro | Tipo | Descripción |
|---|---|---|
| `name` | `str` | Nombre del proyecto (case-insensitive) |
| `tenant_id` | `str` | ID de tenant |

| Retorno | Tipo | Descripción |
|---|---|---|
| | `Project` | Proyecto si existe |

**Excepciones**:
- `ProjectNotFoundError` — Proyecto no registrado

---

## Contratos

### Entrada

| Parámetro | Validación | Impacto si falla |
|---|---|---|
| Nombre válido | `ProjectValidator.validate_name()` | `ProjectNameError` |
| Nombre único | Búsqueda en registro | `ProjectAlreadyExistsError` |
| Base location existe | Validación al crear | `ProjectError` |

### Salida

```python
@dataclass
class Project:
    name: str
    root_path: Path
    created_at: datetime
    tenant_id: str
```

## Registro de Proyectos

**Ubicación**: `~/.doc_organize/projects.json`

**Formato**:
```json
{
  "projects": [
    {
      "name": "mi_proyecto",
      "root_path": "/home/user/docs/mi_proyecto",
      "created_at": "2024-01-15T10:30:00",
      "tenant_id": "default"
    }
  ]
}
```

**Propiedades**:
- Centralizado (fuera de cualquier proyecto)
- Permite ubicaciones distintas por proyecto
- Escritura atómica vía temp file + `os.replace()`
- Locking async (`asyncio.Lock`) para concurrencia (rara)

## Dependencias

| Dependencia | Propósito |
|---|---|
| `core.constants.PROJECT_NAME_*` | Validación de nombres |
| `core.models.Project` | Modelo |
| `core.exceptions` | Excepciones (ProjectError, etc.) |
| `utils.logging` | Logging |
| `utils.path_utils.safe_path_join()` | Manipulación segura de rutas |
| `validators.project_validator.ProjectValidator` | Validación |

## Notas Internas

- **Único tenant = "default"**: Soporte futuro para multi-tenant vía campo `tenant_id`
- **Ruta absoluta**: Cada proyecto almacena `root_path` absoluta (permite `base_location` distinta por tenant)
- **Rollback automático**: Si creación falla después de crear carpeta, se borra (atomicidad)
- **Case-insensitive**: Búsqueda por nombre ignora mayúsculas

#### delete_project

Elimina un proyecto por completo: borra `root_path` en disco y quita la entrada del registro.

| Parámetro | Tipo | Descripción |
|---|---|---|
| `name` | `str` | Nombre del proyecto a eliminar |
| `tenant_id` | `str` | ID de tenant |

**Proceso**: borra primero la carpeta en disco (`shutil.rmtree`) y solo si tiene éxito
quita la entrada del registro — si el borrado físico falla, el proyecto sigue
registrado para poder reintentarlo.

**Excepciones**:
- `ProjectNotFoundError` — No existe ese proyecto
- `ProjectError` — La carpeta no se pudo borrar por completo

---

#### move_project_root

Mueve `root_path` de un proyecto a `<destination_parent>/<name>/`.

| Parámetro | Tipo | Descripción |
|---|---|---|
| `name` | `str` | Nombre del proyecto a mover |
| `destination_parent` | `str \| Path` | Carpeta padre de destino, ya existente |
| `tenant_id` | `str` | ID de tenant |

| Retorno | Tipo | Descripción |
|---|---|---|
| | `Project` | Proyecto actualizado, con el nuevo `root_path` |

**Proceso**: usa `shutil.move` (rename atómico si es el mismo volumen, copiar+borrar si
no) y, si el movimiento físico tiene éxito pero no se puede persistir el registro
actualizado, revierte el movimiento antes de propagar el error.

**Excepciones**:
- `ProjectNotFoundError` — No existe ese proyecto
- `ProjectError` — Destino inexistente, destino ya ocupado, carpeta actual inexistente, o destino igual al actual

---

## ProjectHistoryCleaner

```python
class ProjectHistoryCleaner:
    async def clear(self, project: Project) -> None
```

Vacía por completo `<project.root_path>` (caché, historial de escaneo/errores/
deduplicación, carpetas guardadas, salida de conversión) y regenera únicamente
`project.json`, dejando el proyecto como recién creado. No toca el registro
(`projects.json`) — a diferencia de `ProjectRegistry.delete_project`, el
proyecto sigue existiendo con el mismo nombre y ubicación.

**Excepciones**: `ProjectError` si `root_path` no existe o algún elemento no se pudo borrar.

## Rutas HTTP de gestión destructiva (admin)

Todas bajo `/api/projects/{name}`, solo accesibles a un rol `admin`, y todas
exigen `{"confirm": true}` en el payload y ausencia de una operación en curso
(`409` si hay un escaneo/deduplicación activo sobre el mismo proyecto):

| Ruta | Método | Descripción |
|---|---|---|
| `/impact` | `GET` | `{file_count, total_size_bytes, has_active_operation}` — resumen para la ventana modal de confirmación |
| `/clear-history` | `POST` | Llama a `ProjectHistoryCleaner.clear()` |
| `` (raíz) | `DELETE` | Llama a `ProjectRegistry.delete_project()` |
| `/move` | `POST` | `{destination_path: str, confirm: bool}` → llama a `ProjectRegistry.move_project_root()` |

## Ejemplos Relacionados

- [Crear y listar proyectos](../examples/projects-registry.md)

## ScannedFoldersStore

```python
class ScannedFoldersStore:
    async def list_folders(self, project: Project) -> list[ScannedFolder]
    async def add_folder(self, project: Project, path: str) -> ScannedFolder
    async def remove_folder(self, project: Project, path: str) -> None
    async def mark_used(self, project: Project, paths: list[str]) -> None
```

Lista persistente por proyecto (`<project.root_path>/scanned_folders.json`) de
las carpetas guardadas desde el menú Escaneo de la web. Mismo patrón de
concurrencia que `ProjectRegistry` (lock en proceso + escritura atómica).

| Método | Descripción | Excepciones |
|---|---|---|
| `add_folder` | Añade `path` (o devuelve la entrada existente si ya estaba) | `InvalidPathError` si no existe o no es carpeta |
| `remove_folder` | Elimina `path` de la lista | `ScannedFolderNotFoundError`, `ScannedFolderInUseError` si `used=True` |
| `mark_used` | Marca `paths` como usadas (crea la entrada si no existía); llamado por `scan_websocket` tras un escaneo correcto | — |

```python
@dataclass
class ScannedFolder:
    path: str
    added_at: str  # ISO 8601
    used: bool  # permanente una vez True
```
