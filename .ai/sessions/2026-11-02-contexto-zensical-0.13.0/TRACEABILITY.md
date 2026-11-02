# TRACEABILITY: Resumen de Sesión

## Sesión
- **Fecha**: 2026-11-02
- **Tipo**: `feature`
- **Rama**: `feature/contexto-zensical-0.13.0` → PR a `develop` (squash)
- **Estado**: ✅ COMPLETADA

## Objetivo
Tareas L-8 y L-8a…L-8c del plan de doc_organize_web (Fase 7, contexto y taxonomías; huecos G10, G27, G28 y G29).
Versión **0.13.0** (MINOR): sitio de contexto con Zensical en lugar de MkDocs, reorganización sin seguir enlaces
simbólicos, rutas del contexto públicas y plantillas de taxonomía como texto. La deprecación de la web integrada (L-10),
reservada para 0.13.0, pasa a la siguiente MINOR.

## PLAN

- **Rutas afectadas**: `context/site_generator.py` (nuevo), `context/taxonomy_templates.py` (nuevo),
  `context/mkdocs_generator.py` (alias), `context/reorganizer.py`, `context/taxonomy_template_registry.py`,
  `context/context_registry.py`, `context/taxonomy_manifest.py`, `projects/layout.py`, `utils/path_utils.py`,
  `dedup/deduplication.py` (helpers compartidos), `core/{constants,exceptions,models}.py`, `__init__.py`,
  `web/routes/context.py`, `web/templates/context.html.j2`; tests, docs, `CHANGELOG.md`, `COMPATIBILITY.md`,
  `pyproject.toml`.
- **L-8**: `SiteGenerator.generate(project, context, *, build=True, site_dir=None, timeout=None) -> SiteResult`,
  `build_site`, `delete_site`; `SiteBuildError(DocOrganizeError)`; `Context.site_generated`/`site_built` con
  `validation_alias` para los nombres antiguos y propiedades obsoletas; `MkDocsGenerator` subclase con
  `DeprecationWarning`; extra `site` = `zensical`. TOML escrito a mano (la biblioteca estándar solo lee TOML).
- **L-8a**: helpers `O_NOFOLLOW` de 0.12.1 movidos a `path_utils` (`copy_file_nofollow`, `copy_tree_nofollow`,
  `ensure_tree_has_no_symlinks`); comprobación completa antes de copiar; fallo por documento con `OSError`.
- **L-8b**: propiedades de `ProjectLayout`, `RESERVED_OUTPUT_FOLDER_NAMES`, `validate_output_folder_name`; la web los
  usa en lugar de sus copias.
- **L-8c**: funciones de texto en un módulo sin `Path.home()`; el registro las usa y calcula su carpeta por defecto al
  crearse.

## AUDIT_PLAN

- **Funcional**: Zensical exige que `docs_dir` y `site_dir` cuelguen de la carpeta de `zensical.toml` y **vacía
  `site_dir` al construir** (verificado) → `site_dir` validado: dentro de la raíz, ni la raíz, ni la carpeta
  reorganizada ni otra reservada, ni enlaces. Zensical crea `.cache/` junto a la configuración → reservada y borrada
  por `delete_site`.
- **Compatibilidad**: `MkDocsGenerator` como alias puro cambia el retorno de `generate` (tupla → `SiteResult`) y el
  fallo (`False` → `SiteBuildError`); es lo que pide L-8 («alias de `SiteGenerator`», «nunca `site_built=False` en
  silencio»), documentado en «Changed». La web integrada mantiene su comportamiento (captura `SiteBuildError` →
  `site_built=False`).
- **Seguridad**: build real con Markdown hostil (Zensical 0.0.74): el HTML incrustado pasa tal cual (por defecto de
  Python-Markdown) → documentado. Hallazgo adicional: Zensical no escapa `nav`/`site_name` y el tema aplica
  `striptags` (que deshace entidades) en `<title>` → `</title><script>` en un título de documento se ejecutaba; escapar
  no basta, `<`/`>` pasan a `＜`/`＞`. Verificado con build real.
- **Simplificaciones**: sin escribir TOML con dependencia nueva; sin cambiar `ContextBuildEventType.MKDOCS_STARTED`
  (valor en el cable).
- **Veredicto**: GO.

## Cambios Ejecutados

### ✅ 1. L-8 (G10) — Sitio de contexto con Zensical
**Archivo(s)**: `context/site_generator.py`, `context/mkdocs_generator.py`, `core/exceptions.py`, `core/models.py`,
`web/routes/context.py`, `web/templates/context.html.j2`, `pyproject.toml`
**Descripción**: `SiteGenerator`/`SiteResult`/`SiteBuildError`; `zensical.toml` + `index.md`; `python -m zensical`
del mismo entorno o `zensical` del `PATH`; `timeout`; borrado de `mkdocs.yml` heredado; textos propios neutralizados.
**Status**: hecho.

