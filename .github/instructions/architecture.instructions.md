---
applyTo: "src/**/*.py"
---
# Arquitectura OO, SOLID y Patrones

> **TL;DR** — 2 capas (Foundation → Core Services), más `web/` (Fase D) como orquestador de alto
> nivel. Separar escaneo, conversión, deduplicación y caché en módulos independientes (SRP). Cada
> servicio recibe/devuelve los modelos de `core/models.py` (Pydantic), nunca tipos ad-hoc (LSP).
> Extender por adaptadores/Strategy cuando aparezca un nuevo motor de OCR o formato, nunca editando
> flujos base estables (OCP). Orquestar desde `Protocol`/`ABC` cuando haga falta abstraer un
> servicio, no desde clases concretas (DIP).

## Objetivo
Definir reglas de arquitectura para `doc_organize`, una librería de escaneo, conversión (vía
Docling), deduplicación y caché de documentos, con una interfaz web opcional.

## Principios de diseño
- Claridad antes que abstracción: cada capa y cada clase deben tener un límite explícito.
- Evolución incremental: aplicar patrones solo cuando reducen acoplamiento o duplicación real.
- Compatibilidad: preservar API pública y contratos existentes salvo decisión explícita.

## Checklist SOLID para PR
- `SRP`: la clase/módulo tiene una razón de cambio dominante.
- `OCP`: agregar un motor de OCR o formato de documento no requiere editar múltiples módulos estables.
- `LSP`: implementaciones concretas son intercambiables bajo el mismo contrato.
- `ISP`: contratos pequeños y orientados al uso; sin métodos no relevantes.
- `DIP`: capas de orquestación dependen de interfaces (`Protocol`/`ABC`), no de concretos.

## Patrones recomendados y uso
- `Strategy`: variaciones por motor de OCR (RapidOCR CPU vs. EasyOCR GPU) o formato de salida.
- `Factory Method`: creación de instancias de Docling por combinación de opciones (`DocumentConverter._get_docling`).
- `Adapter`: aislar la API de Docling detrás de `doc_organize.converter.DocumentConverter`, para no
  acoplar el resto de la librería a su interfaz interna.
- `Template Method`: pipeline común de escaneo/conversión con pasos extensibles.
- `Facade`: API de alto nivel en `web/` (Fase D) para orquestar scanner + converter + dedup + cache.
- `Builder`: construcción incremental de reportes (p.ej. `DeduplicationReport`, `ScanResult`).
- No introducir patrones si una solución simple y explícita cubre el caso sin deuda.

### Logging como responsabilidad transversal

Logging no es un patrón sino una responsabilidad **transversal** presente en todas las capas:

#### Principio SOLID aplicado
- **SRP**: Cada clase es responsable de su propio logging (rastreo de su estado y transiciones)
- **OCP**: Nueva clase → nuevo logger, sin modificar logging central
- **DIP**: Código de negocio NO depende de implementación de logging (delegar en `utils.logging.get_logger()`)

#### Patrón en capas

**Level 1 (Foundation):** Tipos y excepciones, sin logging (no tienen comportamiento que rastrear)
```python
# core/exceptions.py
class DocOrganizeError(Exception):
    """Excepcion base para todos los errores de doc_organize."""
```

**Level 2 (Core Services):** Clases que implementan servicios, logging obligatorio
```python
# scanner/document_scanner.py
from doc_organize.utils.logging import get_logger

class DocumentScanner:
    def __init__(self) -> None:
        self.logger = get_logger(__name__)

    async def scan_folders(self, paths: list[str]) -> ScanResult:
        self.logger.info(f"Escaneo completado: {len(documents)} documentos en {duration:.2f}s")
```

**Level 3 (`web/`, Fase D):** Clases que orquestan servicios, logging enriquecido con contexto
```python
# web/routes/conversion.py (futuro)
from doc_organize.utils.logging import get_logger

logger = get_logger(__name__)

class ConversionOrchestrator:
    async def convert_batch(self, doc_ids: list[str]) -> None:
        logger.info(f"Iniciando conversion batch de {len(doc_ids)} documentos")
        ...
```

#### Checklist arquitectónico con logging
- [ ] Cada clase con estado tiene `self.logger: logging.Logger` (via `utils.logging.get_logger(__name__)`)
- [ ] Logger inicializado en `__init__()`
- [ ] Métodos que mutan estado loguean transiciones (`self.logger.info()`)
- [ ] Métodos que fallan loguean con `self.logger.warning()`/`error(..., exc_info=True)`
- [ ] Sin variables globales mutables (usar inyección o factory pattern)

