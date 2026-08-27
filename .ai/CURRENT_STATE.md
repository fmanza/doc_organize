# CURRENT STATE — doc_organize

**Generado**: 2026-06-05  
**Fuente**: Sesiones activas Mayo-31–Junio-05 + docs Zenical  
**Versión estable**: `v0.10.0` (rama `main`)  
**Rama activa**: `develop`

---

## Versión actual y release

| Hito | Estado |
|------|--------|
| `v0.9.0` | Liberado — palancas perf bulk: `commit_every_n_chunks`, `IndexManager`, paralelización FK-topológica, `ParallelBulkLoader`, `bulk_insert_from_chunks` |
| `v0.10.0` | Liberado — fast paths INSERT por motor: `PostgresCopyStrategy` (psycopg3 COPY ~10×), `MySQLMultiRowInsertStrategy` (multi-fila), `InsertStrategyResolver` reescrito |
| `v0.11.0` | Pendiente — objetivo: merge `migrate/zenical-pure` (+80% perf doc builds) cuando Zenical esté instalable |

PR abierta: **PR #18** `feat(connection/bulk): automatización variables MySQL/MariaDB` — revisión pendiente de merge.  
PR en espera: **PR #19** `migrate/zenical-pure` — bloqueada hasta que Zenical v0.0.44 esté en crates.io (o instalación manual de binario).

**Tests actuales**: 3826 passed / 1 skipped (tras sesión bulk-parallelism 2026-06-02).

---

## Trabajo activo (sesiones más recientes)

### Documentación y estándares IA (2026-06-03 a 2026-06-05)
- **Estándar documental v2** implementado: 5 arquetipos × 5 secciones, 7 secciones nav MkDocs, enlace bidireccional api↔examples, autodoc Bulk+Dump corregidos. (`2026-06-03-docs-standard-v2`)
- **`--verify-tools`** (consulta webs oficiales) y **`--verify-build`** (build local + lectura `site/` o `localhost:8000`) incorporados como modificadores del agente Documentation Generator. Guía pública: `docs/doc_verification_guide.md`. (`2026-06-05-verify-docs`)
- **Bootstrap IA cross-project** implementado: prompt `.github/prompts/bootstrap_ai_config.prompt.md` (modelo PULL, 5 plataformas: Claude, Gemini, Copilot, Cursor, Codex). Commit `cd22520` en develop, push/PR pendiente. (`2026-06-05-bootstrap-ai-config`)

### Hotfix crítico MariaDB (2026-06-04)
- **`utf8mb4_uca1400_ai_ci`** establecida como collation por defecto en `migrate/charset.py` (requiere MariaDB ≥ 10.10). Para MariaDB < 10.10 o MySQL pasar `collation=` explícito. (`2026-06-04-mariadb-default-collation-uca1400`)

### Performance bulk (2026-05-31 a 2026-06-02)
- **MySQL auto-config variables**: `MySQLVariableValidator` + `MySQLOptimalConfig` + `BulkCrud.__validate_mysql_config()` — detecta `innodb_buffer_pool_size` / `max_allowed_packet` en `__init__`, logging read-only, sin SUPER requerido. (`2026-06-01g`)
- **SQL template caching** `MySQLMultiRowInsertStrategy._sql_template_cache` por `(num_rows, cols_tuple)` — 5–20% mejora en sub-lotes iguales. (`2026-06-01f`)
- **`RangePartitioner` + `HashPartitioner`** + métricas `PartitionResult`/`ParallelLoadResult` + `maintenance_scope` por worker. (`2026-06-02b`, `2026-06-02`)
- **Paralelismo corregido**: `_resolve_max_workers` acota a `pool_size` (previene deadlock), `_hoist_constraints_for_workers` deshabilita DDL una vez para MSSQL/PG. (`2026-06-02`)
- **`PKSequenceSyncer`**: sincronización automática de contadores PK post-bulk para PostgreSQL/SQLServer/MariaDB/Oracle ≥ 12c. (`2026-05-31-pk-sync-post-bulk`)
- **Dump sin comparación de esquemas**: eliminada cascada N+1 queries (`SchemaComparator.compare()`) del `DumpOrchestrator.run()`. (`2026-06-01b`)

---

## Migración a Zenical

| Estado | Detalle |
|--------|---------|
| **Configuración** | `zensical.toml` (634 L) completo y validado. 92 docs .md, 44 diagramas Mermaid — 100% compatibles, 0 cambios en contenido. |
| **CI/CD** | `.github/workflows/docs.yml` actualizado (`zensical build` + `peaceiris/actions-gh-pages`). |
| **Instrucciones IA** | `CLAUDE.md`, `copilot-instructions.md`, `ZENICAL.md` — referencias actualizadas. |
| **Bloqueador** | Zenical v0.0.44 NO publicado en crates.io (solo v0.0.3 placeholder). |
| **Solución A (ahora)** | Descargar binario precompilado desde https://github.com/zensical/zensical/releases/tag/v0.0.44, copiar a `%USERPROFILE%\.cargo\bin\`. |
| **Solución B (esperar)** | Aguardar publicación en crates.io (~2026-Q3), usar `cargo install zensical --version 0.0.44`. |
| **Rama** | `migrate/zenical-pure` (5 commits, lista para merge cuando Zenical esté disponible). |
| **Build actual** | MkDocs Material 9.5 funcional (`mkdocs build` en 5.5s, 0 errores). |

**Ventaja de migrar**: build 300ms → 80ms (−73%), page load 400ms → 100ms (−75%), −50% dependencias docs.

---

## Próximos pasos

1. **Merge PR #18** (`MySQLVariableValidator`) tras review. Potencial tag `v0.10.1`.
2. **Zenical opción A** (decisión del usuario): descargar binario, validar `zensical build`, merge `migrate/zenical-pure`, tag `v0.11.0`.
3. **FASE 5 doc estándar** (criterios de aceptación): pendiente validación QA — no rellenar `## 4. Criterios de Aceptación` en `docs/functional/*.md` hasta esa sesión.
4. **Push commit `cd22520`** (bootstrap IA) o PR a main — pendiente decisión del usuario.

---

## Motores soportados

| Motor | Como fuente | Como destino | Notas |
|-------|-------------|--------------|-------|
| Oracle | ✅ | ✅ | SEQUENCE+TRIGGER; identity mode opcional |
| MariaDB | ✅ | ✅ | Default collation: `utf8mb4_uca1400_ai_ci` (≥10.10) |
| MySQL | — | ✅ | Comparte estrategia con MariaDB |
| PostgreSQL | ✅ | ✅ | SERIAL/BIGSERIAL/SMALLSERIAL; `PostgresCopyStrategy` |
| SQL Server | ✅ | ✅ | IDENTITY(1,1); `fast_executemany` |
| SQLite | — | ✅ | |
| HSQLDB | — | ✅ | |

**Matriz migrate/** completada: 4 fuentes × 3 destinos = 12 flujos DDL validados.

---

## Calidad actual

- **Lint**: `ruff check src tests` → 0 errores (all checks passed)  
- **Tipos**: `mypy src` → 0 errores (336 source files)  
- **Tests**: 3826 passed / 1 skipped  
- **Build docs**: `mkdocs build --strict` → 0 errores, 0 warnings  
- **Complejidad cognitiva**: reporters ≤ 4, emitter `_topological_sort` → 0 (desglosado en helpers)  
