# TRACEABILITY: Resumen de Sesión

## Sesión
- **Fecha**: 2026-09-16
- **Tipo**: `feature`
- **Rama**: `develop`
- **Estado**: ✅ COMPLETADA

## Objetivo
Añadir una plantilla de taxonomía documental nueva (`sgi-integrado`) a la biblioteca empaquetada de
`doc_organize`, con 7 dominios de trabajo (Gobernanza, Riesgos, Incidencia, Continuidad, Cadena de
Suministro, Tecnología, Compromiso y Mejora Continua) y 9 tipos de material — cada uno con
`description`+`keywords` — para clasificar el corpus de un Sistema de Gestión Integrada. Contenido
derivado y calibrado contra el corpus RAG real ya convertido del proyecto `sgi_calidad`
(`C:\Desarrollo\documentation\prueba_doc\sgi_calidad\Conversión`), no inventado desde cero.

## Cambios Ejecutados

### ✅ 1. Plantilla de taxonomía `sgi-integrado` + documentación

**Archivo(s)**: `src/doc_organize/context/taxonomy_templates_builtin/sgi-integrado.md` (nuevo),
`docs/api/context.md`
**Descripción**: Fichero nuevo con el mismo formato que `calidad.md`/`sgi-iso27001.md` (front matter
YAML `domains`/`material_types` + prosa libre). `docs/api/context.md:197` actualizado para mencionar
las 3 plantillas empaquetadas (antes solo citaba 2). `MANIFEST.in` ya incluye `*.md` de ese
directorio por glob — sin cambios de packaging necesarios.
**Status**: ✅ Completo (sin commit todavía)

### ✅ 2. Cobertura de test ampliada

**Archivo(s)**: `tests/unit/test_taxonomy_template_registry.py`
**Descripción**: Test `test_list_templates_includes_the_two_builtin_templates` renombrado a
`..._three_builtin_templates` con aserciones para `sgi-integrado`; añadido a la aserción de listado
combinado con plantilla de usuario; nuevo test `test_load_template_returns_sgi_integrado_manifest`
que verifica los 7 slugs de dominio, los 9 slugs de tipo de material y que todas las entradas tienen
`description`+`keywords` no vacíos.
**Status**: ✅ Completo

### ✅ 3. Calibración empírica contra el corpus real + 3 rondas de corrección

**Descripción**: En vez de confiar en la lista de keywords a ojo, se ejecutó
`TaxonomyTemplateRegistry.load_template("sgi-integrado")` + la misma fórmula de
`score_catalog()`/`MaterialTypeClassifier` contra 10 documentos `.json` de conversión reales del
proyecto `sgi_calidad` (SOA, plan de formación, certificados, informes de auditoría, el manual del
sistema, la propia norma UNE-ISO 22301, indicadores de seguridad, procedimiento de huella de
carbono). La primera versión de la plantilla tenía un bug real: `normativa-legal` incluía siglas
sueltas (`iso`/`une`/`ens`) que aparecen en casi cualquier documento de una organización certificada
ISO, dando score `1.00` en documentos no relacionados (SOA, informe de auditoría, manual). Corregido
sustituyendo por vocabulario distintivo de texto legal. También se encontraron y eliminaron
duplicados donde `keywords:` repetía literalmente palabras que el propio `slug` ya aporta
automáticamente a `score_catalog()` (afectaba a 9 de 9 `material_types`). Tras la recalibración: la
Declaración de Aplicabilidad clasifica correctamente en el dominio `riesgos` (score 0.71) y el propio
texto de la norma ISO 22301 clasifica correctamente en `continuidad` (0.43).
**Status**: ✅ Completo, con 1 riesgo residual documentado (ver tabla de Riesgos Residuales) — el
Manual de Sistemas de Gestión (146.000 caracteres, documento "paraguas" que toca los 7 dominios a la
vez) sigue puntuando más alto en `compromiso-mejora-continua` que en `gobernanza`; es un límite
estructural del clasificador por reglas, no un bug de keywords corregible sin tocar
`domain_classifier.py` (fuera de alcance, política "prohibido refactorizar").

---

## Impacto

### Código
- **Archivos nuevos** (1): `src/doc_organize/context/taxonomy_templates_builtin/sgi-integrado.md`
- **Archivos modificados** (2): `docs/api/context.md`, `tests/unit/test_taxonomy_template_registry.py`
- **Cambios funcionales**: sí — nueva plantilla empaquetada disponible vía
  `TaxonomyTemplateRegistry.load_template("sgi-integrado")`/`list_templates()`. Ningún endpoint,
  clase o comportamiento existente cambia de forma.

### Compatibilidad
- **BREAKING**: Ninguno.
- **NO BREAKING**: Todo aditivo — un proyecto que ya usa `calidad`/`sgi-iso27001` no se ve afectado
  en absoluto; una plantilla de usuario llamada `sgi-integrado` en `~/.doc_organize/taxonomy_templates/`
  seguiría teniendo prioridad sobre esta (mismo criterio de precedencia ya existente).

---

## Verificación

