# INTEGRATION_MAP.md

**Versionado**: v0.6.7
**Última actualización**: 18 de abril de 2026
**Propósito**: Gobernanza y sincronización entre `.claude/` (Claude Code) y `.github/` (Copilot Chat)

> Este documento es **autoridad única** para responder:
> - ¿Quién mantiene qué archivo?
> - ¿Cuándo debo sincronizar cambios?
> - ¿Cómo evito desalineación entre platforms?
>
> **Actualización v0.6.7**: [`.github/SHARED_INSTRUCTIONS.md`](.github/SHARED_INSTRUCTIONS.md) es ahora la **fuente única de verdad** para arquitectura, SOLID, patrones, flujos y políticas comunes a ambas plataformas. Este documento (INTEGRATION_MAP.md) gestiona **gobernanza de archivos y sincronización**.

---

## Diferencia: INTEGRATION_MAP.md vs CLAUDE_COPILOT_MAPPING.md

Ambos documentos tratan la relación Claude Code ↔ Copilot Chat, pero con propósitos distintos:

| Documento | Propósito | Quién lo lee | Scope |
|-----------|-----------|-------------|-------|
| **CLAUDE_COPILOT_MAPPING.md** | **Equivalencias**: Qué slash command en Claude Code tiene alternate en Copilot Chat | Usuario final (quiere usar ambas platforms) | 8 comandos (new-feature, hotfix, refactor, etc.) |
| **INTEGRATION_MAP.md** | **Gobernanza**: Cómo mantener `.claude/` y `.github/` sincronizados; quién actualiza qué; cuándo | Maintainer del repo + developers | 13 archivos: `.claude/` + `.github/` |

**Cuándo leer cada uno:**
- 👤 **Usuario final**: "¿Cómo ejecuto `/new-feature` en Copilot Chat?" → Leer [`CLAUDE_COPILOT_MAPPING.md`](../docs/v0.6.7/CLAUDE_COPILOT_MAPPING.md)
- 🔧 **Maintainer**: "¿Quién debe editar `.claude/commands/`?" → Leer [`INTEGRATION_MAP.md`](.github/INTEGRATION_MAP.md) (este archivo)

---

## Concepto: Gobernanza de Dos Plataformas

### Arquitectura actual (v0.6.7)

```
.claude/                           ← Claude Code (Anthropic CLI + VS Code extension)
├── commands/                      # 8 slash commands (AUTORIDAD para Claude Code)
│   ├── new-feature.md
│   ├── hotfix.md
│   ├── refactor.md
│   ├── audit-code.md
│   ├── security-review.md
│   ├── tech-debt.md
│   ├── maturity-assessment.md
│   └── version-closure.md
├── settings.json                  # Hooks globales (ruff, mypy, pytest)
├── settings.local.json            # Config local (no commiteable)
├── README.md                      # Setup guide
├── COMMAND_TEMPLATE.md            # Plantilla normativa (Fase 2)
├── EDGE_CASES.md                  # Troubleshooting (Fase 2)
└── TESTING_GUIDE.md               # Testing patterns (Fase 2)

.github/                           ← Copilot Chat (GitHub Copilot, VS Code extension)
├── copilot-instructions.md        # Política base (AUTORIDAD para Copilot Chat)
├── AGENTS.md                      # Registro central de 10 agentes especializados
├── agents/                        # Agentes especializados (10 disponibles)
│   ├── workflow-director.agent.md
│   ├── plan-architect.agent.md
│   ├── feature-implementer.agent.md
│   ├── hotfix-responder.agent.md
│   ├── code-auditor.agent.md
│   ├── documentation-reviewer.agent.md
│   ├── security-reviewer.agent.md
│   ├── maturity-assessment.agent.md
│   ├── version-closer.agent.md
│   └── explore.agent.md
├── prompts/                       # 9 prompts (8 equivalentes a .claude/commands/ + documentation_review)
│   ├── new_feature.prompt.md
│   ├── hotfix.prompt.md
│   ├── refactor.prompt.md
│   ├── audit_code.prompt.md
│   ├── security_review.prompt.md
│   ├── tech_debt.prompt.md
│   ├── maturity_assessment.prompt.md
│   ├── version_closure.prompt.md
│   └── documentation_review.prompt.md  # Solo Copilot Chat / agente directo (sin equivalente en .claude/commands/)
└── instructions/                  # Instrucciones por área (python, architecture, tests, etc.)

CLAUDE.md                          ← Política transversal (ambas plataformas)
docs/v0.6.7/CLAUDE_COPILOT_MAPPING.md  ← Equivalencias (usuario final)
```

