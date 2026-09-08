# Organización Documental — Dominios y Contextos

Clasificar los documentos ya convertidos de un proyecto en dominios, copiarlos a
una carpeta reorganizada y generar un sitio MkDocs navegable.

## Objetivo

Sobre un proyecto ya escaneado y convertido, identificar **dominios** (a qué área
temática pertenece cada documento) por reglas — con un fallback opcional por IA —
copiar cada documento (original + `.md` + `.json`) a
`<output_folder_name>/<dominio>/<tipo>/<stem>/` y generar la configuración de un
sitio [MkDocs](https://www.mkdocs.org/) que lo navegue.

## Precondiciones

- El proyecto tiene documentos ya convertidos con éxito (`cache.db` con entradas
  `conversion_status=success`) — ver [Converter](converter.md).
- Extra `doc_organize[context]` instalado (`pyyaml`, para generar `mkdocs.yml`).
- Sub-fase B (opcional): un LiteLLM Proxy desplegado — ver
  [Desplegar un LiteLLM Proxy](../guides/litellm_proxy_setup.md).

## Flujo Principal

```mermaid
sequenceDiagram
    participant Usuario
    participant API as POST /api/projects/{name}/context
    participant Builder as ContextBuilder
    participant RulesA as DomainClassifier (Sub-fase A)
    participant IA as DomainClassificationClient (Sub-fase B)
    participant Reorg as Reorganizer
    participant MkDocs as MkDocsGenerator

    Usuario->>API: construir contexto (catálogo?, IA?)
    API->>Builder: build(documentos, ...)
    Builder->>RulesA: classify(documentos)
    RulesA-->>Builder: clasificados, sin_clasificar
    opt IA activada y hay catálogo
        Builder->>IA: classify(sin_clasificar, catálogo)
        IA-->>Builder: dominio o null (nunca fuera del catálogo)
    end
    Builder-->>API: Context (persistido)
    API->>Reorg: reorganize(context)
    Reorg-->>API: organizado/ poblado
    API->>MkDocs: generate(context)
    MkDocs-->>API: mkdocs.yml + index.md
    API-->>Usuario: dominios, sin_clasificar, reorganized, mkdocs_generated
```

## Reglas de Negocio

| Regla | Descripción |
|---|---|
| **Fuente de clasificación** | El `.json` de conversión (`chunks`/`title`), nunca el `.md` — ya troceado por sección, sin reparsear Markdown |
| **Nunca inventa dominios** | Con catálogo predefinido, un documento solo se asigna a un dominio de ese catálogo — ni las reglas ni la IA crean uno nuevo |
| **IA es fallback, nunca primera pasada** | Sub-fase B solo se intenta con documentos que la Sub-fase A deja por debajo del umbral de confianza, y opt-in explícito (`ai_classification_enabled`, `False` por defecto) |
| **Copiar, nunca mover** | `Reorganizer` copia los tres artefactos (original + `.md` + `.json`); la fuente original nunca se toca |
| **Reconstrucción limpia** | Cada `POST` reconstruye desde cero: dominios/documentos ya no vigentes se eliminan de `context.json` y de `organizado/`, sin copias huérfanas |
| **Estado honesto ante fallo parcial** | Si la reorganización o la generación de MkDocs fallan a mitad, `context.json` persiste `reorganized`/`mkdocs_generated=false` — nunca se reporta éxito falso |
| **Una operación a la vez** | `POST /api/projects/{name}/context` se rechaza con `409` si hay un escaneo, deduplicación u otra construcción de contexto en curso para el mismo proyecto |

## Límites y Restricciones

❌ No pagina los documentos del proyecto — carga todo `cache.db` en memoria (aceptable para el volumen típico de un proyecto; a revisar si se vuelve un cuello de botella)  
❌ Dos documentos distintos con el mismo nombre de fichero (`stem`) en el mismo dominio/tipo se sobrescriben entre sí en `organizado/` — sin desambiguación todavía  
❌ La Sub-fase B nunca se ejecuta en CI de este repo (queda fuera de alcance del despliegue Docker documentado, que es solo para desarrollo local)

## Casos Especiales

- **Documento con algún artefacto incompleto** (original, `.md` o `.json` ausente):
  la Sub-fase A lo manda a "sin clasificar" sin interrumpir el resto del lote;
  si de algún modo llega a `Reorganizer` con un artefacto ausente, se levanta
  `IncompleteConversionArtifactsError` (no se reorganiza a medias).
- **IA activada sin proxy configurado**: `POST` devuelve `400` con un mensaje
  explícito (`DOC_ORGANIZE_LITELLM_CLASSIFICATION_BASE_URL`/`_VIRTUAL_KEY` sin
  definir), no un error genérico.
- **IA sugiere un dominio fuera del catálogo**: se descarta y se trata como "no
  encaja en ninguno" — validado en `DomainClassificationClient`, no solo por
  instrucción al modelo.
- **Fallo de red/autenticación con el proxy** durante la Sub-fase B: el
  documento afectado queda sin clasificar; no interrumpe el resto del lote.

## Criterios de Aceptación

*Pendiente de validación QA*
