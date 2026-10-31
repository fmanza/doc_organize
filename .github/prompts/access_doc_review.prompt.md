# Prompt: access_doc_review — Validación de la documentación de acceso/autenticación

<!--
  Prompt específico de doc_organize (no forma parte del núcleo compartido
  dpss/.github/prompts/). Valida docs/functional/access.md frente al código
  real cada vez que el mecanismo de autenticación (auth/, web/auth.py,
  web/dependencies.py, main.py) cambie.
  Última revisión: 2026-09-11
-->

Verifica que `docs/functional/access.md` describe con exactitud el mecanismo de
acceso implementado en el código — sin fabricar comportamiento, valores por
defecto, endpoints, mensajes de error, flags de CLI ni pasos de despliegue que no
existan en el repositorio. No es una revisión de estilo: es una comprobación de
veracidad, afirmación por afirmación.

---

## Devuelve en este orden

1. PLAN
2. AUDIT_PLAN
3. AUDIT_CODE
4. VERSION

## Fuentes de verdad (el código manda; el documento se corrige, nunca al revés)

| Fichero | Qué debe confirmar |
|---|---|
| `src/doc_organize/web/auth.py` | `AuthMiddleware.dispatch()` (orden real de comprobaciones), `LoginRateLimiter`, `requires_auth()`, `is_loopback()`, `_EXEMPT_PATHS`, `_PASSWORD_CHANGE_EXEMPT`, `_PROTECTED_PREFIXES`, `_WRITE_METHODS`, nombre de la cookie |
| `src/doc_organize/auth/auth_store.py` | Esquema SQL, `create_tenant`/`create_role`/`create_user`/`create_session`/`authenticate`/`change_password`, mensajes de excepción exactos |
| `src/doc_organize/web/dependencies.py` | `require_admin`, `require_project_access`, `get_allowed_scan_roots`, `authorize_project_websocket` (código de cierre WebSocket, criterio 404 vs 403) |
| `src/doc_organize/web/routes/auth.py`, `change_password.py` | Rutas, métodos HTTP, códigos de estado, plantillas usadas |
| `src/doc_organize/core/models.py` | `Tenant`, `Role`, `User`, `Session`, `SecurityConfig` (nombres de campo y valores por defecto exactos) |
| `src/doc_organize/core/constants.py` | `SESSION_LIFETIME_HOURS`, `LOGIN_MAX_ATTEMPTS`, `LOGIN_LOCKOUT_SECONDS`, `DEFAULT_ADMIN_USERNAME`/`PASSWORD`/`ROLE_NAME`, patrones y longitudes máximas (`USERNAME_PATTERN`, `ROLE_NAME_PATTERN`, `TENANT_ID_MAX_LENGTH`, etc.) |
| `src/doc_organize/main.py` (`build_parser`, `_run_tenant_create`, `_run_user_create`, `_run_web`) | Subcomandos `tenant`/`user`/`web`, nombre y default exacto de cada flag (`--host`, `--port`, `--auth-db-path`, `--templates-path`, `--registry-path`) |
| `.env.example` | Que el documento no reintroduzca variables de entorno ya retiradas (p. ej. un bearer token compartido) |
| `tests/unit/test_web_auth.py`, `tests/unit/test_web_admin_routes.py` | Comportamiento observable de referencia (status codes, cookies, 403/404 por rol) que el documento describe como "cómo probar" |
| `docs/functional/admin.md`, `docs/guides/quick_start.md` | Consistencia — el documento no debe contradecir lo que estas dos páginas ya afirman sobre acceso |

## Qué verificar, por sección de `access.md`

- **Definiciones / Modelo de datos**: cada campo, tipo y valor por defecto citado
  existe literalmente en `core/models.py`/`auth_store.py` — localizar con grep,
  nunca dar por bueno de memoria.
- **Flujo de autenticación (mermaid)**: reproduce el orden real de
  `AuthMiddleware.dispatch()` (login CSRF → `requires_auth`/exentas → sesión →
  cambio de contraseña obligatorio → origen de escritura → `require_admin`/
  `require_project_access`). Cualquier paso reordenado o inventado es Nivel 1.
- **Reglas de Negocio**: cada regla debe señalar una consecuencia verificable
  (excepción, código HTTP, constraint SQL) — no una intención de diseño sin
  aplicación real.
