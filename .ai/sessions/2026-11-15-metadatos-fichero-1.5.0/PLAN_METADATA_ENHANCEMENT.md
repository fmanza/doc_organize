# Plan de Implementación: Enriquecimiento de Metadatos en doc_organize

**Versión:** 1.0  
**Fecha:** 2026-11-15  
**Estado:** BORRADOR  
**Responsable:** Claude Haiku 4.5

---

## 📋 Resumen Ejecutivo

Expandir el sistema de captura de metadatos de doc_organize en **4 fases incrementales**, desde metadatos técnicos básicos hasta auditoría y lineage completos. Cada fase es independiente y entrega valor inmediato.

---

## 🎯 Objetivos

| Objetivo | Resultado |
|----------|-----------|
| **Enriquecimiento técnico** | Detectar idioma, tipo MIME preciso, fecha creación |
| **Enriquecimiento de contenido** | Extraer autor, descripción, palabras clave automáticamente |
| **Trazabilidad de clasificación** | Registrar versión modelo, método, timestamp, confianza |
| **Auditoría y preservación** | Lineage de origen, historial cambios, estado preservación |

---

## 📊 Matriz de Fases

```
FASE 1 (BÁSICA)          FASE 2 (CONTENIDO)       FASE 3 (CLASIFICACIÓN)   FASE 4 (AUDITORÍA)
└─ 2 semanas             └─ 3 semanas              └─ 2 semanas              └─ 2 semanas
   Tipo MIME                Autor (PDF/Office)        Confianza mejorada        Lineage
   Idioma (Docling)         Descripción (IA)          Versión modelo            Historial
   Fecha creación           Palabras clave (IA)       Timestamp clasificación   Estado preservación
   Permisos SO              Resumen extractivo        Versión reglas
```

---

## 🔧 FASE 1: Metadatos Técnicos Básicos (Semanas 1-2)

### 1.1 Objetivos de la Fase
- ✅ Capturar tipo MIME desde archivo original (antes de conversión)
- ✅ Detectar idioma principal del documento
- ✅ Registrar fecha de creación (modificación existe ya)
- ✅ Guardar permisos/propietario en Windows/Unix

### 1.2 Cambios en Modelos (`core/models.py`)

**Extender `DocumentMetadata`:**
```python
class DocumentMetadata(BaseModel):
    # ... campos existentes ...
    
    # NUEVOS en FASE 1
    created_time: float | None = Field(
        default=None,
        description="Timestamp Unix de creación (st_birthtime en macOS, st_ctime en otros)"
    )
    mime_type: str | None = Field(
        default=None,
        description="Tipo MIME detectado (p.ej. 'application/pdf', 'text/plain')"
    )
    detected_language: str | None = Field(
        default=None,
        description="Código ISO 639-1 del idioma detectado (p.ej. 'es', 'en', 'fr')"
    )
    file_permissions: str | None = Field(
        default=None,
        description="Permisos en notación octal (Unix) o SID (Windows), o None si no se obtienen"
    )
    owner_name: str | None = Field(
        default=None,
        description="Propietario del archivo en el SO, o None si no se obtiene"
    )
```

**Extender `CacheEntry`:**
```python
class CacheEntry(BaseModel):
    # ... campos existentes ...
    
    # NUEVOS en FASE 1
    created_time: float | None = Field(default=None)
    mime_type: str | None = Field(default=None)
    detected_language: str | None = Field(default=None)
```

### 1.3 Cambios en Scanner (`scanner/document_scanner.py`)

