# ADR-002: Arquitectura de Caché Transaccional para cache.json

**Fecha**: 2026-08-27  
**Status**: ❌ **SUPERSEDIDO** (2026-08-27, ver Anexo al final) — la decisión real de `doc_organize`
es **SQLite + WAL** (no `cache.json`), y `CacheManager` ya está implementado, probado (98% cobertura)
y en uso por Fase C. El `workflow/orchestrator.py` propuesto aquí está fuera de alcance de Fase 1.
Este documento nunca llegó a estar realmente aprobado (el `[Tech Lead Signature]` al final es un
placeholder sin rellenar) y usa terminología (`sha3_hash`) previa a la corrección a SHA-256.  
**Impacto**: Módulos core, scanner, converter, dedup, cache

---

## Contexto

El AUDIT_PLAN identifica **acoplamiento crítico** en `cache.json`:
- `scanner/` calcula SHA-3 (lee archivos)
- `converter/` modifica documentos (genera .md/.json)
- `dedup/` mueve archivos (descarta duplicados)
- `cache/` guarda estado (cache.json)

**Problema**: Si conversión falla a mitad (ej: documento 50 de 100), ¿cache.json queda inconsistente?

**Ejemplo Fallo**:
```
Estado antes: doc_50.pdf → status: "pending"
Conversión: doc_50.pdf → error "Docling timeout"
Estado después: ???
  A) doc_50.pdf → status: "pending" (viejo)
  B) doc_50.pdf → status: "error" (sin detalles)
  C) cache.json corrupto (crash antes de guardar)
```

Esta decisión establece **responsabilidad única** de cache.json y **transacción atómica** en operaciones críticas.

---

## Opciones Consideradas

### Opción A: Centralized CacheManager (RECOMENDADA para MVP)

**Arquitectura**:
```
scanner/ ──┐
converter/ ├─→ Orchestrator ──→ CacheManager (único mutex)
dedup/    ─┘
```

- `CacheManager` es **único punto de actualización** de cache.json
- Todos los módulos llaman `cache_manager.update_entry(file_path, status, details)`
- Transacción: backup → modificación → validación → commit

**Ventajas**:
- ✅ Responsabilidad clara (CacheManager dueño de estado)
- ✅ Transacciones atómicas (backup + retry)
- ✅ Testing simple (mock CacheManager)
- ✅ Debugging observable (logging centralizado)

**Desventajas**:
- ❌ Coupling explícito (todos → CacheManager)
- ❌ Bottleneck potencial (mutex en operaciones paralelas)
- ❌ Orquestación complicada (orden de operaciones crítica)

**Performance**:
- Overhead: ~10ms por actualización (I/O sync)
- Escalabilidad: OK para 100-1000 docs; límite ~5000 con mutex

### Opción B: Event-Driven (Arquitectura Avanzada)

**Arquitectura**:
```
scanner/ ──→ event: "file_scanned"
converter/ ─→ event: "conversion_done" ──→ EventBus ──→ CacheManager suscriptor
dedup/ ─────→ event: "duplicate_moved"   (async queue, Redis opcional)
```

- Módulos emiten eventos (no modifican cache directamente)
- CacheManager escucha eventos (reacciona)
- Redis pub/sub para escalabilidad (opcional)

**Ventajas**:
- ✅ Desacoplamiento total (módulos no conocen CacheManager)
- ✅ Escalable (event queue, workers paralelos)
- ✅ Extensible (agregar listeners nuevos sin modificar core)

**Desventajas**:
- ❌ Complejo (event sourcing, eventual consistency)
- ❌ Testing difícil (mocks de EventBus)
- ❌ Debugging arduo (eventos pueden llegar out-of-order)
- ❌ Not MVP ready (over-engineering)

---

## Decisión

**Se elige: Opción A — Centralized CacheManager con Orchestrator** para MVP.

**Migración a Opción B** en v1.1 si necesita escalabilidad > 5000 docs.

---

## Implementación Fase MVP

### Estructura de Módulos

```
src/doclink_extractor/
├── core/
│   └── models.py              # CacheEntry, DocumentMetadata, ...
│
├── cache/
│   └── cache_manager.py       # CacheManager (transactional I/O)
│
├── workflow/                  # 🆕 NUEVO MÓDULO (Orquestrador)
│   ├── __init__.py
│   └── orchestrator.py        # Orchestrator (state machine)
│
├── scanner/
│   └── document_scanner.py    # No modifica cache
│
├── converter/
│   └── converter.py           # No modifica cache directamente
│
├── dedup/
│   └── deduplication.py       # No modifica cache directamente
│
└── web/
    └── routes/
        └── conversion.py      # Llama orchestrator.start_conversion()
```