- **Cómo ejecutar y probar en local**: cada comando (`tenant create`,
  `user create --tenant`, `web --host --port --auth-db-path`) se ejecuta tal cual
  contra `build_parser()`; los resultados esperados (mensajes impresos, prompts
  interactivos) coinciden con `main.py`.
- **Consideraciones antes de exponer en producción**: no debe describir ningún
  mecanismo de despliegue (Docker, `systemd`, balanceo, terminación TLS propia)
  que no exista en el repositorio — si el repo no lo tiene, el documento debe
  decir explícitamente que no existe, no inventar un procedimiento plausible.
- **Límites y Restricciones / Casos Especiales**: cada ítem debe ser reproducible
  (idealmente con un test existente citado o reproducible a mano).

## Criterios por severidad

### Nivel 1: Crítico
- Un valor por defecto, endpoint, flag de CLI, código HTTP o mensaje de error
  citado que no coincide con el código.
- Un paso del diagrama de flujo que no refleja el orden real de `AuthMiddleware`.
- Cualquier mecanismo de despliegue/producción descrito que no existe en el repo.
- Cualquier variable de entorno o mecanismo de autenticación retirado
  (p. ej. el bearer token compartido) presentado como vigente.

### Nivel 2: Alto
- Comportamiento de seguridad real omitido que un lector necesitaría para no
  exponer el servidor de forma insegura (p. ej. no advertir la ausencia de TLS
  propio, o el alcance real de `LoginRateLimiter` en memoria de proceso).
- Un comando de "cómo probar" que no reproduce el resultado que el documento
  afirma.

### Nivel 3: Recomendado
- Cross-links faltantes hacia `admin.md`/`quick_start.md`/tests.
- Ejemplos adicionales de casos límite no cubiertos.

## Reglas

- No aceptar ninguna afirmación del documento sin localizarla en el código
  citado (archivo + símbolo exacto, no "en algún sitio del módulo auth").
- Señalar explícitamente cualquier frase que "suene a" funcionalidad no
  implementada (lenguaje aspiracional, futuro, o condicional sin base en código).
- Confirmar que `zensical.toml` referencia `functional/access.md` bajo
  "Funcionalidad" y que `python -m zensical build --strict` no falla.
- Confirmar que el documento no contradice `admin.md`, `quick_start.md` ni
  `.env.example`.
- Prioriza Nivel 1 > Nivel 2 > Nivel 3; no bloquees por Nivel 3.

## Formato de salida completo

### PLAN
- Alcance: `docs/functional/access.md` frente a las fuentes de la tabla anterior
- Fuentes efectivamente consultadas
- Criterio de priorización: Nivel 1 > Nivel 2 > Nivel 3

### AUDIT_PLAN
- Riesgos identificados antes de revisar (secciones más propensas a desactualizarse
  si el código de auth cambió desde la última revisión)
- Veredicto: `GO | GO_CONDICIONAL | NO_GO`

### AUDIT_CODE
- Tabla `Afirmación del documento | Fuente en código | Verificado (Sí/No/Parcial)`
  para cada sección listada arriba
- Discrepancias encontradas, con cita exacta del documento y del código
- Huecos: comportamiento real del código que el documento no menciona

### VERSION
- Hallazgos Nivel 1 (críticos): requieren corrección antes de publicar
- Hallazgos Nivel 2 (altos): planificados para la próxima iteración
- Hallazgos Nivel 3 (recomendados): backlog
- Veredicto: `DOC_VALIDADA | REQUIERE_CORRECCIONES | BLOQUEADA`
- Próximos pasos priorizados (máximo 5 ítems)

---

## Cómo usar este prompt

### Claude Code

```
Lee docs/functional/access.md y valida cada afirmación contra el código fuente
real, usando .github/prompts/access_doc_review.prompt.md. Aplica las
correcciones directamente en el documento si encuentras discrepancias, y deja
sin tocar lo que ya esté verificado.
```

### Copilot Chat

```
#file:.github/prompts/access_doc_review.prompt.md
#file:docs/functional/access.md
#file:src/doc_organize/web/auth.py
#file:src/doc_organize/auth/auth_store.py

Valida la documentación de acceso siguiendo las instrucciones del prompt.
```
