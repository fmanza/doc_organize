# TRACEABILITY: Resumen de Sesión

## Sesión
- **Fecha**: 2026-09-10 / 2026-09-11
- **Tipo**: `audit` → `feature`
- **Rama**: `develop`
- **Estado**: EN CURSO (implementación y auditoría completas; **sin commitear todavía** — pendiente de confirmación del usuario)

## Objetivo
Auditoría (`/audit-code`) de toda la superficie de parametrización de la aplicación (variables de
entorno `DOC_ORGANIZE_*`, constantes de `core/constants.py`, ficheros editados a mano) para detectar
qué falta exponer en la UI web. La auditoría encontró 3 huecos reales: (1) las 5 familias de
credenciales de IA solo eran configurables editando `.env` a mano; (2) `taxonomy_manifest.md` por
proyecto solo se podía crear/editar fuera de la aplicación, aunque el endpoint de borrador por IA ya
existía; (3) la biblioteca de plantillas de `TaxonomyTemplateRegistry` no tenía ningún CRUD web. Tras
aprobación explícita del usuario, se pasó a `/new-feature` para diseñar e implementar el cierre de
los 3 huecos.

## Cambios Ejecutados

### ✅ 1. Auditoría de parametrización + correcciones de documentación obsoleta

**Archivo(s)**: `.env.example`, `docs/guides/litellm_proxy_setup.md`
**Descripción**: Inventario completo de env vars/constantes/ficheros manuales, clasificados en
funcional vs. seguridad interna (con justificación explícita de por qué `SCRYPT_*`/`LOGIN_*`/
`SESSION_LIFETIME_HOURS`/credenciales admin NO se exponen). Durante la auditoría se detectaron y
corrigieron in situ (no se borraron) 2 afirmaciones obsoletas: `.env.example` documentaba 4 variables
(`DOC_ORGANIZE_CACHE_DB_PATH`/`_OUTPUT_DIR`/`_WEB_HOST`/`_WEB_PORT`) que el código nunca lee (son
solo flags de CLI); y ni `.env.example` ni la guía de LiteLLM documentaban
`DOC_ORGANIZE_LITELLM_TAXONOMY_MANIFEST_DRAFT_*`, obligatorias para un endpoint ya en producción. Un
hallazgo inicial de la propia auditoría ("`_BUILTIN_TEMPLATES_DIR` no existe") resultó ser un error
de comprobación (ruta equivocada: `web/routes/` en vez de `context/`) — la carpeta sí existe, con 2
plantillas de ejemplo reales (`calidad`, `sgi-iso27001`); corregido en conversación al detectarlo.
**Status**: ✅ Completo (sin commitear)

### ✅ 2. Almacén de secretos cifrado + panel `/admin/configuracion-ia`

**Archivo(s)**: `auth/secrets_cipher.py` (nuevo), `auth/instance_secrets_store.py` (nuevo),
`web/ai_settings_config.py` (nuevo), `web/routes/ai_settings.py` (nuevo),
`web/templates/ai_settings.html.j2` (nuevo), `ai/*.py` (5 clientes, función nueva
`*_config_from_store_or_env()` en cada uno, sin tocar `*_config_from_env()`), `web/dependencies.py`,
`web/routes/context.py`, `web/app.py`, `pyproject.toml`
**Descripción**: Nueva tabla `instance_secrets` en el mismo `auth.db` de `AuthStore` (SRP: clase
propia, mismo fichero físico). Campos secretos (`virtual_key`/PAT) cifrados con Fernet, clave maestra
`DOC_ORGANIZE_SECRETS_KEY` (mismo patrón que `LITELLM_SALT_KEY`, documentado ya en
`litellm_proxy_setup.md`); sin esa clave, el panel sigue funcionando en modo "solo campos
no-secretos". Precedencia store > `.env` > sin configurar, resuelta en funciones nuevas que
complementan (no sustituyen) las `*_config_from_env()` existentes — ningún despliegue que ya
configura por `.env` se rompe. `cryptography` añadida solo al extra `web` (import perezoso dentro de
`auth`, para no forzarla en instalaciones `[ai]`/base que ya importaban `doc_organize.auth`
indirectamente).
**Status**: ✅ Completo (sin commitear)

