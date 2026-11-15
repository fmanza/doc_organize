# Audit Plan: Enriquecimiento de Metadatos en doc_organize

**Versión:** 1.0  
**Fecha:** 2026-11-15  
**Referencia PLAN:** [PLAN_METADATA_ENHANCEMENT.md](PLAN_METADATA_ENHANCEMENT.md)

---

## 📋 Objetivo del Audit

Verificar que cada **FASE** del enriquecimiento de metadatos se implementa correctamente, sin regresiones, con calidad de código adecuada y documentación completa.

El audit se realiza **al finalizar cada fase** antes de hacer merge a `develop`.

---

## 🔍 Estructura del Audit

```
AUDIT_FASE_N
├─ 1. Revisión de Código (Code Review)
├─ 2. Tests y Coverage
├─ 3. Compatibilidad y Migraciones
├─ 4. Performance
├─ 5. Documentación
├─ 6. Integración con Herramientas Existentes
└─ 7. Criterios de Go/No-Go
```

---

## 🎯 AUDIT FASE 1: Metadatos Técnicos Básicos

### 1.1 Revisión de Código

**Archivo: `core/models.py`**
- [ ] `DocumentMetadata` tiene exactamente 5 campos nuevos: `created_time`, `mime_type`, `detected_language`, `file_permissions`, `owner_name`
- [ ] Todos los campos son `Optional[type]` o tienen `default=None`
- [ ] Docstrings presentes y claros en cada campo
- [ ] `CacheEntry` tiene los mismos 5 campos (excepto que no todos se usan)
- [ ] No hay cambios a campos existentes (compatibilidad hacia atrás)
- [ ] `@field_validator` aplicado si es necesario

**Archivo: `scanner/document_scanner.py`**
- [ ] Nueva función `_extract_basic_metadata()` existe y está correctamente estructurada
- [ ] Funciones helper (`_detect_mime_type`, `_get_creation_time`, `_get_permissions`, `_get_owner_name`) están presentes
- [ ] Detección de tipo MIME intenta `mimetypes` primero, luego `magic` (fallback correcto)
- [ ] Extracción de fecha creación maneja macOS (`st_birthtime`) y otros SO
- [ ] Permisos se extraen en formato octal (3 dígitos)
- [ ] Propietario se intenta vía `pwd` (Unix) y `win32security` (Windows), con fallback a None
- [ ] Todos los try-except están presentes y loguean advertencias
- [ ] Integración en `_build_file_node()` pasa metadatos a `_DiscoveredFile`
- [ ] En `_hash_all()` los metadatos básicos se pasan a `DocumentMetadata()`

**Archivo: `converter/converter.py`**
- [ ] `ConversionResult` tiene campo `detected_language` (tipo `str | None`)
- [ ] Campo tiene docstring correcto

**Archivo: `language_detector.py` (nuevo)**
- [ ] Existe clase `LanguageDetector` con método `detect_language()`
- [ ] Lee fichero JSON de Docling correctamente
- [ ] Extrae `metadata.language` si está disponible
- [ ] Fallback correcto si no hay idioma detectado
- [ ] Logging de errores presente

### 1.2 Tests y Coverage

**Tests nuevos que deben existir:**
- [ ] `tests/unit/test_scanner_metadata_phase1.py` con 4+ tests
  - [ ] `test_detect_mime_type_pdf()` — verifica "application/pdf" para .pdf
  - [ ] `test_detect_mime_type_fallback_binary()` — fallback a "application/octet-stream"
  - [ ] `test_extract_basic_metadata_complete()` — todos 5 campos presentes
  - [ ] `test_extract_creation_time_macos()` — maneja `st_birthtime`
  - [ ] `test_extract_permissions_octal()` — formato octal 3 dígitos
  - [ ] `test_extract_owner_name()` — intenta pwd/win32security

**Coverage:**
- [ ] `DocumentScanner._extract_basic_metadata()` coverage > 85%
- [ ] `LanguageDetector.detect_language()` coverage > 80%
- [ ] Tests corren sin warnings de deprecación
- [ ] Tests pasen en Windows y Unix (si es posible mockearlos)

