---
applyTo: "src/**/introspect/**/*.py"
---
# Introspección (multibase)

> **TL;DR** — API agnóstica de motor; diferencias por dialecto encapsuladas en adaptadores aislados. Devolver modelo IR estable (dataclass puro, sin objetos del driver). Funciones puras para extraccion. Test contra al menos un motor real. Nunca inventar metadatos; si falta información, introspetar más o pedir como parámetro.

- Prioriza APIs de introspección agnósticas del backend (p.ej. Inspector/reflection si usamos SQLAlchemy).
- Donde haya diferencias por motor, encapsula en adaptadores por dialecto y documenta limitaciones.
- Devuelve un modelo intermedio estable (no dependiente de objetos internos del driver).
- Si falta contexto (p.ej. tipo de datos específico), haz introspección adicional o pide input explícito (p.ej. modelo intermedio).
- Evita SQL “crudo” en la medida de lo posible; si es necesario, encapsula por motor y con fallback.
- Prioriza funciones puras para la extracción de metadatos, dejando la generación de documentación a otro módulo.
- Documenta claramente qué metadatos se extraen y qué limitaciones existen por motor.
- Proporciona tests de integración contra al menos un motor real (p.ej. SQLite) para validar la introspección.
- Si la introspección no puede obtener cierta información (p.ej. comentarios de columnas en SQLite), documenta esta limitación y sugiere alternativas (p.ej. input manual o modelo intermedio).