### 1. CacheManager (Centralizado)

```python
# cache/cache_manager.py

from dataclasses import dataclass, asdict
from pathlib import Path
import json
import asyncio
from typing import Literal

@dataclass
class CacheEntry:
    file_path: str
    sha3_hash: str
    sha2_hash: str | None = None
    timestamp: float = 0.0
    status: Literal["new", "unchanged", "modified", "deleted"] = "new"
    conversion_status: Literal["pending", "success", "error", "ocr_required"] | None = None
    conversion_error: str | None = None
    conversion_duration_s: float = 0.0

class CacheManager:
    def __init__(self, cache_file: Path):
        self.cache_file = Path(cache_file)
        self.cache_lock = asyncio.Lock()  # Mutex para transacciones
        self._cache: dict[str, CacheEntry] = {}
        self._backup_file = self.cache_file.with_suffix('.json.bak')
    
    async def load(self) -> dict[str, CacheEntry]:
        """Carga cache.json, valida integridad."""
        async with self.cache_lock:
            if not self.cache_file.exists():
                return {}
            
            try:
                with open(self.cache_file) as f:
                    data = json.load(f)
                self._cache = {
                    k: CacheEntry(**v) for k, v in data.items()
                }
                return self._cache
            except (json.JSONDecodeError, ValueError) as e:
                # Fallback a backup si corrupto
                if self._backup_file.exists():
                    with open(self._backup_file) as f:
                        data = json.load(f)
                    self._cache = {
                        k: CacheEntry(**v) for k, v in data.items()
                    }
                    return self._cache
                else:
                    raise RuntimeError(f"cache.json corrupto y no hay backup: {e}")
    
    async def update_entry(
        self,
        file_path: str,
        status: Literal["new", "unchanged", "modified", "deleted"],
        conversion_status: str | None = None,
        conversion_error: str | None = None,
        conversion_duration_s: float = 0.0,
        sha3_hash: str | None = None
    ) -> CacheEntry:
        """
        Actualiza entrada en caché (transacción).
        
        Pasos:
        1. Acquire lock
        2. Backup cache.json actual
        3. Modificar entrada en memoria
        4. Validar
        5. Escribir cache.json
        6. Release lock
        
        En caso de error: rollback automático desde backup
        """
        async with self.cache_lock:
            # Backup
            if self.cache_file.exists():
                with open(self.cache_file) as src:
                    backup_data = src.read()
                with open(self._backup_file, 'w') as dst:
                    dst.write(backup_data)
            
            # Modificar
            entry = self._cache.get(file_path)
            if not entry:
                entry = CacheEntry(
                    file_path=file_path,
                    sha3_hash=sha3_hash or "",
                    timestamp=time.time()
                )
            
            entry.status = status
            entry.conversion_status = conversion_status
            entry.conversion_error = conversion_error
            entry.conversion_duration_s = conversion_duration_s
            if sha3_hash:
                entry.sha3_hash = sha3_hash
            
            self._cache[file_path] = entry
            
            # Validar
            if not self._validate_cache():
                # Rollback desde backup
                with open(self._backup_file) as f:
                    self._cache = json.load(f)
                raise RuntimeError("Validación de caché falló; rollback aplicado")
            
            # Escribir
            with open(self.cache_file, 'w') as f:
                json.dump(
                    {k: asdict(v) for k, v in self._cache.items()},
                    f, indent=2
                )
            
            return entry
    
    def _validate_cache(self) -> bool:
        """Validaciones post-modificación."""
        for entry in self._cache.values():
            if not entry.file_path or not entry.sha3_hash:
                return False
        return True
    
    def get_changes(
        self,
        current_docs: list[DocumentMetadata]
    ) -> tuple[list[str], list[str], list[str]]:
        """
        Compara caché con estado actual.
        Retorna (new_files, modified_files, unchanged_files).
        """
        new = []
        modified = []
        unchanged = []
        
        for doc in current_docs:
            entry = self._cache.get(doc.full_path)
            if not entry:
                new.append(doc.full_path)
            elif entry.sha3_hash == doc.sha3_hash:
                unchanged.append(doc.full_path)
            else:
                modified.append(doc.full_path)
        
        return new, modified, unchanged
```

### 2. Orchestrator (State Machine)