**Test de migración de BD:**
- [ ] `tests/unit/test_cache_migration.py` existe
  - [ ] `test_old_cache_loads_without_errors()` — BD anterior se carga
  - [ ] `test_new_columns_created_on_first_scan()` — nuevas columnas existen después de escaneo
  - [ ] `test_old_entries_have_null_new_fields()` — campos legacy son NULL
  - [ ] `test_new_entries_fill_all_fields()` — nuevo escaneo rellena todos

### 1.3 Compatibilidad y Migraciones

**Base de datos (`cache.db`)**
- [ ] Migración definida en `cache/cache_manager.py` o módulo new
- [ ] `ALTER TABLE` statements correctos (agregan columnas, no las reemplazan)
- [ ] Migración es idempotente (se puede ejecutar 2x sin error)
- [ ] Versión de schema incrementada (`CACHE_DB_SCHEMA_VERSION`)
- [ ] Se respeta WAL mode si estaba activo

**Compatibilidad de API:**
- [ ] `ScanResult` sigue siendo igual (no cambió)
- [ ] `DocumentMetadata.from_cache_entry()` funciona con FASE 1 (aunque algunos campos sean None)
- [ ] Exportaciones XLSX/JSON incluyen los campos nuevos sin quebrar esquema
- [ ] Clientes antiguos que ignoran campos nuevos siguen funcionando

### 1.4 Performance

- [ ] Tiempo de escaneo aumenta < 5% (métrica: 1000 ficheros small)
  - [ ] Detección MIME no es bottleneck
  - [ ] Extracción de propietario no bloquea en red
- [ ] Detectar lenguaje NO ralentiza escaneo (se hace después, con Docling)
- [ ] Uso de memoria no se incrementa significativamente

### 1.5 Documentación

**Archivos nuevos/actualizados:**
- [ ] `docs/guides/metadata-schema.md` existe y documenta:
  - [ ] Tabla de campos FASE 1 con tipo, descripción, ejemplo
  - [ ] Tipo MIME: cómo se detecta, lista de ejemplos
  - [ ] Fecha creación: diferencia con modificación, SOs soportados
  - [ ] Permisos: formato octal, valores esperados
  - [ ] Propietario: solo en sistemas de ficheros locales
  - [ ] Idioma: cómo se detecta (futuro), soporte actual (None)

- [ ] `docs/guides/database-migration.md` existe y cubre:
  - [ ] Qué cambios hubo en cache.db
  - [ ] Cómo migrar desde v1.4.0
  - [ ] Qué pasa si se vuelve a v1.4.0 (no es posible)
  - [ ] Backup automático antes de migración

- [ ] `CHANGELOG.md` actualizado:
  - [ ] Entrada clara para FASE 1
  - [ ] Breaking changes (si los hay) — Hay que documentar si alguno
  - [ ] Ejemplos de uso de campos nuevos

- [ ] Docstrings en código presente:
  - [ ] Cada campo nuevo en modelos tiene description
  - [ ] Funciones nuevas tienen docstring con Args, Returns, Raises

### 1.6 Integración con Herramientas Existentes

- [ ] `zensical build --strict` pasa sin errores
- [ ] Links en documentación nuevos/actualizados son válidos
- [ ] Type checking (`mypy src`) pasa sin errores
- [ ] Linting (`ruff check src`) sin errores críticos
- [ ] Formateo (`ruff format src`) aplica sin cambios forzados
- [ ] Tests (`pytest tests/unit/test_scanner_metadata_phase1.py`) pasen todos
- [ ] Exportación XLSX/JSON no genera errores con nuevos campos

### 1.7 Criterios de Go/No-Go FASE 1

**GO si:**
- ✅ Todos los checks de 1.1-1.6 pasan
- ✅ 4+ tests unitarios pasen sin fallos
- ✅ Coverage > 80% en código nuevo
- ✅ Documentación es precisa y completa
- ✅ No hay regresiones en tests existentes

**NO-GO si:**
- ❌ Algún test falla o hay excepciones no capturadas
- ❌ Coverage < 70%
- ❌ Documentación incompleta o con links rotos
- ❌ Regresiones en tests de scanner o modelos existentes
- ❌ Migración BD falla en algún SO

