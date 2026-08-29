# CURRENT STATE — doc_organize

**Generado**: 2026-08-28
**Fuente**: `.github/prompts/doclink_extractor_plan.md` (versión 3.1, revisión 12) + suite de tests real
**Rama activa**: `develop` — todo el trabajo de Fase 1 vive sin commitear desde el scaffold inicial

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
| Fase E | Tests de integración adicionales, documentación ampliada | ⬜ Abierta |

**Fuente de verdad detallada** (historial de revisiones, AUDIT_PLAN de cada pieza, decisiones de
alcance): `.github/prompts/doclink_extractor_plan.md`.

---

## Calidad actual (verificado, no una promesa)

```
python -m ruff check src tests    → All checks passed
python -m mypy src                 → Success: no issues found in 42 source files
python -m pytest                    → 233 passed, 95% cobertura
mkdocs build --strict                → exit 0, sin links rotos
```

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
- Rate-limiting en `/login` antes de exponer fuera de loopback.
- Tokens de API personales por usuario (acceso programático sin sesión de navegador).
- Dos decisiones de alcance analizadas con opciones pero no implementadas (`§14` del PLAN):
  validación `AuthStore.tenant_exists()` en `ProjectRegistry`, y anidamiento de rutas de salida en
  `DocumentConverter` (riesgo de `MAX_PATH` en Windows con carpetas de entrada muy profundas).

---

## Próximos pasos

1. `git add`/commit/push del trabajo acumulado (ver mensaje preparado en
   `.ai/sessions/2026-08-28/TRACEABILITY.md`).
2. Fase E: tests de integración adicionales, documentación ampliada.
3. Cerrar los pendientes de la sección anterior según prioridad real (no la del orden en que se
   listaron originalmente en el PLAN — ver `§15` para el reordenamiento por severidad).
