# Desplegar un LiteLLM Proxy (IA de doc_organize)

La organización documental por dominios (`doc_organize.context`) clasifica cada
documento por reglas primero (Sub-fase A). Si activas la clasificación asistida por
IA (`ContextBuilder.build(llm=LlmClient(...), ai_scope="unclassified")`), los documentos que las
reglas dejan sin clasificar pasan por un **LiteLLM Proxy** (Sub-fase B) — nunca se
llama a un proveedor de IA directamente. Esta guía explica cómo levantar ese proxy
en local con Docker.

Desde 2.0.0 un solo cliente (`LlmClient`, §4) hace todas las tareas de IA contra ese proxy: clasificar (con o sin
`taxonomy_manifest.md`; con manifiesto, una sola llamada resuelve todos los ejes pendientes), describir documentos,
proponer una taxonomía, los agentes (diseñador y revisor) y, con la semántica activada, los embeddings.

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

Edita **`config.yaml`** si quieres otro modelo o proveedor. El ejemplo define un alias por tarea
(`doc-organize-classify`, `-enrich`, `-taxonomy-design`, `-agent` y `-embed`): un modelo económico para clasificar y
describir, uno más capaz para la taxonomía y los agentes, y uno local de Ollama para los embeddings. Si usas modelos
locales, mira antes [Modelos locales](#modelos-locales-ollama).

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
  -d '{"models": ["doc-organize-classify", "doc-organize-enrich", "doc-organize-taxonomy-design", "doc-organize-agent", "doc-organize-embed"]}'
```

Incluye solo los alias de las tareas que vayas a usar. Si quieres atribuir presupuesto aparte por tarea, genera una
key por tarea con su alias (`DOC_ORGANIZE_LITELLM_VIRTUAL_KEY_<TAREA>`, opcional).

La respuesta incluye `"key": "sk-..."` — esa es la virtual key.

## 4. Configurar doc_organize

Desde 2.0.0 hay **un solo cliente de IA** (`LlmClient`) para todas las tareas, con un modelo (y si quieres una virtual
key propia) por tarea. La librería lo configura desde estas variables con `settings_from_env()` (`doc_organize.ai`), o
recibe el `AiSettings` ya construido por el consumidor; doc_organize_web tiene su propia configuración de IA.

En el entorno donde corre `doc_organize` (o en tu `.env` de la raíz del proyecto, ver `.env.example`):

```bash
DOC_ORGANIZE_LITELLM_BASE_URL=http://localhost:4000
DOC_ORGANIZE_LITELLM_VIRTUAL_KEY=sk-...                        # la virtual key del paso 3
# Opcional: otro modelo para una tarea (si no, el alias doc-organize-<tarea> del config.yaml)
# DOC_ORGANIZE_LITELLM_MODEL_CLASSIFY=otro-alias
# Opcional: una virtual key propia por tarea, para atribuir presupuesto y límites aparte en el proxy
# DOC_ORGANIZE_LITELLM_VIRTUAL_KEY_CLASSIFY=sk-...
```

Una tarea sin `MODEL_<TAREA>` usa el alias `doc-organize-<tarea>` (`doc-organize-classify`, `doc-organize-enrich`,
`doc-organize-taxonomy-design`, `doc-organize-agent`, `doc-organize-embed`), que es lo que define
`config.yaml.example`: así el modelo se cambia en el proxy sin tocar doc_organize. Sin `BASE_URL`, `settings_from_env()` devuelve `None` (sin IA); con `BASE_URL` y sin
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

## Modelos locales (Ollama)

Con Ollama detrás del proxy (ver el bloque comentado de `config.yaml.example`):

- **Contexto**: Ollama recorta el prompt a 4096 tokens **sin dar error** si no se le pide otro contexto. Fija
  `num_ctx` en `litellm_params` de cada alias: 8192 basta para `classify` y `enrich`; `agent` y `taxonomy_design`
  necesitan 32768 (las herramientas y los informes ocupan mucho).
- **Prefijo**: `ollama_chat/<modelo>` para las tareas de chat (lleva herramientas y `response_format`) y
  `ollama/<modelo>` para los embeddings.
- **Tiempo**: un modelo local de 14B, parte en CPU, tarda de media unos 25 s por clasificación y algunas pasan de
  30 s. El timeout por defecto de `AiSettings` (120 s) basta para clasificar y describir; para el diseño de taxonomía
  y los agentes sube el de la tarea (`TaskSettings(timeout_s=600)`). Un timeout corto hace que varias llamadas fallen
  seguidas y la construcción deje de enviar documentos (`ai_stats.stopped = "connection"`).
- **Modelo**: los que razonan antes de responder pueden agotar `max_tokens` sin llegar al JSON; si una tarea falla
  con «no es el JSON esperado», prueba otro modelo o sube `TaskSettings.max_tokens`.

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
alias de la tarea (`doc-organize-<tarea>`, o el que hayas configurado): repite el paso 3
incluyendo ese alias en `"models"`.

**Clasificaciones que se cortan con `stopped = "connection"`**: varias llamadas seguidas superaron el timeout o el
proxy no respondió. Con modelos locales, revisa `num_ctx` y el timeout (ver [Modelos locales](#modelos-locales-ollama)).

## Referencias

- [LiteLLM Proxy — Docker Quickstart](https://docs.litellm.ai/docs/proxy/docker_quick_start)
- [LiteLLM Proxy — Virtual Keys](https://docs.litellm.ai/docs/proxy/virtual_keys)
- [LiteLLM Proxy — Config Overview](https://docs.litellm.ai/docs/proxy/configs)
