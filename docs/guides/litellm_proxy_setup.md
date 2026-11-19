# Desplegar un LiteLLM Proxy (Sub-fase B: clasificación de dominios por IA)

La organización documental por dominios (`doc_organize.context`) clasifica cada
documento por reglas primero (Sub-fase A). Si activas la clasificación asistida por
IA (`ContextBuilder.build(llm=LlmClient(...), ai_scope="unclassified")`), los documentos que las
reglas dejan sin clasificar pasan por un **LiteLLM Proxy** (Sub-fase B) — nunca se
llama a un proveedor de IA directamente. Esta guía explica cómo levantar ese proxy
en local con Docker.

Desde 2.0.0 un solo cliente (`LlmClient`, §4) hace todas las tareas de IA contra ese proxy: clasificar (con o sin
`taxonomy_manifest.md`; con manifiesto, una sola llamada resuelve todos los ejes pendientes), describir documentos y
proponer una taxonomía.

No necesitas esta guía si no vas a usar la Sub-fase B: la clasificación por reglas
funciona sin ningún proxy ni credencial de IA.

## Requisitos

- [Docker](https://docs.docker.com/get-docker/) y Docker Compose (incluido en
  Docker Desktop en Windows/macOS; en Linux, el plugin `docker compose`).
- Una API key de un proveedor de modelos (el ejemplo de esta guía usa Anthropic).

## 1. Configurar

```bash
cd deploy/litellm
cp .env.example .env
cp config.yaml.example config.yaml
```

Edita **`.env`**:

- `LITELLM_MASTER_KEY`: clave de administrador del proxy — debe empezar por
  `sk-`. Genera una propia (ver [Generar las claves](#generar-las-claves) más
  abajo), nunca uses el valor de ejemplo.
- `LITELLM_SALT_KEY`: cifra las credenciales que se añadan vía la UI del proxy.
  ⚠️ Fíjala una vez y no la cambies después del primer arranque — cambiarla
  invalida cualquier credencial ya cifrada en la base de datos.
- `DATABASE_URL`/`POSTGRES_PASSWORD`: conexión a la Postgres del propio
  `docker-compose.yml` (LiteLLM la necesita para gestionar virtual keys y
  presupuestos) — no cambies el host `postgres`, es el nombre del servicio
  dentro de la red de docker-compose, no un host real.
- `ANTHROPIC_API_KEY`: tu API key real del proveedor.

### Generar las claves

`LITELLM_MASTER_KEY` y `LITELLM_SALT_KEY` son cadenas aleatorias que generas
tú — no hay un valor "correcto", solo que sean únicas, impredecibles y
distintas entre sí. La única diferencia de formato: `LITELLM_MASTER_KEY` debe
empezar por `sk-`; `LITELLM_SALT_KEY` no necesita prefijo.

**Linux / macOS** (bash/zsh, usa `openssl`):

```bash
echo "LITELLM_MASTER_KEY=sk-$(openssl rand -hex 32)"
echo "LITELLM_SALT_KEY=$(openssl rand -hex 32)"
```

**Windows — Git Bash** (incluye `openssl`; viene con Git for Windows, mismos
comandos que Linux/macOS):

```bash
echo "LITELLM_MASTER_KEY=sk-$(openssl rand -hex 32)"
echo "LITELLM_SALT_KEY=$(openssl rand -hex 32)"
```

**Windows — PowerShell** (sin depender de `openssl`):

```powershell
$bytes = [byte[]]::new(32)
[System.Security.Cryptography.RandomNumberGenerator]::Fill($bytes)
$hex = ($bytes | ForEach-Object { $_.ToString('x2') }) -join ''
"LITELLM_MASTER_KEY=sk-$hex"
```

```powershell
$bytes = [byte[]]::new(32)
[System.Security.Cryptography.RandomNumberGenerator]::Fill($bytes)
"LITELLM_SALT_KEY=" + (($bytes | ForEach-Object { $_.ToString('x2') }) -join '')
```

**Cualquier plataforma con Python** (ya lo necesitas para usar doc_organize):

```bash
python -c "import secrets; print('LITELLM_MASTER_KEY=sk-' + secrets.token_hex(32))"
python -c "import secrets; print('LITELLM_SALT_KEY=' + secrets.token_hex(32))"
```

Pega cada valor generado en la línea correspondiente de `.env`.

Edita **`config.yaml`** si quieres otro modelo/proveedor — por defecto usa
`claude-classifier` como alias apuntando a un modelo económico
(`anthropic/claude-haiku-4-5-20251001`), suficiente para clasificar un documento
entre un catálogo cerrado de dominios.

Ni `.env` ni `config.yaml` (los reales, no los `.example`) se versionan — ya están
en el `.gitignore` de la raíz del repo.

## 2. Levantar el proxy

```bash
docker compose up -d
```

Verifica que responde:

```bash
curl http://localhost:4000/health/liveliness
```

## 3. Generar una virtual key para doc_organize

El master key es de administrador — no lo uses directamente en doc_organize.
Genera una virtual key con permiso de `chat/completions`:

```bash
curl -X POST http://localhost:4000/key/generate \
  -H "Authorization: Bearer <tu LITELLM_MASTER_KEY>" \
  -H "Content-Type: application/json" \
  -d '{"models": ["claude-classifier"]}'
```

La respuesta incluye `"key": "sk-..."` — esa es la virtual key.

## 4. Configurar doc_organize

Desde 2.0.0 hay **un solo cliente de IA** (`LlmClient`) para todas las tareas, con un modelo (y si quieres una virtual
key propia) por tarea. La librería lo configura desde estas variables con `settings_from_env()` (`doc_organize.ai`), o
recibe el `AiSettings` ya construido por el consumidor; doc_organize_web tiene su propia configuración de IA.

En el entorno donde corre `doc_organize` (o en tu `.env` de la raíz del proyecto, ver `.env.example`):

```bash
DOC_ORGANIZE_LITELLM_BASE_URL=http://localhost:4000
DOC_ORGANIZE_LITELLM_VIRTUAL_KEY=sk-...                        # la virtual key del paso 3
DOC_ORGANIZE_LITELLM_MODEL_CLASSIFY=claude-classifier          # clasificar ejes
DOC_ORGANIZE_LITELLM_MODEL_ENRICH=claude-classifier            # describir documentos
DOC_ORGANIZE_LITELLM_MODEL_TAXONOMY_DESIGN=claude-classifier   # proponer una taxonomía
# Opcional: una virtual key propia por tarea, para atribuir presupuesto y límites aparte en el proxy
DOC_ORGANIZE_LITELLM_VIRTUAL_KEY_CLASSIFY=sk-...
```

Una tarea sin `MODEL_<TAREA>` usa el alias recomendado `doc-organize-<tarea>` (`doc-organize-classify`,
`doc-organize-enrich`, `doc-organize-taxonomy-design`): puedes crear esos alias en el `config.yaml` del proxy o dar el
modelo real en la variable. Sin `BASE_URL`, `settings_from_env()` devuelve `None` (sin IA); con `BASE_URL` y sin
`VIRTUAL_KEY`, `AiConfigurationError`.

Las variables de 1.x (`DOC_ORGANIZE_LITELLM_CLASSIFICATION_*`, `_TAXONOMY_CLASSIFICATION_*`, `_ENRICHMENT_*`,
`_TAXONOMY_MANIFEST_DRAFT_*`) ya no se leen: si alguna está definida, `settings_from_env()` lanza
`AiConfigurationError` con su equivalente (ver [De 1.x a 2.0](migracion_2_0.md)).

Para comprobar que todo responde, sin enviar nada de ningún documento:

```python
import asyncio
from doc_organize import check_environment

report = asyncio.run(check_environment(check_ai=True))
print([(check.name, check.status, check.detail) for check in report.checks if check.name.startswith("ai")])
```

Requiere el extra `doc_organize[context]` instalado (`pip install doc_organize[context]`) para `pyyaml` (manifiestos,
plantillas y prompts); el cliente en sí solo usa `httpx`, ya incluido en el extra `ai`.

## Parar el proxy

```bash
cd deploy/litellm
docker compose stop
```

Detiene los contenedores (`litellm` y `postgres`) sin borrarlos — las virtual
keys y la config ya generadas quedan intactas para el próximo `docker compose
up -d` (usa `docker compose start` para reanudarlos sin recrearlos, o `up -d`
si has tocado `.env`/`config.yaml`/`docker-compose.yml`).

Si además quieres eliminar los contenedores (por ejemplo, antes de un `up -d`
tras editar `docker-compose.yml`):

```bash
docker compose down
```

Esto **no** borra el volumen `litellm_postgres_data`: las virtual keys
generadas en el paso 3 se conservan. Solo si necesitas empezar de cero (perder
todas las virtual keys y tener que regenerarlas):

```bash
docker compose down -v   # ⚠️ borra también la Postgres con las virtual keys
```

## Troubleshooting

**Puerto 4000 ocupado**: cambia `LITELLM_PORT` en `.env` (p. ej. `LITELLM_PORT=4001`)
y reinicia con `docker compose up -d`.

**El proxy no arranca / reinicia en bucle**: revisa `docker compose logs litellm`.
La causa más común es `DATABASE_URL` mal formada o Postgres todavía no listo —
`docker-compose.yml` ya espera a que Postgres pase su healthcheck antes de
arrancar LiteLLM, pero un primer arranque puede tardar unos segundos más en
completar las migraciones internas de LiteLLM.

**`401`/`403` clasificando documentos**: la virtual key no tiene permiso sobre el
modelo `claude-classifier` (o el que hayas configurado) — repite el paso 3
incluyendo ese modelo en `"models"`.

## Referencias

- [LiteLLM Proxy — Docker Quickstart](https://docs.litellm.ai/docs/proxy/docker_quick_start)
- [LiteLLM Proxy — Virtual Keys](https://docs.litellm.ai/docs/proxy/virtual_keys)
- [LiteLLM Proxy — Config Overview](https://docs.litellm.ai/docs/proxy/configs)
