# DECISIONS LOG — doc_organize

Registro cronológico de decisiones arquitectónicas, técnicas y de proceso.  
Formato: **Decisión → Alternativas descartadas → Razón → Impacto actual**.  
Fuente: TRACEABILITYs de sesiones + docs de análisis.

---

## 2026-03 — Arquitectura 3 niveles Foundation/Services/Domain

**Decisión**: Dividir el módulo en 3 niveles jerárquicos:
- Nivel 1 `_core/`: capabilities, contratos base, tipos internos.
- Nivel 2 `connection/`, `metadata/`, `query/`: servicios reutilizables.
- Nivel 3 `bulk/`, `dump/`, `comparar/`, `migrate/`: lógica de dominio.

**Alternativas descartadas**: Módulo plano sin jerarquía; herencia profunda.  
**Razón**: SOLID — dependencias solo fluyen de Nivel 3 → Nivel 2 → Nivel 1. Previene ciclos.  
**Impacto actual**: Regla de oro en `architecture.instructions.md`: "un módulo de Nivel N solo importa de Nivel N y N-1". Los 3 niveles son el vocabulario compartido entre todas las IAs.

---

## 2026-04-10 — Logging centralizado en 36 clases (v0.6.8)

**Decisión**: Añadir `self.logger: logging.Logger` tipado en 36 clases de todos los niveles. Logger nombrado `__name__` (jerarquía de paquete). Sin logger global.

**Alternativas descartadas**: `print()` + `logging.basicConfig()`; logger a nivel módulo global.  
**Razón**: Trazabilidad granular por clase; silenciable por namespace sin afectar otras clases.  
**Impacto actual**: Cada clase loguea en INFO/WARNING/DEBUG con contexto propio. Patrón obligatorio para clases nuevas.

---

## 2026-04-13 — tech-debt comparar/: gaps multimotor (Fases 0-3)

**Decisión**: Resolver gaps D6+D3, D2+D5, D1+D4, M1+M2 en `comparar/` para soporte multimotor completo. 4 fases ejecutadas en una sesión.

**Razón**: La comparación de esquemas entre motores distintos (Oracle vs MariaDB) fallaba silenciosamente por incompatibilidades de tipo.  
**Impacto actual**: `SchemaComparator` soporta comparación cross-engine. Ver también: decisión 2026-06-01 (case-insensitive columns).

---

## 2026-04-14/16 — SchemaDiff reporters (HTML/Excel/Word/Markdown/SQL)

**Decisión**: Implementar 5 formatos de reporte en `comparar/reporters/` usando clases independientes con `@staticmethod` exclusivo (no herencia). Cada reporter tiene su clase; `SchemaDiffReporter` como facade.

**Alternativas descartadas**: Un único reporter configurable; herencia profunda; funciones sueltas.  
**Razón**: Política OOP: herencia para contratos de tipo (protocols); @staticmethod para utilidades sin estado. Documentado en `CLAUDE.md` y `python.instructions.md`.  
**Impacto actual**: Reporters HTML (Jinja2+Mermaid), Excel (openpyxl), Word (docx), Markdown, SQL. Complejidad cognitiva ≤ 4 en todos.

---

## 2026-04-16 — Excepciones tipadas en comparar/: ComparerError

**Decisión**: Reemplazar `ValueError`/`Exception` genéricas en `comparar/` por `ComparerError` + 3 subclases: `SchemaDiffValidationError`, `MetadataIntrospectionError`, `DiffReportGenerationError`.

**Alternativas descartadas**: Mantener excepciones genéricas; una única excepción de módulo.  
**Razón**: Permite captura diferenciada por capa. Jerarquía documentada en `docs/api/exceptions.md`.  
**Impacto actual**: Patrón replicado en `dump/` (`DumpError`/`DumpConstraintError`/`DumpReportError`).

---

## 2026-04-21 — Eliminación completa de legacy (31 funciones deprecated)

**Decisión**: Eliminar 31 funciones wrapper deprecated de 5 módulos `managers/`. 6 consumidores migrados a OOP directo. Propiedad `DatabaseQueries.queries` eliminada.

**Alternativas descartadas**: Mantener wrappers con deprecation warning.  
**Razón**: Deuda técnica acumulada; wrappers sin tests propios ocultan bugs en la interfaz real.  
**Impacto actual**: API pública de managers es 100% OOP. No hay wrappers de compatibilidad hacia atrás.

---