## Anti-patrones
- `God class`.
- Condicionales por formato/motor de OCR repartidos por toda la base de código (centralizar en `converter/`).
- Mezclar lógica de negocio con detalles de escritura a disco o de red.
- Patrones aplicados por inercia sin necesidad demostrable.
- Reimplementar el cálculo de SHA-256 fuera de `utils/hash_utils.py` (ver regla siguiente).

## Reglas de fuente única de verdad (single source of truth)

> Aplican a cualquier módulo de `src/doc_organize/`.

### REGLA #1 — HASHING: ÚNICA FUENTE EN `utils/hash_utils.py`
`utils/hash_utils.hash_file()` es la única función autorizada para calcular el hash SHA-256 de un
documento. Ningún otro módulo (`scanner/`, `cache/`, `converter/`, `dedup/`) puede reimplementar
este cálculo — todos delegan en `hash_file()`. Confirmado y corregido durante IMPLEMENT: la versión
inicial de esta función tenía I/O bloqueante pese a ser `async def`; ver `doclink_extractor_plan.md`
§13 para el historial.

### REGLA #2 — VALIDACIÓN DE RUTAS: ÚNICA FUENTE EN `utils/path_utils.py`
`utils/path_utils.safe_path_join()` es el único punto autorizado para construir una ruta de destino
a partir de una base y componentes derivados de un documento (nombre de archivo, ruta relativa).
Ningún módulo debe concatenar rutas manualmente cuando el resultado se deriva, aunque sea
parcialmente, de datos del documento — previene path traversal.

### REGLA #3 — MODELOS: ÚNICA FUENTE EN `core/models.py`
Todo tipo de datos compartido entre módulos (`DocumentMetadata`, `ConversionResult`, `CacheEntry`,
`DuplicateGroup`, etc.) vive en `core/models.py` como modelo Pydantic. Los servicios pueden usar
dataclasses internas (`XxxInternal`) solo como optimización del hot path (evitar overhead de
validación Pydantic en escaneos de 10K+ archivos), con un método `.to_pydantic()` para convertir en
el límite del sistema — patrón ya establecido por `DocumentMetadataInternal`/`ConversionResultInternal`.

### REGLA #4 — CONTRATOS ANTES QUE IMPLEMENTACIONES
Si un módulo nuevo necesita abstraer un servicio externo (p.ej. un motor de OCR alternativo):
- Define el contrato como `Protocol`/`ABC`.
- Implementa el adaptador concreto.
- Inyecta la dependencia por constructor.

### REGLA #5 — VALIDAR ANTES DE CREAR
Ante cualquier nueva clase, función o módulo:
- Busca en `src/doc_organize/` funcionalidad similar antes de escribir código nuevo.
- Si existe → reutiliza. Si hay gap menor → extiende. Si la lógica es nueva → crea el módulo mínimo
  necesario y expón en su `__init__.py`.

### REGLA #6 — JERARQUÍA DE DEPENDENCIAS (sin inversiones)
La base de código sigue 2 niveles (más `web/` en Fase D). Las dependencias fluyen **solo hacia
abajo**; nunca hacia arriba ni en horizontal entre módulos de nivel equivalente:

```
Level 1 — Foundation
  core/         utils/

Level 2 — Core Services (independientes entre sí, solo dependen de Level 1)
  validators/   scanner/      converter/    dedup/    cache/

Level 3 — Orquestación (Fase D)
  web/          (orquesta validators/scanner/converter/dedup/cache)
```

**Reglas explícitas:**
- Level 3 puede importar de Level 2 y Level 1.
- Level 2 puede importar de Level 1.
- Level 2 **NUNCA** importa de Level 3, ni de otro módulo de Level 2 salvo dependencia explícita ya
  establecida (p.ej. `converter/ocr_scheduler.py` importa `converter/converter.py`, mismo paquete).
- Level 1 **NUNCA** importa de Level 2 ni Level 3.
- No importaciones circulares dentro del mismo nivel.
- `__init__.py` de cada módulo solo re-exporta; no contiene lógica que genere ciclos.

**En auditoría (AUDIT_CODE):** rechaza cualquier import donde un módulo de Level 1 (`core/`,
`utils/`) referencie un símbolo de Level 2 o superior.

## Evidencia mínima en cambios arquitectónicos
- Justificación del patrón elegido y alternativa descartada.
- Contrato tipado (`Protocol`/`ABC`) y al menos una implementación.
- Tests de contrato (incluye sustitución de implementaciones).
- Riesgos de compatibilidad y estrategia de rollback documentados.

## Referencias
- https://martinfowler.com/eaaCatalog/ (patrones generales; los específicos de acceso a datos
  — Query Object, Repository, Data Mapper, Identity Map — no aplican: `doc_organize` no tiene capa
  de persistencia relacional propia, solo un cache SQLite de hashes en `cache/cache_manager.py`)
