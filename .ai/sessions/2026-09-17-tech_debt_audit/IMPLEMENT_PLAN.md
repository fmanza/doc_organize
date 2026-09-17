# IMPLEMENT_PLAN: Ejecución de Quick Wins

**Fecha**: 2026-09-17  
**Objetivo**: Implementar QW-1 a QW-5 (~ 40 min total)  
**Alcance**: Cambios acotados, sin refactor, bajo riesgo

---

## Estrategia de implementación

### Fase 1: Cambios en código (QW-1, QW-2, QW-3, QW-4)
- **Tiempo**: ~10 min
- **Archivos**: 4 módulos (taxonomy_classification_client, auth_store, project_registry, auth.py)
- **Tipo**: Documentación + logging + especificación de excepciones
- **Risk**: 0 (no cambia lógica, solo mejora)

### Fase 2: Centralización de bugs (QW-5)
- **Tiempo**: ~30 min
- **Archivos**: converter.py + office_detector.py + otros
- **Tipo**: Crear GitHub Issues + actualizar referencias de código
- **Risk**: 0 (documentación pura)

### Fase 3: Validación
- **Tiempo**: ~5 min
- **Acciones**: Linting (ruff), type-checking (mypy), tests existentes
- **Pass/Fail**: Todos deben pasar

---

## Cambios específicos

### QW-1: Documentar `Any` en taxonomy_classification_client.py:243

**Archivo**: `src/doc_organize/ai/taxonomy_classification_client.py`

**Línea actual** (243):
```python
def _clamp_confidence(raw: Any) -> float:
```

**Cambio**: Añadir comentario explicativo (1 línea)

```python
def _clamp_confidence(raw: Any) -> float:  # type: ignore[misc]
    """Restringe confidencia del modelo al rango [0, 1] inclusivo.
    
    Args:
        raw: Valor de confidencia (tipo desconocido de Docling, que no proporciona stubs).
             Típicamente float, int o string numérica. Se clampa al rango [0, 1].
```

---

### QW-2: Logging en auth_store.py:547

**Archivo**: `src/doc_organize/auth/auth_store.py`

**Línea actual** (547-550):
```python
except Exception:
    # Rollback silencioso en caso de error (no aborta apertura de BD)
    pass
```

**Cambio**: Añadir logging + captura de contexto

```python
except Exception as exc:
    # Rollback silencioso en caso de error (no aborta apertura de BD),
    # pero registramos el evento para debugging futuro.
    self.logger.warning(f"No se pudo completar backfill de instance admins: {exc}", exc_info=True)
```

---

### QW-3: Especificar excepciones en project_registry.py:139, 288

**Archivo**: `src/doc_organize/projects/project_registry.py`

**Línea 139** (dentro de `list_projects()`):
```python
except Exception:
    # Cualquier otra excepción (JSON malformado, encoding, etc.)
    self.logger.error(f"Error inesperado leyendo projects.json")
```

**Cambio**: Especificar `json.JSONDecodeError`

```python
except json.JSONDecodeError as exc:
    # projects.json está malformado (JSON inválido)
    self.logger.error(f"projects.json está malformado (JSON inválido): {exc}")
```

**Línea 288** (dentro de `save_projects()`):
```python
except Exception:
    self.logger.error(f"Error inesperado escribiendo projects.json")
```

**Cambio**: Especificar `json.JSONDecodeError`

```python
except json.JSONDecodeError as exc:
    # projects.json está malformado (JSON inválido)
    self.logger.error(f"projects.json está malformado (JSON inválido): {exc}")
```

---

### QW-4: Documentar type:ignore en web/auth.py:159

**Archivo**: `src/doc_organize/web/auth.py`

**Línea actual** (159):
```python
super().__init__(app)  # type: ignore[arg-type]
```

**Cambio**: Añadir comentario explicativo

```python
# type: ignore[arg-type] → BaseHTTPMiddleware.__init__ espera `Callable` sin argumentos,
# pero Starlette acepta `app: ASGIApp` directamente. Mypy no lo entiende, ignoramos.
super().__init__(app)  # type: ignore[arg-type]
```

---

### QW-5: Crear GitHub Issues para bugs reales

**Ubicaciones a documentar**:
- converter.py:183, 223, 230, 277, 293, 467 (bugs reales de Docling/LibreOffice)
- office_detector.py:14 (bug de detección)
- Otros archivos con "bug real" comentado

**Estrategia**:
1. Buscar todos los comentarios con "bug real" en el repo
2. Crear GitHub Issue para cada uno (con sesión + contexto)
3. Actualizar referencias de código para apuntar al issue

**Ejemplo de Issue**:
```markdown
# Bug: Docling `.xls` sin LibreOffice falla sin mensaje claro

**Sesión**: 2026-09-16 (auditoría de deuda técnica)
**Afectado**: converter.py:183
**Descripción**: Cuando Docling intenta convertir archivo `.xls` sin LibreOffice instalado,
falla con excepción genérica sin mensaje descriptivo.

**Workaround**: Ver función `detect_office_status()` en línea 185

**Pasos para reproducir**:
1. Intentar convertir archivo `.xls` en máquina sin LibreOffice
2. Esperado: Mensaje claro "LibreOffice no disponible"
3. Actual: Excepción genérica de Docling

**Referencias de código**:
- converter.py:183 (workaround)
- converter.py:219-230 (batch exception handling)
```

---

## Validación esperada

### Lint
```bash
python -m ruff check src/doc_organize/
# Esperado: 0 errores (sin cambios en lógica, solo documentación)
```

### Type-checking
```bash
python -m mypy src/doc_organize/
# Esperado: 0 errores nuevos (solo mejora)
```

### Tests
```bash
python -m pytest tests/
# Esperado: Todos pasan (no hay lógica modificada)
```

---

## Risk Assessment

| QW | Risk | Justificación |
|----|------|---------------|
| QW-1 | 0 | Solo comentario, sin cambio de lógica |
| QW-2 | 0 | Logging aditivo, no cambia comportamiento |
| QW-3 | Bajo | Mejora captura de errores, podría capturar más excepciones. Verificar con tests. |
| QW-4 | 0 | Solo comentario, sin cambio de lógica |
| QW-5 | 0 | Documentación pura, sin cambio de código |

---

## Próximos pasos

1. ✅ Ejecutar cambios de código (QW-1 a QW-4)
2. ✅ Ejecutar cambios de documentación (QW-5)
3. ✅ Validar con linting + type-checking + tests
4. ✅ Crear PR para v0.9.1
5. ✅ Proceder a AUDIT_CODE después

---

*Plan de implementación completo. Procede a IMPLEMENT.*