### ✅ 3. CRUD de plantillas de taxonomía + guardado de `taxonomy_manifest.md`

**Archivo(s)**: `context/taxonomy_template_registry.py` (+`save_template`/`delete_template`),
`context/taxonomy_manifest.py` (+`save_taxonomy_manifest`), `web/routes/context.py` (endpoints
`GET`/`PUT`/`DELETE /api/taxonomy-templates/{name}`, `PUT .../context/taxonomy-manifest`, página
`/admin/plantillas-taxonomia`), `web/templates/taxonomy_templates_admin.html.j2` (nuevo),
`web/templates/_example_modal_macros.html.j2` (nuevo, modal "Ver ejemplo" reutilizable — primer uso
de ese patrón para contenido informativo, no de confirmación), `web/templates/context.html.j2`
(sección "Manifiesto de taxonomía": Proponer con IA → revisar/editar → Guardar; enlace roto
`/docs/guides/...` sustituido por `/admin/configuracion-ia`)
**Descripción**: Cierra el hueco explícito que documentaba el propio docstring de
`draft_taxonomy_manifest`: el borrador generado por IA ya no se pierde si no se copia a mano — un
botón nuevo lo persiste vía `PUT`, con el mismo lock de operación por proyecto que usan
escaneo/dedup/build. Las plantillas nunca se editan directamente si son empaquetadas (`save_template`
solo escribe en `templates_dir` de usuario, igual que ya hacía `load_template` para la precedencia).
Verificado explícitamente que un slug malicioso vía estos endpoints nuevos no puede escapar de
`project.root_path` al reorganizar — la sanitización ya existente en
`DomainClassifier`/`MaterialTypeClassifier` (`_normalize_candidate_domains`/`_normalize`, AUDIT_CODE
sesión 2026-09-08) se aplica de forma uniforme sea cual sea el origen del slug.
**Status**: ✅ Completo (sin commitear)

### ✅ 4. Hallazgos menores de la auditoría + verificación visual

**Archivo(s)**: `web/routes/{admin,scan,scan_errors}.py`,
`web/templates/{admin_roles,admin_users,project_selector,scan_errors,folder_selector}.html.j2`
**Descripción**: Contador de reintentos muestra `n/MAX_AUTO_ERROR_RETRIES` (antes solo un bool);
`SUPPORTED_EXTENSIONS` visible como tooltip junto al selector de formatos; `maxlength`+texto de ayuda
en los campos de nombre de proyecto/usuario/rol. Verificado en navegador real (Playwright, entorno
aislado en el scratchpad de la sesión, sin tocar datos reales) que las 3 páginas nuevas/modificadas
renderizan sin errores de consola y que los botones/modales interactivos funcionan.
**Status**: ✅ Completo (sin commitear)

### ✅ 5. AUDIT_CODE post-implementación + 3 correcciones

**Archivo(s)**: `web/routes/ai_settings.py`, `web/ai_settings_config.py`,
`auth/instance_secrets_store.py`, `web/routes/context.py`
**Descripción**: Auditoría propia de todo lo anterior. Verificado explícitamente (no solo asumido)
que el path traversal vía slug de taxonomía NO es explotable (ver punto 3). Encontrados y corregidos
3 problemas reales:
(a) inconsistencia de 3 bandas en cómo se trataba un campo guardado como cadena vacía —
`_field_response` lo mostraba como "guardado" mientras que `is_family_configured()`/
`*_config_from_store_or_env()` ya lo trataban como no configurado; ahora una cadena vacía nunca se
persiste (se trata como borrado, igual que `null`);
(b) `context_build_websocket` retenía la conexión a `auth.db` y el cliente HTTP de IA abiertos
durante todo `reorganize()`+`mkdocs build`, no solo durante la clasificación — acotado a la sección
que de verdad los necesita;
(c) `masked_hint` podía mostrar un secreto de ≤4 caracteres completo bajo la apariencia de estar
enmascarado — ahora muestra `"***"` en ese caso.
También se sustituyó un `assert` de invariante en `InstanceSecretsStore.get()` (se pierde bajo
`python -O`) por una excepción de dominio explícita.
**Status**: ✅ Completo (sin commitear)

