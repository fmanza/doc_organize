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

qwen2.5:14b con la plantilla actual frente a una copia (fuera del repositorio) con las descripciones de
`cumplimiento-legal`, `mejora-medicion` y `politica` reescritas según la regla de etiquetado (calibración, 1
repetición; la partida reproduce exactamente la medición anterior: 0,53 y 0,79).

| Eje | Actual | Corregida | Diferencia, IC 95 % | F1 macro | Puerta |
|---|---|---|---|---|---|
| Dominio | 0,53 | 0,58 | +0,05 [−0,02, 0,12] | 0,49 → 0,54 | no inferior, sin mejora |
| Tipo | 0,79 | 0,77 | −0,02 [−0,07, 0,02] | 0,65 → 0,65 | no pasa |

- `politica` mejora (asignada 7 veces frente a 11, con 5 en la referencia).
- `mejora-medicion` apenas: 1 de 9.
- `cumplimiento-legal` sigue de más (55 frente a 35): el modelo no aplica «una guía de aplicación va al dominio de su
  tema» solo con leerlo en la descripción.

Conclusión: retocar descripciones no basta y no se adopta. La siguiente prueba sería llevar la regla de etiquetado al
perfil del proyecto (reglas de desempate, que la IA lee aparte del catálogo), medida igual.

## Regla de etiquetado en el perfil del proyecto

La misma regla llevada a «Reglas de desempate» del perfil (que la IA recibe aparte del catálogo), con la plantilla
original. qwen2.5:14b con `ai_scope="all"`, calibración (100 documentos).

**v1** (tres líneas: qué es `cumplimiento-legal`, qué va a `mejora-medicion` y qué es `politica`), 2 repeticiones
idénticas en dominio:

- Dominio 0,61, F1 macro 0,49 → 0,63 (diferencia +0,14, IC [0,03, 0,21]).
- Tipo 0,79-0,80, pero F1 macro 0,64 → 0,54-0,55 en las dos repeticiones: el modelo aplica la línea de
  `mejora-medicion` también al tipo y deja de asignar `registro-evidencia` (0 veces) y casi todo `informe-auditoria`.
  No pasa la puerta.

**v2** (v1 más una línea: «la regla de `mejora-medicion` es solo del dominio»), pareada con la partida en la misma
ejecución:

| Eje | Exactitud | Diferencia, IC 95 % | F1 macro | Diferencia, IC 95 % | Puerta |
|---|---|---|---|---|---|
| Dominio | 0,53 → 0,59 | +0,06 [−0,03, 0,15] | 0,49 → 0,61 | +0,12 [−0,01, 0,19] | no inferior, sin mejora |
| Tipo | 0,79 → 0,79 | 0,00 [−0,07, 0,07] | 0,64 → 0,65 | +0,01 [−0,10, 0,14] | no pasa (no inferioridad) |

- `mejora-medicion` pasa de no asignarse nunca a 4 aciertos de 9; `informe-auditoria` y `registro-evidencia` vuelven.
- `politica` sigue de más (13 frente a 5 en la referencia, como la partida).
- La cola de revisión sube de 14 a 23 elementos (todos `unverified_evidence`).
- En las 25 filas revisadas por personas: dominio 0,48 → 0,60, tipo 0,76 → 0,84.

Conclusión: **mejor o igual en todos los ejes en el punto, sin demostrar**. Con 100 documentos el intervalo del tipo
(±0,07) no puede probar la no inferioridad de −0,03 con una diferencia de 0, y el tramo bloqueado (50) sería más ancho.
No cambia ningún valor por defecto de la librería. Se adopta como **perfil propio del proyecto medido**
(`.doc_organize/profile.md`, fuera del repositorio; se revierte borrándolo). Demostrarlo requiere ampliar la
referencia o el segundo corpus (Revisión 18).