**Acción si NO-GO:**
1. Listar los issues específicos
2. Arreglar en rama feature
3. Re-auditar antes de merge

---

## 🎯 AUDIT FASE 2: Enriquecimiento de Contenido

### 2.1 Revisión de Código

**Archivo: `core/models.py`**
- [ ] `DomainDocument` tiene exactamente 4 campos nuevos: `author`, `description`, `keywords`, `keywords_confidence`
- [ ] `author` es `str | None`
- [ ] `description` es `str | None`
- [ ] `keywords` es `list[str]` con default vacío
- [ ] `keywords_confidence` es `float` con validadores `ge=0.0, le=1.0`
- [ ] Todos tienen docstrings adecuados
- [ ] No hay cambios a campos existentes

**Archivo: `ai/content_extraction_client.py` (nuevo)**
- [ ] Clase `ContentExtractionClient` existe
- [ ] Método `extract_content_metadata()` recibe parámetros correctos
- [ ] Llamada a LiteLLM proxy bien formada
- [ ] Response JSON parseado correctamente
- [ ] Fallbacks en caso de error (retorna None, [], 0.0)
- [ ] Logging detallado de errores
- [ ] Timeout configurado (no bloquea indefinidamente)

**Archivo: `converter/metadata_extractor.py` (nuevo)**
- [ ] Clase `MetadataExtractor` con métodos static
- [ ] `extract_author_from_pdf()` intenta PyPDF2, fallback a None
- [ ] `extract_author_from_office()` usa python-docx para .docx/.xlsx/.pptx
- [ ] Ambos métodos tienen try-except y logging
- [ ] No hay dependencias no documentadas

**Archivo: `context/context_builder.py`**
- [ ] Método `_enrich_domain_document()` existe
- [ ] Llama a `MetadataExtractor` y `ContentExtractionClient`
- [ ] Intenta autor PDF primero, luego Office
- [ ] IA se ejecuta en paralelo (no secuencial)
- [ ] Resultado se asigna a `DomainDocument` correctamente
- [ ] Fallback si alguno falla: continúa con None

### 2.2 Tests y Coverage

**Tests nuevos:**
- [ ] `tests/unit/test_content_extraction.py` con 4+ tests
  - [ ] `test_extract_author_from_pdf_success()` — obtiene autor válido
  - [ ] `test_extract_author_from_pdf_not_found()` — retorna None sin error
  - [ ] `test_extract_author_from_office_docx()` — docx funciona
  - [ ] `test_extract_content_metadata_structure()` — desc, keywords, confidence válidos
  - [ ] `test_extract_content_metadata_max_keywords()` — respeta max_keywords
  - [ ] `test_content_extraction_handles_missing_file()` — no falla si .md no existe

**Mocking:**
- [ ] `ContentExtractionClient` se puede mockear para no llamar real a LiteLLM
- [ ] Tests unitarios no hacen llamadas HTTP reales

**Coverage:**
- [ ] `MetadataExtractor` coverage > 85%
- [ ] `ContentExtractionClient` coverage > 80%
- [ ] `ContextBuilder._enrich_domain_document()` coverage > 75%

### 2.3 Compatibilidad y Migraciones

**Context.json:**
- [ ] `DomainDocument` en `context.json` incluye 4 campos nuevos
- [ ] Ficheros antiguos sin los campos se cargan correctamente (fields son `None`)
- [ ] Serialización/deserialización sin errores

**API:**
- [ ] `ContextBuilder.build()` sigue teniendo el mismo signature
- [ ] Sub-fase A (reglas) no se altera
- [ ] Sub-fase B (IA) no se altera
- [ ] Enriquecimiento es optional (configurable)

### 2.4 Performance

- [ ] Extracción de autor PDF < 100ms por documento
- [ ] Extracción de Office metadata < 100ms por documento
- [ ] Llamada IA (descripción + keywords) < 2s por documento
- [ ] No hay bloqueos del event loop
- [ ] Tamaño `context.json` aumenta < 10% (con nuevos campos)

