# TRACEABILITY: Resumen de Sesión

## Sesión
- **Fecha**: 2026-11-02
- **Tipo**: `feature`
- **Rama**: `feature/dedup-relativo-0.12.1` → PR #16 a `develop` (squash); ampliación G26:
  `feature/dedup-nofollow-0.12.1` → segundo PR a `develop` (squash), antes del tag
- **Estado**: ✅ COMPLETADA

## Objetivo
Tarea L-11a del plan de doc_organize_web (Fase 6, condición C1, hueco G24): que `duplicados/` pueda replicar la ruta
**relativa** a una carpeta indicada en lugar de la ruta absoluta del servidor. Versión 0.12.1 (aditivo y compatible;
la 0.13.0 queda reservada para L-10, deprecación de la web integrada). Plan del consumidor:
`../doc_organize_web/.ai/sessions/2026-11-02-fase6/PLAN.md`.

## PLAN

- **Rutas afectadas**: `src/doc_organize/dedup/deduplication.py`, `src/doc_organize/scan/scan_command.py`,
  `tests/unit/test_dedup_modes.py`, `tests/unit/test_main.py`, `docs/api/dedup.md`, `CHANGELOG.md`,
  `COMPATIBILITY.md`, `pyproject.toml`.
- **Componentes**: `DeduplicationManager._move_to_duplicates`, `move_group`, `resolve_duplicates`;
  `ScanCommand.deduplicate_streaming`/`_dedup_pipeline`.
- **Tipos**: `relative_to: Path | None = None` (*keyword-only*). Sin tipos nuevos.
- **Riesgos**: escribir fuera de `duplicates_dir` (mitigado: `safe_path_join` sigue validando el destino y la ruta
  relativa se obtiene con `Path.relative_to` sobre rutas resueltas, que nunca produce `..`); documentos fuera de
  `relative_to` (fallo por fichero, no se recurre a la ruta absoluta); dobles de test que sustituyen `move_group` o
  `_move_to_duplicates` con la firma anterior (los argumentos nuevos solo se pasan si no son el valor por defecto).

## AUDIT_PLAN

- **Funcional**: con varias raíces bajo un mismo `relative_to`, dos descartados pueden coincidir en ruta relativa: lo
  cubre el sufijo de hash y, si también existe, la colisión doble es un fallo por fichero (sin sobrescribir).
- **Técnico (LSP/ISP)**: contratos async sin cambios; parámetro opcional y *keyword-only*; llamada idéntica a la
  anterior con los valores por defecto.
- **Seguridad**: es el objetivo (no revelar rutas del servidor). Un enlace simbólico que resuelva fuera de
  `relative_to` falla por fichero.
- **Simplificaciones**: no se añade a la CLI (no lo pide el consumidor).
- **Veredicto**: GO.

## Ampliación G26 (misma versión 0.12.1)

Petición añadida a L-11a: `_move_to_duplicates` no debe seguir enlaces simbólicos (antes resolvía el origen con
`resolve()` y `safe_path_join` resolvía la base de `duplicates_dir`; un enlace cambiado justo antes de mover hacía que
se moviera o copiara un fichero de fuera).

- **PLAN**: `ensure_no_symlinks` en `utils/path_utils.py` (`lstat` de cada tramo existente, sin resolver; también
  uniones de Windows); en `_move_to_duplicates`, rutas con `os.path.abspath` y comprobación del origen, de
  `duplicates_dir` y de la carpeta destino; en POSIX, movimiento/copia con descriptores abiertos tramo a tramo con
  `O_NOFOLLOW` (`rename` con `src_dir_fd`/`dst_dir_fd`; con `EXDEV`, copia `O_NOFOLLOW`/`O_EXCL` + `unlink`);
  `check_duplicates_dir` al inicio de `resolve_duplicates` y `_dedup_pipeline` (`InvalidPathError`).
- **AUDIT_PLAN**: la comprobación con `lstat` sola deja una ventana entre comprobar y mover: por eso en POSIX se opera
  con `dir_fd`. Windows no tiene `dir_fd` ni `O_NOFOLLOW`: queda la comprobación con `lstat` (crear enlaces allí exige
  privilegios). Rutas que pasan por un enlace del sistema (macOS `/tmp`, `/var`) fallan: el llamador debe pasar rutas
  reales. Veredicto: GO.
- **AUDIT_CODE**: en la verificación en Linux (WSL, script que ejecuta las funciones nuevas extraídas con `ast`) se
  encontraron y corrigieron dos fallos que Windows no mostraba: `stat.IO_REPARSE_TAG_MOUNT_POINT` solo existe en
  Windows (constante propia) y la copia perdía la fecha porque el búfer se escribía al cerrar, después de `utime`
  (`flush` antes). Verificado en Linux: move/copy normales, permisos y fecha, sufijo y colisión doble, origen enlace,
  enlace en tramo intermedio y en el fichero final puestos *después* de la comprobación (`ENOTDIR`/`ELOOP`),
  subcarpeta de duplicados enlazada, `duplicates_dir` enlace y movimiento entre sistemas de ficheros (`EXDEV`).
  Residual: `rename` sobrescribe en POSIX si el destino aparece entre la comprobación de existencia y el movimiento
  (ya ocurría antes); `mkdir` puede dejar carpetas vacías bajo `duplicados/` cuando el fichero falla.
