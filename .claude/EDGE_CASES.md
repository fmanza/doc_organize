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

## Escenario 6: CI falla — `AttributeError: module does not have attribute X` en tests con `patch()`

**Síntoma:**
- CI falla en todas las plataformas (idéntico error):
  ```
  AttributeError: <module 'doc_organize.migrate.extractors.X'> does not have the attribute 'func_name'
  ```
- El test hace `with patch("doc_organize.migrate.extractors.X.func_name", ...)`
- La suite local pasa (o el archivo local fue reescrito y no commiteado)

**Causa raíz típica:**
- Un hotfix refactorizó el extractor y eliminó funciones de módulo (`fetch_X_sync`, etc.)
- Los tests seguían parcheando las rutas antiguas
- El archivo de test fue corregido localmente pero **no commiteado** antes del push

**Diagnóstico:**
```bash
# Comparar test local vs commiteado
git diff HEAD -- tests/path/test_X.py | head -60

# Ver qué función parcheaba el test
grep "_PATH\|patch(" tests/path/test_X.py

# Verificar que la función existe en el módulo
grep "def fetch_X_sync" src/doc_organize/migrate/extractors/X.py
```

**Solución:**

1. **Reescribir el test para mockear el manager, no las funciones de módulo**:
   - Extractor actual usa `self._query()` → `manager.execute_custom_many(sql, params)`
   - Pattern correcto:
     ```python
     manager = MagicMock()
     manager.execute_custom_many.side_effect = [iter(rows1), iter(rows2), ...]
     ext = XSchemaExtractor(manager)
     result = ext.extract_routines("schema")
     ```

2. **Añadir y commitear ANTES de push**:
   ```bash
   git add tests/path/test_X.py
   git commit -m "fix(tests): reescribir test_X con manager mock"
   git push
   ```

**Prevención:**
- Cuando un hotfix cambia la interfaz interna de un extractor, actualizar los tests en el mismo commit
- Antes de push, verificar `git status -s` para que no queden archivos de test modificados sin commitear
- Usar `manager.execute_custom_many.side_effect` (patrón establecido) en lugar de `patch()` sobre funciones de módulo

---

## Escenario 7: Heurística de Tamaño Devuelve Valor Inesperado (MySQL Packet Calculation)

**Síntoma:**
- `MySQLMultiRowInsertStrategy.get_min_max_allowed_packet()` retorna 32 MB en lugar de 64 MB
- Test espera `>= 64 * 1048576` pero obtiene `33554432` (32 MB)
- Lógica de escalado de paquete parece "demasiado pequeña" para bulk

**Diagnóstico:**
```bash
# Revisar lógica de cálculo
git diff HEAD src/doc_organize/bulk/_execution/batch.py | grep -A10 "get_min_max_allowed_packet"

# Ejecutar test específico
python -m pytest tests/unit/bulk/test_mysql_min_packet_calculation.py -vv -k "test_small_max_rows"

# Verificar fórmula
# estimated_size = max_rows × avg_row_bytes × 1.5 (overhead)
# Ejemplo: 1000 rows × 2000 bytes × 1.5 = 3 MB
# → Si return 3 MB en lugar de 64 MB mínimo, hay bug en la cadena de condicionales
```

**Causa raíz típica:**
- Lógica original retornaba `estimated_size` directamente sin validar mínimo
- Bulk operations siempre necesitan >= 64 MB (estándar de facto en MySQL)
- 32 MB es insuficiente para típicas cargas con 1000+ filas

**Solución:**

1. **Verifica orden de condicionales**:
   ```python
   # ❌ INCORRECTO: Si estimated < 16 MB → devuelve estimated
   if estimated_size < 16 * 1048576:
       return estimated_size  # ← Bug: puede devolver 3 MB

   # ✅ CORRECTO: Si estimated < 16 MB → standardize a 64 MB
   if estimated_size < 16 * 1048576:
       return 64 * 1048576  # Conservative minimum for bulk
   ```

