# COMMAND_TEMPLATE.md

**Versionado**: v0.6.7
**Propósito**: Normativa estructural para todos los slash commands de Claude Code

> Este archivo define la estructura estándar que debe tener cada comando en `.claude/commands/`. Úsalo como referencia para crear nuevos comandos o auditar existentes.

---

## Estructura Estándar de un Comando

Cada archivo de comando (p.ej. `/new-feature`, `/hotfix`) debe contener estas secciones en este orden:

### 1. Título + Descripción Breve (requerido)

```markdown
# /nombre-del-comando

Descripción de una línea del propósito del comando (3-10 palabras).
```

**Criterios:**
- Título es el nombre del comando precidido de `/`
- Descripción cabe en una línea
- Ejemplo: `# /new-feature` → "Implementar nueva funcionalidad con flujo PLAN→AUDIT_PLAN→IMPLEMENT"

---

### 2. Cuándo Usar (requerido, 5-15 líneas)

```markdown
## Cuándo usar

- Caso 1: descripción clara con contexto
- Caso 2: descripción clara
- Antipatrón: cuándo NO usar este comando
```

**Criterios:**
- Lista de viñetas (2-5 items)
- Incluir al menos 1 antipatrón ("NO usar cuando...")
- Ejemplos concretos, no genéricos
- Diferenciar de otros comandos cercanos

---

### 3. Inputs Requeridos (requerido, checklist obligatorio)

```markdown
## Inputs requeridos (OBLIGATORIO - verifica antes de empezar)

- [ ] **Objetivo**: [Breve descripción del qué se quiere lograr]
- [ ] **Contexto**: [Qué cambios anteriores pueden afectar?]
- [ ] **Restricciones**: [Limitaciones, breaking changes, APIs public?]
- [ ] **[campo adicional específico del comando]**
```

**Criterios:**
- Mínimo 3 campos, máximo 9 campos
- Todos con checkbox `[ ]`
- Nombres de campos en **bold**
- Cada campo con placeholder en `[corchetes]`
- Orden lógico: Objetivo → Contexto → Restricciones → Specifics

---

### 4. Validación Interactiva (requerido, párrafo enfático)

```markdown
### ⚠️ VALIDACIÓN

Si **alguno** de los campos anteriores está vacío o no tiene respuesta clara, **DETENTE AHORA**.
Pide aclaración al usuario antes de continuar. No procegedas a PLAN si falta contexto.

Ejemplo de detención: "Campo 'Restricciones' vacío → preguntar: ¿Rompes API pública? ¿Migraciones? ¿Deprecations?"
```

**Criterios:**
- Siempre presente en cada comando
- Tono imperativo ("DETENTE", "verifica", "aclara")
- Incluir ejemplo de detención
- Símbolo ⚠️ para llamar atención visual

---

### 5. Política de Cambios (requerido en commands de implementación, opcional en audit)

```markdown
## Política de cambios para este comando

**Obligatorio**:
- Sección PLAN obligatoria (min 30 líneas de análisis)
- Riesgos identificados y mitigados (min 3 riesgos)

**Prohibido**:
- Refactorizar código sin justificación en PLAN
- Cambiar contratos de APIs públicas sin deprecation path
- [adicionales según comando]

**Recomendado**:
- Incluir ejemplos deterministas
- AUDIT_CODE valida completitud de changes
```

**Criterios:**
- Secciones: Obligatorio/Prohibido/Recomendado
- 1-3 items por sección
- Lenguaje declarativo y específico

---

### 6. Orden de Salida (requerido, define "returns" del comando)

```markdown
## Devuelve en este orden

El comando emite estructuras Markdown en este orden específico:

1. **PLAN** (30-100 líneas)
   - Objetivo
   - Rutas afectadas
   - Componentes implicados
   - Riesgos (min 3)

2. **AUDIT_PLAN** (20-50 líneas)
   - Riesgos funcionales
   - Riesgos técnicos
   - Riesgos de seguridad
   - Veredicto (GO / NO-GO / GO_CONDICIONAL)

3. **IMPLEMENT** (si GO/GO_CONDICIONAL)
   - Cambios por archivo
   - Código
   - Explicación breve

4. **AUDIT_CODE** (post-IMPLEMENT)
   - Bugs potenciales
   - Edge cases
   - Cobertura de tests

5. **VERSION** (final)
   - Commit message
   - Changelog
   - Impacto
   - Rollback
```

**Criterios:**
- Orden inmutable (algunos comandos pueden saltar IMPLEMENT, pero orden no cambia)
- Cada sección tiene duración estimada (~líneas o ~tiempo)
- Subsecciones listadas para claridad

---

### 7. Ejemplo de Entrada (requerido, determinista)

```markdown
## Ejemplo de entrada

**Usuario proporciona:**

```
Objetivo: Implementar detección de duplicados por hash perceptual en imágenes
Contexto: Ya tenemos deduplicación exacta por SHA-256 en cache/
Restricciones: Sin dependencias nuevas de ML; usar solo lo disponible en Pillow
```
```

**Criterios:**
- Caso concreto, pequeño (3-5 líneas)
- **Determinista**: mismo input siempre produce mismo análisis
- Valores reales, NO placeholders genéricos (ej: "REAL detección de duplicados", no "<FEATURE>")
- Sin credenciales o paths hardcoded
- Usa backticks o bloque code

---

### 8. Ejemplo de Salida Esperada (requerido, estructura Markdown)