**Nueva función en `_build_file_node`:**
```python
def _extract_basic_metadata(self, path: Path) -> dict[str, Any]:
    """Extrae tipo MIME, fecha creación, permisos, propietario."""
    try:
        stat = path.stat()
        
        # Tipo MIME con fallback a extensión
        mime_type = self._detect_mime_type(path)
        
        # Fecha creación (fallback a modificación si no existe)
        created_time = self._get_creation_time(stat, path)
        
        # Permisos y propietario
        file_permissions = self._get_permissions(stat)
        owner_name = self._get_owner_name(stat)
        
        return {
            "mime_type": mime_type,
            "created_time": created_time,
            "file_permissions": file_permissions,
            "owner_name": owner_name,
        }
    except Exception as e:
        self.logger.warning(f"No se pudieron extraer metadatos de '{path}': {e}")
        return {}

def _detect_mime_type(self, path: Path) -> str:
    """Detecta tipo MIME: biblioteca mimetypes + magic (si disponible)."""
    # Intenta mimetypes (rápido, basado en extensión)
    mime, _ = mimetypes.guess_type(str(path))
    if mime:
        return mime
    
    # Intenta python-magic si está disponible (lento pero preciso)
    try:
        import magic
        return magic.from_file(str(path), mime=True)
    except ImportError:
        return f"application/octet-stream"  # fallback

def _get_creation_time(self, stat: os.stat_result, path: Path) -> float:
    """Obtiene fecha creación: st_birthtime (macOS) o st_ctime (otros)."""
    if hasattr(stat, 'st_birthtime'):
        return stat.st_birthtime  # macOS
    # En Windows/Linux, usar st_ctime si es anterior a st_mtime
    return min(stat.st_ctime, stat.st_mtime)

def _get_permissions(self, stat: os.stat_result) -> str | None:
    """Permisos en notación octal (Unix) o representación Windows."""
    try:
        mode = stat.st_mode
        perms = oct(mode)[-3:]  # Últimos 3 dígitos (rwx)
        return perms
    except Exception:
        return None

def _get_owner_name(self, stat: os.stat_result) -> str | None:
    """Propietario del archivo."""
    try:
        import pwd  # Unix
        return pwd.getpwuid(stat.st_uid).pw_name
    except (ImportError, KeyError):
        try:
            import win32security  # Windows
            sid = win32security.GetFileSecurity(...)
            return win32security.LookupAccountSid(...)[0]
        except Exception:
            return None
```

**Integrar detección de idioma con Docling:**
```python
# En scanner/document_scanner.py o nuevo módulo language_detector.py
class LanguageDetector:
    """Detecta idioma usando el documento convertido por Docling."""
    
    async def detect_language(self, conversion_result: ConversionResult) -> str | None:
        """Lee el .json de Docling y extrae idioma si está disponible."""
        if not conversion_result.json_path:
            return None
        
        try:
            with open(conversion_result.json_path) as f:
                data = json.load(f)
                # Docling proporciona metadata.language si OCR está activo
                return data.get("metadata", {}).get("language")
        except Exception as e:
            self.logger.warning(f"No se pudo detectar idioma: {e}")
            return None
```

### 1.4 Cambios en Conversión (`converter/converter.py`)

**Paso básico: guardar metadatos en `ConversionResult`:**
```python
class ConversionResult(BaseModel):
    # ... campos existentes ...
    detected_language: str | None = Field(default=None)
    mime_type_original: str | None = Field(default=None)
```

### 1.5 Bases de Datos y Persistencia

**Migración de `cache.db`:**
```sql
-- En cache.db schema (versión nueva)
ALTER TABLE cache ADD COLUMN created_time FLOAT;
ALTER TABLE cache ADD COLUMN mime_type TEXT;
ALTER TABLE cache ADD COLUMN detected_language TEXT;
```

**Compatibilidad hacia atrás:**
- Campos nuevos son `NULL` en bases de datos antiguas
- En el escaneo siguiente, se rellenan automáticamente
- Test para verificar que versiones antiguas se migren correctamente

### 1.6 Tests Unitarios (FASE 1)

```python
# tests/unit/test_scanner_metadata_phase1.py
def test_detect_mime_type_pdf():
    scanner = DocumentScanner()
    path = Path("document.pdf")
    assert scanner._detect_mime_type(path) == "application/pdf"

def test_extract_basic_metadata_complete():
    # Mock stat
    metadata = scanner._extract_basic_metadata(Path("test.docx"))
    assert "mime_type" in metadata
    assert "created_time" in metadata
    assert "file_permissions" in metadata
    assert "owner_name" in metadata

def test_cache_migration_creates_columns():
    # Verifica que la DB anterior se actualiza sin errores
    pass

def test_language_detection_from_docling_output():
    # Mock JSON de Docling con metadata.language = "es"
    detector = LanguageDetector()
    lang = asyncio.run(detector.detect_language(conversion_result))
    assert lang == "es"
```