### ✅ 2. L-8a (G27) — Reorganizar sin seguir enlaces
**Archivo(s)**: `context/reorganizer.py`, `utils/path_utils.py`, `dedup/deduplication.py`
**Descripción**: carpeta de salida enlazada → `InvalidPathError`; documento con tramo enlazado → falla solo, sin copia
parcial (`Context.reorganize_failed_documents`, `on_document_failed`, evento `document_failed`).
**Status**: hecho.

### ✅ 3. L-8b (G28) — Rutas del contexto públicas
**Archivo(s)**: `projects/layout.py`, `core/constants.py`, `context/context_registry.py`, `web/routes/context.py`
**Status**: hecho.

### ✅ 4. L-8c (G29) — Plantillas de taxonomía como texto
**Archivo(s)**: `context/taxonomy_templates.py`, `context/taxonomy_template_registry.py`
**Descripción**: `parse`/`render` con ida y vuelta estable (forzadas comillas dobles en cadenas con cualquier salto
que `splitlines()` reconozca: con PyYAML por defecto fallaban ~37 % de 5000 casos aleatorios). `delete_template`
valida el nombre (antes `../x` borraba fuera de la carpeta).
**Status**: hecho.

## AUDIT_CODE

- `SiteGenerator.generate` escribía `index.md` sin comprobar que la carpeta reorganizada no fuera un enlace → añadido
  `Reorganizer.check_output_root` (con test).
- Fuzz de ida y vuelta de plantillas: 20 000 casos sin fallo tras el cambio de estilo YAML.
- Verificación en Linux (WSL, Ubuntu, Python 3.14, entorno aparte con zensical): tests de reorganizador, `path_utils`,
  deduplicación, generador (con build real) y plantillas, **sin saltos** (enlace de fichero y casos POSIX), incluido un
  enlace puesto después de la comprobación (`O_NOFOLLOW`). En Windows sin privilegio de symlink, los casos de carpeta se
  cubren con uniones; el de fichero se salta.

## Impacto

### Compatibilidad
- **BREAKING (documentado en «Changed»)**: `MkDocsGenerator.generate` devuelve `SiteResult` y lanza `SiteBuildError`;
  el extra `site` instala `zensical` (no `mkdocs`); `Reorganizer` no sigue enlaces (una ruta bajo un enlace del sistema
  falla, como la deduplicación de 0.12.1).
- **NO BREAKING**: todo lo demás es aditivo; `context.json` antiguo se lee igual; `Context(mkdocs_generated=...)` sigue
  aceptándose.

## Verificación
```
python -m ruff check src tests          # sin errores
python -m ruff format --check src tests # sin cambios
python -m mypy src                      # sin errores (94 ficheros)
python -m pytest                        # ver PR
zensical build --strict                 # sin incidencias
```

## Riesgos Residuales

| Riesgo | Mitigación | Status |
|--------|-----------|--------|
| HTML incrustado en los `.md` (contenido no confiable) llega al sitio | Documentado; quien sirve el sitio debe aislarlo (otro origen o CSP `sandbox`) | Abierto (por diseño de Zensical) |
| La web integrada sirve el sitio en el mismo origen que la aplicación | Igual que con MkDocs; la web se congela y se retira (L-10 en la siguiente MINOR) | Abierto |
| Tema por defecto carga Mermaid de unpkg.com si hay bloques `mermaid` | Documentado | Abierto |
| `ProjectRegistry` sigue evaluando `Path.home()` al importar `doc_organize.projects` | Solo calcula la ruta; las funciones de plantillas no dependen de ella | Abierto (fuera de alcance) |

## Directrices para Futuras IAs

- **[sitio]**: Zensical vacía `site_dir` al construir y exige que cuelgue de la carpeta de `zensical.toml`; nunca pasar
  una carpeta con contenido propio como `site_dir`.
- **[seguridad]**: Zensical inserta sin escapar `nav`/`site_name` y el tema aplica `striptags` en `<title>`; cualquier
  texto nuevo que `SiteGenerator` escriba en la configuración tiene que pasar por `_label`.
- **[yaml]**: `yaml.safe_dump` emite comillas simples multilínea con separadores Unicode crudos; para releer con
  `splitlines()` hay que forzar comillas dobles (`_TemplateDumper`).
- **[enlaces]**: copiar o mover ficheros de un proyecto con `copy_file_nofollow`/`copy_tree_nofollow` de `path_utils`,
  nunca `shutil.copy2`/`copytree` directamente.
- **[tests]**: en Windows sin privilegio de symlink, las uniones (`_winapi.CreateJunction`) cubren los casos de carpeta;
  verificar en Linux (WSL) los de fichero y la ruta `O_NOFOLLOW`.

## Veredicto
CLOSED
