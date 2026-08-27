# Prompt: documentation_review (Python library)

## Devuelve en este orden
1. PLAN
2. AUDIT_PLAN
3. AUDIT_CODE (auditoría de documentación)
4. VERSION

## Revisar
- README y entry points de documentación
- Docstrings en APIs públicas (cobertura, claridad, ejemplos)
- Ejemplos existentes (correctness, completitud, actualización)
- Guías técnicas (arquitectura, onboarding, troubleshooting, migraciones)
- Documentación de instalación y compatibilidad de motores
- Changelog y release notes
- Cross-references y linkability
- Consistencia de lenguaje y tone
- `mkdocs.yml`: navegación, páginas inexistentes, páginas huérfanas, tema Material, Mermaid
- Prompts e instrucciones IA de documentación en `.github/prompts/`, `.github/agents/` y `.github/instructions/`
- Separación clara entre documentación funcional, técnica y ejemplos

## Criterios por severidad

### Nivel 1: Crítico
- README sin descripción clara o sin quick start
- Módulos públicos sin docstrings
- APIs sin type hints o sin documentación de parámetros/return/excepciones
- Ejemplos rotos u obsoletos
- Instalación no documentada
- `mkdocs.yml` referencia páginas inexistentes o excluye páginas necesarias para onboarding

### Nivel 2: Alto
- Features principales sin ejemplos
- Documentación de arquitectura incompleta o sin diagramas
- Guías de troubleshooting ausentes
- Incompatibilidades entre motores no aclaradas
- Errores no documentados
- Prompts de documentación que inducen a inventar capacidades o mezclan funcional y técnico sin secciones claras

### Nivel 3: Recomendado
- Ejemplos avanzados no cubiertos
- Edge cases sin ejemplificar
- Performance tips no documentados
- Integración con herramientas sin guía

## Reglas
- Diferencia gaps críticos (bloquean uso) de mejoras recomendadas.
- NO inventes documentación que no existe; reporta dónde falta.
- Prioriza por impacto en onboarding y seguridad.
- Incluye ubicación exacta de archivos/módulos.
- Sugiere formato y contenido mínimo para cerrar gaps.
- Etiqueta claramente ejemplos faltantes y ubicación sugerida.
- Verifica ejemplos en `docs/examples/` y docstrings en módulos `__init__.py` y archivos públicos.
- Verifica que cada página nueva o existente esté publicada o excluida intencionalmente en `mkdocs.yml`.
- Comprueba que Mermaid se use en bloques fenced y sin detalles sensibles.
- Señala si se propone un único prompt masivo para todo el proyecto; recomienda dividir en fases.
- Excluye por el momento recomendaciones para generación mediante APIs externas.

## Formato adicional requerido

Incluye estas subsecciones dentro de `AUDIT_CODE`:

### MkDocs y navegación
- Estado de `mkdocs.yml`
- Páginas huérfanas o rotas
- Secciones funcional/técnica/ejemplos

### Prompts IA de documentación
- Riesgos de invención
- Duplicación entre prompts/agentes/instrucciones
- Cumplimiento de exclusión de APIs externas

## Formato de salida completo

Devuelve el resultado en este orden y con estas secciones:

### PLAN
- Alcance de la revisión (módulo concreto o proyecto completo)
- Fuentes consultadas: README, `docs/`, `docs/examples/`, docstrings, `mkdocs.yml`, prompts IA
- Criterio de priorización: Nivel 1 > Nivel 2 > Nivel 3

### AUDIT_PLAN
- Riesgos identificados antes de revisar (cobertura insuficiente, desactualización, inventar datos)
- Veredicto: `GO | GO_CONDICIONAL | NO_GO`

### AUDIT_CODE
Incluye las subsecciones:

#### README y puntos de entrada
#### Documentación funcional (`docs/functional/`)
- Módulos con objetivo de negocio, flujo y reglas documentados
- Módulos sin documentación funcional

#### Documentación técnica (`docs/api/`)
- Módulos con responsabilidad, Mermaid, API y contratos documentados
- Módulos sin documentación técnica

#### Ejemplos (`docs/examples/`)
- Ejemplos existentes: ubicación, completitud, reproducibilidad
- Módulos principales sin ejemplo verificable

#### MkDocs y navegación
- Estado de `mkdocs.yml` (separación funcional/técnica/ejemplos)
- Páginas huérfanas (en disco, no en nav)
- Páginas rotas (en nav, no en disco)

#### Docstrings y type hints
- Cobertura en módulos públicos
- APIs sin parámetros, returns o excepciones documentadas

#### Prompts IA de documentación
- Riesgos de invención en prompts/agentes
- Duplicación entre ficheros de instrucciones
- Cumplimiento de la exclusión de APIs externas

### VERSION
- Hallazgos Nivel 1 (críticos): acción inmediata requerida
- Hallazgos Nivel 2 (altos): planificados para próxima iteración
- Hallazgos Nivel 3 (recomendados): backlog
- Veredicto de readiness: `PRODUCTION_READY | NEAR_READY | BLOCKED`
- Próximos pasos priorizados (máximo 5 ítems)