---

## Tabla de Gobernanza: Archivos, Responsables, Frecuencia

| # | Archivo | Plataforma | Owner | Frecuencia | Qué contiene | Sincronización |
|---|---------|-----------|-------|-----------|-------------|---|
| **1** | `.claude/commands/new-feature.md` | Claude Code | Backend Lead | Per-release (Phase change) | Flujo PLAN→AUDIT_PLAN→IMPLEMENT→AUDIT_CODE→VERSION para features | Sync con `.github/prompts/new_feature.prompt.md` (contenido paralelo) |
| **2** | `.claude/commands/hotfix.md` | Claude Code | Backend Lead | Per-release | Flujo PLAN→AUDIT_PLAN→IMPLEMENT→AUDIT_CODE→VERSION para bugs | Sync con `.github/prompts/hotfix.prompt.md` |
| **3** | `.claude/commands/refactor.md` | Claude Code | Backend Lead | Per-release | Flujo PLAN→AUDIT_PLAN→IMPLEMENT→AUDIT_CODE→VERSION para refactors | Sync con `.github/prompts/refactor.prompt.md` |
| **4** | `.claude/commands/audit-code.md` | Claude Code | Backend Lead | Per-release | Flujo PLAN→AUDIT_PLAN→AUDIT_CODE→VERSION (sin IMPLEMENT) | Sync con `.github/prompts/audit_code.prompt.md` |
| **5** | `.claude/commands/security-review.md` | Claude Code | Security Lead | Per-release | Flujo PLAN→AUDIT_PLAN→AUDIT_CODE→VERSION (security-focused) | Sync con `.github/prompts/security_review.prompt.md` |
| **6** | `.claude/commands/tech-debt.md` | Claude Code | Arch Lead | Per-release | Flujo PLAN→AUDIT_PLAN→AUDIT_CODE→VERSION (debt classification) | Sync con `.github/prompts/tech_debt.prompt.md` |
| **7** | `.claude/commands/maturity-assessment.md` | Claude Code | Arch Lead | Q-release (quarterly) | Flujo PLAN→AUDIT_PLAN→AUDIT_CODE→VERSION (repos readiness) | Sync con `.github/prompts/maturity_assessment.prompt.md` |
| **8** | `.claude/commands/version-closure.md` | Claude Code | Backend Lead | Per-release | Flujo VERSION-only (changelog, commit, rollback) | Sync con `.github/prompts/version_closure.prompt.md` |
| **9** | `.claude/settings.json` | Claude Code | DevOps Lead | Ad-hoc (new hooks needed) | Hooks: ruff, mypy, pytest | Documentado en `.claude/README.md` |
| **10** | `.claude/README.md` | Claude Code | DevOps Lead | Per-release (reflect changes) | Setup guide, FAQ, offline tips | Reference from CLAUDE.md |
| **11** | `.github/SHARED_INSTRUCTIONS.md` | Both | Backend Lead + Arch Lead | Per-release (policies change) | **Fuente única de verdad**: arquitectura, SOLID, patrones, flujos, políticas comunes | Authority for both platforms (v0.6.7+) |
| **12** | `CLAUDE.md` | Both | Backend Lead | Per-release (especialidades Claude) | **Especialización**: slash commands, hooks, offline mode, configuración local | References to SHARED_INSTRUCTIONS.md |
| **13** | `.github/copilot-instructions.md` | Copilot Chat | Backend Lead | Per-release | **Especialización**: agentes, prompts de Copilot Chat | References to SHARED_INSTRUCTIONS.md |
| **14** | `docs/v0.6.7/CLAUDE_COPILOT_MAPPING.md` | Both | DevOps Lead | Per-release (new commands) | User-facing matrix + 3 integration options | Authority for equivalences |
| **15** | `.github/AGENTS.md` | Copilot Chat + Claude Code | Arch Lead | Per-release (nuevo agente) | Registro central de 11 agentes: propósito, herramientas, invocación, matriz de relaciones | Sync con `.github/agents/*.agent.md` (añadir entrada cuando se crea agente nuevo) |

---

## Checklist de Sincronización

