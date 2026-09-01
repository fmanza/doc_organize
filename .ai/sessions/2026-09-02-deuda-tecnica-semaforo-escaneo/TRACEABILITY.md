# TRACEABILITY: Resumen de Sesión

## Sesión
- **Fecha**: 2026-09-02
- **Tipo**: `refactor` (ciclo `/tech-debt`: PLAN → AUDIT_PLAN → AUDIT_CODE → IMPLEMENT)
- **Rama**: `develop`
- **Estado**: ✅ COMPLETADA (implementación y verificación en verde; commit pendiente de confirmación del usuario)

## Objetivo
Follow-up de la sesión `2026-09-02-semaforo-escaneo`: el AUDIT_CODE de esa sesión
señaló dos deudas técnicas — literales de fase repetidos en el JS del semáforo, y
ausencia de política del proyecto sobre JS inline/tests frontend. El usuario pidió
ejecutar esa deuda y, además, revisar y mejorar la política del proyecto (no solo
el código), con un ciclo PLAN → AUDIT_PLAN → AUDIT_CODE previo a la implementación.

## Cambios Ejecutados

### ✅ 1. PLAN — alcance de los dos ítems de deuda
**Descripción**: se revisó `.github/SHARED_INSTRUCTIONS.md` completo y se confirmó
que la sección "Plantillas Jinja2" (146-220) no menciona JS inline en ningún punto,
y que "Estrategia de tests" (238-243) no menciona el módulo `web/` pese a que ya
tiene cobertura Python (`tests/unit/test_web_scan.py`). Se fijó el alcance: (1)
extraer constantes de fase en `folder_selector.html.j2`, (2) redactar política
nueva sobre JS inline y el estado real de los tests frontend.
**Status**: ✅ scope confirmado como análisis + implement (ambos ítems de bajo
riesgo).

### ✅ 2. AUDIT_PLAN — riesgos y dependencias entre ítems
**Descripción**: se descartó cualquier solución con toolchain de build/módulos JS
(`import`/`export`) por no existir esa infraestructura en el proyecto (mismo motivo
que Tailwind se carga vía CDN). Se decidió que la política (ítem 2) debía redactarse
*después* de aplicar las constantes (ítem 1), para poder citarlas como ejemplo real
en el propio texto de la política en vez de describirlas en abstracto.
**Status**: ✅ sin riesgos funcionales/seguridad; dependencia de orden documentada.

### ✅ 3. AUDIT_CODE — clasificación final
**Descripción**: 13 ocurrencias de literales de fase (`"idle"|"started"|"running"|
"completed"|"error"`) localizadas en `folder_selector.html.j2:204-293`, sin rama
`else` que capture una fase desconocida (fallo silencioso ante un typo). Clasificado
como `quick_win` (constantes) y `fase_media` (política, requiere criterio de
producto, no solo mecánica).
**Status**: ✅ veredicto **DEUDA_MENOR** — sin riesgo de regresión ni bloqueo de
release.

### ✅ 4. IMPLEMENT — las dos fases
**Archivo(s)**:
- `src/doc_organize/web/templates/folder_selector.html.j2` — añadido
  `const SCAN_PHASE = { IDLE, STARTED, RUNNING, COMPLETED, ERROR }`; reemplazadas
  las 12 ocurrencias de literales de fase (excluida `scanEvent.event === "completed"`,
  que es el nombre del evento del protocolo WebSocket del backend, un namespace
  distinto y de una sola ocurrencia — no se extrajo por no alcanzar el umbral de
  "3+ repeticiones"). Añadida rama `else` en `setSemaforo()` con
  `console.error("setSemaforo: fase desconocida", phase)` para detectar typos en
  vez de fallar en silencio.
- `.github/SHARED_INSTRUCTIONS.md` — nueva subsección "JavaScript inline (`<script>`
  en plantillas)" dentro de "Plantillas Jinja2": convención de constantes con el
  mismo umbral que las macros Jinja2 (3+ repeticiones), y declaración explícita de
  que la ausencia de infraestructura de test frontend (Jest/Vitest/Playwright) es
  una decisión implícita aceptada, no un olvido — con la señal de cuándo dejar de
  aceptarla (lógica que crece debería bajar a Python testeable). Añadida también una
  línea en "Estrategia de tests" reconociendo el módulo `web/` (antes ausente de esa
  sección) y remitiendo a la nueva política.
**Status**: ✅ implementado; `ruff`/`mypy` limpios; `test_web_scan.py` en verde (37
passed) — confirma que la plantilla sigue renderizando sin error de Jinja2 tras el
cambio de JS.