### 1.7 Documentación (FASE 1)

**Actualizar en `docs/guides/`:**
- `metadata-schema.md`: Nuevos campos de FASE 1
- `scanner-configuration.md`: Opciones de detección (activar/desactivar)
- `database-migration.md`: Cómo migran los clientes desde v1.4.0

### 1.8 Criterios de Finalización (FASE 1)

- ✅ `DocumentMetadata` contiene 5 campos nuevos
- ✅ `DocumentScanner` extrae los 5 campos sin fallos
- ✅ `cache.db` se migra automáticamente en primer escaneo
- ✅ 4+ tests unitarios pasen (mime, idioma, permisos, fecha creación)
- ✅ Exportación XLSX/JSON incluye los campos nuevos
- ✅ Zensical build --strict pasa sin errores de links

---

## 📝 FASE 2: Enriquecimiento de Contenido (Semanas 3-5)

### 2.1 Objetivos de la Fase
- ✅ Extraer autor desde metadatos PDF/Office
- ✅ Generar descripción automática con IA (resumen del contenido)
- ✅ Extraer palabras clave con IA
- ✅ Guardar en `DomainDocument` para cada documento clasificado

### 2.2 Cambios en Modelos

**Extender `DomainDocument`:**
```python
class DomainDocument(BaseModel):
    # ... campos existentes ...
    
    # NUEVOS en FASE 2
    author: str | None = Field(
        default=None,
        description="Autor del documento (extraído de PDF/Office metadata)"
    )
    description: str | None = Field(
        default=None,
        description="Descripción/resumen del contenido (generado por IA o editado por usuario)"
    )
    keywords: list[str] = Field(
        default_factory=list,
        description="Palabras clave sugeridas por IA"
    )
    keywords_confidence: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Confianza en las palabras clave generadas (0-1)"
    )
```

### 2.3 Nuevo Cliente de IA para Extracción de Contenido

**Archivo: `ai/content_extraction_client.py`**
```python
class ContentExtractionClient:
    """Extrae descripción y palabras clave de documentos convertidos."""
    
    async def extract_content_metadata(
        self,
        markdown_path: str,
        document_type: str,
        max_keywords: int = 5,
    ) -> tuple[str, list[str], float]:
        """
        Extrae descripción y palabras clave del .md generado por Docling.
        
        Args:
            markdown_path: Ruta al .md del documento convertido
            document_type: Tipo de documento (para contexto)
            max_keywords: Máximo número de palabras clave
        
        Returns:
            (descripción, [palabras_clave], confianza_keywords)
        """
        # Leer primeros 2000 caracteres del .md
        with open(markdown_path) as f:
            content_sample = f.read()[:2000]
        
        # Llamar a LiteLLM proxy con prompt estructurado
        prompt = f"""Analiza este documento ({document_type}) y proporciona:
1. Una descripción de 1-2 líneas del contenido
2. Hasta {max_keywords} palabras clave principales (1-2 palabras cada una)

Responde en JSON: {{"description": "...", "keywords": ["...", "..."]}}

Contenido:
{content_sample}
"""
        response = await self._call_litellm(prompt)
        result = json.loads(response)
        
        return (
            result["description"],
            result["keywords"],
            0.8  # Confianza por defecto
        )
```

### 2.4 Extractor de Autor desde Metadatos

**Archivo: `converter/metadata_extractor.py`**
```python
class MetadataExtractor:
    """Extrae autor desde archivos PDF y Office."""
    
    @staticmethod
    def extract_author_from_pdf(pdf_path: str) -> str | None:
        """Extrae Author, Creator o Producer del PDF."""
        try:
            import PyPDF2
            with open(pdf_path, 'rb') as f:
                reader = PyPDF2.PdfReader(f)
                info = reader.metadata
                return info.get("/Author") or info.get("/Creator")
        except Exception:
            return None
    
    @staticmethod
    def extract_author_from_office(office_path: str) -> str | None:
        """Extrae creator de DOCX, XLSX, PPTX."""
        try:
            from docx import Document  # para .docx
            doc = Document(office_path)
            return doc.core_properties.author
        except Exception:
            return None
```

