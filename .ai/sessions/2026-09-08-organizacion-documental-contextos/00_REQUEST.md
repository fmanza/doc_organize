# 00_REQUEST — Organización documental por dominios y contextos (Fase 2)

> Prompt de entrada para `/new-feature` (ver [`.claude/commands/new-feature.md`](../../../.claude/commands/new-feature.md)).
> No implementado todavía — este documento es el resultado de la Fase 2 ("crear un prompt para...").
> Fase 3 = pegar la sección **"Entrada para /new-feature"** en una sesión nueva para arrancar PLAN → AUDIT_PLAN → IMPLEMENT → AUDIT_CODE → VERSION.

---

## 1. Contexto y motivación

doc_organize hoy escanea carpetas, convierte documentos (`converter/`) y deduplica (`dedup/`), pero
el resultado sigue viviendo como una carpeta plana por proyecto (`project.json`, `cache.db`,
`scanned_folders.json` en `root_path`). No existe ningún concepto de **dominio** (a qué área temática
pertenece un documento) ni de **contexto** (metadatos y plantillas que expliquen ese dominio a un
lector o a una IA futura).

Se pide ampliar la funcionalidad para que, sobre un proyecto ya escaneado, doc_organize pueda:

1. Identificar **dominios** nuevos a partir de la información ya generada por la app (`.json` de
   `converter/`, ver §2.4 sobre por qué JSON y no Markdown), en dos sub-fases dentro del mismo ciclo
   `/new-feature`: **Sub-fase A** (reglas, obligatoria) + **Sub-fase B** (IA asistida vía LiteLLM
   Proxy, opcional tras flag — ver §2.5).
2. Copiar a una **carpeta nueva** reorganizada por dominio el **documento original** más los dos
   artefactos ya generados (`.md` y `.json`) — tres ficheros por documento, nunca solo uno.
3. Rellenar una **plantilla mínima de contexto** por dominio (obligatorio vs. opcional).
4. Generar un **sitio MkDocs** navegable con el resultado del proyecto.

## 2. Referencia de diseño (research)

### 2.1 `doc_calidad/.ai` — fuente principal de inspiración (solo lectura)

`C:\Desarrollo\python\libs\doc_calidad` organiza documentación de un SGI en **dominios normativos**
(Corporativo, Ciberseguridad, Tecnología, Innovación, Sostenibilidad + transversales: Procedimientos,
Controles, Auditorías, Certificaciones, Trazabilidad, Gap Analysis — ver
[`architecture.md`](../../../../doc_calidad/.ai/architecture.md)). Tres piezas son directamente
reutilizables como patrón, no como contenido:

- **`.ai/{product,architecture,runtime,glossary,standards}.md`**: cinco ficheros de contexto de
  tamaño acotado que cualquier IA lee antes de trabajar. Patrón "contexto reutilizable entre sesiones".
- **`standards.md`**: convenciones de nombrado por tipo de documento, front matter YAML obligatorio
  (`title`, `status`, `version`, `normativas_asociadas`), regla "sección vacía se marca *No aplica*,
  nunca se omite".
- **`.ai/sessions/<fecha>_<slug>/{00_REQUEST,00_CONTEXT_SNAPSHOT,TRACEABILITY}.md`**: plantilla de
  sesión con `TEMPLATE/` versionada — el mismo patrón que ya usa doc_organize en
  [`.ai/sessions/TEMPLATE/`](../TEMPLATE/TRACEABILITY.md), pero doc_calidad además arranca con
  `00_REQUEST.md` (que este propio fichero imita).

### 2.2 Estándares externos considerados

- **Diátaxis** (tutorials / how-to / reference / explanation): taxonomía por *función* del documento,
  ortogonal al dominio temático. Útil como segundo eje de clasificación dentro de cada dominio.
