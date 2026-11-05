# Inicio rápido

## 1. Crea un proyecto

Un proyecto agrupa la carpeta de conversión, el caché y los duplicados de un
conjunto de documentos bajo una única carpeta raíz.

```bash
python -m doc_organize project create "Mi Proyecto" --location /ruta/a/workspaces
```

Crea `/ruta/a/workspaces/Mi Proyecto/` y lo registra en
`~/.doc_organize/projects.json`.

```bash
python -m doc_organize project list
```

## 2. Busca duplicados y escanea

`deduplicate` y `scan` son dos acciones independientes, en ese orden:

```bash
python -m doc_organize deduplicate --project "Mi Proyecto" --paths /ruta/a/documentos
python -m doc_organize scan --project "Mi Proyecto" --paths /ruta/a/documentos
```

`deduplicate` busca duplicados exactos y conflictos de versión (por hash SHA-256)
y los mueve a `duplicados/`. Cada ejecución queda registrada, sin sobrescribir las
anteriores, en `duplicados/DEDUP_HISTORY.jsonl`.

`scan` escanea `/ruta/a/documentos` recursivamente, convierte los
nuevos/modificados a Markdown + JSON dentro de `Mi Proyecto/Conversión/`
(replicando su estructura de origen) y actualiza el caché. Una segunda
ejecución sobre la misma carpeta solo procesa lo que cambió. Ya no deduplica
por sí solo — para eso está `deduplicate`.

Flags útiles de `scan`:

```bash
--use-ocr        # reprocesa con OCR los documentos sin capa de texto nativa
--use-gpu        # OCR acelerado por GPU (requiere el extra ocr-gpu), solo con --use-ocr
```

## 3. Interfaz web

Desde 1.0.0 la librería no incluye interfaz web (L-11): usa [doc_organize_web](https://github.com/fmanza/doc_organize_web), que trabaja sobre las mismas carpetas de
proyecto. La guía de la web integrada de 0.14.0 está en el [histórico](../historico/web-access.md).

## 4. Uso avanzado sin proyecto

`scan` y `deduplicate` también funcionan sin `--project`, indicando las rutas
explícitamente:

```bash
python -m doc_organize scan \
  --paths /ruta/a/documentos \
  --output-dir ./Conversión \
  --cache-file ./cache.db

python -m doc_organize deduplicate \
  --paths /ruta/a/documentos \
  --duplicates-dir ./duplicados
```
