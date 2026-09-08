# TRACEABILITY: Resumen de Sesión

## Sesión
- **Fecha**: 2026-09-07 (implementación) → cierre/commit 2026-09-08
- **Tipo**: `feature`
- **Rama**: `develop`
- **Estado**: ✅ COMPLETADA

## Objetivo
Dar visibilidad de uso/coste de IA de dos fuentes externas — spend de una virtual key en un
LiteLLM Proxy y consumo de "premium requests" de un plan GitHub Copilot Pro individual — antes de
poder decidir cómo limitar o facturar ese consumo. Sin funcionalidad de inferencia ni proxying:
solo lectura.

## Cambios Ejecutados

### ✅ 1. Paquete `doc_organize.ai` (protocolo + dos clientes de solo lectura)

**Archivo(s)**: `src/doc_organize/ai/usage_source.py`, `src/doc_organize/ai/litellm_usage_client.py`,
`src/doc_organize/ai/github_copilot_usage_client.py`, `src/doc_organize/ai/__init__.py`

**Descripción**: `UsageSource` (Protocol `runtime_checkable`, sin herencia — ISP) define el
contrato común `async get_usage() -> UsageSnapshot`. `LiteLLMUsageClient` consulta `GET /key/info`
del proxy; `GitHubCopilotUsageClient` consulta `GET /users/{username}/settings/billing/premium_request/usage`
de la API oficial de GitHub Billing. Ambos: config explícita vía `*_config_from_env()` (nunca lectura
implícita del entorno dentro del cliente), `httpx.AsyncClient` como context manager async con
`transport` inyectable (tests sin red real), excepciones dedicadas ante 401/403 y errores de red.

**Status**: ✅ Completo

### ✅ 2. Modelos y excepciones de soporte

**Archivo(s)**: `src/doc_organize/core/models.py`, `src/doc_organize/core/exceptions.py`

**Descripción**: Nuevos `UsageSourceName`, `UsageLineItem`, `UsageSnapshot`, `LiteLLMUsageConfig`,
`GitHubCopilotUsageConfig` (Pydantic); nuevas `UsageSourceError` / `UsageSourceAuthError` /
`UsageSourceConnectionError` (jerarquía bajo `DocOrganizeError`).

**Status**: ✅ Completo

### ✅ 3. Configuración y extra opcional

**Archivo(s)**: `pyproject.toml`, `.env.example`

**Descripción**: Nuevo extra `ai` (`httpx>=0.24`) — el paquete no fuerza esta dependencia si no se
usa `doc_organize.ai`. `.env.example` documenta `DOC_ORGANIZE_LITELLM_BASE_URL`,
`DOC_ORGANIZE_LITELLM_VIRTUAL_KEY`, `DOC_ORGANIZE_GITHUB_USERNAME`, `DOC_ORGANIZE_GITHUB_PAT`
(único bloque del fichero que documenta variables leídas explícitamente, no implícitamente).

**Status**: ✅ Completo

### ✅ 4. Documentación

**Archivo(s)**: `docs/functional/ai_usage_monitoring.md`, `docs/api/ai_usage_monitoring.md`,
`mkdocs.yml` (nav), `CHANGELOG.md` ([Unreleased] → Added)

**Descripción**: Arquetipo funcional (objetivo, alcance, flujo Mermaid, reglas de negocio, casos
especiales) + referencia técnica; entradas de navegación añadidas bajo "Funcional" y "API".

**Status**: ✅ Completo

---

## Impacto

### Código
- **Archivos modificados/creados**: ver "Cambios Ejecutados" — 3 módulos nuevos en `ai/`, 5 modelos
  + 3 excepciones nuevos en `core/`, 1 extra nuevo en `pyproject.toml`, 4 variables nuevas en
  `.env.example`, 2 páginas de documentación + nav de `mkdocs.yml`, entrada en `CHANGELOG.md`.
- **Cambios funcionales**: sí — nueva capacidad opcional (extra `ai`), sin tocar rutas web ni flujos
  existentes de scan/dedup/convert. Ningún consumidor (ruta web, CLI) invoca todavía estos clientes;
  quedan como API de librería lista para un futuro dashboard/comando.

### Compatibilidad
- **BREAKING**: Ninguno.
- **NO BREAKING**: Todo aditivo — nuevo paquete, nuevos modelos/excepciones, nuevo extra opcional.

---

## Verificación

