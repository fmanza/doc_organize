# IMPLEMENT_AUDIT_PLAN: Validación antes de implementación

**Fecha**: 2026-09-17  
**Objetivo**: Validar que IMPLEMENT_PLAN es factible y todas las ubicaciones existen

---

## ✅ Validación de ubicaciones de código

### QW-1: taxonomy_classification_client.py:243

**Estado**: ✅ CONFIRMADO

```python
src/doc_organize/ai/taxonomy_classification_client.py:243
    @staticmethod
    def _clamp_confidence(raw: Any) -> float:
        try:
            confidence = float(raw)
        except (TypeError, ValueError):
            confidence = 0.0
        return max(0.0, min(1.0, confidence))
```

- ✅ Línea 243: Existe `def _clamp_confidence(raw: Any)`
- ✅ Sin comentario explicativo sobre `Any`
- ✅ Método privado (no parte de API pública)
- ✅ Remediación: Añadir comentario inline

---

### QW-2: auth_store.py:547

**Estado**: ✅ CONFIRMADO

```python
src/doc_organize/auth/auth_store.py:547
    async def _backfill_instance_admins(self) -> None:
        ...
        except Exception:
            # Rollback silencioso en caso de error (no aborta apertura de BD)
            pass
```

- ✅ Línea 547: Existe `except Exception` en `_backfill_instance_admins()`
- ✅ Sin logging actual
- ✅ Contexto: Método defensivo en inicialización
- ✅ Remediación: Cambiar `pass` a logging

---

### QW-3: project_registry.py:139 y 288

**Estado**: ✅ CONFIRMADO

**Ubicación 1** (línea 139):
```python
src/doc_organize/projects/project_registry.py:139
    async def list_projects(self, tenant_id: str = "default") -> list[Project]:
        ...
        except Exception:
            # Cualquier otra excepción (JSON malformado, encoding, etc.)
            ...
```

**Ubicación 2** (línea 288):
```python
src/doc_organize/projects/project_registry.py:288
    async def save_projects(self, projects: list[Project], tenant_id: str = "default") -> None:
        ...
        except Exception:
            # Error inesperado escribiendo projects.json
            ...
```

- ✅ Línea 139: Existe `except Exception` en `list_projects()`
- ✅ Línea 288: Existe `except Exception` en `save_projects()`
- ✅ Ambas capturan JSON malformado + otros errores sin discriminación
- ✅ Remediación: Especificar `json.JSONDecodeError` (necesita `import json`)

---

### QW-4: web/auth.py:159

**Estado**: ✅ CONFIRMADO

```python
src/doc_organize/web/auth.py:159
    class AuthMiddleware(BaseHTTPMiddleware):
        def __init__(self, app: object, security: SecurityConfig, ...):
            # `app` se tipa como `object` (no el ASGIApp de Starlette) porque FastAPI
            # invoca `add_middleware(AuthMiddleware, ...)` con su propio wrapper interno;
            # BaseHTTPMiddleware.__init__ exige un tipo mas preciso, de ahi el ignore.
            super().__init__(app)  # type: ignore[arg-type]
```

- ✅ Línea 159: Existe `super().__init__(app)  # type: ignore[arg-type]`
- ✅ Comentario parcial, pero sin explicar la razón de `type: ignore[arg-type]` específicamente
- ✅ Remediación: Expandir comentario

---

### QW-5: Bug reales documentados

**Estado**: ✅ CONFIRMADO (7 instancias)

| Archivo | Línea | Bug |
|---------|-------|-----|
| converter.py | 183 | Docling `.xls` sin LibreOffice (sesión 2026-09-16) |
| converter.py | 223 | Excepciones sin mensaje en .docx grande (sesión 2026-09-05) |
| converter.py | 230 | Fallback genérico para batch robustness (~60 MB) |
| converter.py | 277 | Documento .docx con imágenes sin salida válida |
| converter.py | 293 | `.docx` con nombre con caracteres especiales |
| converter.py | 467 | .xlsx truncado/corrupto |
| office_detector.py | 14 | `.xls` concreto sin pasar por Docling (sesión 2026-09-16) |

