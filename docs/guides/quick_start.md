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
anteriores, en `duplicados/DEDUP_HISTORY.jsonl` (consultable desde la página
"Duplicados" de la interfaz web).

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

## 3. Interfaz web (opcional)

```bash
pip install doc_organize[web]
python -m doc_organize web
```

Arranca en `http://127.0.0.1:8000` — en loopback, sin autenticación. Desde el
Project Selector puedes crear/abrir proyectos; en la página Escanear, buscar
duplicados y escanear con progreso en vivo (el escaneo queda deshabilitado
hasta ejecutar "Buscar duplicados" en esa misma visita); además, ver el caché,
consultar/resolver duplicados y descargar un export ZIP.

### Exponer la web fuera de tu máquina

En un host no-loopback (`--host 0.0.0.0`), la web exige que los usuarios inicien
sesión. Antes de exponerla, crea al menos un tenant y un usuario:

```bash
python -m doc_organize tenant create "Mi Organización"     # -> tenant_id, p.ej. "mi-organizacion"
python -m doc_organize user create alice --tenant mi-organizacion
# La contraseña se pide de forma interactiva (nunca como argumento de CLI)

python -m doc_organize web --host 0.0.0.0 --port 8000
```

Sin ningún usuario provisionado, el servidor arranca igual pero queda
inaccesible: nadie puede autenticarse en `/login`. No expongas `--host 0.0.0.0`
a una red no confiable sin un proxy TLS delante — `doc_organize` no termina TLS
por sí mismo.

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
