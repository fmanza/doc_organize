# TRACEABILITY: Resumen de Sesión

## Sesión
- **Fecha**: 2026-11-03
- **Tipo**: `feature`
- **Rama**: `feature/contexto-seguro-0.14.0` (sobre `feature/ia-multiusuario-0.14.0`, PR #20)
- **Estado**: ✅ COMPLETADA (pendiente de commit/PR a petición del usuario)

## Objetivo
Cerrar los huecos de integridad y seguridad del contexto de 0.13.0 (doc_organize_web G30–G32, tareas L-8d…L-8f), en la
misma 0.14.0 que L-3a…L-3e: nombres que se sobrescriben al reorganizar, temporales que siguen enlaces y
`output_folder_name` sin validar al cargar `context.json`.

## Cambios Ejecutados

### ✅ 1. L-8d — colisiones de nombre al reorganizar
**Archivo(s)**: `src/doc_organize/context/reorganizer.py`, `site_generator.py`, `context_builder.py`, `core/models.py`
**Descripción**: `resolve_organized_paths(domain, project_root)` (pública) + `assign_organized_paths` (interna del
paquete). Colisión = mismo `(tipo, stem)` en el dominio con clave NFC + casefold + sin puntos/espacios finales; todos
los miembros llevan `-<8 hex>` (SHA-256 del `.md` relativo a la raíz del proyecto; se alarga a 16/64 si aún chocan).
`DomainDocument.organized_path` informativo; `Reorganizer`/`SiteGenerator` recalculan siempre.

### ✅ 2. L-8e — temporales sin seguir enlaces
**Archivo(s)**: `src/doc_organize/utils/atomic_write.py` (nuevo, interno), `context_registry.py`, `site_generator.py`,
`taxonomy_manifest.py`
**Descripción**: `write_text_atomic` con `tempfile.mkstemp` en la misma carpeta + `os.replace`; conserva permisos
(o `0o666 & ~umask` si es nuevo) y borra el temporal si falla. Mismo tratamiento de saltos de línea que `write_text`.

### ✅ 3. L-8f — `output_folder_name` validado
**Archivo(s)**: `core/models.py`, `context_registry.py`, `reorganizer.py`, `site_generator.py`
**Descripción**: `field_validator` (importación dentro de la función para evitar el ciclo `models` ↔ `layout`);
`load_context` da `ContextError` con mensaje específico; `Reorganizer` y `SiteGenerator` revalidan.

---

## Impacto

### Compatibilidad
- **BREAKING**: ninguno de firma. Cambios de comportamiento: `Context(output_folder_name=<inválido>)` da
  `ValidationError`; con colisión, cambia el nombre de la carpeta (antes se perdían copias).
- **NO BREAKING**: sin colisiones, rutas idénticas a 0.13.0; tests existentes de `Reorganizer`/`SiteGenerator`/contexto
  pasan sin cambios.

## Verificación
```
python -m ruff check src tests            -> All checks passed!
python -m mypy src                        -> Success: no issues found in 95 source files
pytest tests/unit/test_context_integrity_l8.py -> 30 passed, 2 skipped (permisos POSIX en Windows)
pytest (contexto/sitio/taxonomía existentes)   -> 335 passed sin cambios
zensical build --strict                   -> No issues found
```

## Directrices para Futuras IAs
- **[context/rutas]**: la ruta de un documento en la carpeta reorganizada sale SOLO de `resolve_organized_paths`; no
  vuelvas a componer `<dominio>/<tipo>/<stem>/` a mano ni uses `DomainDocument.organized_path` leído de disco.
- **[utils/escritura]**: cualquier escritura atómica nueva usa `utils.atomic_write.write_text_atomic`; nunca
  `write_text` sobre un `.tmp` de nombre fijo.
- **[deuda]**: `ProjectRegistry`, `ScannedFoldersStore` y `TaxonomyTemplateRegistry` siguen con `.tmp` de nombre fijo
  (viven en la raíz de estado, no en el recurso compartido); candidatos a pasar a `write_text_atomic`.
- **[models]**: `Context` no tiene `validate_assignment`; las defensas en profundidad de `output_folder_name` están en
  `Reorganizer`/`SiteGenerator`.

## Veredicto
CLOSED (pendiente de commit/PR a petición del usuario).