---

## Impacto

### Código
- **Archivos nuevos** (12): `auth/{instance_secrets_store,secrets_cipher}.py`,
  `web/ai_settings_config.py`, `web/routes/ai_settings.py`,
  `web/templates/{ai_settings,taxonomy_templates_admin,_example_modal_macros}.html.j2`,
  `docs/functional/ai_settings.md`, `tests/unit/test_{ai_settings_config,instance_secrets_store,
  secrets_cipher,web_ai_settings}.py`
- **Archivos modificados** (32): ver `git status`; incluye los 5 clientes de `ai/`, `context/
  {taxonomy_manifest,taxonomy_template_registry,__init__}.py`, `web/routes/{context,admin,scan,
  scan_errors,app}.py`, `web/dependencies.py`, 8 plantillas Jinja, `pyproject.toml`, `.env.example`,
  `docs/guides/litellm_proxy_setup.md`, `mkdocs.yml`, 4 ficheros de test existentes ampliados.
- **Cambios funcionales**: sí — 2 páginas admin nuevas, 5 endpoints nuevos (templates CRUD +
  guardado de manifiesto), 5 funciones `*_config_from_store_or_env()` nuevas, 1 tabla SQLite nueva.
  Ningún endpoint/función existente cambia de comportamiento por defecto.

### Compatibilidad
- **BREAKING**: Ninguno.
- **NO BREAKING**: Todo aditivo. Un despliegue que ya configura las 5 familias de IA por `.env` sigue
  funcionando exactamente igual sin tocar los paneles nuevos (precedencia store > env, sin fila en
  `instance_secrets` = comportamiento idéntico al de antes de esta sesión).

---

## Verificación

