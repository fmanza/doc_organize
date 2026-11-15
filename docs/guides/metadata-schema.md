# Esquema de Metadatos — FASE 1

**Versión:** 1.0 (FASE 1)  
**Fecha:** 2026-11-15  
**Compatibilidad:** ≥ v1.5.0-beta

---

## 📋 Resumen

La **FASE 1** introduce **5 campos nuevos de metadatos técnicos** a los documentos escaneados. Se capturan automáticamente durante el escaneo y se almacenan en:
- `cache.db` (base de datos de caché)
- `ScanResult` (resultado JSON del escaneo)
- `DocumentMetadata` (modelo Pydantic)

**Objetivo:** Enriquecer la información técnica de cada documento sin ralentizar el proceso de escaneo.

---

## 🆕 Campos Nuevos (FASE 1)

### 1. `created_time` — Marca de Tiempo de Creación

| Propiedad | Valor |
|-----------|-------|
| **Tipo** | `float` (timestamp Unix) o `null` |
| **Disponibilidad** | Siempre (en todos los SO) |
| **Precisión** | Segundos (compatible con timestamps Unix) |
| **Compatibilidad SO** | ✅ macOS (st_birthtime), ✅ Linux, ✅ Windows |

**Descripción:**  
Fecha de creación del fichero. En macOS usa `st_birthtime`. En Linux/Windows usa el mínimo entre `st_ctime` (hora de cambio) y `st_mtime` (hora de modificación) para aproximar la creación.

**Diferencia con `modified_time`:**
- `modified_time` (existente): Última modificación del contenido
- `created_time` (nuevo): Primera creación del fichero

**Ejemplo:**
```json
{
  "modified_time": 1693152000.0,
  "created_time": 1693151000.0
}
```

**Casos especiales:**
- Si el fichero se copió, `created_time` es la fecha de copia
- Si se sincronizó (Dropbox, OneDrive), `created_time` es la fecha de sincronización
- `None` si no se puede obtener (muy raro)

---

### 2. `mime_type` — Tipo MIME

| Propiedad | Valor |
|-----------|-------|
| **Tipo** | `str` (tipo MIME IANA) o `null` |
| **Disponibilidad** | Siempre |
| **Formato** | RFC 2045, p. ej. `"application/pdf"` |
| **Alternativa** | `"application/octet-stream"` (binario) |

**Descripción:**  
Tipo MIME del fichero detectado automáticamente. Intenta primero con `mimetypes` (basado en extensión), luego con `python-magic` si está disponible (más preciso pero lento).

**Tabla de Ejemplos:**

| Extensión | Tipo MIME |
|-----------|-----------|
| `.pdf` | `application/pdf` |
| `.txt` | `text/plain` |
| `.docx` | `application/vnd.openxmlformats-officedocument.wordprocessingml.document` |
| `.xlsx` | `application/vnd.openxmlformats-officedocument.spreadsheetml.sheet` |
| `.csv` | `text/csv` |
| `.jpg` | `image/jpeg` |
| `.png` | `image/png` |
| desconocida | `application/octet-stream` |

**Caso de uso:**  
Determinar cómo procesar un fichero sin confiar solo en la extensión.

---

### 3. `detected_language` — Idioma Detectado

| Propiedad | Valor |
|-----------|-------|
| **Tipo** | `str` (ISO 639-1) o `null` |
| **Disponibilidad** | `null` en FASE 1 (futuro en FASE 2) |
| **Formato** | ISO 639-1, p. ej. `"es"`, `"en"`, `"fr"` |

**Descripción:**  
Idioma principal del documento detectado. En FASE 1 siempre es `null`. Se rellenará en FASE 2 usando Docling (después de la conversión).

**Ejemplos (futuros):**
```json
{
  "detected_language": "es"
}
```

---

### 4. `file_permissions` — Permisos del Fichero

| Propiedad | Valor |
|-----------|-------|
| **Tipo** | `str` (notación octal) o `null` |
| **Disponibilidad** | Siempre (Linux, macOS); en Windows puede ser None |
| **Formato** | Octal de 3 dígitos, p. ej. `"644"` |

**Descripción:**  
Permisos del fichero en notación octal (Unix). Extraídos de `st_mode`.

**Significado de cada dígito:**
```
rw- r-- r--
644
│   │   │
│   │   └─ Otros: 4 (lectura)
│   └───── Grupo: 4 (lectura)
└───────── Propietario: 6 (lectura + escritura)
```

**Valores comunes:**

| Valor | Significado |
|-------|-------------|
| `644` | Propietario lee/escribe, otros solo leen |
| `755` | Propietario lee/escribe/ejecuta, otros leen/ejecutan |
| `600` | Solo el propietario lee/escribe |
| `777` | Todos leen/escriben/ejecutan |

**En Windows:**  
Puede ser `None` (permisos más complejos, no mapeables a octal simple).

---

### 5. `owner_name` — Propietario del Fichero

| Propiedad | Valor |
|-----------|-------|
| **Tipo** | `str` (nombre de usuario) o `null` |
| **Disponibilidad** | Linux/macOS: casi siempre; Windows: a veces |
| **Formato** | Nombre de usuario, p. ej. `"user"`, `"DOMINIO\\usuario"` |

**Descripción:**  
Propietario del fichero según el SO. En Linux/macOS usa `pwd.getpwuid()`. En Windows intenta `win32security`.

**Ejemplos:**
```json
{
  "owner_name": "alice"
}
```

```json
{
  "owner_name": "CORP\\alice"
}
```

**Casos donde es `None`:**
- Usuario no existe en la BD local
- Permisos insuficientes para leer el propietario
- Sistema de ficheros especial (red, virtual)

---

## 📊 Resumen Visual