```python
# workflow/orchestrator.py

from enum import Enum
from datetime import datetime
import asyncio

class DocumentState(Enum):
    PENDING = "pending"           # Descubierto en escaneo
    SCANNING = "scanning"          # Calculando SHA-3
    DEDUPLICATING = "deduplicating"  # Revisando duplicados
    CONVERTING = "converting"      # Conversión Docling en progreso
    OCR_REQUIRED = "ocr_required"  # Pospuesto para fase 2
    SUCCESS = "success"            # Conversión completada
    ERROR = "error"                # Error (con retry lógica)
    RECOVERED = "recovered"        # Recovery exitoso
    FINAL_ERROR = "final_error"    # Error después de reintentos

class Orchestrator:
    def __init__(self, cache_manager: CacheManager, config: AppConfig):
        self.cache = cache_manager
        self.config = config
        self.doc_states: dict[str, DocumentState] = {}
    
    async def start_conversion_batch(
        self,
        doc_ids: list[str],
        use_ocr: bool = False,
        max_retries: int = 3
    ) -> ConversionReport:
        """
        Orquesta conversión batch completa.
        
        Fases:
        1. Load caché existente
        2. Scan de docs
        3. Deduplicación
        4. Conversión con retry exponencial
        5. OCR (opcional, fase 2)
        6. Cierre de transacción
        """
        
        report = ConversionReport(started_at=datetime.now())
        
        try:
            # Fase 1: Caché
            await self.cache.load()
            
            # Fase 2: Scan
            scanner = DocumentScanner()
            scan_result = await scanner.scan_folders(doc_ids)
            new_docs, modified_docs, unchanged = self.cache.get_changes(scan_result.documents)
            report.new_documents = len(new_docs)
            report.modified_documents = len(modified_docs)
            
            # Fase 3: Dedup
            deduper = DeduplicationManager()
            dup_groups = deduper.find_duplicates(scan_result.documents)
            report.duplicates_found = len(dup_groups)
            
            # Fase 4: Conversión con retry
            converter = DocumentConverter()
            for doc_path in new_docs + modified_docs:
                for attempt in range(max_retries):
                    try:
                        await self.cache.update_entry(
                            doc_path, 
                            status="modified",
                            conversion_status="converting"
                        )
                        
                        result = await converter.convert_document(
                            doc_path,
                            use_ocr=use_ocr
                        )
                        
                        await self.cache.update_entry(
                            doc_path,
                            status="modified",
                            conversion_status="success",
                            conversion_duration_s=result.duration_seconds
                        )
                        
                        report.successful_conversions += 1
                        break  # Exitoso, salir retry loop
                        
                    except ConversionError as e:
                        if attempt < max_retries - 1:
                            # Retry con backoff exponencial
                            await asyncio.sleep(2 ** attempt)
                            continue
                        else:
                            # Final error después de reintentos
                            await self.cache.update_entry(
                                doc_path,
                                status="modified",
                                conversion_status="final_error",
                                conversion_error=str(e)
                            )
                            report.failed_conversions += 1
                            report.errors.append(f"{doc_path}: {e}")
            
            # Fase 5: OCR (opcional)
            if use_ocr:
                # OCR logic aquí
                pass
            
            report.completed_at = datetime.now()
            report.status = "success"
            
        except Exception as e:
            report.status = "error"
            report.errors.append(str(e))
            # Cache.update_entry rollback automático si falla
        
        return report
```

### 3. Contratos en Models

```python
# core/models.py

@dataclass
class ConversionReport:
    started_at: datetime
    completed_at: datetime | None = None
    status: str = "pending"
    new_documents: int = 0
    modified_documents: int = 0
    successful_conversions: int = 0
    failed_conversions: int = 0
    duplicates_found: int = 0
    ocr_conversions: int = 0
    errors: list[str] = field(default_factory=list)
    
    @property
    def duration_seconds(self) -> float:
        if self.completed_at:
            return (self.completed_at - self.started_at).total_seconds()
        return 0.0
```

---

## Testing

### Test Scenario 1: Conversión exitosa

```python
@pytest.mark.asyncio
async def test_orchestrator_full_conversion_success(tmp_path, cache_manager):
    """Flujo completo exitoso."""
    orchestrator = Orchestrator(cache_manager, config)
    
    report = await orchestrator.start_conversion_batch(
        doc_ids=["doc1.pdf", "doc2.pdf"]
    )
    
    assert report.status == "success"
    assert report.successful_conversions == 2
    assert report.failed_conversions == 0
```

