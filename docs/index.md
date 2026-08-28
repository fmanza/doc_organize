# doc_organize

`doc_organize` escanea carpetas de documentos, los convierte a Markdown + JSON con
[Docling](https://github.com/docling-project/docling), detecta y resuelve duplicados,
y mantiene un caché incremental (SHA-256) para no reconvertir lo que no ha cambiado.
Se usa desde la línea de comandos, o desde una interfaz web opcional con
autenticación multi-usuario y multi-tenant.

## Qué hace

- **Escanea** carpetas recursivamente y calcula el hash SHA-256 de cada documento
  soportado (PDF, Word, Excel, PowerPoint, imágenes).
- **Convierte** cada documento a Markdown + JSON, preservando su estructura de
  carpetas de origen; detecta cuándo un documento necesita OCR (sin capa de texto
  nativa) y lo reprocesa bajo demanda.
- **Deduplica**: detecta duplicados exactos (mismo hash) y conflictos de versión
  (mismo nombre base, contenido distinto), y los mueve a una carpeta separada sin
  tocar los originales que decides conservar.
- **Cachea** de forma incremental: una segunda pasada sobre la misma carpeta solo
  procesa lo nuevo o modificado.
- **Organiza en proyectos**: cada proyecto agrupa su propia carpeta de conversión,
  caché y duplicados bajo una ubicación que tú eliges.
- **Interfaz web opcional** (extra `[web]`): las mismas operaciones desde el
  navegador, con progreso en tiempo real por WebSocket. En modo no-loopback (host
  distinto de `127.0.0.1`), exige autenticación por usuario con soporte
  multi-tenant (varias organizaciones, cada una con sus propios usuarios y
  proyectos, aisladas entre sí).

## Instalación rápida

```bash
pip install doc_organize            # núcleo: CLI, OCR en CPU incluido
pip install doc_organize[web]       # + interfaz web
```

Ver [Instalación](guides/installation.md) para el detalle de cada extra, y
[Inicio rápido](guides/quick_start.md) para el primer proyecto de principio a fin.

## Documentación

- **[Guías](guides/installation.md)** — instalación, primer uso, problemas comunes.
- **[Funcionalidad](functional/index.md)** — qué hace cada módulo del paquete.
- **[API](api/index.md)** — arquitectura, capas y referencia técnica generada desde
  el código.
