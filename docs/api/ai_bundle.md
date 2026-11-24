# Paquete para IA (2.0)

El uso más habitual del contexto fuera de la web es dárselo a un chat o un agente de IA (un proyecto de Claude,
NotebookLM, Copilot). `write_ai_context_bundle` escribe un ZIP pensado para subirlo tal cual.

```python
import asyncio
from doc_organize import write_ai_context_bundle

stats = await asyncio.to_thread(write_ai_context_bundle, "contexto_ia.zip", project, context)
print(stats.documents, stats.redacted_documents, stats.sha256)
```

## Qué lleva

| Fichero | Contenido |
|---|---|
| `llms.txt` | Formato de [llmstxt.org](https://llmstxt.org/): el proyecto, una sección por dominio y una línea por documento con su enlace y su descripción (o tipo de material) |
| `documentos/<dominio>/<tipo>/<carpeta>/<doc>.md` | El texto del documento con un front matter YAML: `title`, `domain`, `material_type`, `axes` (valores por eje), `classified_by`, `source` (ruta del original **relativa** a la raíz de escaneo), `source_sha256`, `version`/`is_current` si tiene versiones, `description` y `keywords` si se enriqueció |
| `context.json` | El contexto reducido: dominios, ejes del catálogo y la ficha de cada documento, sin rutas absolutas |
| `llms-full.txt` | Opcional (`max_full_chars`): todo el texto en un fichero, hasta ese tope |

Las rutas de `documentos/` son las de la carpeta reorganizada (`resolve_organized_paths`): únicas y estables.

## Opciones

| Opción | Por defecto | Qué hace |
|---|---|---|
| `redact` | `True` | Títulos, descripciones y textos sin credenciales (`redact_credentials`). Con `False` salen los valores secretos |
| `current_only` | `True` | Solo las versiones vigentes (F5): sin las versiones antiguas |
| `include_text` | `True` | Con `False`, solo las fichas |
| `max_file_chars` | `None` | Tope de caracteres del texto de cada documento (se avisa del corte) |
| `max_full_chars` | `None` | Con un valor, añade `llms-full.txt` hasta ese tope |
| `roots` | `None` | Raíces de escaneo para las rutas relativas de los originales (`source`); por defecto, la carpeta común |
| `on_progress` | `None` | Recibe `ProgressEvent(operation="export")`, como `write_project_zip` |
| `cancel_token` | `None` | Si se cancela, para entre dos documentos (`OperationCancelledError`; si el destino es una ruta, el fichero parcial se borra) |

El ZIP es reproducible (mismo contexto y textos → mismo SHA-256) y se escribe en *streaming*, con progreso y
cancelación como `write_project_zip`.

**El paquete es todo el corpus en texto**: trátalo como la exportación del proyecto. `llms.txt` no sirve para que te
encuentren los buscadores: es el índice para el modelo al que subes el paquete. Con muchos documentos, `llms-full.txt`
supera el contexto de cualquier modelo: lo normal es subir la carpeta `documentos/` (o la de un dominio).

## `llms.txt` en el sitio

`SiteGenerator.generate(llms_txt=True)` deja el mismo `llms.txt` en la raíz del sitio, con enlaces a las páginas
(`.html` en el sitio sin conexión) y sin credenciales si `redact_credentials`. `render_llms_txt` lo genera para
cualquier destino.

::: doc_organize.export.ai_bundle
    options:
      show_root_heading: false
      members:
        - write_ai_context_bundle
        - AiBundleStats

::: doc_organize.context.llms_txt
    options:
      show_root_heading: false
      members:
        - render_llms_txt
