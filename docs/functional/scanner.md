# Scanner — Escaneo Recursivo de Documentos

## 1. Descripción General

Descubre documentos en carpetas, calcula SHA-256, genera árbol de directorios.

### Objetivo

Inventariar todos los documentos en una carpeta (respetando extensiones soportadas e ignorando nombres especiales), calcular su identidad criptográfica (SHA-256) y reportar estructura de directorios.

### Precondiciones

- Carpetas válidas (verificadas por `FolderValidator`)
- Permisos de lectura en directorios y archivos
- Extensiones soportadas: las de `SUPPORTED_EXTENSIONS` (PDF, Office, imágenes, HTML, CSV,
  OpenDocument, AsciiDoc, EPUB, correo y texto; ver [Converter](converter.md)); audio y vídeo solo con
  `include_audio_video`

## 2. Reglas de Negocio

| Regla | Descripción |
|---|---|
| **Extensiones soportadas** | Matriz definida en `constants.SUPPORTED_EXTENSIONS` |
| **Ignorar nombres** | `.git/`, `__pycache__/`, `.DS_Store`, más las rutas excluidas y los patrones de nombre que indique el usuario (`exclude_paths`, `ignore_patterns`, 1.3.0) |
| **Hash determinista** | Mismo archivo = mismo SHA-256 siempre |
| **Concurrencia segura** | Hashing paralelo sin bloqueos en archivos |

### Límites y Restricciones

❌ No modifica archivos  
❌ No sigue symlinks ni *junctions* de Windows (se muestran como nodo opaco, sin recorrerlos ni calcular su hash)  
❌ No valida contenido de documentos (escanea solo metadatos)  

## 3. Casos de Uso

### Flujo principal

```mermaid
sequenceDiagram
    participant Usuario
    participant Scanner
    participant Sistema
    
    Usuario->>Scanner: scan(["/repo"])
    Scanner->>Sistema: walk("/repo")
    loop para cada archivo
        Scanner->>Sistema: hash(file) = SHA-256
        Scanner->>Scanner: Clasificar: soportado, ignorado, error
    end
    Scanner->>Usuario: return ScanResult<br/>(documents=[...],<br/>tree=DirectoryTree,<br/>summary={...})
```

**Paso a paso:**

1. **Descubrimiento**: Recorre directorios recursivamente
2. **Filtrado**: Solo archivos con extensión soportada
3. **Hashing**: Calcula SHA-256 concurrente (async)
4. **Árbol**: Construye estructura jerárquica de directorios
5. **Retorno**: Lista de `DocumentMetadata` + árbol visual

### Flujos alternativos y de error

- **Archivo en uso**: Se captura pero estado puede ser inconsistente
- **Permisos insuficientes**: Archivo se reporta con error
- **Archivos muy grandes**: Hashing puede ser lento; informar en logs

## 4. Criterios de Aceptación

*Pendiente de QA: esta sección se completará cuando el equipo QA valide los criterios.*

## 5. Glosario y Términos

*No aplica para este módulo.*
