# TRACEABILITY

## Session metadata
- id: 2026-11-18-m3b-redaccion
- fecha: 2026-11-18
- rama: `feat/redact-credentials` (desde `develop`, que es v1.6.0 + planes: no hizo falta `support/1.6`)
- skill: new_feature
- fase: IMPLEMENT + AUDIT_CODE de **M3b** (F1, redacción de credenciales) del plan único
  [`../2026-11-17-ai-2.0/PLAN.md`](../2026-11-17-ai-2.0/PLAN.md); D18: publicarla antes de 2.0.0

## Prompt issued
«Empieza con M3b, doc_organize 1.6.1».

## AI output summary
- `doc_organize.security.credentials`: `redact_credentials`, `scan_credentials`, `RedactionResult`,
  `CredentialFinding`, `REDACTED` (`«REDACTADO»`, sin `<`/`>` para que se vea en Markdown) y `CREDENTIAL_RULES`.
  Adaptado de `doc_ia/scripts/redact_secrets.py`, con tres reglas más (AWS, GitHub, `sk-…`) y «clave» como palabra de
  contraseña.
- `ContextBuilder(ai_redact_credentials=True)`: título y texto redactados antes de la Sub-fase B (un eje y manifiesto)
  y del enriquecimiento; las reglas, el idioma y `context.json` usan el texto original. `Context.ai_redact_credentials`
  y `Context.credential_findings` (`DocumentCredentialFindings`: documento y recuento por regla, sin valores).
- `LiteLLMTaxonomyManifestDraftConfig.redact_credentials=True`: la muestra del borrador sale redactada (la web llama al
  cliente sin pasar por `ContextBuilder`).
- `SiteGenerator.generate(redact_credentials=True)` y `SiteResult.credentials_redacted`: páginas de la carpeta
  reorganizada **y títulos del `nav`** redactados antes de publicar.

## Desviaciones del plan
- **Nombres «credentials», no «secrets»**: la guarda `test_library_architecture.py` rechaza cualquier nombre público con
  «secret» (protege contra la vuelta de la autenticación de la web). En lugar de debilitarla, se renombra la API nueva.
  El plan único (F1, G1.3) usa `redact_secrets`/`secret_findings`: hay que actualizarlo.
- Los títulos del `nav` del sitio también se redactan (el plan solo hablaba de las páginas): sin eso, un título con una
  credencial se publicaba.
- Sin rama `support/1.6`: `develop` no tiene nada de 2.0 todavía.

## Pendiente
- **Versión**: el plan dice 1.6.1 (D18), pero M3b añade API pública (funciones, parámetros y campos); con SemVer eso es
  una MINOR (**1.7.0**). Decisión del mantenedor antes de cerrar la versión; el CHANGELOG queda en `Unreleased` y el
  código cita «1.6.1» en docstrings hasta entonces.
- La web tiene que adoptarla (subir el pin y, si se quiere, mostrar `credential_findings`).

## Verificación
- ruff, ruff format, mypy, pytest completo (1042 passed, 8 skipped), doctests del módulo y `zensical build --strict`.