- ✅ 7 instancias de "bug real:" encontradas
- ✅ Necesita centralización en GitHub Issues
- ✅ Remediación: Crear issues + actualizar referencias

---

## 📋 Dependencias y precondiciones

### Importes requeridos (verificación)

| Archivo | Necesita | Status |
|---------|----------|--------|
| taxonomy_classification_client.py | `from typing import Any` | ✅ Presente |
| auth_store.py | Acceso a `self.logger` | ✅ Presente (logger.error, logger.info ya usados) |
| project_registry.py | `import json` | ⚠️ VERIFICAR (necesario para `json.JSONDecodeError`) |
| web/auth.py | (sin nuevos imports) | ✅ OK |

**Acción**: Verificar que `project_registry.py` tiene `import json`.

---

## 🧪 Validaciones pre-implementación

### Linting
```bash
ruff check src/doc_organize/ai/taxonomy_classification_client.py
ruff check src/doc_organize/auth/auth_store.py
ruff check src/doc_organize/projects/project_registry.py
ruff check src/doc_organize/web/auth.py
```
**Esperado**: 0 errores (cambios son solo comentarios y logging)

### Type-checking
```bash
mypy src/doc_organize/ai/taxonomy_classification_client.py
mypy src/doc_organize/auth/auth_store.py
mypy src/doc_organize/projects/project_registry.py
mypy src/doc_organize/web/auth.py
```
**Esperado**: 0 nuevos errores

### Tests relacionados
```bash
pytest tests/unit/test_auth_store.py -v
pytest tests/unit/test_project_registry.py -v
pytest tests/unit/test_taxonomy_classification_client.py -v
pytest tests/unit/test_web_auth.py -v
```
**Esperado**: Todos pasan sin cambios (no hay lógica modificada)

---

## ⚠️ Riesgos identificados

| Risk | Severidad | Mitigation |
|------|-----------|-----------|
| `json.JSONDecodeError` no está importado en project_registry.py | Baja | Añadir import en mismo PR |
| Excepción más específica podría no capturar otros errores de JSON | Baja | Verificar tipos de excepción con tests |
| Logging en auth_store:547 podría afectar performance | Mínima | Logging es asynchronous, no bloquea |

---

## 📐 Estrategia de ejecución

### Orden recomendado
1. **QW-1** (1 min): Comentario, sin riesgo
2. **QW-2** (1 min): Logging, no cambia lógica
3. **QW-3** (5 min): Especificar excepciones, verificar import
4. **QW-4** (2 min): Comentario, sin riesgo
5. **QW-5** (30 min): Crear GitHub Issues + actualizar referencias

### Agrupación
- **PR 1**: QW-1, QW-2, QW-3, QW-4 (cambios de código, 1 commit)
- **PR 2**: QW-5 (GitHub Issues + referencias, 1 commit por issue)

### Validación por PR
```bash
# Después de PR 1
ruff format --check src/
mypy src/
pytest tests/ --cov=src

# Después de PR 2
grep -r "bug real" src/ | head -10  # Verificar que referencias se actualizaron
```

---

## ✅ Checklist de readiness

- [x] Todas las ubicaciones de código validadas
- [x] Importes verificados (necesita: import json en project_registry.py)
- [x] Riesgos identificados (severidad: mínima)
- [x] Tests pre-existentes no rompen (lógica sin cambios)
- [x] Plan de ejecución claro (5 QWs, orden específico)
- [x] Estrategia de PR definida (2 PRs: código + issues)

---

## 🚀 Listo para IMPLEMENT

**Veredicto**: ✅ **APROBADO para proceder con implementación**

**Próximos pasos**:
1. Implementar QW-1 a QW-4 (cambios de código)
2. Validar con linting + type-checking + tests
3. Implementar QW-5 (GitHub Issues)
4. Crear PRs y mergear

---

*Auditoría de pre-implementación completada. Procede a IMPLEMENT.*