2. **Valida power-of-2**:
   - Rango válido: `[64 MB, 128 MB, 256 MB]` (alineado con OS memory allocation)
   - Nunca < 64 MB (demasiado restrictivo)
   - Nunca > 256 MB (límite práctico)

3. **Escala progresiva**:
   ```python
   if estimated_size <= 16 * 1048576:      # <= 16 MB → 64 MB
       return 64 * 1048576
   elif estimated_size <= 80 * 1048576:    # <= 80 MB → 128 MB
       return 128 * 1048576
   else:                                    # > 80 MB → 256 MB
       return 256 * 1048576
   ```

4. **Corre suite de tests**:
   ```bash
   python -m pytest tests/unit/bulk/test_mysql_min_packet_calculation.py -v
   ```
   Verifica que `test_min_packet_size_lower_bound` pase (siempre >= 64 MB)

**Prevención:**
- Usa constants para límites (MIN_PACKET = 64 MB, MAX_PACKET = 256 MB)
- Tests deben validar >= MIN, no exact equality
- Comentar la "razón" por la que 64 MB es mínimo (bulk operations, típicos 1000+ filas)

---

## Escenario 8: Mock de MySQLVariableValidator Falla por Conexión Incorrecta

**Síntoma:**
- Test en `test_mysql_variables_config.py` falla:
  ```
  AssertionError: Mock connection returned None for SHOW VARIABLES
  ```
- O: `AttributeError: 'MagicMock' object has no attribute 'execute'`
- El validator no puede leer variables de BD

**Diagnóstico:**
```bash
# Ver test specific
git diff HEAD tests/unit/connection/mariadb/test_mysql_variables_config.py | grep -A15 "test_read_variables"

# Ejecutar con traceback
python -m pytest tests/unit/connection/mariadb/test_mysql_variables_config.py::TestMySQLVariableValidator::test_read_variables -vv --tb=long
```

**Causa raíz típica:**
- Mock de `connection.execute()` no devuelve Iterator (Row objects)
- Código espera `execute() → Iterator[Row]`, pero mock devuelve `None` o `list`
- MySQLVariableValidator itera sobre None → TypeError

**Solución:**

1. **Usa MagicMock.return_value para simular ResultProxy**:
   ```python
   # ❌ INCORRECTO
   connection.execute.return_value = [Row(max_allowed_packet=16777216)]

   # ✅ CORRECTO
   mock_result = MagicMock()
   mock_result.__iter__ = MagicMock(return_value=iter([
       {'max_allowed_packet': 16777216},
       {'innodb_buffer_pool_size': 1073741824}
   ]))
   connection.execute.return_value = mock_result
   ```

2. **O usa MagicMock con side_effect**:
   ```python
   connection.execute.side_effect = [
       iter([{'max_allowed_packet': 16777216}]),
       iter([{'innodb_buffer_pool_size': 1073741824}])
   ]
   ```

3. **Verifica try/except en validator**:
   - `MySQLVariableValidator.read_variables()` debe capturar SQLAlchemyError
   - Si mock falla, debe retornar `{}`

4. **Corre test con output**:
   ```bash
   python -m pytest tests/unit/connection/mariadb/test_mysql_variables_config.py::TestMySQLVariableValidator -v
   ```

**Prevención:**
- Aisla mock de connection en fixture (`conftest.py`)
- Valida que mock tenga atributos correctos antes de usar
- Usa `MagicMock(spec=Connection)` para forzar esquema correcto

---

## Escenario 9: Módulo Nuevo No Auto-Importa por Lazy-Loading Incompleto

**Síntoma:**
- Código hace: `from doc_organize.connection.mariadb import MySQLOptimalConfig`
- Error: `ImportError: cannot import name 'MySQLOptimalConfig'`
- Pero el archivo `_config.py` existe y tiene la clase