---

## Impacto

### Código
- **Archivos modificados**: `src/doc_organize/web/templates/folder_selector.html.j2`,
  `.github/SHARED_INSTRUCTIONS.md`.
- **Cambios funcionales**: no — refactor mecánico (renombrado 1:1 de literales a
  constantes) + documentación de política. Sin cambio de comportamiento observable.

### Compatibilidad
- **BREAKING**: ninguno.
- **NO BREAKING**: cambio interno de JS inline (mismos `id` de DOM, mismo protocolo
  WebSocket); la política nueva es aditiva sobre `SHARED_INSTRUCTIONS.md`.

---

## Verificación
```
python -m ruff check src tests -q                → sin salida (limpio)
python -m mypy src                                → Success: no issues found in 47 source files
python -m pytest tests/unit/test_web_scan.py -q  → 37 passed
```

---

## Riesgos Residuales

| Riesgo | Mitigación | Status |
|--------|-----------|--------|
| La política nueva sobre JS inline es la primera de su tipo en el proyecto — si aparece JS con estado más complejo en otra plantilla, esta sesión es el único precedente a seguir | Documentado con un ejemplo real citado (`SCAN_PHASE`) para que sea replicable sin ambigüedad | Aceptado, mitigado con ejemplo concreto |
| La rama `else`/`console.error` en `setSemaforo()` no tiene test que la ejercite (no hay infraestructura de test JS, ver política) | Aceptado explícitamente por la política nueva; revisión manual en navegador recomendada si se toca de nuevo esta función | Aceptado, no mitigado |

---

## Siguientes Pasos (Recomendado)
1. Confirmar con el usuario el mensaje de commit preparado en la respuesta del
   turno y ejecutar `git add`/`git commit`.
2. Si en el futuro se añade JS con estado a otra plantilla de `web/`, aplicar el
   mismo patrón `SCAN_PHASE` (objeto de constantes con umbral de 3+ repeticiones)
   documentado en `SHARED_INSTRUCTIONS.md → Plantillas Jinja2 → JavaScript inline`.

---

## Directrices para Futuras IAs

- **[Umbral de extracción a constantes en JS inline]**: `SHARED_INSTRUCTIONS.md`
  ahora fija el mismo umbral que ya usaba para macros Jinja2 (3+ repeticiones) para
  decidir cuándo un valor JS repetido (estado, fase, nombre de evento) debe
  extraerse a un objeto de constantes al principio del bloque `<script>`. Con 1-2
  usos, un literal inline sigue siendo preferible — no aplicar la extracción de
  forma anticipada.
- **[Ausencia de test frontend es una decisión documentada, no una laguna]**: no
  instalar Jest/Vitest/Playwright sin registrar la decisión en
  `.ai/DECISIONS_LOG.md` primero. La política actual acepta JS inline sin test
  mientras se mantenga simple (funciones puras y cortas); si crece lo suficiente
  como para necesitar tests reales, la señal correcta es mover esa lógica a Python
  testeable (un endpoint), no montar un framework de test JS.
- **[`scanEvent.event === "completed"` no comparte namespace con `SCAN_PHASE`]**:
  aunque ambos usan el string `"completed"`, uno es el nombre del evento del
  protocolo WebSocket (`ScanEventType` del backend) y el otro es el estado visual
  del semáforo (cliente). Coinciden por casualidad de vocabulario, no por ser el
  mismo concepto — no fusionarlos en una sola constante si se refactoriza de nuevo
  este bloque.

---

## Veredicto

### 🟢 COMPLETADA

**Criterios**:
- ✅ Ciclo completo `/tech-debt` (PLAN → AUDIT_PLAN → AUDIT_CODE → IMPLEMENT)
  ejecutado con veredicto **DEUDA_MENOR** en el AUDIT_CODE
- ✅ Quick win (constantes `SCAN_PHASE`) implementado sin cambio funcional
- ✅ Política de proyecto revisada y ampliada en `SHARED_INSTRUCTIONS.md` con
  ejemplo real citado
- ✅ `ruff`, `mypy` limpios; `test_web_scan.py` en verde (37 passed)
- ⬜ Commit: pendiente de confirmación explícita del usuario

**Evidencia**:
- Branch: `develop`
- Commits: ninguno todavía — cambios en working tree, mensaje preparado en la
  respuesta del turno
- Tests: 37 passed (`test_web_scan.py`)

**Sesión cerrada**: 2026-09-02
