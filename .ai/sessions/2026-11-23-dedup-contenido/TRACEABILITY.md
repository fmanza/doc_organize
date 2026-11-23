# TRACEABILITY

## Session metadata
- id: 2026-11-23-dedup-contenido
- fecha: 2026-11-22 / 2026-11-23
- rama: feat/2.2.0-dedup-contenido → develop → main
- skill: new_feature (entrega 2 del plan de la web; PLAN y AUDIT_PLAN en la conversación, sin fichero de sesión) +
  version_closure
- fase: IMPLEMENT + AUDIT_CODE + VERSION

## Prompt issued
Incorporar IA a la búsqueda de duplicados (aproximación por contenido, con `BAAI/bge-m3` según
`deteccion_duplicados_local.md`), con configuración de IA independiente para duplicados y que la prueba de un modelo
diga qué modelo contestó. Plan en tres entregas: web 2.1.1 (incidencias) → librería 2.2.0 → web 2.2.0. Decisión del
mantenedor: la búsqueda por contenido es la misma antes y después de convertir, y lo convertido se **mueve** con el
descartado, nunca se borra.

## Context supplied
- `deteccion_duplicados_local.md` (embeddings por bloques, umbral, contención).
- Plan y AUDIT_PLAN de la sesión (no se guardaron como ficheros: esta trazabilidad los reconstruye desde los PR).

## AI output summary
- `doc_organize.dedup.content` (nuevo): `ContentDuplicateFinder` (`find(documents, semantic=...)`), mismo contenido
  sin IA (texto normalizado) y contenido parecido con embeddings por bloques (800 palabras, solape 100), vecinos por
  documento, similitud bloque a bloque en los dos sentidos (contención) y Jaccard de trozos de 5 palabras. Grupos
  voraces completos (sin cadenas A~B~C). `exclude_from_context` para el modo `copy`.
- Tarea de IA `dedup` (`AiTask`, `AI_TASKS`, `EMBEDDING_TASKS`) con modelo y clave propios; sin modelo propio,
  `AiConfigurationError`. `DuplicateReason.SAME_CONTENT` y `SEMANTIC_CONTENT_MATCH`; `DuplicateGroup.similarity`,
  `lexical_similarity`, `contained`.
- `move_group`/`resolve_duplicates(conversions=, conversion_dir=)`: el `.md`, el `.json` y las imágenes del descartado
  van a `duplicados/Conversión/` (`layout.duplicate_conversions_dir`, regla L-4). Las imágenes se mueven fichero a
  fichero sin seguir enlaces (en POSIX `_transfer_nofollow` solo mueve ficheros normales: el CI de Linux lo detectó).
- `LlmClient.embed(task=)`, `embed_detailed()` → `EmbeddingResult`; `LlmResult.served_model`. `EmbeddingIndex` con numpy
  (`matrix()`), mismo formato en disco. `check_environment` prueba `dedup` y avisa si el modelo corta antes de ~1.500
  palabras; `EnvironmentCheck.model`, `served_model`, `dimension`.
- `numpy>=1.26` directa; alias `doc-organize-dedup` (`ollama/bge-m3`, `num_ctx: 8192`) en el ejemplo de LiteLLM.
- Docs: guía `docs/guides/duplicados_por_contenido.md`, `docs/api/dedup.md`, `litellm_proxy_setup.md`, `nav`,
  CHANGELOG, COMPATIBILITY.

## Artefactos generados
| Artefacto | Ruta | Estado |
|---|---|---|
| IMPLEMENT | src/doc_organize/dedup/content.py, dedup/deduplication.py, projects/layout.py, ai/llm_client.py, ai/embeddings.py, diagnostics.py, core/models.py, tests/unit/test_content_dedup.py | fusionado (#101) |
| Release | https://github.com/fmanza/doc_organize/releases/tag/v2.2.0 | publicada |

## Directrices para Futuras IAs
- **[dedup/contenido]**: el umbral 0,90 y los bloques de 800 palabras solo están probados con vectores sintéticos;
  calibrar con `bge-m3` y documentos reales antes de cambiar los valores por defecto.
- **[dedup/mover]**: en POSIX, `_transfer_nofollow` no mueve carpetas; para mover un árbol, recorrerlo fichero a
  fichero y quitar después las carpetas vacías (`_remove_empty_dirs`).
- **[release]**: las notas de la release se completan con la tabla de SHA-256 y la URL del wheel, y los enlaces a
  `docs/` como URL absoluta a la etiqueta (en la 2.2.0 se hizo en el cierre, no al publicar).

## VERSION (2026-11-23)

- PR #101 (`feat(dedup)`) y #102 (`release: v2.2.0`) fusionados en `develop` con squash; CI de `develop` en verde en
  `4222d8f`; `main` por fast-forward a `4222d8f`; etiqueta `v2.2.0`; `release.yml` en verde.
- `pyproject.toml` 2.2.0, CHANGELOG `[2.2.0]`, COMPATIBILITY: 2.2.0 activa y 2.1.0 EOL.
- Artefactos: `doc_organize-2.2.0-py3-none-any.whl` (`eefb32fcb57613da7c78a6a5974c1d2619899f05f7a728898a1bb38570cc8c86`)
  y `doc_organize-2.2.0.tar.gz` (`de21a0d7f831a56df400dcb7fced46b55d1f6fabf217b2641a69a9cb459b6f2c`), añadidos a las
  notas de la release en el cierre, con el enlace de la guía corregido a URL absoluta.
- doc_organize_web 2.2.0 la fija por ese wheel y su SHA-256 (G45 de la web resuelto).

## Veredicto final
Veredicto: CLOSED
Pendientes al cierre:
- Calibrar el umbral y el tamaño de bloque de «contenido parecido» con `bge-m3` real.
- En 3.0: retirar Copilot (ver `2026-11-22-copilot-obsoleto`).
