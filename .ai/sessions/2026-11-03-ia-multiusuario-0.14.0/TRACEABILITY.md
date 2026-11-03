# TRACEABILITY: Resumen de Sesión

## Sesión
- **Fecha**: 2026-11-03
- **Tipo**: `feature`
- **Rama**: `develop`
- **Estado**: ✅ COMPLETADA (sin commit; pendiente de revisión del usuario)

## Objetivo
Hacer la Sub-fase B de `ContextBuilder` y los clientes de `doc_organize.ai` seguros para consumidores multiusuario
(doc_organize_web, peticiones de la Fase 8, huecos G33–G36): parada ante clave rechazada, reintentos y presupuesto,
recuento de lo hecho, muestra del borrador sin carpetas por encima de la raíz y la clave fuera de la URL del cliente de
uso. Release 0.14.0 (MINOR).

## Cambios Ejecutados

### ✅ 1. L-3a — parada ante auth y errores de conexión seguidos
**Archivo(s)**: `src/doc_organize/context/context_builder.py`, `src/doc_organize/core/models.py`
**Descripción**: `_AiRun` privado (compartido por los dos modos) con recuentos, racha de errores de conexión y
motivo de parada. Un `*AuthError` para en el acto; `build(ai_max_failures=)` para tras N errores de conexión seguidos.
Pendientes sin leer ni enviar, pero siguen emitiendo progreso (y el `cancel_token`). `Context.ai_classification_stopped`.
**Status**: hecho y probado (incluye 1 petición exacta con el cliente real + `MockTransport`, en los dos modos).

### ✅ 2. L-3b — reintentos y presupuesto
**Archivo(s)**: `src/doc_organize/ai/_http_client_base.py`, los 5 clientes de `ai/`, `core/models.py`
**Descripción**: `retries`/`retry_backoff_s` en las 5 `*Config` (decisión: en la config, no en el constructor de cada
cliente, porque la web ya construye las configs). Solo `httpx.TransportError`; nunca HTTP. `build(ai_max_documents=)`.
**Status**: hecho y probado.

### ✅ 3. L-3c — recuentos en `Context`
**Descripción**: `ai_documents_sent/_classified/_failed`; `sent = classified + failed + enviados sin asignación`.

### ✅ 4. L-3d — muestra relativa a la raíz
**Archivo(s)**: `src/doc_organize/context/taxonomy_manifest_sampler.py`
**Descripción**: `select_document_sample(roots=)` usando `relative_source_path` (G23); `""` en la raíz o fuera de toda
raíz; un `source_path` relativo se toma tal cual (sin `..`).

### ✅ 5. L-3e — la clave fuera de la URL
**Archivo(s)**: `src/doc_organize/ai/litellm_usage_client.py`
**Descripción**: verificado en el código de LiteLLM (`info_key_fn`, rama main 2026-11-03):
`key = key or user_api_key_dict.api_key`. Sin `key` o con la propia, no se envía `key=`. Con otra se envía y se
documenta el riesgo (recomendado el hash SHA-256).

---

## Impacto

### Código
- **Archivos modificados/creados**: 11 de `src/`, 3 tests nuevos/ampliados + 1 nuevo de reintentos, docs (`api/context.md`,
  `api/ai_usage_monitoring.md`, `api/publica.md`), `CHANGELOG.md`, `pyproject.toml` (0.14.0).
- **Cambios funcionales**: sí (ver Compatibilidad).

### Compatibilidad
- **BREAKING**: ninguno de firma. Cambios de comportamiento documentados: 401/403 para la Sub-fase B en el acto;
  `get_usage()` sin `?key=` con la clave propia. Un test existente
  (`test_get_usage_returns_spend_from_key_info`) afirmaba la fuga y se corrigió.
- **NO BREAKING**: todo lo demás es opcional y keyword-only; `context.json` antiguo se lee con valores por defecto.

---

## Verificación
```
python -m ruff check src tests      -> All checks passed!
python -m mypy src                  -> Success: no issues found in 94 source files
python -m pytest                    -> 1141 passed, 2 skipped (suite completa, antes del último test añadido)
pytest (módulos afectados)          -> 103 passed (tras el ajuste del aviso de parada)
zensical build --strict             -> No issues found
```

## Directrices para Futuras IAs
- **[context/ai]**: el estado de la Sub-fase B vive en `_AiRun` (`context_builder.py`); cualquier modo nuevo de
  clasificación por IA debe llamar a `may_send()` antes de `client.classify()` y a `record_result`/`record_failure` después.
- **[ai/seguridad]**: `httpx` registra cada URL en INFO; nunca pongas secretos en `params`/URL. El test de regresión
  captura logs en DEBUG (`test_get_usage_never_logs_the_virtual_key`, `test_secret_never_appears_in_logs_or_messages`).
- **[ai/reintentos]**: solo `httpx.TransportError` se reintenta en `AiHttpClientBase._request`; una respuesta HTTP nunca.
- **[web]**: `doc_organize.web` (congelada) no se tocó; no pasa `roots` ni los límites nuevos.

## Veredicto
CLOSED (pendiente de commit/PR a petición del usuario).