### 2.5 Integración en `ContextBuilder`

**Cambios en `context/context_builder.py`:**
```python
async def _enrich_domain_document(
    self,
    source_path: str,
    markdown_path: str,
    conversion_result: ConversionResult,
    domain: Domain,
    confidence: float,
) -> DomainDocument:
    """Sub-fase A2: enriquecimiento de contenido después de clasificación."""
    
    # Extraer autor
    author = MetadataExtractor.extract_author_from_pdf(source_path)
    if not author:
        author = MetadataExtractor.extract_author_from_office(source_path)
    
    # Generar descripción y palabras clave con IA (paralelo)
    extraction_client = ContentExtractionClient(self.litellm_config)
    description, keywords, kw_confidence = await extraction_client.extract_content_metadata(
        markdown_path,
        self._get_document_type(source_path),
    )
    
    # Construir DomainDocument
    return DomainDocument(
        source_path=source_path,
        markdown_path=markdown_path,
        json_path=conversion_result.json_path,
        title=self._extract_title(markdown_path),
        document_type=self._get_document_type(source_path),
        material_type=...,  # existente
        confidence=confidence,
        classified_by="rules",  # o "ai"
        # NUEVOS en FASE 2
        author=author,
        description=description,
        keywords=keywords,
        keywords_confidence=kw_confidence,
    )
```

### 2.6 Tests Unitarios (FASE 2)

```python
# tests/unit/test_content_extraction.py
def test_extract_author_from_pdf():
    author = MetadataExtractor.extract_author_from_pdf("sample.pdf")
    assert author is not None

def test_extract_content_metadata_structure():
    desc, kw, conf = asyncio.run(
        extraction_client.extract_content_metadata("sample.md", "pdf")
    )
    assert isinstance(desc, str) and len(desc) > 0
    assert isinstance(kw, list) and len(kw) <= 5
    assert 0.0 <= conf <= 1.0

def test_domain_document_has_new_fields():
    doc = DomainDocument(...)
    assert hasattr(doc, "author")
    assert hasattr(doc, "description")
    assert hasattr(doc, "keywords")
```

### 2.7 Criterios de Finalización (FASE 2)

- ✅ `DomainDocument` tiene 4 campos nuevos (author, description, keywords, keywords_confidence)
- ✅ `MetadataExtractor` extrae autor sin fallos
- ✅ `ContentExtractionClient` llamadas a IA son exitosas
- ✅ `context.json` almacena los nuevos campos
- ✅ 4+ tests unitarios pasen
- ✅ Exportación XLSX/JSON incluye los nuevos campos

---

## 🔍 FASE 3: Trazabilidad de Clasificación (Semanas 6-7)

### 3.1 Objetivos de la Fase
- ✅ Registrar versión del modelo IA usado
- ✅ Registrar versión de reglas de clasificación
- ✅ Timestamp preciso de clasificación
- ✅ Mejorar registro de confianza con desglose por eje

### 3.2 Cambios en Modelos

**Extender `DomainDocument`:**
```python
class DomainDocument(BaseModel):
    # ... campos anteriores ...
    
    # NUEVOS en FASE 3
    classification_timestamp: str | None = Field(
        default=None,
        description="Timestamp ISO 8601 de cuándo se clasificó el documento"
    )
    classification_model_version: str | None = Field(
        default=None,
        description="Versión del modelo IA usado (p.ej. 'claude-opus-5-5' o 'rule-v1.2')"
    )
    classification_method_version: str | None = Field(
        default=None,
        description="Versión del motor de clasificación (p.ej. 'DomainClassificationClient-v1')"
    )
    domain_confidence_breakdown: dict[str, float] | None = Field(
        default=None,
        description="Desglose de confianza: {'reglas': 0.7, 'ai': 0.85, 'final': 0.80}"
    )
```

**Extender `Context`:**
```python
class Context(BaseModel):
    # ... campos anteriores ...
    
    # NUEVOS en FASE 3
    classification_timestamp: str | None = Field(
        default=None,
        description="Timestamp ISO 8601 de la última clasificación"
    )
    ai_model_version: str | None = Field(
        default=None,
        description="Versión del modelo IA usado en Sub-fase B (p.ej. 'claude-opus-5-5')"
    )
    rules_engine_version: str | None = Field(
        default=None,
        description="Versión de reglas de clasificación (p.ej. 'v1.2.0')"
    )
```

