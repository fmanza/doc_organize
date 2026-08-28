# EDGE_CASES.md

**Versionado**: v0.10.0
**Propósito**: Troubleshooting scenarios comunes durante uso de slash commands en Claude Code

> Si encuentras alguno de estos síntomas, sigue los pasos de diagnóstico y solución para resolver sin perder contexto o trabajo.

---

## Escenario 1: Comando Interrumpido a Mitad de Ejecución

**Síntoma:**
- Claude se detiene o pierde contexto durante PLAN/AUDIT_PLAN
- Ves mensaje tipo "Context limit exceeded" o "Token budget exhausted"
- Comando nunca alcanza IMPLEMENT

**Diagnóstico:**
```bash
# Revisar últimas líneas de salida
# ¿Termin\u00f3 PLAN? → AUDIT_PLAN incompleto
# ¿Falta PLAN? → Solicitud demasiado grande

# Cálculo aproximado LoC de solicitud:
# Inputs + contexto proyecto + detalles riesgos + ejemplos
# → Si > ~15K líneas, riesgo de cutoff
```

**Solución:**

1. **Undo y reconoce punto de corte**
   - Lee hasta dónde llegó (final de PLAN? AUDIT_PLAN incompleto?)
   - Copia ese fragmento en `clipboard.txt` local (no commitear)

2. **Reinicia con contexto condensado**
   - Abre nuevo chat o pide continuación: "Continuemos AUDIT_PLAN desde donde se cortó"
   - Repite inputs requeridos pero MÁS CONCISOS
   - Ejemplo: "Objetivo: [1 línea]" en lugar de "[párrafo]"

3. **Split si necesario**
   - Si LoC muy alto, divide en 2 comandos más pequeños
   - Ejemplo: `/new-feature` (motor) + `/hotfix` (bug independiente)

4. **Verificación**
   - Revisa visor de contexto de Claude: ¿cuántos tokens usados?
   - Si > 80% del budget, siguiente comando debe ser más chico

**Prevención:**
- Usa `settings.local.json` para desabilitar hooks si están usando LoC
- Keep inputs cortos (máximo 3 líneas por campo)
- si proyecto es ENORME, particiona en módulos

---

## Escenario 2: Merge Conflict en .claude/commands/

**Síntoma:**
- Git merge falla porque dos ramas modificaron el mismo comando
- Conflict markers en `.claude/commands/nombre.md`
- No sabes cuál versión conservar

**Diagnóstico:**
```bash
git diff --name-only --diff-filter=U
# Busca .claude/commands/ en output

git log --oneline -n 20 | grep -i "comando\|command"
# Identifica commits en conflicto
```

**Solución:**

1. **Inspecciona ambas versiones**
   ```bash
   git show HEAD:.claude/commands/nombre.md > version_local.md
   git show MERGE_HEAD:.claude/commands/nombre.md > version_remoto.md
   diff version_local.md version_remoto.md
   ```

2. **Decide cuál mantener o fusiona**
   - Si ambas agrega secciones válidas → FUSIONA (keep both)
   - Si overwrite completo → ELIGE UNO

3. **Merge segments**
   - Ejemplo: rama A añadió "Qué hacer si falla", rama B expandió "Ejemplo"
   - Copia ambas secciones en archivo final

4. **Verifica coherencia**
   - ¿Las 10 secciones del COMMAND_TEMPLATE están presentes?
   - ¿Links internos aún válidos?

5. **Resuelve y commitea**
   ```bash
   git add .claude/commands/nombre.md
   git commit -m "chore: merge conflict resolution en /nombre"
   ```

**Prevención:**
- Evita editar mismo comando en dos ramas
- Usa feature branches aisladas por módulo (no por comando)

---

## Escenario 3: Tests Fallan Después de IMPLEMENT

**Síntoma:**
- `pytest --collect-only` pasa pero `pytest` falla
- Error en tests/path/test_X.py
- Cambios de IMPLEMENT parecen correctos

**Diagnóstico:**

```bash
# 1. Ejecuta tests específicos
python -m pytest tests/ -v --tb=short 2>&1 | tail -50

# 2. Revisa tipo de error
# - AssertionError → lógica
# - ImportError → dependencias faltantes
# - TimeoutError → test muy lento
# - TypeError → contrato API roto

# 3. Localiza archivo affected
grep -r "def test_" tests/ | grep -i "nombre_cambio"
```

**Solución:**

1. **Aísla test que falla**
   ```bash
   python -m pytest tests/path/test_specific.py::TestClass::test_name -vv
   ```

2. **Revisa AVANT vs APRÈS**
   - Lee cambios en IMPLEMENT
   - Confronta con test expectations
   - ¿El test es obsoleto o el código cambió API?

3. **Fix options:**
   - A) Actualizar test (si código es correcto)
   - B) Revertir cambio de código (si API pública y rompe)
   - C) Deprecate (si necesitas breaking change)

4. **Verifica cobertura**
   ```bash
   python -m pytest tests/ --cov=src --cov-report=term-missing
   ```
   - Target: 80%+ para new_feature, 100% para hotfix