```markdown
## Ejemplo de salida esperada

### PLAN
[30-50 líneas de análisis]
- Objetivo: Deduplicación por hash perceptual en imágenes
- Rutas: src/doc_organize/dedup/perceptual_hash.py, tests/unit/test_perceptual_hash.py
- Componentes: PerceptualHasher, DuplicateResolver
- Riesgos: R1 (falsos positivos), R2 (LoC limit), R3 (test time)

### AUDIT_PLAN
[20 líneas]
- Riesgos funcionales: hash perceptual puede fallar en imágenes muy comprimidas
- Riesgos técnicos: coste de cómputo en carpetas grandes
- Riesgos de seguridad: N/A (no hay entrada de red ni credenciales)
- Veredicto: GO_CONDICIONAL (si añadimos umbral configurable)

[Continúa con IMPLEMENT, AUDIT_CODE, VERSION...]
```

**Criterios:**
- Muestra estructura exacta de salida esperada
- Niveles de detalle (~líneas) son realistas
- Coherente con "Orden de Salida" (sección 6)
- No es pseudocódigo; es Markdown auténtico

---

### 9. Qué Hacer Si Falla (requerido, links cruzados)

```markdown
## Qué hacer si falla

Si encuentras alguno de estos síntomas durante ejecución:

- **"Timeout en PLAN"** → Ver `.claude/EDGE_CASES.md` (Escenario 4: LoC limit)
- **"Merge conflict en .claude/commands/"** → Ver `.claude/EDGE_CASES.md` (Escenario 2: Merge conflicts)
- **"Test suite falla después de IMPLEMENT"** → Ver `.claude/TESTING_GUIDE.md` (Debugging tips)
- **"Contexto perdido entre pasos"** → Consulta `.claude/README.md` (FAQ: "¿Puedo usar dos comandos?")
```

**Criterios:**
- Lista links cruzados a recursos troubleshooting
- Síntomas reales, no hipotéticos
- Links válidos a archivos existentes
- 3-5 síntomas típicos

---

### 10. Referencias y Dependencias (opcional, para comandos complejos)

```markdown
## Referencias

- CLAUDE.md → Lee primero si nuevo al proyecto
- docs/v0.6.7/CLAUDE_COPILOT_MAPPING.md → Equivalencia con Copilot Chat
- `.claude/settings.json` → Configuración de hooks
```

**Criterios:**
- Links relativos o marcas de archivo (p.ej. `CLAUDE.md`)
- Orden: authority → equivalents → config
- Opcional (solo si necesario >= 2 referencias)

---

## Checklist de Comando Bien Formado

Antes de considerar un comando "listo", verifica:

- [ ] Sección 1: Título con `/` y descripción 1 línea
- [ ] Sección 2: "Cuándo usar" con 2-5 casos + 1 antipatrón
- [ ] Sección 3: "Inputs requeridos" con 3-9 campos, todos `[ ]`
- [ ] Sección 4: "⚠️ VALIDACIÓN" con párrafo imperativo + ejemplo detención
- [ ] Sección 5: "Política de cambios" con Obligatorio/Prohibido/Recomendado (si aplica)
- [ ] Sección 6: "Devuelve" en orden explícito (PLAN→AUDIT_PLAN→...→VERSION)
- [ ] Sección 7: "Ejemplo de entrada" determinista, valores reales
- [ ] Sección 8: "Ejemplo de salida" estructura Markdown, no pseudocódigo
- [ ] Sección 9: "Qué hacer si falla" con links a EDGE_CASES/TESTING_GUIDE
- [ ] Sección 10: "Referencias" (si >= 2 necesarias)

---

## Validación de Coherencia Cross-Comando

Si mantienes múltiples comandos, valida:

| Métrica | Estándar | Verificación |
|---------|----------|-------------|
| Orden de secciones | Uniforme (1→2→3→...→10) | Todos comandos siguen? |
| Email de inputs | 3-9 campos | Mínimo 2, máximo 10 campos |
| Longitud PLAN | 30-100 líneas | ±20% tolerance |
| Longitud AUDIT_PLAN | 20-50 líneas | ±15% tolerance |
| Ejemplos deterministas | SÍ, 100% | Sin placeholders genéricos |
| Links rotos | 0 | Revisar all cross-files |
| Síntomas en "Qué hacer" | Reales | Basado en issues/sessions |

---

## Cómo Usar Este Template

**Para crear un comando nuevo:**
1. Copia esta estructura
2. Llena secciones 1-10 con contenido específico del nuevo comando
3. Corre checklist (última sección)
4. Vincula desde CLAUDE.md

**Para auditar un comando existente:**
1. Lee el comando existente
2. Confronta vs esta plantilla, sección por sección
3. Documenta hallazgos (falta de sección, longitud fuera de rango, ejemplos vagos)
4. Prioriza fixes → Fase 3 o siguiente sprint

**Para evolucionar este template:**
- Si descubres sección NEW necesaria, añádela aquí (incremente números)
- Si sección es redundante, marcar como "OPCIONAL → Fase 3"
- Actualizar versión en heading

---

## Versión de este Template

| Versión | Fecha | Cambios |
|---------|-------|---------|
| v0.6.7 | 10 abr 2026 | Initial: 10 secciones, 2 checklists |
| 2026-08-28 | 28 ago 2026 | Ejemplos actualizados a dominio doc_organize (deduplicación de documentos) — antes referenciaban la encarnación anterior de este repo (motores de base de datos) |