### Test Scenario 2: Error en mitad, recovery

```python
@pytest.mark.asyncio
async def test_orchestrator_retry_on_conversion_error(tmp_path, cache_manager):
    """Error en doc2, pero retry exitoso."""
    converter = Mock()
    # doc1 ok, doc2 error → error → ok en retry
    converter.convert_document.side_effect = [
        ConversionResult(...),  # doc1 ok
        ConversionError("Timeout"),  # doc2 intento 1
        ConversionError("Timeout"),  # doc2 intento 2
        ConversionResult(...),  # doc2 intento 3 ok
    ]
    
    report = await orchestrator.start_conversion_batch(
        doc_ids=["doc1.pdf", "doc2.pdf"]
    )
    
    assert report.successful_conversions == 2
    assert report.failed_conversions == 0
```

### Test Scenario 3: Cache consistency en error final

```python
@pytest.mark.asyncio
async def test_cache_consistency_after_error(tmp_path, cache_manager):
    """Cache.json refleja estado final incluso si error."""
    # doc1 ok, doc2 error después de max retries
    
    report = await orchestrator.start_conversion_batch(
        doc_ids=["doc1.pdf", "doc2.pdf"],
        max_retries=2
    )
    
    await cache_manager.load()
    entry_doc1 = cache_manager._cache["doc1.pdf"]
    entry_doc2 = cache_manager._cache["doc2.pdf"]
    
    assert entry_doc1.conversion_status == "success"
    assert entry_doc2.conversion_status == "final_error"
    assert entry_doc2.conversion_error is not None
```

---

## Consecuencias

### Positivas
- ✅ Responsabilidad clara de CacheManager
- ✅ Transacciones atómicas (backup + retry)
- ✅ Debugging observable (logging centralizado)
- ✅ Testing simple (mock Orchestrator)

### Negativas
- ❌ Mutex puede bottleneck si 10K+ docs
- ❌ Coupling explícito (Orchestrator ← todos módulos)
- ❌ Complejidad inicial (state machine)

---

## Plan de Evolución a v1.1

Si > 5000 docs simultáneos:
1. Redis pub/sub para events (Opción B)
2. Worker pool para conversiones paralelas
3. Horizontalmente escalable con múltiples workers

---

**Revisado por**: Plan Architect  
**Aprobado por**: [Tech Lead Signature]  
**Fecha**: 2026-08-27

---

## Anexo — Superseded (Claude, 2026-08-27)

Este ADR nunca se reconcilió con `doclink_extractor_plan.md`. El AUDIT_PLAN (revisión 1) ya había
identificado el mismo problema de fondo que motiva este ADR (`cache.json` reescrito por requests
concurrentes de la web app), pero lo resolvió de forma distinta: **SQLite con modo WAL y
transacciones ACID nativas** (`§2.6`), no un JSON con backup/rollback manual ni un `workflow/`
orchestrator con máquina de estados. Esa decisión ya está implementada:

- `src/doc_organize/cache/cache_manager.py` — `CacheManager` real, con `aiosqlite`, WAL,
  `compute_hash()` delegando en `utils/hash_utils.hash_file()`, y `get_changes()` como función pura
  (recibe el cache cargado y los documentos actuales, sin estado mutable interno) — 5 tests, 98% cobertura.
- `CacheEntry` en `core/models.py` usa `sha256_hash` (Pydantic), no `sha3_hash`/`sha2_hash` como
  este ADR — señal de que el ADR se escribió antes de (o sin conocer) la corrección SHA-256 del plan.

El `workflow/orchestrator.py` con máquina de estados (`DocumentState`, retry exponencial,
`Orchestrator.start_conversion_batch()`) tampoco forma parte de Fase 1: `SHARED_INSTRUCTIONS.md`
lista `workflow/` explícitamente como **TODO v0.2.0**, no v0.1.0. Introducirlo ahora sería expandir
el alcance de esta fase sin que nadie lo haya decidido realmente (la firma
`[Tech Lead Signature]` nunca se rellenó).

**Decisión vigente**: `CacheManager` con SQLite+WAL, tal como está implementado. Retry/backoff y
orquestación centralizada quedan como candidatos reales para v0.2.0, no como algo ya aprobado. Se
conserva este ADR como referencia histórica (el análisis de por qué un JSON plano no basta sigue
siendo válido — es la misma razón por la que se eligió SQLite), pero **no debe tratarse como la
decisión activa**.
