# 🏗️ Arquitectura de doc_organize

**Versión:** 0.10.0
**Última Actualización:** Junio 2026
**Estado:** Estable | Completamente Refactorizado
**Motores Soportados:** MariaDB • MySQL • PostgreSQL • Oracle • SQLite • HSQLDB • SQL Server • Redshift • Snowflake

---

## Visión General

**doc_organize** es una librería que proporciona abstracción unificada para operaciones con múltiples motores de base de datos:

- **Jerarquía de 3 niveles**: Foundation → Services → Specialization
- **API moderna**: Managers sync/async con soporte nativo para async/await
- **Type-safe**: Full type hints con validación en tiempo de desarrollo
- **Modular**: Cada componente tiene responsabilidad única y clara
- **Metadata canónica**: `metadata/*/tables.py` es el único punto autorizado para SQL de introspección (Regla #1–#6, `architecture.instructions.md`)

---

## Estructura Modular (3 niveles)

```
📦 doc_organize
│
├─── LEVEL 1: ABSTRACCIONES (Foundation Layer)
│
│    _core/                          ⭐ Core abstractions
│    ├── types.py                    # Type aliases
│    ├── exceptions.py               # DatabaseException y jerarquía completa
│    ├── contracts.py                # Protocols base
│    └── constants.py                # Enums compartidos
│
│    _drivers/                       🔌 Detección de drivers
│    ├── validator.py                # DatabaseTypeValidator
│    ├── driver_validator.py         # DriverValidator
│    └── _config_loader.py
│
│    core/
│    └── capabilities.py             # Capacidades por motor
│
├─── LEVEL 2: SERVICIOS (Services Layer)
│
│    connection/                     🔌 Gestión de conexiones
│    ├── factory.py                  # ConnectFactory
│    ├── builder.py                  # build_conn_params()
│    ├── protocols.py
│    ├── close.py
│    └── motors/                     # Adaptadores: mariadb, postgresql, oracle, sqlite, hsqldb, sqlserver
│
│    query/                          ❓ Registry y ejecución
│    ├── registry.py                 # QueryRegistry
│    ├── resolver.py                 # QueryResolver
│    └── queries.py                  # DatabaseQueries
│
│    executors/                      ⚡ Ejecución de queries
│    ├── base.py
│    ├── sync_query_executor.py
│    └── async_query_executor.py
│
│    metadata/                       🔍 Esquemas y caché
│    ├── cache.py                    # DatabaseMetadataCache + RelationshipMetadataCache
│    ├── normalizer.py
│    ├── builder.py
│    ├── fetcher.py
│    ├── manager.py                  # MetadataManager
│    ├── contracts.py
│    ├── mariadb/ mysql/ oracle/ postgresql/ sqlserver/ sqlite/
│    │   └── tables.py               # ← ÚNICO punto canónico de SQL de introspección
│    └── providers/                  # SyncMetadataProvider / AsyncMetadataProvider
│
│    results/                        📋 Tipos de retorno
│    └── types.py, normalizer.py
│
│    factory/                        🏭 SQLAlchemy engines
│    └── pool_factory.py, sqlalchemy_engine_factory.py, async_sqlalchemy_engine_factory.py
│
│    validators/                     ✓ Validadores de queries
│
├─── LEVEL 3: ESPECIALIZACIÓN (Specialization Layer)
│
│    managers/                       🎛️ API pública principal
│    ├── sync_mgr.py                 # SyncDatabaseManager
│    └── async_mgr.py                # AsyncDatabaseManager
│
│    bulk/                           📦 Operaciones masivas
│    ├── crud.py                     # BulkCrud — INSERT/UPDATE/DELETE + maintenance_scope
│    ├── audit.py                    # AuditManager, AuditTransaction (thread-safe en paralelo)
│    ├── normalize.py                # Normalización de registros
│    ├── parallel.py                 # ParallelBulkLoader — carga paralela por particiones
│    ├── partition.py                # RangePartitioner (PK entera/datetime) + HashPartitioner (str/UUID)
│    ├── strategies/                 # InsertStrategyResolver — selección automática de fast-path
│    │   ├── postgres_copy.py        # PostgresCopyStrategy (~10× vía psycopg3 COPY)
│    │   ├── mysql_multirow.py       # MySQLMultiRowInsertStrategy (multi-fila + SQL template cache)
│    │   └── default.py              # Fallback executemany
│    ├── pk_sync.py                  # PKSequenceSyncer + PKSyncResult
│    └── mysql_variables.py          # MySQLVariableValidator + MySQLOptimalConfig
│
│    comparar/                       🔍 Comparación de esquemas
│    ├── comparator.py               # SchemaComparator (cross-engine case-insensitive)
│    ├── contracts.py
│    ├── models.py                   # SchemaDiff
│    └── reporters/                  # HTML (Jinja2+Mermaid), Excel, Word, Markdown, SQL, Text
│
│    dump/                           📤 Volcado entre motores (v0.8.0+)
│    ├── orchestrator.py             # DumpOrchestrator (sin SchemaComparator en hot-path)
│    ├── _constraints.py             # ConstraintManager (PG savepoints, Oracle batch, SS NOCHECK)
│    ├── _models.py                  # DumpConfig, DumpResult, DumpAuditSummary, ConstraintResult
│    ├── _protocols.py               # BulkInserter Protocol
│    ├── _sql_utils.py               # Quoting helpers
│    ├── reporters.py                # DumpReporter (Excel + texto)
│    └── (index_manager, parallel)   # IndexManager, paralelización FK-topológica
│
│    migrate/                        🔄 Migración DDL (v0.8.0+, 4×3 = 12 flujos)
│    ├── planner.py                  # MigrationPlanner
│    ├── ir/models.py                # CanonicalTable, CanonicalView, CanonicalRoutine, MigrationPlan
│    ├── extractors/                 # OracleSchemaExtractor, MariaDBSchemaExtractor, PostgreSQLSchemaExtractor, SQLServerSchemaExtractor
│    ├── transformers/               # 12 transformers (origen×destino)
│    ├── emitters/                   # OracleDDLEmitter, MariaDBDDLEmitter, PostgreSQLDDLEmitter, SQLServerDDLEmitter
│    ├── _compat/                    # type_map_*.py (12 mapas de tipos)
│    ├── charset.py                  # DEFAULT_COLLATION = utf8mb4_uca1400_ai_ci (MariaDB ≥10.10)
│    └── reporters/                  # format_plan_markdown, format_plan_text (con rutinas y body)
│
│    analysis/                       📊 Grafos de relaciones
│    ├── base.py                     # GraphDocument, traversal multinivel
│    ├── graphviz.py + graphviz_ext.py
│    └── matplotlib_graph.py
│
│    doc/                            📄 Documentación de BD
│    └── (Jinja2 templates → HTML/Word/Excel)
│
│    async_utils.py                  # maybe_await
│    models.py                       # Modelos de dominio compartidos
│    __init__.py                     # API pública (re-exports)
│    docs_build_plugin.py            # Plugin MkDocs: documentation_zip (ZIP + SHA256)
```

---

## Reglas de dependencia (NO violar)

| Regla | Descripción |
|---|---|
| Level 1 → no importa Level 2/3 | Foundation nunca depende de servicios |
| Level 2 → importa Level 1 únicamente | Services no importa managers ni bulk |
| Level 3 → importa Level 1+2 | Specialization construye sobre la base |
| `metadata/*/tables.py` = único punto canónico SQL | Ningún módulo duplica SQL de introspección |
| Sin ciclos de importación | Orden estricto por nivel |

---

## APIs Públicas (importes recomendados)

```python
from doc_organize import (
    SyncDatabaseManager, AsyncDatabaseManager,
    DatabaseMetadataCache, RelationshipMetadataCache,
    SyncMetadataProvider, AsyncMetadataProvider,
    SchemaComparator, SchemaDiff,
    ConnectionFactory, PoolFactory, build_conn_params,
    maybe_await,
)

# Bulk operations
from doc_organize.bulk import BulkCrud, ParallelBulkLoader, AuditManager, PKSequenceSyncer
from doc_organize.bulk import RangePartitioner, HashPartitioner

# Migration DDL
from doc_organize.migrate import MigrationPlanner, MigrationPlan

# Dump
from doc_organize.dump import DumpOrchestrator, DumpConfig, DumpResult

# Exceptions (fuente canónica: _core/exceptions.py)
from doc_organize import DatabaseException, ConnectionError, QueryError, ValidationError
```

---

## Decisiones Arquitectónicas Clave

| ID | Decisión | Motivo |
|---|---|---|
| D1 | 3 niveles en lugar de 1/2 | Separación de concerns; Foundation estable, Specialization evoluciona |
| D2 | `metadata/*/tables.py` punto canónico | Evitar duplicación de SQL de introspección entre migrate/ y metadata/ |
| D3 | Managers en Level 3 | Dependen de TODOS los servicios Level 2; ponerlos en Level 2 causaría ciclos |
| D4 | InsertStrategyResolver | Elegir fast-path (COPY/multi-fila/executemany) sin modificar la API de BulkCrud |
| D5 | DumpOrchestrator sin SchemaComparator en hot-path | Eliminar cascada N+1 queries; skipped_columns se calcula en _common_columns |
| D6 | utf8mb4_uca1400_ai_ci por defecto (MariaDB ≥10.10) | Mejora de UCA 1400; utf8mb4_unicode_ci sigue siendo opción válida para versiones anteriores |
| D7 | PKSequenceSyncer post-bulk | Evitar errores de PK duplicada tras INSERT masivo sin IDENTITY/SERIAL |
| D8 | MigrationPlanner pass-through v1 para rutinas | Las rutinas se extraen con su DDL original; transformación semántica es revisión manual |

---

*Documento actualizado: Junio 2026 - alineado a v0.10.0*
