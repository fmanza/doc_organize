# 📚 Glossary - doc_organize

## Core Concepts

### Level 1: Foundation
- **_core/**: Tipos básicos, excepciones, contratos (no dependencias de otra parte de la librería)
- **_drivers/**: Registro de drivers, validación, capacidades por motor
- **Types**: Aliases unificados (RowOrNone, Rows, QueryParams)
- **Protocols**: Contratos (ConnectionLike, PoolLike, QueryResultLike)

### Level 2: Core Services
- **connection/**: Pool singleton, lifecycle, parámetros de conexión
- **metadata/**: Caché de esquema, introspection, relaciones
- **query/**: Registro centralizado, versionado, ejecución
- **results/**: Normalización, mapeo, conversión de resultados

### Level 3: Domain Logic
- **managers/**: APIs sync/async (SyncDatabaseManager, AsyncDatabaseManager)
- **bulk/**: CRUD masivo (insert, update, delete desde DataFrame)
- **audit/**: Registro de auditoría en CSV
- **analysis/**: Grafos relacionales multinivel, cardinalidad y renderizado documental

## Key Terms

- **Motor**: Engine/dialect de BD (MariaDB, PostgreSQL, Oracle, etc.)
- **Pool**: Conjunto de conexiones reutilizables
- **Manager**: API pública sync o async para operaciones
- **Query Registry**: Registro centralizado de SQL con versiones
- **Metadata Cache**: Esquema en caché con TTL
- **Audit Trail**: CSV con user, timestamp, operación, delta
- **GraphDocument**: Modelo intermedio del grafo con nodos, aristas, niveles y resumen de niveles ocultos
- **DiagramSummary Payload**: Contrato compartido que resume profundidad visible, niveles por sentido y ayudas de navegación para HTML y Word
- **DiagramLegend Payload**: Contrato compartido con leyenda visual de dirección, cardinalidad, tipo de tabla y tipo de relación
- **LevelDirection**: Sentido del recorrido relacional: `incoming`, `outgoing` o `both`
- **Relation Graph**: Grafo de FK/PK con soporte multinivel y agrupación por nivel

## Abbreviations

- **BD**: Base de Datos
- **CRUD**: Create, Read, Update, Delete
- **FK**: Foreign Key
- **PK**: Primary Key
- **TTL**: Time To Live
- **ORM**: Object-Relational Mapping
- **Core**: SQLAlchemy Core (usado aquí; no ORM)
- **RCA**: Root Cause Analysis