### 2.5 Documentación

**Archivos nuevos:**
- [ ] `docs/guides/content-extraction.md` documenta:
  - [ ] Cómo funciona extracción de autor
  - [ ] Qué formatos soportan autor (PDF, DOCX, XLSX)
  - [ ] Generación automática de descripción y keywords con IA
  - [ ] Confianza de keywords y qué significa
  - [ ] Ejemplos JSON de `DomainDocument` con nuevos campos
  - [ ] Cómo desactivar extracción si se quiere

- [ ] `CHANGELOG.md` actualizado con FASE 2

### 2.6 Integración

- [ ] `zensical build --strict` pasa
- [ ] `mypy src` pasa
- [ ] `ruff check src` pasa
- [ ] `pytest tests/unit/test_content_extraction.py` pasa todo
- [ ] Exportación XLSX/JSON incluye nuevos campos

### 2.7 Criterios de Go/No-Go FASE 2

**GO si:**
- ✅ Todos checks 2.1-2.6 pasan
- ✅ 6+ tests unitarios pasen
- ✅ Coverage > 75%
- ✅ No hay regresiones en tests de FASE 1 o anteriores
- ✅ Documentación completa

**NO-GO si:**
- ❌ Algún test falla
- ❌ Coverage < 70%
- ❌ Llamadas reales a LiteLLM en tests unitarios
- ❌ Documentación incompleta

---

## 🎯 AUDIT FASE 3: Trazabilidad de Clasificación

### 3.1 Revisión de Código

**Archivo: `core/models.py`**
- [ ] `DomainDocument` tiene 3 campos nuevos: `classification_timestamp`, `classification_model_version`, `domain_confidence_breakdown`
- [ ] `Context` tiene 3 campos nuevos: `classification_timestamp`, `ai_model_version`, `rules_engine_version`
- [ ] `classification_timestamp` es `str | None` (ISO 8601)
- [ ] `classification_model_version` es `str | None` (p.ej. "claude-opus-5-5")
- [ ] `domain_confidence_breakdown` es `dict[str, float] | None`
- [ ] Todos tienen docstrings claros

**Archivo: `ai/domain_classification_client.py`**
- [ ] Constante `MODEL_VERSION = "X.X"` definida
- [ ] `classify()` retorna resultado con `model_version` y `timestamp`
- [ ] `MODEL_VERSION` se bumpea en CHANGELOG cuando cambien prompts

**Archivo: `context/rules_version.txt`**
- [ ] Fichero existe en `src/doc_organize/context/rules_version.txt`
- [ ] Contiene versión semver (p.ej. "1.2.0")
- [ ] Se carga correctamente por `ContextBuilder`

**Archivo: `context/context_builder.py`**
- [ ] `__init__` carga `self.ai_model_version` y `self.rules_version`
- [ ] `build()` anota timestamps en `DomainDocument`
- [ ] Sub-fase A asigna `classification_model_version = "rules-" + version`
- [ ] Sub-fase B asigna `classification_model_version` del cliente IA
- [ ] `domain_confidence_breakdown` tiene desglose: `{"reglas": X, "ai": Y, "final": Z}`
- [ ] Timestamps son ISO 8601 válidos

### 3.2 Tests y Coverage

**Tests nuevos:**
- [ ] `tests/unit/test_versioning.py` con 3+ tests
  - [ ] `test_load_rules_version()` — carga correctamente
  - [ ] `test_ai_model_version_in_classification()` — se asigna en resultado
  - [ ] `test_confidence_breakdown_structure()` — desglose tiene estructura correcta
  - [ ] `test_timestamp_iso8601_format()` — timestamp es válido ISO 8601

**Coverage:**
- [ ] `ContextBuilder.build()` coverage > 80% (verificar versioning)
- [ ] Carga de `rules_version.txt` coverage > 90%

### 3.3 Documentación

- [ ] `docs/guides/versioning.md` existe y explica:
  - [ ] Cómo se versionan las reglas
  - [ ] Cómo se versionan los modelos IA
  - [ ] Qué significa cada versión en `domain_confidence_breakdown`
  - [ ] Ejemplos de context.json con versiones

