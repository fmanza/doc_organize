# Prompt: onboarding_dev — Guía de incorporación para desarrolladores (Arquetipo 7)

<!--
  NÚCLEO BASE compartido con dpss/.github/prompts/onboarding_dev.prompt.md
  ÚNICA SECCIÓN EDITABLE POR PROYECTO: ## Especialización de dominio (abajo)
  Última revisión: 2026-06-08
-->

Genera o actualiza la guía de incorporación para nuevos desarrolladores de **doc_organize** usando
solo información verificable del código, configuración real y ficheros del repositorio.

---

## Especialización de dominio

<!-- ÚNICO BLOQUE EDITABLE PARA ESTE PROYECTO — no modificar el resto del fichero -->

- **Proyecto**: doc_organize — librería Python multimotor de bases de datos (sync/async)
- **Rol del modelo**: Senior Developer Experience Engineer especializado en librerías Python open-source
- **Tipo de proyecto**: librería Python (no tiene servidor local ni base de datos propia)
- **Stack**: Python 3.12+, SQLAlchemy 2, pandas, pyproject.toml, pip
- **Build tool**: `pip install -e ".[dev]"` / `python -m build`
- **Infraestructura local §5**: *No aplica* — los tests usan SQLite en memoria (`:memory:`); no requiere BD ni Docker
- **Ejecutar en local §6**: *No aplica* — librería; se importa o se ejecutan los tests directamente
- **Herramientas de calidad**: ruff (lint + format), mypy (type-check), pytest (tests)
- **Audiencia**: desarrolladores Python que contribuyen o extienden la librería
- **Tiempo estimado**: 20–40 minutos para tener el entorno operativo
- **Rama principal de trabajo**: `develop`

---

## Instrucción al modelo

```
Actúa como Senior Developer Experience Engineer especializado en librerías Python open-source.

Lee pyproject.toml, README.md, CLAUDE.md, .github/SHARED_INSTRUCTIONS.md y el código real del
repositorio antes de generar cualquier sección. Consulta la sección "Especialización de dominio"
de este prompt para los valores específicos del proyecto.
No inventes comandos, rutas ni configuraciones — verifica todo contra los ficheros reales.

Genera un documento Markdown con estas 11 secciones en este orden exacto:

# [Nombre del Proyecto] — Guía de Incorporación para Desarrolladores

**Audiencia**: [audiencia del domain slot]
**Tiempo estimado**: [tiempo del domain slot]

---

## 1. Prerequisitos del Entorno
Tabla con herramientas obligatorias. Columnas: | Herramienta | Versión mínima | Verificar con | Notas |
Incluye solo las herramientas realmente necesarias según pyproject.toml y la configuración real.

## 2. Obtener el Código
Comandos de clonado, rama de trabajo principal, primer checkout.
Si el repo tiene submódulos o dependencias privadas vía git, documentarlas aquí.

## 3. Configurar el Entorno de Desarrollo
Creación del entorno virtual, instalación de dependencias de desarrollo, ficheros de configuración
necesarios (.env, settings locales, credenciales de registro privado si las hay).
Cada paso verificable con un comando concreto.

## 4. Primera Instalación de Dependencias
Comando principal de instalación. Tabla de errores frecuentes:
| Error / Síntoma | Causa probable | Solución |

## 5. Infraestructura Local (Base de Datos / Servicios)
[Usar el valor del domain slot §5. Si no aplica: "*No aplica para este proyecto — los tests usan
SQLite en memoria; no se requiere base de datos ni contenedor Docker.*"]

## 6. Ejecutar la Aplicación en Local
[Usar el valor del domain slot §6. Si no aplica: "*No aplica para este proyecto — es una librería.
Para probar funcionalidades, ejecuta los tests (ver §10) o importa el paquete en un script."]

## 7. Mapa del Código
Árbol de la estructura de directorios relevante (no exhaustivo — solo lo que un nuevo contribuidor
necesita entender). Para cada módulo o paquete: una línea explicando su responsabilidad.
Incluir la regla de dependencia entre capas si existe.

## 8. Convenciones y Herramientas de Calidad
Lista de convenciones obligatorias con el comando que las verifica o aplica.
Agrupar por categoría: formato, lint, tipos, tests.
No inventar convenciones — leer pyproject.toml y SHARED_INSTRUCTIONS.md.

## 9. Flujo de Trabajo Git
Estrategia de ramas, convenciones de commit (Conventional Commits si aplica), proceso de PR/MR.
Leer SHARED_INSTRUCTIONS.md para el flujo canónico del proyecto.

## 10. Verificación del Entorno
Checklist ejecutable: comandos exactos con el output esperado que confirma que el entorno funciona.
| Verificación | Comando | Output esperado |
Al finalizar esta sección el desarrollador debe poder afirmar que su entorno está operativo.

## 11. Recursos y Referencias
- Documentación de dominio y arquitectura: rutas dentro del repositorio
- Ficheros de contexto IA: .ai/product.md, .ai/architecture.md, etc. si existen
- Guías específicas: enlazar a docs/ relevantes
- Contacto o canal de equipo si se menciona en README o CONTRIBUTING
Si no hay información verificable: omitir el subapartado.
```

