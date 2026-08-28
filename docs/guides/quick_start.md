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

## 2. Escanea y convierte

```bash
python -m doc_organize scan --project "Mi Proyecto" --paths /ruta/a/documentos
```

Escanea `/ruta/a/documentos` recursivamente, calcula el hash SHA-256 de cada
documento soportado, convierte los nuevos/modificados a Markdown + JSON dentro de
`Mi Proyecto/Conversión/` (replicando su estructura de origen) y actualiza el
caché. Una segunda ejecución sobre la misma carpeta solo procesa lo que cambió.

Flags útiles:

```bash
--deduplicate    # detecta duplicados exactos/conflictos de version y los mueve a duplicados/
--use-ocr        # reprocesa con OCR los documentos sin capa de texto nativa
--use-gpu        # OCR acelerado por GPU (requiere el extra ocr-gpu), solo con --use-ocr
```

## 3. Interfaz web (opcional)

```bash
pip install doc_organize[web]
python -m doc_organize web
```

Arranca en `http://127.0.0.1:8000` — en loopback, sin autenticación. Desde el
Project Selector puedes crear/abrir proyectos, escanear con progreso en vivo,
ver el caché, resolver duplicados y descargar un export ZIP.

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

`scan` también funciona sin `--project`, indicando las rutas explícitamente:

```bash
python -m doc_organize scan \
  --paths /ruta/a/documentos \
  --output-dir ./Conversión \
  --cache-file ./cache.db
```
