# Medición final de 2.0 contra M0 (M10)

Fecha: 2026-11-19. CALIDAD_VD (contexto guardado, solo lectura; clasificación en memoria), plantilla de 5 ejes de M0,
referencia etiquetada a mano (150 documentos; fuera del repositorio). Mismo modelo que la línea base:
`qwen2.5-coder:14b` en el LiteLLM Proxy local. `ai_scope="unclassified"`: la IA clasifica los 38 documentos que las
reglas dejan sin dominio, como en M0.

## Criterio de salida (exactitud con IA)

| Eje | 1.6.0 (M0) | 2.0 | Por quién (2.0) | ¿Cumple? |
|---|---|---|---|---|
| Dominio | 0,23 (IA 0,33) | **0,247** (IA **0,391**) | reglas 0,22 · IA 0,39 | Sí: no baja y sube en los documentos que van a la IA |
| Tipo de material | 0,22 (IA 0,33) | **0,227** (IA **0,348**) | reglas 0,20 · IA 0,35 | Sí: no empeora (+0,7 puntos) |

Sin IA, la clasificación es la de 1.7 (M1, comprobado con el corpus de los tests y CALIDAD_VD).

## Coste y fiabilidad

| | M0 (1.6.0) | M5 | **M10** |
|---|---|---|---|
| Tokens de entrada por documento (media) | 1226 | 1985 (1,62×) | **2007 (1,64×)** |
| Tokens de salida por documento (media) | 112 | 284 | **260** |
| Total por documento | 1338 | 2269 (1,70×) | **2267 (1,69×)** |
| Documentos enviados / asignados / fallidos | 38 / — / — | 38 / 38 / 0 | **38 / 38 / 0** |

El coste de entrada (1,64×) queda por encima de la referencia de 1,5×, igual que en M5, donde el mantenedor lo aceptó
como valor de referencia. La mitad del prompt es fija (instrucciones, catálogo y perfil) y la caché de resultados hace
que reconstruir sin cambios cueste cero llamadas. Tiempo medio por llamada: 24 s (modelo local, 14B, parte en CPU).

## Otros modelos (para el alias `doc-organize-classify`)

Con `qwen3.5:9b` la clasificación falla a menudo («no es el JSON esperado»: 14 fallos en los primeros 10 documentos,
con reintentos): es un modelo que razona antes de responder y agota el tope de 1024 tokens de `classify`. No es apto
para `classify` sin desactivar el razonamiento o subir `TaskSettings.max_tokens`.

## Diseñador de la taxonomía (M8.2) con un modelo mayor

Con `qwen3.8:27b` (alias `doc-organize-agent`, 32k de contexto) y la plantilla de 5 ejes: 11 pasos, 52 minutos. Las
ediciones son razonables (quitar palabras clave que no aparecen en ningún documento) y deshace las que empeoran; la
mejor sube la cobertura de tipo de material de 87,8 % a 92,0 % con un conflicto más (107 → 108). Termina sin cambios:
concluye que los conflictos de dominio y tipo son intrínsecos a un corpus de guías genéricas. **La puerta estricta
(ningún eje con un conflicto más) sigue sin cumplirse**; queda a decisión del mantenedor.