### 3.3 Cambios en Clientes de IA

**Versioning en `ai/domain_classification_client.py`:**
```python
class DomainClassificationClient:
    MODEL_VERSION = "1.0"  # Bump en cada cambio de prompt
    
    async def classify(self, ...) -> DomainClassificationResult:
        result = await self._call_litellm(...)
        result.model_version = self.MODEL_VERSION
        result.timestamp = datetime.now(timezone.utc).isoformat()
        return result
```

### 3.4 Cambios en `ContextBuilder`

**Registrar versiones:**
```python
class ContextBuilder:
    def __init__(self, ...):
        self.ai_model_version = self._resolve_ai_model_version()
        self.rules_version = self._load_rules_version()  # desde fichero
    
    async def build(self, ...):
        start_time = datetime.now(timezone.utc)
        
        # Sub-fase A: reglas
        for doc in documents:
            domain = self._classify_by_rules(doc)
            domain_doc = DomainDocument(
                ...
                classification_timestamp=start_time.isoformat(),
                classification_model_version="rules-" + self.rules_version,
                domain_confidence_breakdown={"reglas": 0.75},
            )
        
        # Sub-fase B: IA
        if self.ai_classification_enabled:
            ai_start = datetime.now(timezone.utc)
            domain_doc.classification_timestamp = ai_start.isoformat()
            domain_doc.classification_model_version = self.ai_model_version
            domain_doc.domain_confidence_breakdown["ai"] = score
            domain_doc.domain_confidence_breakdown["final"] = final_score
```

### 3.5 Fichero de Versiones de Reglas

**Nuevo archivo: `context/rules_version.txt`**
```
1.2.0
```

**Actualizable por usuario o por CI:**
```bash
echo "1.3.0" > src/doc_organize/context/rules_version.txt
```

### 3.6 Criterios de Finalización (FASE 3)

- ✅ `DomainDocument` tiene timestamp y versiones de modelo
- ✅ `Context` almacena versiones globales
- ✅ Clientes IA registran su versión automáticamente
- ✅ Desglose de confianza se calcula correctamente
- ✅ `context.json` es retrocompatible (campos nuevos son opcionales)
- ✅ Tests para versionado de modelos

---

## 📜 FASE 4: Auditoría y Lineage (Semanas 8-9)

### 4.1 Objetivos de la Fase
- ✅ Registrar origen del documento (importado, escaneado, copiado)
- ✅ Historial de cambios en clasificación
- ✅ Estado de preservación (archivado, borrable, permanente)
- ✅ Lineage completo para compliance

### 4.2 Cambios en Modelos

**Extender `DomainDocument`:**
```python
class DocumentLineageEntry(BaseModel):
    timestamp: str = Field(..., description="ISO 8601")
    action: Literal["imported", "classified", "reclassified", "archived", "accessed"] = Field(...)
    actor: str | None = Field(default=None, description="Usuario o sistema que realizó la acción")
    old_value: Any | None = Field(default=None, description="Valor anterior (para cambios)")
    new_value: Any | None = Field(default=None, description="Valor nuevo")

class DomainDocument(BaseModel):
    # ... campos anteriores ...
    
    # NUEVOS en FASE 4
    origin: Literal["imported", "scanned", "created", "migrated"] = Field(
        default="scanned",
        description="Cómo llegó el documento al proyecto"
    )
    lineage: list[DocumentLineageEntry] = Field(
        default_factory=list,
        description="Historial completo de cambios y acciones"
    )
    preservation_status: Literal["active", "archived", "delete_pending", "permanent"] = Field(
        default="active",
        description="Estado de preservación (cuándo destruir o conservar)"
    )
    retention_expiry: str | None = Field(
        default=None,
        description="Fecha ISO 8601 de expiración de retención"
    )
```

### 4.3 Registro de Lineage

