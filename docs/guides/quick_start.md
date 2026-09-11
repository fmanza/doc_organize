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
Project Selector puedes crear/abrir proyectos; en la página del proyecto
(Dashboard) gestionas las carpetas guardadas; en Escanear, escanear con
progreso en vivo y consultar el caché (dos pestañas: Escanear / Caché); en
Duplicados, buscar/resolver duplicados y consultar el histórico de
deduplicaciones (dos pestañas: Buscar duplicados / Histórico de
deduplicaciones); y descargar un export ZIP.

### Exponer la web fuera de tu máquina

En un host no-loopback (`--host 0.0.0.0`), la web exige que los usuarios inicien
sesión. No hace falta provisionar nada por CLI de antemano: al abrir `auth.db`
por primera vez, `doc_organize` crea de fábrica el tenant `default` con un
usuario `admin`/`admin`. Esa cuenta, sin embargo, no puede completar el login
mientras el servidor esté en modo no-loopback y conserve la contraseña de
fábrica — cámbiala primero desde loopback:

```bash
# 1. En loopback (por defecto), entra con admin/admin y cambia la contraseña
python -m doc_organize web
# http://127.0.0.1:8000/login -> te redirige a /change-password tras entrar

# 2. Ahora sí, expón el servidor
python -m doc_organize web --host 0.0.0.0 --port 8000
# entra con admin / la contraseña nueva
```

Para un tenant y usuario propios (en vez de usar el de fábrica), sigue
disponible `tenant create`/`user create` por CLI, o la pantalla "Tenants y
usuarios" del panel `/admin` (solo visible para un usuario `is_instance_admin`,
como el `admin` de fábrica):

```bash
python -m doc_organize tenant create "Mi Organización"     # -> tenant_id, p.ej. "mi-organizacion"
python -m doc_organize user create alice --tenant mi-organizacion
# La contraseña se pide de forma interactiva (nunca como argumento de CLI)
```

No expongas `--host 0.0.0.0` a una red no confiable sin un proxy TLS delante —
`doc_organize` no termina TLS por sí mismo. Ver
[Acceso a la Aplicación](../functional/access.md) para el detalle completo del
bloqueo de la cuenta de fábrica y el resto del modelo de autenticación.

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
