# Directorio `.claude/`

Configuración y comandos especializados para **Claude Code** (Anthropic, extensión en VS Code).

---

## Archivos

### `settings.json`
Configuración global de hooks y comportamiento de Claude Code.

**Hooks disponibles**:
- `ruff check src tests` — Linting/formatting (siempre activado)
- `mypy src` — Type checking (opcional, puede omitirse si es lento)
- `pytest --collect-only` — Test recolección sin ejecución (opcional)

**Uso**: No editar directamente; usar `.claude/settings.local.json` para customizaciones locales.

```json
{
  "hooks": {
    "PostToolUse": [
      { "matcher": "Edit|Write", "hooks": [...] }
    ]
  }
}
```

**Referencia**: [settings.json.example](settings.json.example)

---

### `settings.local.json`
Configuración local personalizada. **No se commitea** (debe estar en `.gitignore`).

**Usos comunes**:

1. **Desabilitar hooks lentos** (p.ej. mypy en máquina lenta):
   ```json
   {
     "hooks": {
       "PostToolUse": [
         {
           "matcher": "Edit|Write",
           "hooks": [
             { "type": "command", "command": "python -m ruff check src tests --quiet 2>&1 | head -15" }
           ]
         }
       ]
     }
   }
   ```

2. **Cambiar comando de ruff**:
   ```json
   {
     "hooks": {
       "PostToolUse": [
         {
           "matcher": "Edit|Write",
           "hooks": [
             { "type": "command", "command": "python -m ruff check . --quiet 2>&1 | head -20" }
           ]
         }
       ]
     }
   }
   ```

**Referencia**: [settings.json.example](settings.json.example) como guía de qué cambiar

---

### `commands/`
Directorio con slash commands para Claude Code.

**Comandos disponibles**:
- `new-feature.md` — Nueva funcionalidad (`/new-feature`)
- `hotfix.md` — Corrección de bug (`/hotfix`)
- `refactor.md` — Refactor sin cambios funcionales (`/refactor`)
- `audit-code.md` — Auditoría técnica (`/audit-code`)
- `security-review.md` — Revisión de seguridad (`/security-review`)
- `tech-debt.md` — Inventario de deuda técnica (`/tech-debt`)
- `maturity-assessment.md` — Evaluación de madurez (`/maturity-assessment`)
- `version-closure.md` — Cierre de versión (`/version-closure`)

**Política**: Editar solo si se añaden nuevos comandos o se actualizan máquinas de estado. Para cambios en estructura, coordinar con `.github/copilot-instructions.md`.

---

## Flujo de trabajo

### Paso 1: Usar `settings.json` global
```bash
# Predeterminado; sin acciones requeridas
```

### Paso 2: Customizar localmente (opcional)
```bash
# Crear .claude/settings.local.json con ajustes
vim .claude/settings.local.json  # Tu editor favorito
# Guardar (no se commitea, está en .gitignore)
```

### Paso 3: Usar slash commands
```
# En Claude Code, escribe:
/new-feature
[contexto]

# O:
/hotfix
[bug description]

# etc.
```

---

## Configuración de `.gitignore`

Asegúrate de que `.gitignore` incluya:

```gitignore
# Claude Code local settings (no commitear)
.claude/settings.local.json
```

---

## Relación con `.github/copilot-instructions.md`

| Archivo | Plataforma | Rol |
|---------|-----------|-----|
| `.claude/settings.json` | Claude Code | Hooks + configuración |
| `.claude/commands/*.md` | Claude Code | Slash commands |
| `.github/copilot-instructions.md` | Copilot Chat | Política base + agentes |
| `.github/prompts/*.md` | Copilot Chat | Prompts (Fase 2) |

**Sincronización**: Si cambias un comando en `.claude/commands/`, considera si `.github/copilot-instructions.md` o `.github/prompts/` necesitan actualización.

Para gobernanza completa entre plataformas, ver: [`.github/INTEGRATION_MAP.md`](../.github/INTEGRATION_MAP.md)

---

## Ejecución Offline

Claude Code funciona sin internet para tareas locales. Ver sección **"Ejecución Offline"** en [`CLAUDE.md`](../CLAUDE.md) para:
- Qué comandos funcionan sin internet
- Qué requiere acceso (GitHub, SonarQube, APIs)
- Cómo configurar `settings.local.json` para modo offline

---

## Troubleshooting

Si encuentras problemas al usar Claude Code o slash commands, consulta **[EDGE_CASES.md](EDGE_CASES.md)** para:
- Comando interrumpido a mitad de ejecución (token budget exhausted)
- Tests fallan después de IMPLEMENT
- Módulo nuevo no auto-importa (lazy-loading incompleto)
- Heurística devuelve valor inesperado (p.ej. packet size calculation)
- Y más escenarios comunes con diagnostico y soluciones

**Versión**: EDGE_CASES.md v0.10.0 (9 escenarios documentados)

---

## FAQ

### ¿Mi `settings.local.json` no afecta nada?
Verifica que esté guardado en la ruta correcta: `.claude/settings.local.json` (mismo nivel que `settings.json`).

### ¿Puedo desabilitar todos los hooks?
Sí, en `settings.local.json`:
```json
{
  "hooks": {
    "PostToolUse": []
  }
}
```

### ¿Qué si ruff/mypy/pytest no están instalados?
Hooks opcionales (`optional: true`) los ignoran silenciosamente. Hooks obligatorios (como ruff) fallarán; instala con `pip install -r requirements.txt` o `pip install ruff mypy pytest`.

### ¿Puedo agregar más hooks?
Sí, en `settings.local.json`. Ejemplo: agregar `pylint`:
```json
{
  "hooks": {
    "PostToolUse": [
      {
        "matcher": "Edit|Write",
        "hooks": [
          { "type": "command", "command": "python -m ruff check src tests --quiet 2>&1 | head -15" },
          { "type": "command", "command": "python -m pylint src --disable=all 2>&1 | head -10", "optional": true }
        ]
      }
    ]
  }
}
```

### ¿Dónde reporto problemas con hooks?
Crea un issue en el repositorio con:
- Comando que ejecutaste (`/new-feature`, etc.)
- Línea de error del hook (si está disponible)
- Sistema operativo + versión Python

---

## Referencias

- **CLAUDE.md**: Política general para Claude Code
- **docs/v0.6.7/CLAUDE_COPILOT_MAPPING.md**: Mapeo Claude Code ↔ Copilot Chat
- **docs/examples/claude_code_usage_complete_example.md**: Ejemplos completos de flujos
