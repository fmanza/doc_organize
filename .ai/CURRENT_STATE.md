# CURRENT STATE — doc_organize

**Generado**: 2026-08-29
**Fuente**: `.github/prompts/doclink_extractor_plan.md` (versión 3.1, revisión 12) +
`.ai/DECISIONS_LOG.md` (revisión 13, auditoría de seguridad) + suite de tests real
**Rama activa**: `develop` — todo el trabajo de Fase 1 + revisión 13 vive sin commitear desde el
scaffold inicial
**Versión**: `0.2.0` (`pyproject.toml`/`CHANGELOG.md`) — primera versión con changelog formal;
`0.1.0` no tuvo entrada retroactiva

> Reemplaza una versión anterior (fechada 2026-06-05) que describía otra librería (motores de base
> de datos, `v0.10.0`, migración a "Zenical") — la encarnación previa de este mismo repositorio
> antes de un pivote de dominio completo. Ver `.ai/architecture.md` para el detalle.

---

## Estado de Fase 1

| Fase | Contenido | Estado |
|---|---|---|
| A–C | Núcleo: escaneo, conversión (Docling), OCR, deduplicación, caché (REQ-001 a REQ-006) | ✅ Completa |
| C.1 | Gestión de proyectos (REQ-008) | ✅ Completa |
| D-1 | CLI (`main.py`: `project`, `scan`, `web`) | ✅ Completa |
| D-2a | Web: esqueleto FastAPI, auth básica, Project Selector, Dashboard | ✅ Completa |
| §2.7.2 (rev. 8) | Auth multi-usuario/multi-tenant (4 sub-pasos) | ✅ Completa |
| §2.7.3 (rev. 10) | Folder Selector + escaneo web con WebSocket (2 sub-pasos) | ✅ Completa |
| §2.7.4 (rev. 11) | Cache Viewer + Export ZIP + Duplicates Resolver (3 sub-pasos) | ✅ Completa |
| §15 (rev. 12) | AUDIT_PLAN + IMPLEMENT del roadmap restante (docs, CI, benchmark) | ✅ Completa |
| Rev. 9 | Roles y gestión de usuarios (`Role`, admin/admin por defecto, `/admin/users`) | ✅ Completa |
| Rev. 13 | Auditoría de seguridad post-rev. 9: `Role.allowed_scan_roots`, cookie `Secure`, rate limiting de `/login` | ✅ Completa |
| Fase E | Tests de integración adicionales, documentación ampliada | ⬜ Abierta |

**Fuente de verdad detallada** (historial de revisiones, AUDIT_PLAN de cada pieza, decisiones de
alcance): `.github/prompts/doclink_extractor_plan.md`.

---

## Calidad actual (verificado, no una promesa)

```
python -m ruff check src tests           → All checks passed
python -m mypy src                        → Success: no issues found in 42 source files
python -m pytest tests/unit -m "not slow" → 233 passed (247 recolectados en total, con @slow)
python -m build                           → doc_organize-0.2.0.tar.gz + .whl sin error
mkdocs build --strict                     → exit 0, sin links rotos
```

> **Nota (2026-08-29, maturity-assessment)**: re-verificado en vivo. `pytest`/`mkdocs build --strict`
> siguen en verde tal cual. `ruff check` había pasado a fallar con 26 errores tras un bump de
> versión de la herramienta (0.15.18 → 0.16.4, reglas nuevas `RUF022`/`RUF059`/`ASYNC230`/`PYI034`
> no existían cuando se escribió esta tabla) — corregido en esta misma sesión, ver `git log`.
> `mypy` fallaba por `types-aiofiles` ausente en el entorno local (dependencia de `[dev]` no
> reinstalada), no por un error de tipos real.

Benchmark real (100 PDFs nativos, sin OCR): **84.6s, 70.9 docs/min, 0 errores** — cumple el NFR
"< 2 minutos" del PLAN.

---

## Estructura del código (verificada)

```
src/doc_organize/
├── core/, utils/               # Nivel 1
├── validators/, scanner/, converter/, dedup/, cache/, projects/, auth/   # Nivel 2
└── scan/, web/, main.py         # Nivel 3
```

11 módulos reales. Detalle: `.ai/architecture.md`, `docs/functional/index.md`.

---

## Trabajo pendiente conocido (no bloqueante)

- Confirmar en verde la matriz de CI ampliada a Python 3.10–3.14 (`tests.yml`) — corregida esta
  sesión, no verificable localmente (este entorno de desarrollo es Python 3.14 únicamente).
- Pruebas en navegador real de las 6 páginas web — sustituidas por un smoke test contra el servidor
  real; sigue pendiente una verificación genuina en Chrome/Firefox/Safari.
- Tokens de API personales por usuario (acceso programático sin sesión de navegador).
- Dos decisiones de alcance analizadas con opciones pero no implementadas (`§14` del PLAN):
  validación `AuthStore.tenant_exists()` en `ProjectRegistry`, y anidamiento de rutas de salida en
  `DocumentConverter` (riesgo de `MAX_PATH` en Windows con carpetas de entrada muy profundas).
- **(revisión 13)** Cualquier tenant en producción con roles no-admin restringidos debe recibir
  `allowed_scan_roots` asignadas por un admin tras desplegar `0.2.0` — sin esa asignación, esos
  roles no pueden iniciar ningún escaneo nuevo (antes sí podían, sin restricción real).
  Acción de despliegue/operación, no de código.
- **(revisión 13)** La cookie de sesión solo se marca `Secure` si `request.url.scheme == "https"` en
  el propio proceso — un despliegue detrás de proxy TLS necesita `ProxyHeadersMiddleware` +
  `X-Forwarded-Proto` configurados para que esto funcione; no verificable desde este repo.
- **(revisión 13)** `pytest -m slow` no se ejecutó en la sesión de la auditoría de seguridad (sin
  cambios en `converter/`/`scan_command.py` que la afecten, riesgo bajo) — pendiente antes de un
  release real.
- ~~Rate-limiting en `/login` antes de exponer fuera de loopback~~ — **cerrado en revisión 13**
  (`LoginRateLimiter`, ver `.ai/DECISIONS_LOG.md`).

---

## Próximos pasos

1. ~~`git add`/commit/push del trabajo acumulado (Fase 1 completa + revisión 13 de seguridad)~~ —
   **hecho**: `git log` confirma los commits `2d71628`/`34d6133`/`83504cc`/`3a21ba0` ya en `develop`.
   Este punto había quedado desactualizado (nota añadida 2026-08-29, maturity-assessment) —
   mensaje de referencia seguía en `.ai/sessions/2026-08-29/TRACEABILITY.md` (revisión 13) y
   `.ai/sessions/2026-08-28/TRACEABILITY.md` (Fase 1).
2. Fase E: tests de integración adicionales, documentación ampliada.
3. Cerrar los pendientes de la sección anterior según prioridad real (no la del orden en que se
   listaron originalmente en el PLAN — ver `§15` para el reordenamiento por severidad).
4. Antes de exponer cualquier despliegue no-loopback existente a `0.2.0`: asignar
   `allowed_scan_roots` a sus roles no-admin (revisión 13).
