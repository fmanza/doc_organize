# doc_organize

`doc_organize` escanea carpetas de documentos, los convierte a Markdown + JSON con
[Docling](https://github.com/docling-project/docling), detecta y resuelve duplicados,
y mantiene un caché incremental (SHA-256) para no reconvertir lo que no ha cambiado.
Se usa como librería de Python o desde la línea de comandos; la interfaz web es
[doc_organize_web](https://github.com/fmanza/doc_organize_web).

## Qué hace

- **Escanea** carpetas recursivamente y calcula el hash SHA-256 de cada documento
  soportado (PDF, Word, Excel, PowerPoint, imágenes).
- **Convierte** cada documento a Markdown + JSON, preservando su estructura de
  carpetas de origen; detecta cuándo un documento necesita OCR (sin capa de texto
  nativa) y lo reprocesa bajo demanda.
- **Deduplica**: detecta duplicados exactos (mismo hash) y conflictos de versión
  (mismo nombre base, contenido distinto), y los mueve a una carpeta separada sin
  tocar los originales que decides conservar. Desde 2.2.0, sobre lo ya convertido,
  también busca **duplicados por contenido**: el mismo texto en ficheros distintos
  y, opcionalmente con IA, contenido parecido o un documento contenido en otro
  ([guía](guides/duplicados_por_contenido.md)).
- **Cachea** de forma incremental: una segunda pasada sobre la misma carpeta solo
  procesa lo nuevo o modificado.
- **Organiza en proyectos**: cada proyecto agrupa su propia carpeta de conversión,
  caché y duplicados bajo una ubicación que tú eliges.
- **Construye un contexto documental**: clasifica cada documento según una
  taxonomía por ejes, por reglas y, si se quiere, con IA a través de un
  [LiteLLM Proxy](guides/litellm_proxy_setup.md); reorganiza una copia en
  carpetas, genera un sitio navegable (también sin conexión) y un paquete para IA.
- **Exporta** un proyecto: ZIP de la conversión y Excel de la caché, de los
  errores de escaneo y del historial del contexto.
- **Interfaz web**: [doc_organize_web](https://github.com/fmanza/doc_organize_web), un proyecto aparte, ofrece las mismas operaciones
  desde el navegador. La web integrada (extra `[web]`) se retiró en 1.0.0:
  ver [De la web integrada a doc_organize_web](guides/migracion_web.md).

## Instalación rápida

```bash
pip install doc_organize            # núcleo: CLI, OCR en CPU incluido
```

Ver [Instalación](guides/installation.md) para el detalle de cada extra, y
[Inicio rápido](guides/quick_start.md) para el primer proyecto de principio a fin.

## Documentación

- **[Guías](guides/installation.md)** — instalación, primer uso, problemas comunes,
  LiteLLM Proxy, duplicados por contenido y guías de migración.
- **[Funcionalidad](functional/index.md)** — qué hace cada módulo del paquete.
- **[API](api/index.md)** — arquitectura, capas y referencia técnica generada desde
  el código.

## Compatibilidad

- Versión actual: **2.6.0**. Python 3.12 o superior (probado en 3.12, 3.13 y 3.14;
  el extra `[av]` necesita 3.12 o 3.13).
- La API pública estable son los nombres de `doc_organize.__all__`, con SemVer:
  ver [API pública y compatibilidad](api/publica.md).
- Cambios de versión: [De 1.x a 2.0](guides/migracion_2_0.md) y
  [Hacia 3.0](guides/migracion_3_0.md) (lo obsoleto en 2.x).
