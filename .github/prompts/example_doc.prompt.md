# Prompt: example_doc — Guía de ejemplo de código (Arquetipo 4)

Genera o actualiza guías de ejemplos de código para **doc_organize** usando solo
información verificable del código fuente y los archivos `.py` en `docs/examples/`.

## Instrucción al modelo

```
Actúa como developer advocate especializado en ejemplos de código para librerías Python.

Analiza el archivo `.py` de ejemplo proporcionado y el contexto real del repositorio.
No asumas comportamientos, outputs ni capacidades que no estén en el código real.

Antes de generar el documento, verifica:
1. El archivo .py referenciado existe en disco.
2. Es sintácticamente válido (`python -m py_compile [ruta]`).
3. No contiene credenciales reales.

Genera el documento Markdown siguiendo el Arquetipo 4 con estas secciones en este orden exacto:

# Ejemplo: [Nombre del Patrón/Funcionalidad]

## 1. Contexto del Ejemplo
Qué problema concreto resuelve este código (1-2 párrafos).
Menciona el caso de uso típico y qué módulos de doc_organize se utilizan.

## 2. Implementación de Referencia
Usa EXCLUSIVAMENTE la directiva de snippet. Nunca código inline si el .py existe.

```python
--8<-- "examples/[ruta-relativa-al-archivo].py"
```

## 3. Explicación del Código
Análisis de los puntos críticos del ejemplo:
- Decisiones de diseño no obvias (concurrencia, particionado, gestión de transacciones)
- Parámetros clave y sus implicaciones de rendimiento
- Advertencias o precondiciones importantes
Si el ejemplo es trivial o se autoexplica: "*No aplica para este módulo.*"

## 4. Ejecución y Pruebas
Comando exacto para ejecutar o validar el ejemplo localmente:

```bash
# Validación sintáctica (siempre incluir)
python -m py_compile docs/examples/[nombre].py

# Ejecución real (si no requiere credenciales)
python docs/examples/[nombre].py
```

Si el ejemplo requiere credenciales reales para ejecutarse, indicarlo explícitamente
y documentar los placeholders que deben reemplazarse.

## 5. Referencias Relacionadas
Incluir SIEMPRE los tres tipos de enlace (enlace bidireccional obligatorio):
- **Documentación funcional**: [Nombre módulo](../functional/[nombre].md) — 1 línea de contexto
- **Referencia técnica**: [API Nombre módulo](../api/[nombre].md) — 1 línea de contexto
- **Ejemplos relacionados**: otros ejemplos del mismo área funcional, si existen

Si no hay documentación funcional ni técnica del módulo:
  "Pendiente — crear docs/functional/[nombre].md y docs/api/[nombre].md"

---

Restricciones:
- Si una sección queda vacía, escribe "*No aplica para este módulo.*" — nunca omitas la sección
- En ## 2. usar SIEMPRE --8<-- si el .py existe; nunca copiar el código inline
- Si el .py no existe, CREARLO antes de referenciar con docstring de módulo y contenido mínimo válido
- NO inventes outputs, comportamientos ni capacidades del código
- ## 5. siempre presente; enlaza al menos la referencia técnica correspondiente
- Si falta información verificable, añade subsección "### Pendiente de verificación"
- Responde SOLO con el Markdown, sin texto introductorio ni cierre
```

## Cómo usar este prompt

### Modo ejemplo único — Claude Code

```
Lee docs/examples/[nombre].py y genera la guía de ejemplo usando el
prompt en .github/prompts/example_doc.prompt.md.
Actualiza docs/examples/[nombre].md si existe, o crea la página si no hay equivalente.
Actualiza mkdocs.yml si se crea una página nueva.
Verifica que el .py es sintácticamente válido antes de referenciar.
```

### Modo ejemplo único — Copilot Chat

```
#file:.github/prompts/example_doc.prompt.md
#file:docs/examples/[nombre].py

Genera la guía de ejemplo del archivo indicado siguiendo las instrucciones del prompt.
```

## Regla de extracción de código inline

Si un `.md` existente tiene código inline ≥30 líneas que debería estar en un `.py`:

1. Extrae el código a `docs/examples/[nombre].py` con docstring de módulo.
2. Valida: `python -m py_compile docs/examples/[nombre].py`
3. Reemplaza el bloque inline en el `.md` por `--8<-- "examples/[nombre].py"`.
4. Actualiza `mkdocs.yml` si el `.py` es nuevo.

## Organización de archivos `.py`

```
docs/examples/
├── [patron].py          # Ejemplos standalone en raíz
├── scanner/              # Escaneo de carpetas, filtros por extensión
├── converter/             # Conversión a Markdown/JSON con Docling
├── dedup/                # Detección y resolución de duplicados
├── cache/                 # Caché incremental (SQLite + WAL)
└── web/                  # API FastAPI, auth multi-tenant, WebSocket
```

## Output esperado

Markdown con título `# Ejemplo: [Nombre]` y las 5 secciones del Arquetipo 4 numeradas
(`## 1.`–`## 5.`). `## 2.` contiene exclusivamente `--8<-- "examples/..."`.
`## 4.` incluye siempre `python -m py_compile` como verificación mínima.
`## 5. Referencias Relacionadas` es obligatoria (enlace bidireccional con Arquetipo 2 §5).
