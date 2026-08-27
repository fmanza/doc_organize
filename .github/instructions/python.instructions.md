---
applyTo: "**/*.py"
---
# Python – Estándares para esta librería

> **TL;DR** — Python 3.12+, mypy strict, ruff, tipado en todo código público. Usar dataclasses para modelos de metadatos, `pathlib.Path` para rutas, composición sobre herencia, excepciones específicas nunca `Exception` genérica. Sin credenciales en ejemplos, sin SQL crudo fuera de adaptadores.

## Estilo
- Python 3.12+ o la versión definida en `pyproject.toml`; mantén consistencia con la configuración real del proyecto.
- Docstrings estilo Google o NumPy (elige uno y mantén consistencia).
- Usa `pathlib.Path` para rutas.
- Prefiere dataclasses para estructuras de metadatos.

### Formato de cadenas: F-Strings OBLIGATORIOS

**REGLA CRÍTICA:** Todo string que contenga parámetros DEBE usar **f-strings** (`f"...{var}..."`). No se permiten `.format()`, `%` formatting ni concatenación de strings para este propósito.

**✅ Correcto:**
```python
logger.info(f"Processing {len(data)} records with timeout={timeout}")
error_msg = f"Expected {expected} rows, got {actual}"
print(f"Table {table_name} ({row_count} rows)")
```

**✗ Prohibido:**
```python
logger.info("Processing {} records with timeout={}".format(len(data), timeout))  # ❌
error_msg = "Expected %s rows, got %s" % (expected, actual)                      # ❌
print("Table " + table_name + " (" + str(row_count) + " rows)")                 # ❌
```

**Excepciones permitidas (solo strings sin parámetros):**
- Strings estáticos: `"Inicializando conexión"`
- Docstrings con ejemplos
- Constantes documentales

**En auditoría de código (AUDIT_CODE):** Bloquea PR si encuentra `.format()`, `%` formatting o concatenación en strings con parámetros.

## Programación orientada a objetos
- **Diseña exclusivamente con clases.** No crear funciones sueltas a nivel de módulo en ficheros de clase.
- Las transformaciones sin estado van como `@staticmethod` dentro de la clase responsable. Las constantes privadas de una clase van como `ClassVar` en la propia clase.
- Solo se permiten funciones o constantes a nivel de módulo en ficheros de utilidades genuinamente compartidas entre varios módulos (p.ej. `_base.py`, `utils.py`).
- Diseña clases cohesivas con invariantes claras y responsabilidades únicas.
- Prefiere composición sobre herencia; usa herencia solo si existe sustitución real (`LSP`).
- Mantén el estado mínimo y explícito; evita estado global mutable.
- Expón comportamiento mediante métodos públicos pequeños y predecibles.
### Logging obligatorio y trazabilidad

Toda clase con lógica debe incluir logging apropiado para rastrear estado y eventos:

```python
import logging

class MyProcessor:
    def __init__(self, config: Config):
        self.logger: logging.Logger = logging.getLogger(__name__)
        self.config = config

    def process(self, data: list[dict]) -> list[dict]:
        self.logger.info(f"Processing {len(data)} records")
        result = []
        for idx, record in enumerate(data):
            self.logger.debug(f"Record {idx}: {record['id']}")
            try:
                processed = self._transform(record)
                result.append(processed)
            except ValidationError as e:
                self.logger.warning(f"Skipping record {idx}: {e}")
        self.logger.info(f"✅ Processed {len(result)}/{len(data)} records")
        return result
```

**Niveles de logging:**
- `debug()` — Rastreo detallado (valores internos, transiciones de estado)
- `info()` — Eventos normales (inicio, fin, hitos, cambios de estado)
- `warning()` — Situaciones anómalas pero recuperables (valores fuera de rango, retry)
- `error()` — Errores que requieren manejo, siempre con `exc_info=True` para stack trace

**Anti-patrones:**
- ✗ `print()` en código de librería
- ✗ `logger` global sin tipado (`logger = logging.getLogger()` sin `: logging.Logger`)
- ✗ Omitir `exc_info=True` en error handlers
- ✗ Setup de logging en librerías (responsabilidad del consumer)
## SOLID
- `SRP`: separa acceso a datos, normalización, reglas de negocio y renderizado.
- `OCP`: soporta nuevos motores/formatos añadiendo adaptadores o estrategias, sin romper contratos existentes.
- `LSP`: toda implementación concreta debe poder sustituir al contrato base sin cambiar semántica.
- `ISP`: divide interfaces por casos de uso; evita métodos "placeholder" no implementados.
- `DIP`: orquestadores y servicios dependen de `Protocol`/`ABC`, no de clases concretas.

## Diseño de API
- Expón modelos de metadatos (Schema, Table, Column, Relationship).
- Separa: extracción (introspección) vs render (generación de docs).
- Las transformaciones de renderizado sin estado se implementan como `@staticmethod` dentro de la clase renderizadora.
- Usa `Protocol` (o `ABC` cuando proceda) para contratos de adaptadores por motor.
- Evita condicionales por motor dispersos; centraliza resolución en factorías/registro.

## Patrones recomendados
- `Strategy` para variaciones por motor o formato.
- `Factory Method` o `Abstract Factory` para construir conectores/adaptadores.
- `Adapter` para encapsular diferencias entre librerías/driver SQL.
- `Template Method` para flujos base de introspección y render con pasos extensibles.
- `Builder` para salidas documentales complejas por etapas.
- `Query Object`, `Repository`, `Data Mapper` e `Identity Map` cuando ayuden a aislar SQL, mapear modelos y evitar cargas repetidas.
- No introducir patrones si una solución simple y explícita cubre el caso sin deuda.

## Errores
- Define excepciones propias (p.ej., `IntrospectionError`, `RenderError`).
- Mensajes de error accionables (qué falló y cómo corregir).