**Nuevo módulo: `context/lineage_recorder.py`**
```python
class LineageRecorder:
    """Registra cada cambio en documento para auditoría."""
    
    @staticmethod
    def record_import(doc: DomainDocument, source: str, actor: str | None = None):
        entry = DocumentLineageEntry(
            timestamp=datetime.now(timezone.utc).isoformat(),
            action="imported",
            actor=actor or "system",
            new_value={"origin": source}
        )
        doc.lineage.append(entry)
    
    @staticmethod
    def record_classification_change(
        doc: DomainDocument,
        old_domain: str,
        new_domain: str,
        reason: str = "reclassification",
        actor: str | None = None
    ):
        entry = DocumentLineageEntry(
            timestamp=datetime.now(timezone.utc).isoformat(),
            action="reclassified",
            actor=actor,
            old_value={"domain": old_domain},
            new_value={"domain": new_domain, "reason": reason}
        )
        doc.lineage.append(entry)
```

### 4.4 Políticas de Retención

**Nuevo archivo: `context/retention_policies.yaml`**
```yaml
default_retention_years: 7

policies:
  legal_documents:
    retention_years: 10
    preservation_status: permanent
  
  technical_docs:
    retention_years: 3
    preservation_status: active
  
  temporary:
    retention_years: 0.5  # 6 meses
    preservation_status: delete_pending
```

### 4.5 Exportación de Auditoría

**Comando nuevo: `scan --export-audit-report`**
```python
# En scan_command.py
async def export_audit_report(self, context: Context) -> str:
    """Genera JSON con lineage completo de todos los documentos."""
    audit = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "context_version": "1.0",
        "domains": []
    }
    
    for domain in context.domains:
        domain_audit = {
            "domain": domain.slug,
            "documents": [
                {
                    "source_path": doc.source_path,
                    "origin": doc.origin,
                    "preservation_status": doc.preservation_status,
                    "retention_expiry": doc.retention_expiry,
                    "lineage": [entry.model_dump() for entry in doc.lineage]
                }
                for doc in domain.documents
            ]
        }
        audit["domains"].append(domain_audit)
    
    # Guardar como JSON
    audit_path = Path(context_dir) / f"AUDIT_REPORT_{datetime.now().isoformat()}.json"
    with open(audit_path, 'w') as f:
        json.dump(audit, f, indent=2)
    
    return str(audit_path)
```

### 4.6 Tests Unitarios (FASE 4)

```python
# tests/unit/test_lineage_and_audit.py
def test_lineage_recorder_import():
    doc = DomainDocument(...)
    LineageRecorder.record_import(doc, "S3://bucket", actor="admin")
    assert len(doc.lineage) == 1
    assert doc.lineage[0].action == "imported"

def test_lineage_recorder_reclassification():
    doc = DomainDocument(...)
    LineageRecorder.record_classification_change(doc, "legal", "technical")
    assert doc.lineage[-1].action == "reclassified"

def test_retention_expiry_calculation():
    # Mock policy
    expiry = calculate_retention_expiry("legal_documents")
    assert expiry > datetime.now()

def test_audit_report_export():
    report_path = asyncio.run(context_builder.export_audit_report(context))
    assert report_path.endswith(".json")
    with open(report_path) as f:
        data = json.load(f)
        assert "domains" in data
        assert "lineage" in data["domains"][0]["documents"][0]
```

### 4.7 Criterios de Finalización (FASE 4)

- ✅ `DomainDocument` tiene origin, lineage, preservation_status, retention_expiry
- ✅ `LineageRecorder` registra importaciones, cambios, archivado
- ✅ `retention_policies.yaml` configurable
- ✅ Exportación de auditoría genera JSON válido
- ✅ Tests de lineage y retención pasen
- ✅ Documentación de compliance en `docs/compliance/`

---

## 🎬 Resumen de Entregables por Fase

| Fase | Archivos Nuevos | Modelos Ext. | Tests | Docs | Duración |
|------|-----------------|-------------|-------|------|----------|
| 1 | `language_detector.py` | `DocumentMetadata`, `CacheEntry` | 4+ | `metadata-schema.md` | 2w |
| 2 | `content_extraction_client.py`, `metadata_extractor.py` | `DomainDocument` | 4+ | `content-extraction.md` | 3w |
| 3 | `rules_version.txt` | `DomainDocument`, `Context` | 3+ | `versioning.md` | 2w |
| 4 | `lineage_recorder.py`, `retention_policies.yaml` | `DomainDocument`, `DocumentLineageEntry` | 4+ | `audit-compliance.md` | 2w |

