# Metadatos de fichero

Desde 1.5.0, cada documento escaneado (`DocumentMetadata`) y su entrada de caché (`CacheEntry`) llevan cuatro datos
del sistema de ficheros, además del nombre, la extensión, el tamaño, la fecha de modificación y el SHA-256 de antes.
Sirven para filtrar y ordenar documentos sin abrirlos: por tipo, por antigüedad o por propietario.

| Campo | Ejemplo | Origen | `None` cuando |
|---|---|---|---|
| `created_time` | `1693151000.0` | `st_birthtime` | En Linux, que no da la fecha de creación |
| `mime_type` | `"application/pdf"` | La extensión (`mimetypes`) | La extensión no es conocida |
| `file_permissions` | `"644"` | `st_mode` (permisos POSIX en octal) | En Windows |
| `owner_name` | `"ana"`, `"EMPRESA\\ana"` | El propietario del fichero | Por defecto (hay que pedirlo) o si la cuenta no se resuelve |

Ninguno lee el contenido del fichero: salen del `stat` que el escáner ya hace para cada documento. Lo que el sistema
no da de forma fiable queda en `None` en lugar de aproximarse.

## Propietario: solo si se pide

`owner_name` identifica a una persona, así que no se guarda salvo que se active:

```python
from doc_organize import ScanOptions

options = ScanOptions(capture_owner=True)
```

En Windows se lee el descriptor de seguridad del fichero (una llamada al sistema por documento, y una consulta al
dominio por cada cuenta distinta); en POSIX solo se traduce el UID. Un UID sin usuario local (p. ej. en un montaje NFS)
o un SID de una cuenta borrada dan `None`.

Sin `capture_owner`, `owner_name` es `None` también en la caché: un escaneo sin la opción borra el propietario que
hubiera guardado uno anterior.

## En la caché

Las columnas `created_time`, `mime_type`, `file_permissions` y `owner_name` se añaden solas la primera vez que se abre
en escritura una caché anterior; en solo lectura se leen como `None` (ver [Caché](../api/cache.md#schema-sqlite)).

Cada escaneo guarda los metadatos de los documentos que convierte y, sin reconvertirlos, actualiza los de los
documentos sin cambios de contenido. Así una caché de una versión anterior se completa en el primer escaneo, y un
cambio de permisos o de propietario llega a la caché aunque el contenido no cambie.

`DocumentMetadata.from_cache_entry` los conserva, de modo que se pueden usar sin volver a escanear:

```python
from datetime import datetime, timedelta

from doc_organize.cache import CacheManager
from doc_organize.core.models import DocumentMetadata

async with CacheManager(cache_db, read_only=True) as cache:
    entries = await cache.load_cache()
docs = [DocumentMetadata.from_cache_entry(e) for e in entries.values() if e.size_bytes is not None]

pdfs = [d for d in docs if d.mime_type == "application/pdf"]
hace_un_ano = (datetime.now() - timedelta(days=365)).timestamp()
antiguos = [d for d in docs if d.created_time is not None and d.created_time < hace_un_ano]
```

## Limitaciones

- **`mime_type` se deduce de la extensión.** Un fichero renombrado con otra extensión da el tipo de la extensión, no
  el de su contenido.
- **`created_time` es la creación de ese fichero en ese disco.** Una copia o una sincronización (OneDrive, Dropbox)
  crea un fichero nuevo; para la fecha original del documento hay que mirar sus propios metadatos (PDF, Office, EXIF).
- **`file_permissions` no dice quién puede leer el fichero en Windows**, donde manda la ACL; por eso ahí es `None`.

> Corregido antes de publicarse (2026-11-15): la primera versión de esta guía, en el PR #34, documentaba un campo
> `detected_language` que nunca se rellenaba, aproximaba `created_time` con `st_ctime` en Linux, daba permisos en
> Windows y guardaba el propietario siempre, con pywin32, que no es dependencia. También afirmaba una migración de la
> caché y unas cifras de rendimiento (+4 %) que no existían. Esta versión describe el código que se publica.