Cada vez que **actualices un flujo** (PLAN→AUDIT_PLAN→IMPLEMENT, policy, o estructura de salida), ejecuta este **checklist**:

### ✅ Si cambias un comando en `.claude/commands/`

1. [ ] **Lee el comando actualizado** (`/new-feature`, `/hotfix`, etc.)
2. [ ] **Localiza su equivalente** en `.github/prompts/` (e.g., `new_feature.prompt.md`)
3. [ ] **Compara estructura**:
   - ¿Ambos emiten en mismo orden? (PLAN → AUDIT_PLAN → IMPLEMENT → AUDIT_CODE → VERSION)
   - ¿Mismos inputs requeridos?
   - ¿Mismas restricciones y políticas?
4. [ ] **Actualiza prompt en `.github/prompts/`** si no coinciden
5. [ ] **Comenta en PR**: "Sync: `.claude/commands/X.md` ↔ `.github/prompts/X.prompt.md`"
6. [ ] **Valida en lectura cruzada**: Developer no-familiarizado puede leer ambos y notar que son "equivalentes"

### ✅ Si cambias policy en `.github/SHARED_INSTRUCTIONS.md`

1. [ ] **Identifica cambio**: ¿Afecta arquitectura, SOLID, patrones, flujos comunes, o políticas?
2. [ ] **EDITA**: `.github/SHARED_INSTRUCTIONS.md` (fuente única de verdad)
3. [ ] **NO EDITES**: `CLAUDE.md` ni `.github/copilot-instructions.md` automáticamente sincronizarán por referencia
4. [ ] **Actualiza timestamp** en INTEGRATION_MAP.md (este archivo) → "Última actualización"
5. [ ] **Comenta en PR**: "Policy change in SHARED_INSTRUCTIONS.md: <descripción>. Both platforms sync automatically via references."

### ✅ Si cambias especialización en `CLAUDE.md` (slash commands, hooks, offline)

1. [ ] **Identifica cambio**: ¿Afecta solo Claude Code? (slash commands, offline mode, hooks)
2. [ ] **EDITA**: `CLAUDE.md` (no SHARED_INSTRUCTIONS.md)
3. [ ] **Propaga a relevantes**:
   - Si comando cambia: actualizar `.claude/commands/X.md` y `.github/prompts/X.prompt.md`
4. [ ] **Actualiza timestamp** en INTEGRATION_MAP.md (este archivo)
5. [ ] **Comenta en PR**: "Specialization change in CLAUDE.md: <descripción>. Propagated to .claude/commands/ and .github/prompts/"

### ✅ Si cambias estructura de salida (por ejemplo: agregar sección CHANGELOG a VERSION)

1. [ ] **Actualiza COMMAND_TEMPLATE.md** (sección 6: "Devuelve en este orden")
2. [ ] **Actualiza todos 8 comandos** para reflejar nueva estructura
3. [ ] **Actualiza prompts correspondientes** en `.github/prompts/`
4. [ ] **Documenta cambio** en `CLAUDE.md` → nueva sección o referencia
5. [ ] **Comenta en PR**: "Output structure change: Agreguado CHANGELOG a VERSION. Updated in: .claude/commands/*.md, .github/prompts/*.md, COMMAND_TEMPLATE.md"

### ✅ Si agregas un nuevo comando (Post-v0.6.7)

1. [ ] **Crea** `.claude/commands/new-command.md` siguiendo `COMMAND_TEMPLATE.md`
2. [ ] **Crea equivalente** `.github/prompts/new_command.prompt.md`
3. [ ] **Crea agente si aplica** `.github/agents/new-command.agent.md` (si el comando requiere agente especializado)
4. [ ] **Actualiza tablas de referencia**:
   - CLAUDE_COPILOT_MAPPING.md (matriz de equivalencias)
   - INTEGRATION_MAP.md (esta tabla de gobernanza)
   - `.github/AGENTS.md` (registro de agentes — añadir entrada con propósito, herramientas, invocación)
5. [ ] **Agrega entrada en CLAUDE.md** → slash commands disponibles
6. [ ] **Actualiza docstring en `.claude/settings.json`** si afecta hooks
7. [ ] **Comenta en PR**: "New command: `/new-command`. Added in: .claude/commands/, .github/prompts/, .github/agents/, .github/AGENTS.md, CLAUDE_COPILOT_MAPPING.md, INTEGRATION_MAP.md"

---

## Responsables por Rol