**Diagnóstico:**
```bash
# Verifica que archivo existe
ls -la src/doc_organize/connection/mariadb/_config.py

# Verifica __all__ en __init__.py
grep "MySQLOptimalConfig" src/doc_organize/connection/mariadb/__init__.py

# Verifica _SYMBOL_TO_MODULE
grep "_config" src/doc_organize/connection/mariadb/__init__.py
```

**Causa raíz típica:**
- Archivo `_config.py` fue creado pero NO registrado en `__init__.py`
- `__all__` actualizado pero `_SYMBOL_TO_MODULE` no
- O typo en mapping: `"MySQLOptimalConfig": "_config"` vs `"MySQLOptimalConfig": "config"`

**Solución:**

1. **Verifica __all__ export**:
   ```python
   # En src/doc_organize/connection/mariadb/__init__.py
   __all__ = [
       # ... existing ...,
       "MySQLOptimalConfig",        # ← Agregado en lista
       "MySQLVariableValidator",
   ]
   ```

2. **Verifica _SYMBOL_TO_MODULE mapping**:
   ```python
   _SYMBOL_TO_MODULE = {
       # ... existing ...,
       "MySQLOptimalConfig": "_config",         # ← Entrada en mapping
       "MySQLVariableValidator": "_variables",
   }
   ```

3. **Verifica __getattr__ existence**:
   ```python
   def __getattr__(name):
       if name in _SYMBOL_TO_MODULE:
           module_name = _SYMBOL_TO_MODULE[name]
           module = importlib.import_module(f".{module_name}", __name__)
           return getattr(module, name)
       raise AttributeError(f"No attribute {name} in mariadb")
   ```

4. **Test import manualmente**:
   ```bash
   python -c "from doc_organize.connection.mariadb import MySQLOptimalConfig; print(MySQLOptimalConfig)"
   ```
   Debe imprimir `<class 'doc_organize.connection.mariadb._config.MySQLOptimalConfig'>`

5. **Ejecuta full test suite**:
   ```bash
   python -m pytest tests/unit/connection/mariadb/test_mysql_variables_config.py -v
   ```

**Prevención:**
- Cuando crees nuevo módulo `_X.py`, SIEMPRE actualizar `./__init__.py`:
  1. Agregar a `__all__`
  2. Agregar mapping en `_SYMBOL_TO_MODULE`
  3. Si clase es pública, add `TYPE_CHECKING` import para type hints
- Usar checklist: "Did I update __init__.py?"
- Test import en el mismo commit que creaste el módulo

---

## Matriz de Resolución Rápida

| Síntoma | Link a Escenario | Fix Time | Severity |
|---------|------------------|----------|----------|
| "Token budget exhausted" | Escenario 1 | 10-30 min | 🔴 P1 |
| Merge conflict en `.claude/` | Escenario 2 | 5-15 min | 🟡 P2 |
| Tests fallan post-IMPLEMENT | Escenario 3 | 15-60 min | 🔴 P1 |
| LoC warning (archivo pequeño) | Escenario 4 | 2-5 min | 🟢 P3 |
| Cambios desaparecidos | Escenario 5 | 30-120 min | 🔴 P1 |
| CI: `AttributeError` en `patch()` de función removida | Escenario 6 | 5-15 min | 🔴 P1 |
| Packet size calculation devuelve < 64 MB | Escenario 7 | 10-15 min | 🔴 P1 |
| Mock connection para validator falla | Escenario 8 | 5-10 min | 🟡 P2 |
| Módulo nuevo no auto-importa | Escenario 9 | 5-10 min | 🟡 P2 |

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
| v0.6.7 | 10 abr 2026 | 5 scenarios + matriz resolución |
| v0.9.0 | 22 may 2026 | +Escenario 6: CI AttributeError patch módulo (tests extractor sqlserver) |
| v0.10.0 | 2 jun 2026 | +Escenario 7: Heurística packet size, +Escenario 8: Mock validator connection, +Escenario 9: Lazy-loading módulo nuevo |
