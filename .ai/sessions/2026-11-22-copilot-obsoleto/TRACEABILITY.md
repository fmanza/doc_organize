# TRACEABILITY

## Session metadata
- id: 2026-11-22-copilot-obsoleto
- fecha: 2026-11-22
- rama: feature/2.1-copilot-deprecation
- skill: new_feature (parte L1 del plan de la web `doc_organize_web/.ai/sessions/2026-11-22-ia-uso-copilot/PLAN.md`)
- fase: IMPLEMENT + AUDIT_CODE + VERSION (PLAN y AUDIT_PLAN en la sesión de la web)

## Prompt issued
«En configuración de la IA ya no es necesario el Uso de GitHub Copilot, todo se gestionará sobre LiteLLM.» Decisión
D1 del mantenedor: obsoleto en 2.1, fuera en 3.0.

## Context supplied
- Plan de la web (F1/F2) y decisiones del mantenedor (A2: el proxy no manda `x-litellm-response-cost` → sin L2).

## AI output summary
- `GitHubCopilotUsageConfig` (`model_post_init`), `GitHubCopilotUsageClient.__init__` y
  `github_copilot_usage_config_from_env()` emiten `DeprecationWarning` con `COPILOT_DEPRECATION_MESSAGE`
  (`doc_organize.core.models`). Docstrings con sección `Deprecated`.
- Tests: los de Copilot silencian el aviso (`pytestmark`), y `test_copilot_api_is_deprecated` comprueba los tres puntos.
  Pasan con `-W error::DeprecationWarning`.
- Docs: aviso en `docs/api/ai_usage_monitoring.md` y `docs/functional/ai_usage_monitoring.md`; guía nueva
  `docs/guides/migracion_3_0.md` («Hacia 3.0») en el `nav`; CHANGELOG `[Unreleased]` → `Deprecated`.
- L2 (coste por llamada con `x-litellm-response-cost`) **descartada**: el proxy del mantenedor no manda la cabecera.
- Verificado: `ruff check`, `ruff format --check` (se deshizo el formato de `diagnostics.py`, ajeno al cambio), `mypy`,
  `pytest` completo (1362 passed, 8 skipped) y `zensical build --strict`.
- Sin subir la versión (queda para el cierre de 2.1.0) y sin commit.

## Artefactos generados
| Artefacto | Ruta | Estado |
|---|---|---|
| IMPLEMENT | src/doc_organize/core/models.py, src/doc_organize/ai/github_copilot_usage_client.py, tests/unit/test_github_copilot_usage_client.py, tests/unit/test_ai_usage_source.py, docs/, zensical.toml, CHANGELOG.md | completado, sin commit |

## Directrices para Futuras IAs
- **[ai/copilot]**: obsoleto desde 2.1.0; en 3.0 se borran `github_copilot_usage_client.py`, `GitHubCopilotUsageConfig`,
  `COPILOT_DEPRECATION_MESSAGE`, `UsageSourceName.GITHUB_COPILOT` y sus tests y docs, y se actualiza
  `docs/guides/migracion_3_0.md`.
- **[repo]**: los ficheros del repo usan CRLF; al editar con scripts, conservarlo.
- **[release]**: `main` avanza por fast-forward (`git push origin <sha>:main`) al commit `release:` de `develop` con su
  CI en verde; GitHub avisa «Bypassed rule violations» por la excepción de administrador, es lo previsto. La etiqueta
  va sobre ese commit y `release.yml` publica wheel, sdist y `.sha256`; las notas se completan después con la tabla de
  SHA-256 y la URL del wheel (`gh release edit --notes-file`), con los enlaces a `docs/` como URL absoluta a la etiqueta.

## VERSION (2026-11-22)

- PR #98 (`feat(ai)`) y #99 (`release: v2.1.0`) fusionados en `develop` con squash; CI de `develop` en verde en
  `6a2d4f4`; `main` por fast-forward a `6a2d4f4`; etiqueta `v2.1.0`; `release.yml` en verde.
- `pyproject.toml` 2.1.0, CHANGELOG `[2.1.0] - 2026-11-22`, COMPATIBILITY: 2.1.0 activa y 2.0.1 EOL.
- Artefactos: `doc_organize-2.1.0-py3-none-any.whl` (`77bd1e2319ea18e85f25728237b3d2d731a61e430bda4d4c0d5254bd436608ac`)
  y `doc_organize-2.1.0.tar.gz` (`65d28e31d955507f60787a99056bc6bfd40783cdabf6c7ed6b8f1b9675267ea2`), en las notas
  de la release.
- doc_organize_web 2.1.0 sigue con doc_organize 2.0.1 (este cambio solo marca Copilot como obsoleto).

## Veredicto final
Veredicto: CLOSED
Pendientes al cierre:
- Ninguno. En 3.0: retirar Copilot (ver Directrices).