| Rol | Responsabilidades | Activa cuando | Contacto |
|-----|---|---|---|
| **Backend Lead** | Mantiene CLAUDE.md, .claude/commands/, .github/copilot-instructions.md; decide política | Policy change, command change | Backend @channel |
| **DevOps Lead** | Mantiene settings.json, .claude/README.md, CLAUDE_COPILOT_MAPPING.md; maneja hooks | New tools, offline needs, integrations | DevOps @channel |
| **Security Lead** | Mantiene security-review.md y security_review.prompt.md; revisa policy | Security findings, new threats | Security @channel |
| **Arch Lead** | Mantiene maturity-assessment, tech-debt; oversee SOLID compliance | Architecture decisions, tech debt | Arch @channel |

---

## Pre-Release Checklist (Antes de Publicar v0.6.8+)

Antes de cerrar una release, ejecuta **este checklist** para asegurar coherencia:

### Phase 1: Validación de Cabeceras
- [ ] `.github/SHARED_INSTRUCTIONS.md` tiene versión actualizada (v0.6.X) y timestamp correcto
- [ ] `CLAUDE.md` tiene versión actualizada (v0.6.X)
- [ ] `.github/copilot-instructions.md` tiene referencia a SHARED_INSTRUCTIONS.md
- [ ] `.claude/COMMAND_TEMPLATE.md` tiene versión actualizada
- [ ] `docs/v0.6.7/CLAUDE_COPILOT_MAPPING.md` tiene versión actualizada
- [ ] INTEGRATION_MAP.md tiene "Última actualización" = hoy

### Phase 2: Validación de 8 Comandos
- [ ] Cada comando en `.claude/commands/` sigue estructura de COMMAND_TEMPLATE.md (10 secciones)
- [ ] Cada comando tiene ejemplo determínístico (sin placeholders genéricos)
- [ ] Cada prompt en `.github/prompts/` tiene equivalente `.claude/commands/` versión

### Phase 3: Validación de Referencias
- [ ] SHARED_INSTRUCTIONS.md enlaza a AGENTS.md, INTEGRATION_MAP.md ✅
- [ ] CLAUDE.md enlaza a SHARED_INSTRUCTIONS.md ✅
- [ ] `.github/copilot-instructions.md` enlaza a SHARED_INSTRUCTIONS.md ✅
- [ ] `.claude/README.md` enlaza a CLAUDE.md ✅
- [ ] CLAUDE_COPILOT_MAPPING.md enlaza a SHARED_INSTRUCTIONS.md ✅
- [ ] No hay links rotos (buscar `[broken]` o URLs muertas)

### Phase 4: Validación de Contenido
- [ ] Offline section en CLAUDE.md doc claramente: qué funciona sin internet ✅
- [ ] FAQ en `docs/examples/claude_code_usage_complete_example.md` tiene 18+ preguntas ✅
- [ ] No hay duplicación entre CLAUDE_COPILOT_MAPPING.md (equivalencias) e INTEGRATION_MAP.md (gobernanza)

### Phase 5: Co señ Off
- [ ] [ ] Backend Lead sign-off on CLAUDE.md + commands (name + date)
- [ ] [ ] DevOps Lead sign-off on settings.json + README (name + date)
- [ ] [ ] Security Lead sign-off on security-review (name + date)
- [ ] [ ] Arch Lead sign-off on maturity/tech-debt (name + date)

---

## Cómo Mantener Este Documento Actualizado

**Este documento (INTEGRATION_MAP.md) debe actualizarse cuando:**

1. Se agrega un nuevo comando (p.ej. `/analyze-performance`)
2. Se cambia política de salida (p.ej., PLAN ahora requiere mínimo 100 líneas, no 30)
3. Se cambia responsable de un archivo
4. Se descubre nueva sincronización necesaria (p.ej., `.claude/EDGE_CASES.md` ↔ `.github/troubleshooting.md`)

**Responsable principal**: Backend Lead + DevOps Lead (revisado trimestralmente)

---

## Versión

| Versión | Fecha | Cambios |
|---------|-------|---------|
| v0.6.7 | 10 abr 2026 | Initial: 13 files, 2 platforms, 4 responsables, pre-release checklist |
| v0.6.7.1 | 13 abr 2026 | Add `.github/AGENTS.md` (fila 14), `.github/agents/` (10 agentes), `documentation_review.prompt.md` (9º prompt), checklist actualizado para nuevos agentes |