**TOTAL: 9 semanas (~2 meses)**

---

## 🚀 Orden de Ejecución Recomendado

```
SEMANA 1: FASE 1.1-1.3 (Modelos + Scanner básico)
  └─ PR: Añadir 5 campos a DocumentMetadata
  └─ Merge before continuing

SEMANA 2: FASE 1.4-1.7 (Integración + Tests + Docs)
  └─ PR: Completar FASE 1, liberar v1.5.0-beta

SEMANA 3: FASE 2.1-2.3 (Modelos + Cliente IA)
  └─ PR: ContentExtractionClient base

SEMANA 4: FASE 2.4-2.6 (MetadataExtractor + Integración)
  └─ PR: Extracción de autor + descripción

SEMANA 5: FASE 2.7 (Tests + Docs + Release)
  └─ PR: Liberar v1.6.0

SEMANA 6: FASE 3.1-3.3 (Versionado de modelos)
  └─ PR: Versioning y trazabilidad

SEMANA 7: FASE 3.4-3.6 (Integración + Release)
  └─ PR: Liberar v1.7.0

SEMANA 8: FASE 4.1-4.3 (Lineage + Auditoría)
  └─ PR: LineageRecorder base

SEMANA 9: FASE 4.4-4.7 (Retención + Exportación + Release)
  └─ PR: Liberar v1.8.0
```

---

## 📌 Dependencias y Riesgos

### Dependencias Externas
- `python-magic` o `mimetypes` (FASE 1)
- `PyPDF2` para extracción de autor PDF (FASE 2)
- `python-docx` para extracción de autor Office (FASE 2)
- LiteLLM Proxy con soporte `chat/completions` (FASE 2, 3)

### Riesgos y Mitigación

| Riesgo | Probabilidad | Impacto | Mitigación |
|--------|-------------|--------|-----------|
| LiteLLM no disponible en desarrollo | MEDIA | ALTO | Mock en tests, feature flag |
| Extractores de autor fallan silenciosamente | MEDIA | BAJO | Logs detallados, fallback a None |
| DB antigua no migra bien | BAJA | CRÍTICO | Migración reversible, tests exhaustivos |
| Performance: lineage agrega overhead | BAJA | MEDIO | Indexar por timestamp, lazy load |

---

## ✅ Criterios de Éxito Global

- [ ] Todas las 4 fases completadas sin errores críticos
- [ ] 100% de tests unitarios pasen (12+ nuevos)
- [ ] Documentación completa y sin links rotos (zensical build --strict)
- [ ] Compatibilidad hacia atrás verificada (v1.4.0 → v1.8.0 migration)
- [ ] Rendimiento: tiempo de escaneo < 10% más lento con nuevos metadatos
- [ ] Usuarios pueden opcionalmente deshabilitar FASE 2-4 por configuración
- [ ] Changelog actualizado con breaking changes (si los hay)

---

*Versión 1.0 | 2026-11-15 | Estado: BORRADOR → PLAN_REVIEW*

---

> **Nota de corrección (2026-11-15, tras `/audit-code`).** Este plan se conserva como se escribió, pero la Fase 1 se
> implementó de otra forma: sin `detected_language` (nada lo rellenaba); `created_time` solo con `st_birthtime` (`None`
> en Linux, donde `st_ctime` no es la creación); `file_permissions` `None` en Windows; `owner_name` opcional
> (`ScanOptions.capture_owner=False` por defecto) y leído en Windows con `ctypes`, no con pywin32; `mime_type` solo por
> la extensión, sin python-magic; y migración real de `cache.db` en `CacheManager._migrate_schema`. Las duraciones en
> semanas, las cifras de rendimiento y las versiones 1.6.0-1.8.0 eran estimaciones sin base. La Fase 2 se rehace sobre
> `AiHttpClientBase` y con opt-in, no como se describe aquí. Lo implementado está en
> [TRACEABILITY.md](TRACEABILITY.md).