## 2026-05-18 — Pipeline 3 capas para módulo migrate/

**Decisión**: Arquitectura `extractor → transformer → emitter` para cada flujo DDL. Cada motor tiene sus propias implementaciones. `MigrationPlanner` orquesta.

**Alternativas descartadas**: Conversión directa SQL→SQL; un único transformer genérico.  
**Razón**: Separación de responsabilidades: extractor lee metadatos reales (INFORMATION_SCHEMA/syscat), transformer aplica reglas semánticas, emitter genera DDL dialect-específico.  
**Impacto actual**: 12 flujos validados (4 fuentes × 3 destinos). Añadir un nuevo motor = implementar las 3 clases para ese motor.

---

## 2026-05-19 — `metadata/*/tables.py` como punto canónico del SQL de introspección

**Decisión**: Todo SQL de introspección (fetch tablas, vistas, rutinas, índices) vive exclusivamente en `metadata/<motor>/tables.py`. Prohibido duplicar en `migrate/`, `comparar/` u otras capas.

**Alternativas descartadas**: SQL inline en cada módulo consumidor; `migrate/sql/` como paquete separado (creado y eliminado en misma semana).  
**Razón**: Un único punto de verdad para SQL de metadatos evita divergencias entre la comparación y la migración del mismo motor. Regla REGLA #1 en `architecture.instructions.md`.  
**Impacto actual**: `migrate/sql/` fue eliminado (sesión `2026-05-22-metadata-sql-canonical`). Toda función `fetch_*_sql()` vive en `metadata/`.

---

## 2026-05-22 — "Directrices para Futuras IAs" formalizada en TRACEABILITY

**Decisión**: Toda TRACEABILITY.md de sesión debe incluir sección `## Directrices para Futuras IAs` con hechos verificables, patrones y contratos que una IA nueva no puede inferir del código.

**Razón**: IAs sucesivas perdían contexto de decisiones tomadas. Las directrices son persistencia de memoria entre sesiones.  
**Impacto actual**: Plantilla `TEMPLATE/TRACEABILITY.md` incluye el placeholder. REGLAS #1–#6 de metadata access documentadas como modelo.

---

## 2026-05-25 — dump/ y BulkInserter Protocol

**Decisión**: `dump/` no depende directamente de `BulkCrud` (Nivel 3 → Nivel 3 prohibido). Se introduce `BulkInserter` Protocol (`@runtime_checkable`) en `dump/_protocols.py`. `DumpConfig.bulk_audit_path` propagado al constructor.

**Alternativas descartadas**: Import directo de BulkCrud en DumpOrchestrator.  
**Razón**: Evitar dependencia circular entre módulos del mismo nivel. Protocol permite mock en tests.  
**Impacto actual**: `dump._process_table` tipado con `crud: BulkInserter`. `BulkInserter` re-exportado en `dump/__init__.py`.

---

## 2026-05-31 / 2026-06-01 — Palancas de rendimiento bulk/dump (v0.9.0 → v0.10.0)

**Decisiones de performance implementadas**:
1. `commit_every_n_chunks` (commit-as-you-go, reduce memoria).
2. `IndexManager.manage_indexes` — deshabilita índices secundarios no únicos durante carga masiva.
3. `bulk_session(atomic=True)` — transacción única por tabla (antes 1 por chunk).
4. `ParallelBulkLoader` — paralelización por tabla (niveles topológicos FK) y por rangos de PK.
5. `bulk_insert_from_chunks` — streaming de datos.
6. **v0.10.0**: `PostgresCopyStrategy` (psycopg3 COPY ~10×), `MySQLMultiRowInsertStrategy` (multi-fila parametrizado), `InsertStrategyResolver` reescrito.
7. **Dump sin SchemaComparator**: `DumpOrchestrator.run()` eliminó la llamada a `compare()` (cascada ~500 queries/100 tablas).

**Razón**: Perfiles de producción mostraron cuellos de botella en commit granular, índices y paso de comparación innecesario.  
**Impacto actual**: Tabla de estrategias INSERT en `docs/api/bulk-crud.md`. `collect_row_counts=False` para volcados de alto volumen.

---

## 2026-06-01 — MySQL/MariaDB variables auto-config en BulkCrud (PR #18)

**Decisión**: `BulkCrud.__init__` detecta `innodb_buffer_pool_size` y `max_allowed_packet` via `SHOW VARIABLES` (read-only) y loguea recomendaciones. No modifica la BD (sin `SET GLOBAL`).