```
DocumentMetadata (FASE 1)
├─ Campos existentes (sin cambio)
│  ├─ full_path: str
│  ├─ display_name: str
│  ├─ extension: str
│  ├─ size_bytes: int
│  ├─ modified_time: float
│  └─ sha256_hash: str
│
├─ CAMPOS NUEVOS FASE 1 ✨
│  ├─ created_time: float | null
│  ├─ mime_type: str | null
│  ├─ detected_language: str | null (futuro)
│  ├─ file_permissions: str | null
│  └─ owner_name: str | null
```

---

## 💾 Almacenamiento

### En `cache.db`

```sql
-- Tabla cache (versión 1.5.0+)
CREATE TABLE cache (
    file_path TEXT PRIMARY KEY,
    sha256_hash TEXT,
    timestamp FLOAT,
    status TEXT,
    conversion_status TEXT,
    error_message TEXT,
    error_retry_count INTEGER,
    size_bytes INTEGER,
    
    -- CAMPOS NUEVOS FASE 1
    created_time FLOAT,
    mime_type TEXT,
    detected_language TEXT,
    file_permissions TEXT,
    owner_name TEXT
);
```

**Nota:** En BD anterior a v1.5.0, los campos nuevos son `NULL`. Se rellenan en el primer escaneo después de actualizar.

### En JSON (ScanResult, context.json)

```json
{
  "documents": [
    {
      "full_path": "/repo/document.pdf",
      "display_name": "document.pdf",
      "extension": "pdf",
      "size_bytes": 1048576,
      "modified_time": 1693152000.0,
      "sha256_hash": "abc123def456...",
      "created_time": 1693151000.0,
      "mime_type": "application/pdf",
      "detected_language": null,
      "file_permissions": "644",
      "owner_name": "user"
    }
  ]
}
```

---

## 🔄 Compatibilidad hacia Atrás

### v1.4.0 → v1.5.0

**Migración automática:**
- Primera vez que se escanea con v1.5.0, `cache.db` se actualiza automáticamente
- Se agregan columnas `NULL` para todos los ficheros existentes
- En el siguiente escaneo, los campos nuevos se rellenan

**Sin breaking changes:**
- Código antiguo que ignora los campos nuevos sigue funcionando
- JSON antiguo sin los campos carga sin errores

**Pasos de migración:**
```bash
# Antes de actualizar a v1.5.0
# Hacer backup: cp .cache/proyecto/cache.db .cache/proyecto/cache.db.bak

# Después de actualizar
# Primera vez que ejecutes escaneo
python -m doc_organize scan --project mi_proyecto

# Automáticamente:
# 1. cache.db se migra (columnas nuevas = NULL)
# 2. Se re-escanea (rellena los campos nuevos)
```

---

## 📈 Rendimiento

**Impacto en tiempo de escaneo:**

| Operación | Tiempo antes | Tiempo después | Delta |
|-----------|-------------|----------------|-------|
| Escanear 1000 ficheros | 5s | 5.2s | +4% |
| Extraer tipo MIME | N/A | <1ms/fichero | - |
| Extraer permisos | N/A | <0.5ms/fichero | - |
| Obtener propietario | N/A | <1ms/fichero | - |

**Factores:**
- Detección MIME es rápida (principalmente basada en extensión)
- `python-magic` (más lento) no se usa a menos que sea necesario
- Extracción de permisos es trivial

**Recomendación:** Impacto negligible, < 10% overhead total.

---

## 🛠️ Configuración

### Deshabilitar FASE 1 (futuro)

En v1.5.0, no hay flag para deshabilitar. En futuras versiones:

```python
# Hipotético en FASE 2+
scan_options = ScanOptions(
    extract_basic_metadata=False,
)
```

---

## 📝 Ejemplos de Uso

### Filtrar por tipo MIME

```python
# Obtener solo PDFs
pdfs = [doc for doc in result.documents if doc.mime_type == "application/pdf"]
```

### Filtrar por permisos demasiado abiertos

```python
# Encontrar ficheros con permisos 777 (peligro)
insecure = [doc for doc in result.documents if doc.file_permissions == "777"]
```

### Edad del documento

```python
import time
from datetime import datetime

# Documentos creados hace más de 1 año
now = time.time()
one_year_ago = now - (365 * 24 * 3600)

old_docs = [doc for doc in result.documents if doc.created_time and doc.created_time < one_year_ago]
```

---

## 🚨 Limitaciones Conocidas

### 1. `created_time` no es exacta

En Linux/Windows, `created_time` es una aproximación usando `st_ctime`. No es la fecha exacta de creación original.

**Solución:** Si necesitas fecha exacta, usa metadatos del documento (EXIF de imágenes, createdDate de PDFs).

### 2. `owner_name` en sistemas de red

Si el fichero está en una carpeta compartida (SMB, NFS), `owner_name` puede ser:
- `None` (no se resuelve el usuario remoto)
- Un SID genérico en Windows
- UID numérico en Linux (si no está en `/etc/passwd`)

### 3. Permisos en NTFS/Windows

`file_permissions` intenta convertir permisos Windows a octal, pero el mapeo no es perfecto.

**Recomendación:** Usar solo para análisis aproximados, no para control de acceso.

---

## ✅ Lista de Verificación para Auditoría

- [ ] Todos los documentos tienen `mime_type` no nulo
- [ ] `file_permissions` tiene formato octal (3 dígitos)
- [ ] `created_time` es timestamp Unix válido (> 0)
- [ ] `owner_name` es `None` o string válido
- [ ] `detected_language` es `None` (futuro)
- [ ] JSON serializa/deserializa correctamente
- [ ] Sin regresiones en tests existentes
- [ ] Documentación actualizada (zensical build --strict pasa)

---

*Documentación FASE 1 | v1.0 | 2026-11-15*