- [ ] `CHANGELOG.md` documenta:
  - [ ] Bump de `MODEL_VERSION` cuando hay cambios de prompt
  - [ ] Cambios en `rules_version.txt`

### 3.4 Criterios de Go/No-Go FASE 3

**GO si:**
- ✅ 3+ tests pasen
- ✅ Coverage > 80%
- ✅ Versionado funciona en ambas sub-fases
- ✅ Documentación completa
- ✅ No hay regresiones

**NO-GO si:**
- ❌ Tests fallan
- ❌ Timestamps mal formados
- ❌ `rules_version.txt` no se carga

---

## 🎯 AUDIT FASE 4: Auditoría y Lineage

### 4.1 Revisión de Código

**Archivo: `core/models.py`**
- [ ] `DocumentLineageEntry` existe con campos: `timestamp`, `action`, `actor`, `old_value`, `new_value`
- [ ] `action` es `Literal` con valores válidos: `imported`, `classified`, `reclassified`, `archived`, `accessed`
- [ ] `DomainDocument` tiene 4 campos nuevos: `origin`, `lineage`, `preservation_status`, `retention_expiry`
- [ ] `origin` es `Literal["imported", "scanned", "created", "migrated"]`
- [ ] `lineage` es `list[DocumentLineageEntry]` con default vacío
- [ ] `preservation_status` es `Literal["active", "archived", "delete_pending", "permanent"]`
- [ ] `retention_expiry` es `str | None` (ISO 8601)

**Archivo: `context/lineage_recorder.py` (nuevo)**
- [ ] Clase `LineageRecorder` con métodos static
- [ ] `record_import()` crea `DocumentLineageEntry` válido
- [ ] `record_classification_change()` registra cambios correctamente
- [ ] Timestamps son ISO 8601
- [ ] `actor` se asigna (usuario o "system")

**Archivo: `context/retention_policies.yaml` (nuevo)**
- [ ] Fichero YAML válido
- [ ] Campos: `default_retention_years`, `policies`
- [ ] Cada política tiene: `retention_years`, `preservation_status`
- [ ] Se carga correctamente sin errores YAML

**Archivo: `context/context_builder.py`**
- [ ] Carga y aplica `retention_policies.yaml`
- [ ] `calculate_retention_expiry()` funciona correctamente
- [ ] `export_audit_report()` genera JSON válido

### 4.2 Tests y Coverage

**Tests nuevos:**
- [ ] `tests/unit/test_lineage_and_audit.py` con 4+ tests
  - [ ] `test_lineage_record_import()` — entry válido en lineage
  - [ ] `test_lineage_record_reclassification()` — cambio registrado
  - [ ] `test_retention_expiry_calculation()` — fecha correcta
  - [ ] `test_audit_report_export_json()` — JSON válido y parseable
  - [ ] `test_lineage_multievent()` — múltiples eventos en lista

**Coverage:**
- [ ] `LineageRecorder` coverage > 85%
- [ ] `export_audit_report()` coverage > 80%
- [ ] Carga de `retention_policies.yaml` coverage > 90%

### 4.3 Documentación

- [ ] `docs/compliance/audit-compliance.md` existe y cubre:
  - [ ] Qué es lineage y por qué es importante
  - [ ] Estructura de `DocumentLineageEntry`
  - [ ] Estados de preservación y cuándo aplicarlos
  - [ ] Políticas de retención: cómo configurar
  - [ ] Exportación de auditoría: formato y uso
  - [ ] Ejemplos JSON de lineage

- [ ] `CHANGELOG.md` documentado

### 4.4 Criterios de Go/No-Go FASE 4

**GO si:**
- ✅ 4+ tests pasen
- ✅ Coverage > 80%
- ✅ JSON de auditoría es válido
- ✅ Lineage se persiste en context.json
- ✅ Documentación completa
- ✅ No hay regresiones en FASES 1-3

**NO-GO si:**
- ❌ Tests fallan
- ❌ JSON inválido
- ❌ Documentación incompleta

---

## 🔄 Meta-Audit: Validación Cruzada Entre Fases