5. **Validación**
   - Pasa ruff, mypy, pytest antes de finalizar
   - Corre full test suite (no solo test fallido)

**Prevención:**
- En IMPLEMENT, incluye test updates como parte de cambios
- TESTING_GUIDE: snapshots y fixtures deben ser robustas

---

## Escenario 4: Archivo Bajo LoC Limit (Sin Procesamiento)

**Síntoma:**
- Claude reporta "Archivo muy pequeño, saltando análisis"
- Cambios propuestos son superficiales o omiten puntos
- Sientes que análisis está incompleto

**Qué significa:**
- Algunos herramientas (p.ej. SonarQube) ignoran archivos < 20 LoC
- Claude puede auto-limitar análisis si ve archivo "trivial"
- No es error; es optimización

**Cuándo ignorar:**
- Archivos verdaderamente cortos (< 10 líneas):
  - `.gitignore` entry
  - Configuración simple JSON
  - Stubs de tipo (`*.pyi`)
- Si contexto de cambio es claro (p.ej. "add one line")

**Cuándo preocuparse:**
- Archivo > 50 LoC pero Claude omite análisis
- Cambio afecta lógica crítica (connection, auth, DB)
- Feels like algo fue saltado sin justificación

**Solución:**

1. **Verifica realmente es chico**
   ```bash
   wc -l archivo.py
   ```

2. **Si es importante, pide re-análisis**
   - En corrección: "Este archivo es pequeño pero crítico (conexión BD)"
   - Claude puede entonces dar análisis más profundo

3. **No es bloqueante**
   - Si LoC pequeña y cambios simples, continúa
   - Si LoC pequeña pero lógica compleja, pide `AUDIT_CODE` recomendado

**Prevención:**
- Para archivos críticos, siempre include en `/audit-code`
- No resíes en "pequeño = simple"; critica puede ser pequeña

---

## Escenario 5: Regresión Silenciosa (Cambio Se Revierte)

**Síntoma:**
- Cambios fueron aplicados correctamente (commits visibles)
- Pero en snapshot/cobertura, cambios desaparecieron
- Feature funciona, pero código volvió a viejo

**Diagnóstico:**

```bash
# 1. Confirma commits existen
git log --oneline | head -20

# 2. Revisa rama actual
git branch -v

# 3. Diff vs main
git diff main..HEAD src/archivo.py | head -50

# 4. Busca revert
git log --oneline | grep -i "revert\|rollback"

# 5. Consulta git blame
git blame src/archivo.py | grep "linea_que_cambió"
```

**Causas posibles:**
- Pull request rechazado pero commits no limpiados
- Revert accidental en CI
- Rama mergeada en wrong order
- Colaborador overwrite sin notificación

**Solución:**

1. **Identifica dónde se perdió**
   ```bash
   git log -p src/archivo.py | grep -B5 -A5 "@@.*linea"
   ```

2. **Recupera cambios**
   - A) Re-aplica manualmente (copy-paste desde IMPLEMENT)
   - B) `git cherry-pick` commit original
   - C) `git revert <revert-commit>` (si alguien hizo revert)

3. **Comunica**
   - Abre issue o DM: "Cambios de [feature] se revirtieron"
   - Pide contexto (fue intencional? bug? accidental?)

4. **Valida**
   - Tests pasan
   - Cobertura intacta
   - Commits en order

5. **Prevención going forward**
   - Protege `main`/`develop` (require reviews)
   - Usa cherrypick en lugar de manual re-edit
   - Documental rollbacks en changelog

**Prevención:**
- Code review antes de merge (ve cambios antes de que sucedan)
- Snapshot tests para detectar cambios silenciosos
- CI/CD checks: cobertura no baja

---

## Matriz de Resolución Rápida

| Síntoma | Link a Escenario | Fix Time | Severity |
|---------|------------------|----------|----------|
| "Token budget exhausted" | Escenario 1 | 10-30 min | 🔴 P1 |
| Merge conflict en `.claude/` | Escenario 2 | 5-15 min | 🟡 P2 |
| Tests fallan post-IMPLEMENT | Escenario 3 | 15-60 min | 🔴 P1 |
| LoC warning (archivo pequeño) | Escenario 4 | 2-5 min | 🟢 P3 |
| Cambios desaparecidos | Escenario 5 | 30-120 min | 🔴 P1 |

---

## Referencia Cruzada

Este archivo está linked desde:
- `.claude/commands/*.md` (sección "Qué hacer si falla")
- `.claude/README.md` (FAQ troubleshooting)
- CLAUDE.md (sección de anexos)

Si encuentras escenario NOT cubierto aquí, abre issue en repo o actualiza directamente.

---

## Versión de este Edge Cases

| Versión | Fecha | Escenarios |
|---------|-------|-----------|
| — | 10 abr 2026 | 5 scenarios + matriz resolución |
| 2026-08-28 | 28 ago 2026 | Retirados 4 escenarios específicos de la encarnación anterior de este repo (motores de base de datos: `migrate/extractors/`, `MySQLVariableValidator`, packet size de MySQL, lazy-loading en `connection/mariadb/`) — no aplican a `doc_organize` tal como existe hoy |