---

## Restricciones

- Lee pyproject.toml (o pom.xml / package.json / go.mod según el stack) antes de generar §1 y §4
- Lee SHARED_INSTRUCTIONS.md antes de generar §8 y §9; no inventes convenciones
- Las secciones §5 y §6 deben usar el valor exacto del domain slot — no omitirlas aunque digan "No aplica"
- Verifica que todos los comandos de §10 son reales y ejecutables tal como aparecen
- NO expliques implementación interna ni nombres de clases privadas
- NO inventes configuraciones, puertos, credenciales ni rutas que no existan en el repositorio
- En §7, el árbol del código es descriptivo, no exhaustivo: solo lo que un nuevo contribuidor necesita
- Responde SOLO con el Markdown del documento, sin texto introductorio ni cierre
- Si falta información verificable, añade `### Pendiente de verificación` con la pregunta concreta

---

## Cuándo usar este prompt

- Al incorporar el primer desarrollador externo al proyecto
- Cuando el README ya no es suficiente para arrancar el entorno
- Tras cambios significativos en el stack, build tool o infraestructura local
- Como revisión periódica (cada release mayor) para mantener el documento actualizado

---

## Cómo usar este prompt

### Generación desde cero — Claude Code

```
Lee pyproject.toml, README.md, CLAUDE.md y .github/SHARED_INSTRUCTIONS.md.
Genera la guía de incorporación para desarrolladores usando
.github/prompts/onboarding_dev.prompt.md.
Guarda en docs/ONBOARDING_DEV.md.
Actualiza mkdocs.yml si la página es nueva.
No inventes comandos ni configuraciones; verifica todo contra los ficheros reales.
```

### Actualización — Claude Code

```
Lee docs/ONBOARDING_DEV.md y el estado actual de pyproject.toml y .github/SHARED_INSTRUCTIONS.md.
Actualiza la guía de incorporación para reflejar los cambios de la versión actual.
Mantén la estructura de 11 secciones del Arquetipo 7.
Marca como [PENDIENTE] cualquier sección que no puedas verificar.
```

### Generación — Copilot Chat

```
#file:.github/prompts/onboarding_dev.prompt.md
#file:pyproject.toml
#file:README.md
#file:.github/SHARED_INSTRUCTIONS.md

Genera la guía de incorporación para desarrolladores del proyecto.
Guarda en docs/ONBOARDING_DEV.md.
```

### Auditoría (solo lectura)

```
Lee docs/ONBOARDING_DEV.md y verifica cada comando de §10 contra el estado actual del proyecto.
Detecta secciones desactualizadas o comandos que ya no funcionan.
Entrega un informe de gaps sin modificar el fichero.
```

---

## Output esperado

Un fichero Markdown con:
- Cabecera con audiencia y tiempo estimado
- 11 secciones numeradas (`## 1.` — `## 11.`)
- Tabla de prerequisitos en `## 1.`
- Todos los comandos en bloques fenced con el lenguaje indicado
- §5 y §6 con contenido o con `*No aplica*` explícito según el domain slot
- Tabla de verificación ejecutable en `## 10.`
- Pie de página con versión verificada y fecha
