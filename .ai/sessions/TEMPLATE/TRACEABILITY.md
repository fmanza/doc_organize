# TRACEABILITY: Resumen de Sesión

<!--
Plantilla canónica (`.ai/sessions/TEMPLATE/`, ver `.github/SHARED_INSTRUCTIONS.md` §Gobernanza
de plataformas IA y `.github/instructions/sync.instructions.md` §6). Copiar a
`.ai/sessions/<YYYY-MM-DD>[-slug]/TRACEABILITY.md` al cerrar una sesión (fase VERSION).

Checklist de validación antes de cerrar (sync.instructions.md §6):
- [ ] Sección "Directrices para Futuras IAs" presente y poblada (no vacía, no solo "-")
- [ ] Cada directriz con formato `**[área]**: <hecho verificable>`
- [ ] Veredicto final es CLOSED (o GO / GO_CONDICIONAL si la sesión queda abierta)
-->

## Sesión
- **Fecha**:
- **Tipo**: `feature` | `hotfix` | `refactor` | `docs` | `audit`
- **Rama**:
- **Estado**: EN CURSO | ✅ COMPLETADA

## Objetivo
<!-- 1-3 frases: qué se pidió y por qué. -->

## Cambios Ejecutados
<!-- Uno por sub-tarea significativa. Repetir el bloque según haga falta. -->

### ✅/⬜ 1. <Título del cambio>

**Archivo(s)**:
**Descripción**:
**Status**:

---

## Impacto

### Código
- **Archivos modificados/creados**:
- **Cambios funcionales**: sí/no, cuáles

### Compatibilidad
- **BREAKING**:
- **NO BREAKING**:

---

## Verificación
<!-- Comandos reales ejecutados y su resultado, no una promesa. -->
```
python -m ruff check src tests
python -m mypy src
python -m pytest
zensical build --strict   # si se tocó docs/ o zensical.toml
```

---

## Riesgos Residuales

| Riesgo | Mitigación | Status |
|--------|-----------|--------|
|        |           |        |

---

## Siguientes Pasos (Recomendado)
1.

---

## Directrices para Futuras IAs

<!-- OBLIGATORIO, no dejar vacío ni con un solo "-". Formato: **[área]**: <hecho verificable>.
Hechos que una IA futura necesitaría para no repetir análisis: puntos canónicos que centralizan
una responsabilidad, decisiones de diseño y su justificación breve, patrones con nombre
establecidos en la sesión, lecciones de herramientas/técnicas. -->

- **[área]**: hecho verificable

---

## Veredicto

### 🟢 COMPLETADA / 🟡 GO_CONDICIONAL / 🔴 BLOQUEADA

**Criterios**:
-

**Evidencia**:
- Branch:
- Commits:
- Tests:

**Sesión cerrada**: <fecha, hora UTC>