- **arc42, cap. "Context and Scope"**: separa contexto de negocio (entradas/salidas de dominio) de
  contexto técnico (canales, protocolos) — confirma que "contexto" debe declarar explícitamente
  **límites** (qué entra y qué no) y no solo una descripción libre.
  Fuente: [docs.arc42.org/section-3](https://docs.arc42.org/section-3/)
- **MADR/ADR**: ya usado en `.github/adr/` de este propio repo — reutilizable para documentar
  decisiones de clasificación de dominio ambiguas.
- **Front matter YAML / Dublin Core**: metadatos mínimos por documento (`title`, `domain`, `type`,
  `source_path`, `generated_at`) — mismo mecanismo que `standards.md` de doc_calidad, adaptado.

### 2.3 Convención ya vigente en doc_organize (no romper)

El estado de un proyecto vive **plano** dentro de `root_path` (`project.json`, `cache.db`,
`scanned_folders.json` — ver [`project_registry.py`](../../../src/doc_organize/projects/project_registry.py)
y [`scanned_folders_store.py`](../../../src/doc_organize/projects/scanned_folders_store.py)) y usa
**JSON**, no YAML, para todo estado propio de la app. La propuesta de estructura de contexto (§3)
sigue esa misma convención en vez de copiar YAML de doc_calidad literalmente.

### 2.4 Fuente de clasificación: ¿Markdown o JSON? — decisión

`converter/converter.py` ya genera **ambos** artefactos por documento (`<stem>.md` + `<stem>.json`,
ver [`converter.py:139-358`](../../../src/doc_organize/converter/converter.py)). No hay que elegir
uno "en vez de" otro para el proyecto — pero **para clasificar** (decidir a qué dominio pertenece un
documento) sí hay que elegir cuál lee el clasificador, y la respuesta es **el `.json`**, no el `.md`:

- El `.json` ya trae `chunks` (troceado por sección vía `HierarchicalChunker`, **"pensado para RAG"**
  según el propio docstring del conversor) más `title`, `source_path`, `sha256_hash` — exactamente la
  forma que necesita un clasificador por reglas o por IA: unidades semánticas ya delimitadas, sin
  tener que re-parsear prosa Markdown (encabezados, imágenes, tablas) para extraer significado.
- El `.md` está optimizado para **lectura humana y renderizado** (MkDocs, preview) — es el formato de
  salida, no de entrada al clasificador. Reutilizarlo también evita depender de heurísticas de
  parseo de Markdown (fences, imágenes `img/<stem>/`) que el `.json` ya resolvió.
- Conclusión: `DomainClassifier` lee `document_json["chunks"]` (+ `title`) como señal principal;
  reglas por ruta/extensión del documento original se usan como señal secundaria/desempate. El `.md`
  se usa después, solo para generar la vista humana del dominio y el sitio MkDocs.

### 2.5 Clasificación asistida por IA (Sub-fase B) — análisis de `src/doc_organize/ai/`

**Decidido con el usuario (2026-09-08)**: IA desde el mismo `/new-feature` que las reglas, reutilizando
el LiteLLM Proxy ya desplegado, como Sub-fase B (obligatoria en el diseño, opcional en runtime tras flag).

**Lo que ya existe en `src/doc_organize/ai/` NO es reutilizable como código de inferencia** — es
monitorización de gasto, no clasificación. El propio módulo lo declara explícito en
[`ai_usage_monitoring.md`](../../../docs/functional/ai_usage_monitoring.md): *"❌ No enruta ni
intercepta llamadas de inferencia"*. `LiteLLMUsageClient` solo lee `GET /key/info` (spend acumulado);
no hay ningún cliente que llame a `chat/completions`.

**Lo que sí se reutiliza es el patrón, no el código**:

- **Infraestructura ya sancionada**: el LiteLLM Proxy que `LiteLLMUsageClient` ya monitoriza es el
  canal a usar para clasificación por IA — nunca una clave directa de Anthropic nueva. El proxy es
  OpenAI-compatible y soporta salida estructurada y presupuestos por virtual-key
  ([LiteLLM Auto Routing](https://docs.litellm.ai/docs/proxy/auto_routing),
  [Budgets/Rate Limits](https://docs.litellm.ai/docs/proxy/users)).
- **Plantilla arquitectónica de `ai/usage_source.py` + los dos clientes**: `Protocol` estructural
  (`runtime_checkable`, sin herencia — ISP), config-desde-entorno explícita vía función dedicada
  (`*_config_from_env()`, nunca lectura implícita dentro del cliente), jerarquía de excepciones propia
  (`UsageSourceAuthError` / `UsageSourceConnectionError` / `UsageSourceError` — no confundir con los
  builtins `ConnectionError`/`Exception` de Python), `httpx.AsyncClient` como context manager
  async con `transport` inyectable para tests sin red real. El nuevo cliente de clasificación
  (`DomainClassificationClient`, en `src/doc_organize/ai/domain_classification_client.py` — mismo
  paquete, no uno nuevo) sigue exactamente ese mismo patrón.
- **Config propia, no compartida**: `ai_usage_monitoring.md` fija la regla "dos fuentes, dos
  clientes, sin compartir config ni credenciales (ISP)" — por el mismo criterio, y porque LiteLLM
  recomienda una virtual-key por carga de trabajo para poder atribuir presupuesto/rate-limit,
  `DomainClassificationClient` usa su propia config (`LiteLLMClassificationConfig`, sus propias env
  vars) aunque apunte a la misma URL de proxy que `LiteLLMUsageConfig`.
- **Complemento de observabilidad**: una vez exista el cliente de clasificación,
  `LiteLLMUsageClient.get_usage()` (ya implementado) sirve para vigilar el gasto que genera, sin
  cambios — dato a favor de reusar el mismo proxy.

### 2.6 Despliegue local del LiteLLM Proxy (Docker) — documentación obligatoria a crear

**Gap detectado (verificado, no hay nada de esto en el repo hoy)**: tanto `ai/litellm_usage_client.py`
(ya cerrado, sesión 2026-09-07) como la Sub-fase B de esta feature (§2.5) **asumen** "un LiteLLM Proxy
ya desplegado y accesible por red" como precondición — pero el repo no explica en ningún sitio cómo
levantar uno. Búsqueda confirmada: cero ficheros `docker*` o `litellm*` de infraestructura en el
repo (solo el propio código cliente). Esta sesión debe cerrar ese hueco, porque sin él la Sub-fase B
no es ejecutable por nadie que no tenga ya un proxy corriendo.

**Entregables concretos** (nuevo directorio `deploy/litellm/`, junto a `scripts/` en la raíz):

| Fichero | Rol |
|---|---|
| `deploy/litellm/docker-compose.yml` | Servicio `litellm` (imagen oficial `ghcr.io/berriai/litellm:main-stable`) + servicio `postgres` (LiteLLM requiere BD para virtual keys/presupuestos — no es opcional en este diseño, ver restricción abajo) |
| `deploy/litellm/config.yaml.example` | `model_list` mínimo: alias de modelo (p. ej. `claude-classifier`) → proveedor Anthropic, `api_key` referenciada desde variable de entorno, nunca en claro; `general_settings.master_key` idem |
| `deploy/litellm/.env.example` | `LITELLM_MASTER_KEY`, `LITELLM_SALT_KEY` (aviso explícito: cambiarla tras el primer arranque invalida credenciales ya cifradas en BD), `DATABASE_URL`, `ANTHROPIC_API_KEY` |
| `.gitignore` (raíz, editar) | **Añadir `.env` / `deploy/litellm/.env`** — verificado (auditoría 2026-09-08): el `.gitignore` actual del repo no ignora ningún `.env`; sin esta línea, `deploy/litellm/.env` (con `LITELLM_MASTER_KEY`/`ANTHROPIC_API_KEY` reales, generado a partir del `.example`) se colaría en el primer commit de quien siga la guía |
| `docs/guides/litellm_proxy_setup.md` | Arquetipo 3 — Guía de Usuario, mismo patrón que `installation.md`/`quick_start.md` ya existentes en `docs/guides/`: prerequisitos (Docker + Docker Compose), `docker compose up -d`, generar una virtual key (`POST /key/generate` con el master key), y cómo mapear esa key a las variables que doc_organize ya espera (`DOC_ORGANIZE_LITELLM_BASE_URL`/`DOC_ORGANIZE_LITELLM_VIRTUAL_KEY` de la monitorización existente, y las nuevas de `LiteLLMClassificationConfig` de §2.5), más troubleshooting mínimo (puerto ocupado, BD no migrada) |
| `mkdocs.yml` | Nueva entrada de nav bajo "Guías" apuntando a `litellm_proxy_setup.md` |

Fuentes verificadas: [LiteLLM Docker Quickstart](https://docs.litellm.ai/docs/proxy/docker_quick_start),
[Virtual Keys](https://docs.litellm.ai/docs/proxy/virtual_keys),
[Config Overview](https://docs.litellm.ai/docs/proxy/configs).

**Alcance explícito**: esto es infraestructura de **desarrollo/self-host documentada**, no un
servicio gestionado por doc_organize — el proxy vive fuera del ciclo de vida de un "proyecto" de la
app (dependencia de entorno, igual que Docling), por eso vive en `deploy/`, no dentro de
`<project.root_path>/`.

### 2.7 Regla general: toda novedad de esta sesión debe quedar documentada

Aplica a **ambas sub-fases**, no solo a la B — requisito explícito del usuario, alineado con
`CLAUDE.md` §Documentación Obligatoria de este repo:

- Toda clase/función pública nueva → docstring Google-style con ejemplo (`context_builder.py`,
  `domain_classifier.py`, `mkdocs_generator.py`, `domain_classification_client.py`, modelos nuevos).
- Todo módulo o capacidad nueva → página MkDocs del arquetipo que corresponda: funcional
  (`docs/functional/`), técnica/API (`docs/api/`), guía (`docs/guides/litellm_proxy_setup.md`, §2.6).
- `mkdocs build --strict` sin warnings de enlaces rotos antes de VERSION (regla ya vigente en
  `CLAUDE.md`, aplicada aquí explícitamente a los ficheros nuevos).
- `CHANGELOG.md` con entrada por sub-fase (A y B pueden ir en el mismo bloque `### Added` o
  separadas, pero ninguna sub-fase cierra VERSION sin su entrada).
- **No se cierra la sesión (`TRACEABILITY.md`) con documentación pendiente** — mismo criterio ya
  aplicado al cierre de `ai/` (sesión 2026-09-07): checklist de verificación incluye `mkdocs build
  --strict` igual que ruff/mypy/pytest.

## 3. Estructura estándar de contexto propuesta

```
<project.root_path>/
├── project.json                  # ya existe
├── cache.db                      # ya existe
├── scanned_folders.json          # ya existe
├── context.json                  # NUEVO — metadatos del contexto: versión de plantilla,
│                                  #   dominios detectados/confirmados, reglas de clasificación,
│                                  #   ai_classification_enabled (flag, default false, Sub-fase B)
├── domains/                      # NUEVO — un subdirectorio por dominio
│   └── <dominio-slug>/
│       ├── DOMAIN.md             # ficha legible: nombre, descripción, alcance (qué SÍ/qué NO),
│       │                         #   tipos de documento esperados — "No aplica" si vacío
│       └── index.json            # inventario generado: documentos clasificados en este dominio
├── organizado/                   # NUEVO — carpeta destino (nombre configurable), COPIA no move
│   └── <dominio-slug>/<tipo>/<stem>/    # 3 ficheros por documento:
│       ├── <stem>.<ext original>        # documento original, tal cual
│       ├── <stem>.md                    # ya generado por converter/, se copia
│       └── <stem>.json                  # ya generado por converter/, se copia
└── docs/                         # NUEVO — sitio MkDocs generado del proyecto
    ├── mkdocs.yml
    └── index.md, <dominio>/...
```

| Fichero/carpeta | Obligatorio | Rol |
|---|---|---|
| `context.json` | Sí | Metadatos del contexto completo del proyecto |
| `domains/<slug>/DOMAIN.md` | Sí (uno por dominio detectado) | Ficha mínima rellenable — plantilla con secciones fijas |
| `domains/<slug>/index.json` | Sí | Generado, no editable a mano |
| `organizado/` | Sí | Salida reorganizada por dominio > tipo; 3 ficheros por documento (original + `.md` + `.json`) |
| `docs/` (MkDocs) | Sí | Sitio navegable del proyecto |

Plantilla mínima de `DOMAIN.md` (secciones fijas, "*No aplica a este dominio.*" si no procede —
regla heredada de `standards.md` de doc_calidad):

```markdown
---
domain: <slug>
status: borrador | confirmado
document_count: <N>
---

# Dominio: <Nombre>

## Descripción
## Alcance (qué SÍ / qué NO)
## Tipos de documento esperados
## Documentos clasificados
<!-- generado desde index.json, no editar a mano -->
```

## 4. Entrada para `/new-feature`

- [x] **Objetivo**: Añadir a un proyecto de doc_organize la capacidad de clasificar sus documentos
  convertidos en dominios (por reglas, con fallback opcional a IA vía LiteLLM Proxy — ver §2.5),
  generar una ficha de contexto mínima por dominio, copiarlos a una carpeta reorganizada
  `<dominio>/<tipo>/` y construir un sitio MkDocs del proyecto.

- [x] **Módulo(s) o clase(s)**:
  - `src/doc_organize/core/models.py` — nuevos modelos `Context`, `Domain`, `DomainDocument`,
    `DomainClassificationResult` (retorno de `DomainClassificationClient.classify()`, ver "API pública");
    extender `Project` con referencia opcional a contexto (o modelo separado leído bajo demanda).
  - `src/doc_organize/context/` (paquete nuevo) — `context_builder.py`, `domain_classifier.py`
    (Sub-fase A, reglas), `context_registry.py` (persistencia de `context.json`/`domains/`, mismo
    patrón CRUD plano que `ProjectRegistry`/`ScannedFoldersStore` — ver "API pública").
  - `src/doc_organize/context/mkdocs_generator.py` (nuevo) — genera `docs/` + `mkdocs.yml`.
  - `src/doc_organize/ai/domain_classification_client.py` (nuevo, Sub-fase B) — mismo paquete que
    `usage_source.py`/`litellm_usage_client.py`, mismo patrón (Protocol, config-from-env, excepciones
    `UsageSourceError`-sibling propias, `httpx.AsyncClient` con `transport` inyectable). Ver §2.5.
  - `src/doc_organize/core/models.py` — `LiteLLMClassificationConfig` (config propia, no comparte
    credenciales con `LiteLLMUsageConfig` — ISP, ver §2.5).
  - `src/doc_organize/web/routes/projects.py` — nuevas rutas para construir/ver el contexto.
  - `src/doc_organize/web/templates/` — pantalla de dominios y ficha de contexto, incluye toggle
    del flag `ai_classification_enabled`.
  - `tests/unit/test_context_*.py`, `tests/unit/test_domain_classification_client.py` (nuevos, este
    último con `httpx.MockTransport` — sin llamadas de red reales, mismo criterio que los tests
    existentes de `ai/`).
  - `deploy/litellm/{docker-compose.yml,config.yaml.example,.env.example}` (nuevo) +
    `docs/guides/litellm_proxy_setup.md` (nuevo) + entrada en `mkdocs.yml` — ver §2.6.

- [x] **API pública esperada**:
  - `ContextBuilder.build(project: Project) -> Context` — orquesta clasificación (A + B si el flag
    está activo) + copia + fichas.
  - `DomainClassifier.classify(documents: list[ConversionResult]) -> dict[str, list[ConversionResult]]`
    — Sub-fase A: lee `document_json["chunks"]`/`title` (ver §2.4) como señal principal, ruta/extensión
    del original como señal secundaria; reglas configurables. `ConversionResult` es el tipo real ya
    devuelto por `converter.py:convert_document()` (`core/models.py:121`) — no un tipo nuevo.
  - `DomainClassificationClient.classify(chunks: list[str], candidate_domains: list[str]) -> DomainClassificationResult`
    — Sub-fase B, mismo contrato `async`/config-explícita que `UsageSource.get_usage()`; se invoca
    solo para documentos que la Sub-fase A deja por debajo del umbral de confianza (ver §5).
    `DomainClassificationResult` es un modelo Pydantic nuevo (`core/models.py`, ver "Módulo(s)").
  - `ContextRegistry` — CRUD plano de `context.json`/`domains/<slug>/{DOMAIN.md,index.json}` bajo
    `project.root_path`, mismo criterio de persistencia que `ProjectRegistry`/`ScannedFoldersStore`
    (`asyncio.Lock` + escritura atómica `tmp` + `os.replace`, no una base de datos nueva).
  - `MkDocsGenerator.generate(project: Project, context: Context) -> Path`.
  - Rutas web: `POST /projects/{name}/context` (construir/reconstruir), `GET /projects/{name}/context`
    (ver dominios), `GET /projects/{name}/context/{domain}` (ficha).

- [x] **Contrato de entrada**: Proyecto ya escaneado y convertido — documento original + `.md` + `.json`
  ya producidos por `converter/` para cada fichero — y deduplicado (`dedup/`); el clasificador no
  debe procesar duplicados ya marcados. La clasificación lee el `.json` (`chunks` + `title`, §2.4),
  no el `.md`. Reglas de dominio opcionales suministradas por el usuario (JSON).

- [x] **Contrato de salida**: `context.json` + `domains/<slug>/{DOMAIN.md,index.json}` completos
  (sin secciones omitidas — "No aplica" si vacío); `organizado/<dominio>/<tipo>/<stem>/` con **los
  tres ficheros** (original + `.md` + `.json`) copiados, nunca moviendo el origen; `docs/` construible
  con `mkdocs build --strict` sin warnings de enlaces rotos (generado a partir de los `.md` copiados).
  Además (§2.6/§2.7): `deploy/litellm/` funcional (`docker compose up -d` levanta un proxy
  operativo) + `docs/guides/litellm_proxy_setup.md` publicada + docstrings de todo lo nuevo — sin
  esto no se considera cerrada la sesión.

- [x] **Reglas de negocio**:
  - No inventar dominios ni metadatos — clasificar solo por evidencia real (`chunks`/`title` del
    `.json`, ruta y extensión del original).
  - Un documento tiene un dominio primario único; dominios transversales se listan aparte, no duplican el archivo.
  - Reorganizar es **copiar**, nunca mover, salvo opción explícita del usuario — y copia siempre los
    **tres artefactos** del documento (original + `.md` + `.json`), nunca solo uno.
  - Si falta alguno de los tres artefactos (p. ej. `.json` no generado aún), el documento no se
    clasifica y se reporta en `context.json` como pendiente — no se reorganiza a medias.
  - Front matter mínimo del `.md` copiado: `title`, `domain`, `source_path`, `generated_at`.
  - Secciones vacías de `DOMAIN.md` se marcan "*No aplica a este dominio.*", nunca se omiten.
  - **Sub-fase B (IA)**: solo se invoca si `context.json.ai_classification_enabled = true` (default
    `false`, opt-in explícito) y solo para documentos que la Sub-fase A deja por debajo del umbral de
    confianza (§5) — la IA nunca es la primera pasada, siempre fallback.
  - La IA **nunca inventa un dominio fuera del catálogo** ya detectado/confirmado por la Sub-fase A;
    si no encaja en ninguno, se marca `domain: null, status: "sin_clasificar"` — nunca se inventa uno
    nuevo solo con la sugerencia del modelo.
  - Toda llamada de IA pasa por el LiteLLM Proxy ya configurado en el proyecto — nunca una clave de
    proveedor directa (mismo criterio que `ai/litellm_usage_client.py`).
  - **Documentación (§2.7)**: ninguna sub-fase (A o B) se da por completa sin docstring en lo público,
    página MkDocs del arquetipo correspondiente y entrada en `CHANGELOG.md` — mismo criterio que ya
    se aplicó al cerrar `ai/` (sesión 2026-09-07, ver su `TRACEABILITY.md`).

- [x] **Restricciones técnicas**:
  - Todo I/O en `asyncio.to_thread`, coherente con `ProjectRegistry` existente.
  - Contexto y dominios respetan `tenant_id` igual que `Project`.
  - MkDocs pasa de dependencia de *build* del propio repo a posible dependencia *runtime* del
    paquete (necesario para generar el sitio de un proyecto de usuario) — **riesgo a resolver en
    AUDIT_PLAN**, no asumir sin más.
  - Sin romper el layout plano existente de `root_path` (`project.json`, `cache.db`,
    `scanned_folders.json` siguen donde están).
  - **Sub-fase B**: `DomainClassificationClient` sigue el mismo patrón que `LiteLLMUsageClient`/
    `GitHubCopilotUsageClient` (§2.5) — config propia vía `*_config_from_env()`, sin lectura implícita
    del entorno, excepciones dedicadas, tests con `httpx.MockTransport` (sin red real). No añade
    dependencias nuevas de SDK: llamadas HTTP directas al proxy OpenAI-compatible con `httpx`, igual
    que los clientes de `ai/` ya existentes.
  - **§2.6 (Docker)**: Docker + Docker Compose pasan a ser **prerequisito nuevo del entorno de
    desarrollo** — hasta ahora doc_organize es Python puro, sin ninguna dependencia de contenedores.
    `pytest`/CI del repo **no** deben depender de que Docker esté disponible salvo que la decisión
    abierta §5.2-7 (integrar en CI) se resuelva explícitamente a favor.

- [x] **Motores o formatos afectados**: Markdown, JSON (front matter + índices), MkDocs (Material,
  igual que el resto del repo); LiteLLM Proxy (JSON/salida estructurada, Sub-fase B); Docker/Docker
  Compose (infraestructura de despliegue local del proxy, §2.6).

- [x] **¿Hay archivos relevantes existentes?**: Sí —
  `src/doc_organize/core/models.py` (clase `Project`), `src/doc_organize/projects/project_registry.py`,
  `src/doc_organize/projects/scanned_folders_store.py` (patrón de store plano a imitar),
  `src/doc_organize/converter/` (fuente de los Markdown/JSON a clasificar),
  `src/doc_organize/dedup/` (debe ejecutarse antes de clasificar), `mkdocs.yml` del propio repo
  (referencia de configuración Material), `doc_calidad/.ai/*` (solo lectura, inspiración de §2),
  `src/doc_organize/ai/{usage_source,litellm_usage_client,github_copilot_usage_client}.py` +
  [`docs/functional/ai_usage_monitoring.md`](../../../docs/functional/ai_usage_monitoring.md)
  (patrón arquitectónico a imitar para `DomainClassificationClient`, ver §2.5 — no es código a
  reutilizar directamente, solo el patrón); `docs/guides/{installation,quick_start}.md` (patrón de
  guía a imitar para `litellm_proxy_setup.md`, §2.6). **No existente y a crear** (verificado, gap
  real): ninguna infraestructura Docker/LiteLLM en el repo hoy.

## 5. Decisiones

### 5.1 Ya resueltas (2026-09-08)

- ✅ **Método de clasificación**: híbrido, un solo `/new-feature` con dos sub-fases — A) reglas sobre
  `.json`/`chunks` (obligatoria), B) IA vía LiteLLM Proxy como fallback tras flag (opcional en
  runtime, ver §2.5).
- ✅ **Infraestructura de IA**: reutilizar el mismo LiteLLM Proxy ya desplegado para
  `src/doc_organize/ai/`, con config propia (`LiteLLMClassificationConfig`) por ISP.
- ✅ **Fuente de clasificación**: `.json` (`chunks`), no `.md` — ver §2.4.
- ✅ **Carpeta destino**: configurable por proyecto (`context.json.output_folder_name`), default
  `"organizado/"`.
- ✅ **Alcance de "dominio"**: híbrido — si el usuario predefine un catálogo de dominios en
  `context.json`, el clasificador solo elige entre esos (no crea dominios nuevos); si no predefine
  ninguno, se descubren automáticamente del contenido escaneado (heurística ruta/palabras clave).
- ✅ **Umbral de confianza Sub-fase A → B**: score numérico (`context.json.ai_fallback_threshold`,
  configurable, default `~0.5`) calculado por señales coincidentes en `DomainClassifier` — por debajo
  del umbral se dispara la Sub-fase B.

### 5.2 Resueltas con valores por defecto (ajustables sin replanificar, decisión de implementación)

- **MkDocs runtime**: extra opcional `pyproject.toml` (`doc_organize[docs]`), mismo patrón que los
  extras ya existentes (`ai`, `ocr-gpu`, `av`) — no se fuerza como dependencia dura del paquete.
- **Presupuesto/rate-limit Sub-fase B**: solo visibilidad vía `LiteLLMUsageClient.get_usage()`
  existente, sin bloqueo — mismo criterio que el resto de `ai/` hoy ("❌ No calcula presupuestos ni
  bloquea acceso"). Un límite duro queda fuera de alcance de este ciclo.
- **Alias de modelo**: configurable por proyecto (`context.json.ai_classification_model`), con un
  valor por defecto razonable en código si no se especifica (a fijar en IMPLEMENT).
- **Alcance del `docker-compose.yml`**: solo conveniencia de desarrollo local documentada — no se
  integra en CI en este ciclo (evita ampliar el alcance a infraestructura de pipeline).
- **`config.yaml.example`**: plantilla con un alias de ejemplo comentado (sugerencia de modelo
  económico), no un proveedor fijo obligatorio — cada despliegue lo adapta a su propia cuenta.

## 6. Ciclo `/new-feature` — PLAN / AUDIT_PLAN (2026-09-08)

Ver desarrollo completo en el propio hilo de la sesión; resumen de veredicto: **GO_CONDICIONAL**,
IMPLEMENT por capas (Level 1: modelos/excepciones/paquete `context/` + Sub-fase A; Level 2: rutas
web/plantillas/MkDocsGenerator; Level 3: Sub-fase B + `deploy/litellm/` + guía).

## 7. Siguiente paso

Copiar la sección 4 (o el documento completo) como entrada de `/new-feature` en una sesión nueva.
La fase PLAN debe primero resolver §5 antes de tocar código (regla de `new-feature.md`: "si falta
algún campo, DETENTE y aclara").