**Después de completar todas las fases:**

- [ ] No hay regresiones en tests de FASES 1-3 al agregar FASE 4
- [ ] `context.json` de v1.5 se carga en v1.8 sin errores
- [ ] `cache.db` de v1.4 se migra a v1.8 sin pérdida de datos
- [ ] Flujo completo escaneo → clasificación → enriquecimiento → auditoría sin errores
- [ ] Documentación es coherente entre todas las fases
- [ ] No hay TODOs o FIXMEs pendientes en código
- [ ] Zensical build --strict pasa sin warnings de links rotos
- [ ] Type checking (mypy) pasa con strict mode
- [ ] Todos los tests unitarios pasan (100% de los nuevos)
- [ ] Performance es aceptable (< 10% overhead total)

---

## 📊 Checklist de Audit Consolidado

```markdown
### FASE 1
- [ ] Código: 1.1 ✓/✗
- [ ] Tests: 1.2 ✓/✗ (4+ tests)
- [ ] Migración: 1.3 ✓/✗
- [ ] Performance: 1.4 ✓/✗
- [ ] Docs: 1.5 ✓/✗
- [ ] Integración: 1.6 ✓/✗
- [ ] Go/No-Go: FASE 1 → ✓ GO / ✗ NO-GO

### FASE 2
- [ ] Código: 2.1 ✓/✗
- [ ] Tests: 2.2 ✓/✗ (6+ tests)
- [ ] Compatibilidad: 2.3 ✓/✗
- [ ] Performance: 2.4 ✓/✗
- [ ] Docs: 2.5 ✓/✗
- [ ] Integración: 2.6 ✓/✗
- [ ] Go/No-Go: FASE 2 → ✓ GO / ✗ NO-GO

### FASE 3
- [ ] Código: 3.1 ✓/✗
- [ ] Tests: 3.2 ✓/✗ (3+ tests)
- [ ] Docs: 3.3 ✓/✗
- [ ] Go/No-Go: FASE 3 → ✓ GO / ✗ NO-GO

### FASE 4
- [ ] Código: 4.1 ✓/✗
- [ ] Tests: 4.2 ✓/✗ (4+ tests)
- [ ] Docs: 4.3 ✓/✗
- [ ] Go/No-Go: FASE 4 → ✓ GO / ✗ NO-GO

### META-AUDIT
- [ ] Regresiones: 0 ✓/✗
- [ ] Migración v1.4→v1.8: ✓ OK / ✗ FALLA
- [ ] Flujo completo: ✓ OK / ✗ ERROR
- [ ] Docs coherentes: ✓ SÍ / ✗ NO
- [ ] Zensical strict: ✓ PASS / ✗ FAIL
- [ ] Mypy strict: ✓ PASS / ✗ FAIL

### APROBACIÓN FINAL
- [ ] Todo audit completado
- [ ] Todas las fases: GO
- [ ] Meta-audit: ✓ PASS
- [ ] Listo para release: ✓ SÍ / ✗ NO
```

---

## 🚨 Escalación

Si algún criteria de Go/No-Go falla:

1. **Documentar el issue específico** con evidencia (logs, stack trace)
2. **Clasificar por severidad:**
   - 🔴 CRÍTICO: Pérdida de datos, incompatibilidad total → No-Go
   - 🟡 ALTO: Performance degradado, algunos tests fallan → Revisar, posible No-Go
   - 🟢 BAJO: Documentación menor, warnings ignorables → Reparar, Go condicionado

3. **Arreglar en rama feature** y re-auditar sección afectada
4. **Re-auditoría debe ocurrir antes de merge a develop**

---

*Audit Plan v1.0 | 2026-11-15 | Paired with PLAN_METADATA_ENHANCEMENT.md*

---

> **Nota de corrección (2026-11-15).** Los checks de la Fase 1 se escribieron para el diseño del plan, no para el
> código final: los que mencionan `detected_language`, `LanguageDetector`, `win32security` o el formato `oct()[-3:]` ya
> no aplican. El resultado real de la auditoría y de las correcciones está en [TRACEABILITY.md](TRACEABILITY.md).