Ejecutado en vivo, 2026-09-11:
```
python -m ruff check src tests            → All checks passed!
python -m ruff format --check <archivos tocados>  → sin diferencias
python -m mypy src                        → Success: no issues found in 74 source files
python -m pytest -q --no-cov              → 793 passed (215.60s)
mkdocs build --strict                     → Documentation built in ~2.5s, sin errores
                                             (único aviso: deprecación de Material for MkDocs
                                             sobre MkDocs 2.0 — ruido del tema, no del build)
```
Verificación visual adicional: servidor arrancado contra un directorio temporal aislado (scratchpad
de la sesión, nunca `~/.doc_organize/` real) y recorrido con Playwright/Chromium real — las 3
páginas nuevas/modificadas renderizan correctamente, 0 errores de consola JS, botones/modales
interactivos verificados (añadir fila de dominio, abrir/cerrar modal "Ver ejemplo", botón "Proponer
con IA" correctamente deshabilitado sin LiteLLM configurado).

**Incidente durante la propia verificación**: la primera ejecución completa de la suite (antes de
aislar `auth_db_path` en `test_web_context.py`) tocó el `~/.doc_organize/auth.db` **real** del
desarrollador — el nuevo `InstanceSecretsStore` se abre ahora, sin querer, en rutas de `context.py`
que no pasan por ninguna comprobación de admin/loopback, rompiendo la invariante implícita de que
"en modo loopback/sin auth, nada toca `auth.db`". Se detectó por el `mtime` del fichero real, se
revirtió la tabla `instance_secrets` añadida (0 filas, sin pérdida de datos) y se corrigieron ~50
llamadas a `create_app()` en `test_web_context.py` para pasar `auth_db_path` explícito. Re-verificado
que el `mtime` del fichero real no vuelve a cambiar tras la re-ejecución completa de la suite.

---

## Riesgos Residuales

| Riesgo | Mitigación | Status |
|--------|-----------|--------|
| `InstanceSecretsStore.get_all()` hace una `SELECT` por campo (hasta 13 por carga de `/admin/configuracion-ia`) en vez de una consulta por lote | Volumen bajo (página admin, no en un hot path); documentado en AUDIT_CODE | Abierto |
| `context_page`/`build_context` ahora abren una conexión SQLite a `auth.db` en cada petición (antes era una comprobación pura en memoria) | Coherente con el patrón ya usado por `/admin/roles`/`/admin/users`; SQLite local, overhead <10ms | Aceptado |
| Solo 1 de las 5 funciones `*_config_from_store_or_env()` tiene test unitario directo de precedencia store/env (las otras 4 solo se ejercitan indirectamente) | Documentado como pendiente en VERSION | Abierto |
| Sin test end-to-end que compruebe que un valor guardado en el panel llega de verdad a una llamada de clasificación simulada durante `build_context`/`context_build_websocket` | Documentado como pendiente en VERSION | Abierto |
| `masked_hint` también revela los últimos 4 caracteres de un secreto que viene de `.env` (no solo de los guardados desde el panel) — aceptable con el alcance actual (config de instancia, no por tenant) | Decisión documentada en AUDIT_CODE; reconsiderar si la config de IA pasa a ser por tenant | Aceptado por ahora |
| `InstanceSecretsStore` no tiene lógica de migración de esquema (a diferencia de `AuthStore._migrate_schema()`) | Aceptable hoy (tabla nueva, sin datos legacy); necesaria si cambian las columnas en el futuro | Abierto |
| Nada de esta sesión está commiteado todavía | Pendiente de confirmación explícita del usuario antes de `git commit` | Abierto |

---

## Siguientes Pasos (Recomendado)
1. Confirmar con el usuario si se commitea ahora (mensaje propuesto en la fase VERSION de esta
   misma sesión) o si quiere revisar el diff primero.
2. Añadir tests unitarios directos de `*_config_from_store_or_env()` para las 4 familias que hoy
   solo se ejercitan indirectamente (`taxonomy_classification`, `taxonomy_manifest_draft`,
   `litellm_usage`, `github_copilot_usage`).
3. Añadir un test end-to-end (con `httpx.MockTransport`) que compruebe que un valor guardado en el
   panel llega de verdad a una llamada de clasificación simulada durante `build_context`.
4. Validar manualmente el panel de configuración IA contra un LiteLLM Proxy real (heredado de
   sesiones anteriores — sigue sin haber validación contra un proxy real, solo mocks).
5. Decidir si `CHANGELOG.md`/`pyproject.toml` (versión) necesitan una pasada de sincronización antes
   de cerrar una release — no tocados en esta sesión.

---

## Directrices para Futuras IAs

- **[patrón]**: La precedencia "config de IA editable desde la UI" es **store > `.env` > sin
  configurar**, resuelta en `*_config_from_store_or_env()` (una función nueva por cliente en
  `doc_organize.ai`, junto a — no en sustitución de — cada `*_config_from_env()` ya existente). Un
  cliente de IA nuevo que necesite lo mismo debe seguir este mismo patrón, no inventar uno distinto.
- **[patrón]**: Un valor vacío (`""`) en `InstanceSecretsStore` **nunca** debe tratarse como
  "configurado" — `update_ai_settings_family()` lo trata como borrado (igual que `null`) antes de
  persistir nada. Si se añade un nuevo punto de escritura al store, debe respetar esta misma regla o
  se reabre la inconsistencia ya corregida en esta sesión (ver AUDIT_CODE).
- **[patrón/gotcha]**: `InstanceSecretsStore`/`AuthStore` comparten el mismo fichero físico
  (`auth.db`) pero son clases independientes (SRP) — **cualquier ruta nueva que abra
  `get_instance_secrets_store(request)` toca `auth.db` incondicionalmente**, incluso en modo
  loopback/sin auth donde antes nada lo tocaba. Si se añade a una ruta que NO es
  `/admin/*`-equivalente, hay que decidir conscientemente si ese acoplamiento es aceptable (lo es
  para `context.py`, porque el propio feature de config de IA lo exige) — y en tests, pasar siempre
  `auth_db_path` explícito a `create_app()` para no tocar el `~/.doc_organize/auth.db` real del
  desarrollador (bug real que ocurrió en esta misma sesión, ver Verificación).
- **[patrón]**: El saneado de slugs de taxonomía (`DomainClassifier._normalize_candidate_domains()`/
  `MaterialTypeClassifier._normalize()`, vía `_slugify()`) se aplica **en el constructor de ambos
  clasificadores**, no en cada llamador — cualquier origen nuevo de slugs (fichero a mano, plantilla,
  API) queda protegido automáticamente contra path traversal sin tener que acordarse de sanearlo en
  el punto de entrada. No dupliques ese saneado en un endpoint nuevo; confía en que el clasificador
  ya lo hace.
- **[patrón]**: Modal reutilizable "Ver ejemplo" (`_example_modal_macros.html.j2`) — mismo esqueleto
  técnico que los modales de confirmación ya existentes (`#confirm-modal`/`#force-confirm-modal`)
  pero para contenido informativo (solo botón "Cerrar", sin "Confirmar"). Usar esta macro para
  cualquier ayuda contextual nueva en vez de duplicar el HTML/JS del modal.
- **[gotcha]**: Antes de asumir que un fichero/carpeta "no existe" durante una auditoría, verificar
  la ruta exacta (`Path(__file__).parent` relativo al módulo que define la constante, no a donde
  "parece lógico" que viva) — un hallazgo de esta misma sesión resultó ser un error de ruta, no un
  hueco real (`_BUILTIN_TEMPLATES_DIR` vive en `context/`, no en `web/routes/`).
- **[decisión]**: Las credenciales de IA (`virtual_key`/PAT) se cifran con Fernet y una clave
  maestra por instalación (`DOC_ORGANIZE_SECRETS_KEY`), nunca se derivan de una contraseña de
  usuario ni se guardan en claro — mismo criterio que `LITELLM_SALT_KEY` del proxy externo. Sin esa
  clave, el panel degrada a "solo campos no-secretos", nunca guarda un secreto sin cifrar como
  fallback silencioso.
- **[decisión]**: `cryptography` se importa de forma perezosa dentro de `auth/secrets_cipher.py`
  (nunca a nivel de módulo) porque solo está declarada en el extra `web`, pero `doc_organize.auth`
  ya se importa desde `doc_organize.ai.*` y desde el CLI (`tenant create`/`user create`) sin ese
  extra instalado. Cualquier dependencia nueva y opcional que se añada a `auth/`/`ai/` debe seguir
  este mismo patrón de import perezoso si no está en las dependencias base.

---

## Veredicto

### 🟡 GO_CONDICIONAL

**Criterios**:
- Las 5 sub-áreas de trabajo (auditoría + 2 fixes de doc, almacén cifrado + panel IA, CRUD de
  plantillas + guardado de manifiesto, hallazgos menores + verificación visual, AUDIT_CODE + 3
  correcciones) completas y verificadas en vivo.
- ruff/ruff format/mypy/pytest/`mkdocs build --strict` todos en verde tras las correcciones.
- Sin cambios breaking.
- **Condición pendiente**: nada de esto está commiteado — el usuario no ha confirmado todavía si
  proceder con el commit propuesto en la fase VERSION.

**Evidencia**:
- Branch: `develop`
- Commits: ninguno todavía (working tree con 32 ficheros modificados + 12 nuevos)
- Tests: `pytest` → 793 passed (150 más que el cierre de la sesión anterior, `2026-09-10`, con 643)

**Sesión abierta**: 2026-09-11 (pendiente de cierre tras decisión de commit)
