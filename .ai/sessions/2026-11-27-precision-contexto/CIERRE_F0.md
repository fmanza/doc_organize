# Cierre de F0 «Medir bien» (2026-11-28)

F0 se cierra con la condición C1 del PLAN cumplida y una conclusión que cambia el orden de la hoja de ruta
(ANALISIS_MEJORAS §6): **se adelanta P3 (la IA sobre todos los documentos) y se recorta P1 (puntuador nuevo de
reglas)**. Decisiones registradas: Revisiones 18 y 19 de `.ai/DECISIONS_LOG.md`.

Todas las cifras son agregadas. Los informes, la referencia y la partición tienen nombres de documentos reales y están
fuera del repositorio.

## C1: condiciones de cierre

| Condición | Estado |
|---|---|
| Referencia de M0 recuperada | Sí: 150 documentos etiquetados en dominio y tipo de material |
| Acuerdo humano medido (≥ 50 filas a ciegas, kappa por eje) | Sí: 50 filas. Kappa **0,63** en dominio y **0,60** en tipo, tras fijar la regla de etiquetado (el texto de una ley o norma va a `cumplimiento-legal`; una guía de aplicación, al dominio de su tema) y revisar 35 filas con ella |
| Informe en tres vistas | Sí. La vista reponderada por estratos sale «No fiable» porque el contexto guardado se reconstruyó después de sacar la muestra; el informe lo avisa solo |
| Partición fija | 100 documentos de calibración y 50 bloqueados, semilla 0, estratificada por dominio |

## Lo que se midió

Tramo de calibración (100 documentos) salvo donde se indica. Puerta de 2.7.0: no inferioridad de −3 puntos en
exactitud y en F1 macro, mejora con el intervalo por encima de 0 y por encima de la línea base de mayoría.

**Línea base de mayoría**: dominio 0,35 («cumplimiento-legal»), tipo 0,55 («referencial-normativo»).

### Reglas (v1) y sus ablaciones

| Configuración | Dominio | Tipo | Puerta frente a v1 |
|---|---|---|---|
| Reglas v1 | 0,20 | 0,20 | — |
| Palabra completa | 0,21 | 0,14 | no |
| Sin dividir por el número de términos | 0,21 | 0,54 | no (F1 macro del dominio −0,18: asigna casi todo a un valor) |
| Solo título y comienzo | 0,13 | 0,16 | no |
| Empate → abstención | 0,13 | 0,19 | no |

Las reglas quedan **por debajo de la mayoría** en los dos ejes y ninguna de las causas de §4 que se pueden aislar con
una ablación explica el error por sí sola: el problema es de fondo (palabras clave genéricas en un corpus de guías que
hablan de todo), no un parámetro.

### IA sobre toda la referencia

Sin caché, 2 repeticiones; el ruido entre repeticiones es como mucho 0,02.

| Modelo | Dominio | Tipo | Tiempo |
|---|---|---|---|
| qwen2.5-coder:14b (partida) | 0,46 | 0,67 | 36 s/doc |
| qwen2.5:14b | 0,53 | 0,79 | 20 s/doc |
| qwen3.5:9b | 0,64 | 0,66 | 11 s/doc |

- qwen2.5:14b pasa la puerta frente a coder-14b en calibración. En el tramo bloqueado (50) mejora la media (dominio
  +0,14, tipo +0,04) pero los intervalos son anchos y no pasa: se adopta solo en el despliegue local (Revisión 19).
- qwen3.5:9b es el mejor en dominio, pero no es no inferior en tipo (asigna `politica` de más).
- Ningún modelo asigna nunca `mejora-medicion` (9 documentos en la referencia), y los dos qwen2.5 asignan
  `cumplimiento-legal` de más (unas 50 veces frente a 35). Se mide aparte una plantilla con las descripciones
  corregidas (ver abajo).

## Conclusión para la hoja de ruta

La regla de F0 era: «si la IA sobre todo el corpus gana claramente, se adelanta P3 y se recorta P1». Gana claramente:
+0,33 a +0,44 en dominio y +0,46 a +0,59 en tipo frente a las reglas, con cualquiera de los tres modelos.

- **Siguiente fase: P3** (`ai_scope="all"`), PLAN en `.ai/sessions/2026-11-28-ia-sobre-todo/PLAN.md`.
- **P1 se recorta**: el puntuador nuevo de reglas pierde prioridad. Las reglas siguen siendo la clasificación sin IA y
  la pista barata, pero no la vía para mejorar la precisión.
- **Pendiente**: un segundo corpus para poder cambiar valores por defecto (Revisión 18) y ampliar el tramo bloqueado.

## Plantilla con descripciones corregidas

En curso al escribir esta nota: qwen2.5:14b con la plantilla actual frente a una copia (fuera del repositorio) con las
descripciones de `cumplimiento-legal`, `mejora-medicion` y `politica` reescritas según la regla de etiquetado. El
resultado se añadirá aquí.
