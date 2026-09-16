# Deduplicación — Referencia Técnica

API Reference para detección y resolución de duplicados.

## Arquitectura

```mermaid
classDiagram
    class DeduplicationManager {
        -logger: Logger
        +find_duplicates(docs: list[DocumentMetadata], fuzzy_threshold: int | None) list[DuplicateGroup]
        +resolve_duplicates(groups: list[DuplicateGroup], duplicates_dir: Path) DeduplicationReport
    }
    
    class DuplicateGroup {
        +group_id: str
        +canonical_doc: DocumentMetadata
        +duplicates: list[DocumentMetadata]
        +reason: DuplicateReason
        +user_choice: DocumentMetadata | None
    }
    
    class DeduplicationReport {
        +timestamp: datetime
        +total_exact_duplicates: int
        +total_version_conflicts: int
        +duplicates_folder_path: Path
        +audit_json_path: Path
        +groups: list[DuplicateGroup]
    }
    
    DeduplicationManager --> DuplicateGroup
    DeduplicationManager --> DeduplicationReport
```

## API Pública

### DeduplicationManager

```python
class DeduplicationManager:
    def find_duplicates(
        self,
        docs: list[DocumentMetadata],
        fuzzy_threshold: int | None = None
    ) -> list[DuplicateGroup]
    
    async def resolve_duplicates(
        self,
        groups: list[DuplicateGroup],
        duplicates_dir: Path
    ) -> DeduplicationReport
```

#### find_duplicates (Síncrono)

Agrupa documentos por duplicado exacto, conflicto de versión y, opcionalmente, similitud
aproximada de nombre.

| Parámetro | Tipo | Descripción |
|---|---|---|
| `docs` | `list[DocumentMetadata]` | Documentos escaneados |
| `fuzzy_threshold` | `int \| None` | Score mínimo RapidFuzz (0-100) para la 3ª pasada; `None` (por defecto) la desactiva — retrocompatible |

| Retorno | Tipo | Descripción |
|---|---|---|
| | `list[DuplicateGroup]` | Grupos de duplicados (incluyendo grupos unitarios) |

**Agrupación**:
1. Por SHA-256 exacto → `reason=exact_duplicate`
2. Por nombre base (sin extensión, sin versión) → `reason=version_conflict`
3. (opcional, si `fuzzy_threshold` no es `None`) Por similitud aproximada de `display_name` entre
   los documentos que no quedaron agrupados en 1-2, usando `rapidfuzz.process.cdist` (vectorizado)
   y componentes conexas del grafo de similitud (score ≥ `fuzzy_threshold`, sin exigir
   transitividad estricta par a par) → `reason=fuzzy_name_match`. Excluido siempre de la
   resolución automática masiva ("Buscar duplicados"); solo se resuelve desde el formulario
   interactivo de "Revisar Duplicados" (elección manual del usuario por grupo).

**Selección de canónico**:
- Documento más antiguo (mínimo `modified_time`) — en grupos `fuzzy_name_match` es una propuesta,
  no se aplica sin que el usuario la confirme (o la sobrescriba) explícitamente

---

#### resolve_duplicates (Async)

Mueve documentos descartados a carpeta de duplicados.

| Parámetro | Tipo | Descripción |
|---|---|---|
| `groups` | `list[DuplicateGroup]` | Grupos de `find_duplicates()` |
| `duplicates_dir` | `Path` | Carpeta destino para duplicados |

| Retorno | Tipo | Descripción |
|---|---|---|
| | `DeduplicationReport` | Reporte de resolución (incluyendo `DEDUP_REPORT.json`) |

**Proceso**:
1. Para cada grupo, determina canónico (o usa `user_choice` si proporciona)
2. Mueve documentos no-canónicos a `duplicates_dir`, preservando estructura original
3. Escribe `DEDUP_REPORT.json` con auditoría completa (solo la última ejecución)
4. Añade una línea a `DEDUP_HISTORY.jsonl` (histórico acumulado, nunca se sobrescribe)
5. Retorna `DeduplicationReport` con resumen

**Excepciones**:
- `ProjectError` — Errores críticos durante movimiento

---

## Contratos

### Entrada

| Parámetro | Validación | Impacto si falla |
|---|---|---|
| Documento con SHA-256 | Validación previa (Scanner) | Documento no se agrupa |
| Carpeta existe | Validación en `resolve_duplicates()` | Error |

### Salida

```python
@dataclass
class DuplicateGroup:
    group_id: str
    canonical_doc: DocumentMetadata
    duplicates: list[DocumentMetadata]
    reason: DuplicateReason  # exact_duplicate | version_conflict | fuzzy_name_match
    user_choice: DocumentMetadata | None = None

@dataclass
class DeduplicationReport:
    timestamp: datetime
    total_exact_duplicates: int
    total_version_conflicts: int
    duplicates_folder_path: Path
    audit_json_path: Path
    groups: list[DuplicateGroup]
```

## Dependencias

| Dependencia | Propósito |
|---|---|
| `core.constants.VERSION_SUFFIX_PATTERN` | Detecta sufijos de versión |
| `core.models.DuplicateGroup`, `DeduplicationReport` | Modelos |
| `core.exceptions.ProjectError` | Excepciones |
| `utils.path_utils.is_subpath()`, `safe_path_join()` | Manipulación segura de rutas |
| `utils.logging` | Logging |
| `rapidfuzz.process.cdist`, `rapidfuzz.fuzz.WRatio`, `rapidfuzz.utils.default_process` | Matriz de scores de similitud de nombre (3ª pasada, vectorizado, con normalización previa) |
| `numpy` (transitivo vía `pandas`) | Extrae, vectorizado, los pares de la matriz de scores por encima del umbral |

## Notas Internas

- **Naming**: `_extract_base_name()` normaliza nombres (strip extensión, sufijo versión, lowercase)
- **Movimiento seguro**: `safe_path_join()` previene path traversal
- **Colisiones**: Si destino existe, añade sufijo con hash de 8 caracteres
- **Auditoría completa**: `DEDUP_REPORT.json` incluye lista de todas las decisiones
- **Histórico incremental**: `DEDUP_HISTORY.jsonl` (una línea JSON por ejecución de
  `resolve_duplicates()`, formato JSON Lines) acumula todas las ejecuciones, a
  diferencia de `DEDUP_REPORT.json` (que solo refleja la última)

## Ejemplos Relacionados

- [Deduplicar documentos](../examples/dedup-resolve.md)
