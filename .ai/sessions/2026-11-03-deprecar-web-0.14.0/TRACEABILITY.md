# TRACEABILITY: Resumen de Sesión

## Sesión
- **Fecha**: 2026-11-03
- **Tipo**: `feature`
- **Rama**: `feature/deprecar-web-0.14.0` (sobre `feature/contexto-seguro-0.14.0`, PR #21)
- **Estado**: ✅ COMPLETADA (pendiente de commit/PR a petición del usuario)

## Objetivo
L-10: deprecar la web integrada (`doc_organize.web`, `doc_organize.auth` y los subcomandos `web`, `tenant`, `user`)
porque doc_organize_web 0.9.0 cubre la paridad. Solo avisos y documentación; se retira en 1.0.0 (L-11).

## Cambios Ejecutados

### ✅ 1. Avisos al importar
**Archivo(s)**: `src/doc_organize/_deprecations.py` (nuevo, interno), `web/__init__.py`, `auth/__init__.py`
**Descripción**: `DeprecationWarning` con `skip_file_prefixes=(<paquete doc_organize>, "<frozen importlib")`
(Python ≥ 3.12): se atribuye a la línea del consumidor, también cuando `web` importa `auth` por dentro.

### ✅ 2. Avisos del CLI
**Archivo(s)**: `src/doc_organize/main.py`
**Descripción**: aviso único por stderr tras `parse_args` para `web`/`tenant`/`user`; «[obsoleto]» en `help` y
`description` (también de `create`/`set-instance-admin`). `doc_organize.auth` pasa a importarse dentro de
`_auth_store` (y `AuthStore` bajo `TYPE_CHECKING`), con el aviso de import silenciado ahí y en `_run_web` para no
duplicarlo. Antes `main.py` lo importaba al cargarse y cualquier comando habría avisado.

### ✅ 3. Documentación
README, `docs/functional/{access,admin,ai_settings}.md` (nota al principio), `docs/api/publica.md`, CHANGELOG
(«Deprecated» de 0.14.0, con lo que se queda y lo que se va).

## Compatibilidad
- **BREAKING**: ninguno. Mismo stdout, mismo código de salida; los comandos de librería no avisan.

## Verificación
```
pytest tests/unit/test_web_deprecation.py -> 16 passed
ruff / mypy / zensical build --strict    -> sin errores
```

## Directrices para Futuras IAs
- **[cli]**: no vuelvas a importar `doc_organize.auth`/`doc_organize.web` en el nivel de módulo de `main.py`: haría
  avisar (y cargar la web) a `scan`, `project`, `deduplicate` y `export`.
- **[deprecations]**: el texto del aviso sale solo de `_deprecations.web_deprecation_message`; L-11 (1.0.0) borra
  `web/`, `auth/`, los tres subcomandos y este módulo.
- **[tests]**: los tests de import usan un proceso aparte con `PYTHONIOENCODING=utf-8` (en Windows el aviso, con
  tildes, rompía la lectura de la salida).

## Veredicto
CLOSED (pendiente de commit/PR a petición del usuario).
