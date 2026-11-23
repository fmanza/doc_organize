# Validadores de Entrada

Validación previa de carpetas y nombres de proyecto antes de procesarlos.

## Objetivo

Detectar y prevenir datos inválidos **antes** de iniciar el escaneo o crear proyectos, evitando redundancia (carpeta padre + subcarpeta) y errores de nombre.

## Precondiciones

- Las carpetas de entrada deben existir en el sistema de archivos.
- El usuario debe tener permisos de lectura en las carpetas.
- Los nombres de proyecto deben ser strings no vacíos.

## Flujo Principal

```mermaid
sequenceDiagram
    participant Usuario
    participant FolderValidator
    participant Sistema
    
    Usuario->>FolderValidator: validate_folder_set(["/repo", "/repo/docs", "/home"])
    FolderValidator->>Sistema: Verificar que existen
    FolderValidator->>FolderValidator: Detectar "/repo/docs" ⊂ "/repo"
    FolderValidator->>Usuario: return ValidationResult<br/>(clean=["/repo", "/home"],<br/>warnings=[...])
```

**Paso a paso:**

1. **Recepción**: Se recibe lista de rutas (absolutas o relativas)
2. **Resolución**: Expande symlinks, normaliza rutas
3. **Validación**: Comprueba que existen y son directorios
4. **Deduplicación**: Detecta si alguna es subcarpeta de otra
5. **Retorno**: Lista limpias sin redundancia + avisos

## Reglas de Negocio

| Regla | Descripción |
|---|---|
| **Sin redundancia** | Si `/repo` y `/repo/docs` se seleccionan, solo `/repo` |
| **Carpetas existentes** | Todas las rutas deben existir como directorios |
| **Nombres normalizados** | Normalizados a NFC; sin caracteres `<>:"\\/\|?*` ni de control, máximo 100 caracteres, sin espacio al principio o al final y sin terminar en punto |
| **Nombres únicos** | No duplicar nombres en el registro de proyectos |

## Límites y Restricciones

❌ No crea ni modifica carpetas  
❌ No sigue symlinks en profundidad  
❌ No valida contenido (eso es responsabilidad del Scanner)  

## Casos Especiales

- **Carpeta no existe**: Lanza `InvalidPathError`
- **Ruta es un archivo**: Lanza `InvalidPathError`
- **Nombres reservados Windows** (CON, PRN, AUX, NUL, COM1-9, LPT1-9): `is_valid=False` con el motivo en `warnings` (no lanza excepción; tampoco el resto de nombres inválidos)
- **Lista vacía**: Retorna `is_valid=False`

## Criterios de Aceptación

*Pendiente de validación QA*