**Alternativas descartadas**: SET GLOBAL automático (requiere SUPER privilege); documentación solamente.  
**Razón**: Variables por defecto (<128 MB buffer, 16 MB packet) causan error 2013 "Lost connection" en cargas masivas. La lectura es segura y transparente.  
**Impacto actual**: `MySQLVariableValidator` + `MySQLOptimalConfig` en `connection/mariadb/`. Logging INFO para estado, WARNING si debajo de mínimos. PR #18 OPEN.

---

## 2026-06-02 — Paralelismo safe: `_resolve_max_workers` acota a pool_size

**Decisión**: `ParallelBulkLoader._resolve_max_workers` = `min(requested, pool_size)`. Constraints DDL se deshabilitan UNA VEZ antes del pool (no per-worker) para MSSQL (SCH-M) y PostgreSQL (ACCESS EXCLUSIVE).

**Razón**: Workers > pool_size causa deadlock por agotamiento de conexiones. Per-worker DDL en MSSQL/PG falla por bloqueos exclusivos.  
**Impacto actual**: `ValueError` explícito si `commit_every_n_chunks` y `max_retries > 0` simultáneos (incompatibles semánticamente).

---

## 2026-06-03 — Estándar documental v2: 5 arquetipos × 5 secciones

**Decisión**: Toda documentación sigue 5 arquetipos (Funcional, Técnico/API, Guía, Ejemplo, ADR) × 5 secciones fijas. Nav MkDocs tiene exactamente 7 secciones top-level (no añadir más).

**Alternativas descartadas**: Documentación libre sin estructura; 4 arquetipos × 4 secciones (v1).  
**Razón**: Facilita búsqueda por IA y por humanos. Enlace bidireccional api↔examples es obligatorio.  
**Impacto actual**: Prompts actualizados: `functional_doc.prompt.md`, `technical_doc.prompt.md`, `guide_doc.prompt.md`, `example_doc.prompt.md`, `architecture_doc.prompt.md` (nuevo ADR). `mkdocstrings` apunta a nombre real de clase (no alias).

---

## 2026-06-04 — Collation por defecto MariaDB: utf8mb4_uca1400_ai_ci

**Decisión**: `DEFAULT_COLLATION` en `migrate/charset.py` cambiado de `utf8mb4_unicode_ci` → `utf8mb4_uca1400_ai_ci`.

**Razón**: UCA1400 es el estándar moderno de MariaDB ≥ 10.10 (mejor ordenación Unicode, case-insensitive, accent-insensitive).  
**Impacto actual**: Destinos MariaDB < 10.10 o MySQL DEBEN pasar `collation=` explícito. Tests existentes con `utf8mb4_unicode_ci` como entrada son válidos (sigue siendo collation válida).

---

## 2026-06-04 — Documentación: Zenical vs MkDocs vs Sphinx

**Decisión**: **Zenical** como generador estático de destino. MkDocs Material 9.5 se mantiene provisionalmente mientras Zenical no esté en crates.io.

**Alternativas descartadas**:
- **Sphinx**: requiere ~70% reescritura de docs, complejidad alta de configuración, no apto para multi-lenguaje.
- **Seguir con MkDocs**: sin ventaja técnica a largo plazo.

**Razón**: Zenical = +80% performance (Rust), Material Design 3, Mermaid nativo, 100% compat. con Markdown existente, 0 cambios de contenido.  
**Impacto actual**: Rama `migrate/zenical-pure` lista (5 commits, `zensical.toml` 634L). Bloqueado por publicación en crates.io. Rollback: `git checkout develop && mkdocs build`.

---

## 2026-06-05 — Bootstrap IA cross-project: modelo PULL

**Decisión**: Para trasladar config IA a otro proyecto, invocar desde el DESTINO con el origen como plantilla de solo lectura (modelo PULL). Clasificar activos en 4 capas: A (verbatim+revisar comandos), B (copiar+reescribir dominio), C (regenerar), D (excluir).

**Alternativas descartadas**: Modelo PUSH (desde el origen) — arrastra supuestos Python/doc_organize al destino.  
**Razón**: El destino puede tener otro lenguaje y arquitectura. El prompt necesita el código real del destino en contexto.  
**Impacto actual**: Prompt `.github/prompts/bootstrap_ai_config.prompt.md`. Soporta 5 plataformas: Claude, Gemini, Copilot, Cursor, Codex.