Ejecutado en vivo, 2026-09-16:
```
python -m ruff check src tests                                        → All checks passed!
python -m mypy src                                                    → Success: no issues found in 76 source files
python -m pytest tests/unit/test_taxonomy_template_registry.py -q --no-cov → 18 passed
python -m pytest -q --no-cov (suite completa)                         → 865 passed (252.94s)
mkdocs build --strict                                                 → Documentation built in ~2.65s, sin errores
                                                                          (único aviso: deprecación de
                                                                          Material for MkDocs sobre
                                                                          MkDocs 2.0 — ruido del tema,
                                                                          no del build)
```
Verificación adicional (no un comando del checklist estándar, pero central al AUDIT_CODE de esta
sesión): script ad hoc ejecutando `score_catalog()`/`MaterialTypeClassifier` contra 10 documentos
`.json` reales de `sgi_calidad` en 3 rondas sucesivas, para medir el efecto real de cada ajuste de
keywords en vez de solo inspeccionar la lista.

---

## Riesgos Residuales

| Riesgo | Mitigación | Status |
|--------|-----------|--------|
| El dominio `compromiso-mejora-continua` puede ganar sobre `gobernanza` en documentos "paraguas" muy extensos (p. ej. el Manual de Sistemas de Gestión, 146K caracteres) porque `score_catalog()` puntúa por presencia/longitud de lista sin ponderar relevancia temática | Es exactamente el escenario para el que existe la Sub-fase B (clasificación por IA); no corregible solo con keywords sin tocar `domain_classifier.py` (fuera de alcance) | Aceptado |
| El tipo de material `registro-evidencia` (palabras "registro"/"evidencia", genéricas en cualquier texto administrativo) tiende a puntuar alto en documentos extensos | Mismo motivo que el anterior; las 2 plantillas preexistentes (`calidad`, `sgi-iso27001`) tampoco se han validado nunca contra documentos > 50K caracteres | Aceptado |
| La plantilla no se ha probado end-to-end contra `ContextBuilder`/`context_build_websocket` reorganizando el corpus real completo de `sgi_calidad` | Documentado como siguiente paso | Abierto |
| Commit pendiente de confirmación explícita del usuario | El propio usuario aprobó el mensaje de commit propuesto | ✅ Resuelto (commit `e3d3c29`) |

---

## Siguientes Pasos (Recomendado)
1. Si se usa esta plantilla como `taxonomy_manifest.md` real del proyecto `sgi_calidad`, validar con
   un test end-to-end que reorganice el corpus completo y mida qué fracción de documentos cae en
   Sub-fase B (sin clasificar por reglas) frente a Sub-fase A.
2. Revisar si conviene un dominio "Cumplimiento"/"Auditoría" independiente — el corpus real tiene una
   carpeta `Auditorias/` con ~15 documentos que hoy reparten su score entre `riesgos` y otros
   dominios sin un ganador claramente dedicado.

---

## Directrices para Futuras IAs

- **[patrón/gotcha]**: `score_catalog()` (`context/domain_classifier.py`) puntúa `hits/len(keywords)`,
  y `keywords` siempre incluye las palabras derivadas del propio `slug`
  (`slug.replace("-", " ").split()`) **antes** de sumar `extra_keywords` del manifiesto — nunca
  repitas en el campo `keywords:` de un catálogo de taxonomía una palabra que el slug ya vaya a
  aportar; no suma precisión, solo desperdicia una posición de la lista. Bug real cometido y
  corregido en esta sesión en las 9 entradas de `material_types` de `sgi-integrado.md`.
- **[patrón/gotcha]**: siglas cortas (`iso`, `une`, `ens`) o palabras genéricas de una sola pieza
  (`activos`, `sistemas`, `compromiso`) como `keywords` de un catálogo de taxonomía son una trampa —
  en el corpus de una organización certificada ISO aparecen en casi cualquier documento, así que el
  tipo/dominio que las incluya gana casi siempre con score artificialmente alto (verificado: `1.00`
  en 3 documentos no relacionados con solo `iso`/`une`/`ens`). Antes de confiar en un catálogo de
  taxonomía nuevo, validarlo ejecutando `score_catalog()` a mano contra `.json` de conversión reales,
  no solo por inspección visual de la lista.
- **[gotcha]**: documentos "paraguas" muy extensos (manuales de sistema completos, SOA, informes de
  auditoría de 90K-150K caracteres) tocan por diseño casi todos los dominios de cualquier catálogo —
  es un límite estructural del clasificador por reglas (Sub-fase A), no un bug de keywords. No
  perseguir precisión perfecta ahí; es exactamente el caso de uso de la Sub-fase B (IA).
- **[referencia]**: el corpus de contexto RAG usado para calibrar esta plantilla vive en
  `C:\Desarrollo\documentation\prueba_doc\sgi_calidad\Conversión` — es un proyecto real de
  `doc_organize` (organización "Virtual Desk"), con certificaciones ISO 27001/20000/22301/9001/
  45001/37001/33000/14001 y ENS ya convertidas a `.md`/`.json`. Corpus de prueba real útil para
  cualquier cambio futuro en `domain_classifier.py` o en plantillas de taxonomía.

---

## Veredicto

### 🟢 COMPLETADA

**Criterios**:
- Código, docs y tests completos y verificados (`ruff`/`mypy`/`pytest`/`mkdocs build --strict` en
  verde; 865 tests, 0 fallos).
- Catálogo calibrado empíricamente contra 10 documentos reales del corpus `sgi_calidad`, no solo por
  inspección de nombres de fichero — bug real encontrado y corregido durante la propia sesión.
- Commit confirmado explícitamente por el usuario. Working tree limpio tras el commit (`git status`
  sin salida).

**Evidencia**:
- Branch: `develop`
- Commits: `e3d3c29`
- Tests: `pytest -q --no-cov` → 865 passed (252.94s)

**Sesión cerrada**: 2026-09-16