- **Tests**: origen sustituido por un enlace (move y copy) y carpeta de origen sustituida por un enlace →
  `failed_paths` sin tocar el destino del enlace; `duplicates_dir` enlace → `InvalidPathError` y `OSError`; carrera
  simulada (solo POSIX); copia conserva la fecha; `ensure_no_symlinks`. En Windows sin privilegios se saltan los que
  crean enlaces; en el CI de Ubuntu se ejecutan.

## Cambios Ejecutados

### ✅ 1. `relative_to` en la resolución de duplicados

**Archivo(s)**: `src/doc_organize/dedup/deduplication.py`, `src/doc_organize/scan/scan_command.py`
**Descripción**: `_move_to_duplicates` calcula las partes de la ruta relativas a `relative_to` (resuelto); si el
origen no cuelga de esa carpeta lanza `OSError`, que `move_group` registra en `failed_paths`. `move_group`,
`resolve_duplicates` y `deduplicate_streaming` propagan el parámetro.
**Status**: ✅

### ✅ 2. Tests

**Archivo(s)**: `tests/unit/test_dedup_modes.py`, `tests/unit/test_main.py`
**Descripción**: `move` y `copy` con `relative_to` (`duplicados/2024/a_copia.pdf`); sufijo de hash con
`relative_to`; documento fuera de `relative_to` → `failed_paths` sin tocar el origen ni escribir nada; sin
`relative_to` se replica la ruta absoluta como antes; `deduplicate_streaming(relative_to=)` de extremo a extremo.
**Status**: ✅

### ✅ 3. Documentación y versión

**Archivo(s)**: `docs/api/dedup.md` (firmas actuales de `resolve_duplicates` y `move_group`), `CHANGELOG.md` (con
firmas finales), `COMPATIBILITY.md`, `pyproject.toml` (0.12.1)
**Status**: ✅

---

## Impacto

### Código
- **Cambios funcionales**: sí, solo si se pasa `relative_to`.

### Compatibilidad
- **BREAKING**: ninguno.
- **NO BREAKING**: parámetro opcional nuevo en cuatro métodos.

---

## AUDIT_CODE

| Área | Hallazgo | Resolución |
|---|---|---|
| Bugs | Origen igual a `relative_to` (ruta relativa vacía) | Se usa el nombre del fichero, igual que la rama absoluta |
| Edge case | Documento fuera de `relative_to` | `OSError` → `failed_paths`; test |
| Edge case | Colisión con `relative_to` | Sufijo de hash; test |
| Performance | Un `resolve()` más por fichero movido | Despreciable frente al movimiento |
| Seguridad | Escritura fuera de `duplicates_dir` | `safe_path_join` sin cambios + `relative_to` sin `..` |
| Tipado | `mypy src` sin errores | — |
| Deuda técnica | `safe_path_join` lanza `InvalidPathError` (no `OSError`), que `move_group` no aísla por fichero | Previo a esta tarea; inalcanzable con rutas resueltas. Sin cambios (política de no refactorizar) |

## Verificación
```
python -m ruff format src tests     # 2 ficheros reformateados (los nuevos tests)
python -m ruff check src tests      # All checks passed!
python -m mypy src                  # Success: no issues found in 92 source files
python -m pytest                    # 1005 passed, 3 skipped (PR #16); 1007 passed, 9 skipped con G26
zensical build --strict             # sin errores
```

## VERSION

- **Commit (squash)**: `feat: ruta relativa en duplicados/ (L-11a) y versión 0.12.1`
- **Impacto en API pública**: aditivo (`relative_to` opcional, *keyword-only*).
- **Rollback**: revertir el commit de squash en `develop` (sin migraciones ni cambios de formato).

## Riesgos Residuales

| Riesgo | Mitigación | Status |
|--------|-----------|--------|
| El consumidor pasa un `relative_to` que no contiene las raíces escaneadas | Cada fichero queda en `failed_paths` y en el informe; nada se mueve | Aceptado |

## Directrices para Futuras IAs

- **[dedup]**: con `relative_to`, `_move_to_duplicates` nunca recurre a la ruta absoluta; un origen fuera de esa
  carpeta es `OSError` (fallo por fichero en `move_group`).
- **[dedup]**: `_move_to_duplicates` no resuelve ni sigue enlaces (G26); en POSIX opera con `dir_fd` + `O_NOFOLLOW`.
  No volver a usar `resolve()` ni `safe_path_join` (resuelve la base) en ese camino.
- **[verificación]**: los tests con enlaces se saltan en Windows sin privilegios; para probar la ruta POSIX en local
  sirve WSL (sin `pip`: extraer las funciones con `ast`, no dependen de numpy/pydantic).
- **[compatibilidad]**: los parámetros nuevos de `move_group`/`_move_to_duplicates` solo se pasan cuando no tienen el
  valor por defecto, porque hay tests que sustituyen esos métodos con la firma anterior.

## Veredicto
CLOSED
