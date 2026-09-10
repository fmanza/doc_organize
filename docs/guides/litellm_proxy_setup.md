# Desplegar un LiteLLM Proxy (Sub-fase B: clasificación de dominios por IA)

La organización documental por dominios (`doc_organize.context`) clasifica cada
documento por reglas primero (Sub-fase A). Si activas el toggle **"Clasificación
asistida por IA"** en la pantalla Contexto de un proyecto, los documentos que las
reglas dejan sin clasificar pasan por un **LiteLLM Proxy** (Sub-fase B) — nunca se
llama a un proveedor de IA directamente. Esta guía explica cómo levantar ese proxy
en local con Docker.

Un proyecto con `taxonomy_manifest.md` (clasificación de 2 ejes: dominio + tipo de
material) usa el mismo proxy pero un cliente y unas variables de entorno propias
(`TaxonomyClassificationClient`, §4) — el mismo toggle "IA" activa una llamada
combinada que resuelve ambos ejes a la vez, en vez de la llamada de 1 eje.

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

- `LITELLM_MASTER_KEY`: clave de administrador del proxy — genera una propia
  (p. ej. `openssl rand -hex 32`), nunca uses el valor de ejemplo.
- `LITELLM_SALT_KEY`: cifra las credenciales que se añadan vía la UI del proxy.
  ⚠️ Fíjala una vez y no la cambies después del primer arranque — cambiarla
  invalida cualquier credencial ya cifrada en la base de datos.
- `DATABASE_URL`/`POSTGRES_PASSWORD`: conexión a la Postgres del propio
  `docker-compose.yml` (LiteLLM la necesita para gestionar virtual keys y
  presupuestos) — no cambies el host `postgres`, es el nombre del servicio
  dentro de la red de docker-compose, no un host real.
- `ANTHROPIC_API_KEY`: tu API key real del proveedor.

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

**AÑADIDO (2026-09-11)**: alternativa a editar `.env` a mano — el panel
`/admin/configuracion-ia` de la propia aplicación permite guardar estas mismas
variables desde la web (persistidas cifradas en reposo), sin reiniciar el
proceso. Ver [Configuración de IA y plantillas](../functional/ai_settings.md).
Ambas vías son equivalentes y pueden combinarse; lo que sigue documenta la vía
por `.env`, siempre disponible.

En el entorno donde corre `python -m doc_organize web` (o en tu `.env` de la raíz
del proyecto, ver `.env.example`):

```bash
DOC_ORGANIZE_LITELLM_CLASSIFICATION_BASE_URL=http://localhost:4000
DOC_ORGANIZE_LITELLM_CLASSIFICATION_VIRTUAL_KEY=sk-...   # la virtual key del paso 3
DOC_ORGANIZE_LITELLM_CLASSIFICATION_MODEL=claude-classifier   # opcional, es el valor por defecto
```

Estas variables se leen explícitamente vía
`litellm_classification_config_from_env()` (`doc_organize.ai`) — nunca de forma
implícita. Si activas el toggle "IA" en la pantalla Contexto sin haberlas
definido, `POST /api/projects/{name}/context` devuelve un 400 con un mensaje
explícito en vez de un error críptico.

**Si el proyecto tiene `taxonomy_manifest.md`** (modo de 2 ejes), configura en su
lugar las variables de `TaxonomyClassificationClient` — son una config separada
(ISP: una virtual key por carga de trabajo, para poder atribuir presupuesto/rate-limit
por separado), aunque apunten al mismo proxy que acabas de levantar:

```bash
DOC_ORGANIZE_LITELLM_TAXONOMY_CLASSIFICATION_BASE_URL=http://localhost:4000
DOC_ORGANIZE_LITELLM_TAXONOMY_CLASSIFICATION_VIRTUAL_KEY=sk-...   # genera otra virtual key en el paso 3
DOC_ORGANIZE_LITELLM_TAXONOMY_CLASSIFICATION_MODEL=claude-classifier   # opcional, es el valor por defecto
```

Un proyecto sin manifiesto solo necesita las variables de 1 eje; uno con
manifiesto solo necesita las de 2 ejes — no hace falta definir ambos juegos a la
vez salvo que el mismo despliegue de doc_organize sirva proyectos de los dos tipos.

**AÑADIDO (auditoría de parametrización, 2026-09-10)**: esta guía no mencionaba
las variables del endpoint `POST /api/projects/{name}/context/taxonomy-manifest-draft`
(botón "Proponer con IA" al crear un `taxonomy_manifest.md` nuevo) — quedó sin
actualizar al añadirse ese endpoint. Config propia (ISP, mismo criterio que
separa las dos configs de arriba):

```bash
DOC_ORGANIZE_LITELLM_TAXONOMY_MANIFEST_DRAFT_BASE_URL=http://localhost:4000
DOC_ORGANIZE_LITELLM_TAXONOMY_MANIFEST_DRAFT_VIRTUAL_KEY=sk-...   # genera otra virtual key en el paso 3
DOC_ORGANIZE_LITELLM_TAXONOMY_MANIFEST_DRAFT_MODEL=claude-classifier   # opcional, es el valor por defecto
```

Requiere el extra `doc_organize[context]` instalado (`pip install
doc_organize[context]`) para `pyyaml` (generación de `mkdocs.yml`) — el cliente
de clasificación en sí solo usa `httpx`, ya incluido en el extra `ai`.

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