```
python -m ruff check src/doc_organize/ai src/doc_organize/core/exceptions.py src/doc_organize/core/models.py \
  tests/unit/test_ai_usage_source.py tests/unit/test_github_copilot_usage_client.py tests/unit/test_litellm_usage_client.py
  → All checks passed!

python -m mypy src/doc_organize/ai src/doc_organize/core/exceptions.py src/doc_organize/core/models.py
  → Success: no issues found in 6 source files

python -m pytest tests/unit/test_ai_usage_source.py tests/unit/test_github_copilot_usage_client.py tests/unit/test_litellm_usage_client.py -q
  → 14 passed

python -m build --wheel
  → Successfully built doc_organize-0.7.0-py3-none-any.whl

mkdocs build --strict
  → Documentation built in 2.47 seconds (sin warnings de enlaces rotos)
```

---

## Riesgos Residuales

| Riesgo | Mitigación | Status |
|--------|-----------|--------|
| Scope exacto de PAT de GitHub que autoriza el endpoint de Billing Usage no está documentado explícitamente por GitHub | Documentado en docstring de `GitHubCopilotUsageClient` y en `ai_usage_monitoring.md`; pendiente de confirmar contra una cuenta real | Abierto |
| Sin consumidor real (ruta web/CLI) todavía — solo API de librería | Fuera de alcance deliberado de esta sesión (ver `ai_usage_monitoring.md` §Alcance) | Aceptado |

---

## Siguientes Pasos (Recomendado)
1. Si se decide exponer esto en la UI (dashboard de coste), diseñarlo como sesión `/new-feature`
   aparte — no reabrir esta.
2. Confirmar empíricamente el scope de PAT de GitHub contra una cuenta real antes de documentarlo
   como definitivo.
3. Ver `.ai/sessions/2026-09-08-organizacion-documental-contextos/00_REQUEST.md` §2.5: el patrón de
   `UsageSource`/config-from-env/excepciones de esta sesión es la plantilla a imitar para el futuro
   `DomainClassificationClient` (Sub-fase B de esa feature) — no reusar código, sí el patrón, y
   reutilizar el mismo LiteLLM Proxy ya configurado aquí.

---

## Directrices para Futuras IAs

- **[arquitectura]**: `doc_organize.ai` es monitorización de uso/coste, no inferencia — no interactúa
  con `chat/completions` de ningún proveedor ni con el endpoint interno de Copilot (términos de uso).
  Cualquier feature futura que sí necesite invocar un modelo (p. ej. clasificación asistida por IA)
  es un cliente nuevo, no una extensión de estos.
- **[patrón]**: `UsageSource` fija el patrón para cualquier cliente externo de solo lectura en este
  repo: `Protocol` `runtime_checkable` sin herencia compartida (ISP), config resuelta explícitamente
  vía una función `*_config_from_env()` dedicada (nunca leída implícitamente dentro del `__init__`
  del cliente), `httpx.AsyncClient` como context manager async con `transport: httpx.AsyncBaseTransport | None`
  inyectable para tests sin red real, y una jerarquía de excepciones propia bajo `DocOrganizeError`
  distinguiendo auth (401/403) de conexión (timeout/red) de "cualquier otro error".
- **[infra]**: Ya existe un LiteLLM Proxy desplegado y accesible — es el canal a reutilizar para
  cualquier llamada de inferencia futura en este proyecto, nunca una clave de proveedor directa
  nueva. `LiteLLMUsageConfig`/`GitHubCopilotUsageConfig` no comparten campos ni credenciales entre sí
  (ISP) — un cliente de inferencia futuro necesita su propia config, aunque apunte a la misma URL.
- **[decisión]**: `UsageLineItem.cost_usd` es `None` en el caso común de Copilot Pro (solo reporta
  coste si hay overage de cuota) — no tratar `None` como error o dato faltante.

---

## Veredicto

### 🟢 COMPLETADA

**Criterios**:
- ruff/mypy/pytest/build/mkdocs --strict en verde (ver "Verificación").
- CHANGELOG.md, docs funcional + API, nav de mkdocs.yml y .env.example ya reflejan la feature.
- Sin cambios breaking, sin consumidor pendiente que bloquee el cierre (deliberadamente fuera de
  alcance).

**Evidencia**:
- Branch: `develop`
- Commits: ver commit de cierre inmediatamente después de este fichero (mismo commit incluye este
  `TRACEABILITY.md`).
- Tests: `pytest tests/unit/test_ai_usage_source.py tests/unit/test_github_copilot_usage_client.py tests/unit/test_litellm_usage_client.py` → 14 passed.

**Sesión cerrada**: 2026-09-08
