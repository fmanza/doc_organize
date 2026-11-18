# BASELINE — Línea base de la clasificación (hito M0 del plan único 2.0.0)

Estado: **M0 cerrado**. Línea base de clasificación cerrada (U6): referencia aceptada por el mantenedor el 2026-11-18
(39 filas revisadas una a una, `notas = Revisado`, y las otras 111 aceptadas tal como las propuso Claude); sonda del
proxy hecha; tokens y tiempo por documento enviado medidos con `measure_with_ai.py` (en memoria, sin reconstruir el
proyecto).
Fecha: 2026-11-18. Versión medida: doc_organize **1.7.1** (igual que 1.6.0 en clasificación: 1.7.0 solo redacta lo que
sale hacia la IA y 1.7.1 solo cambia la navegación del sitio).

## Qué se mide y para qué

El criterio de salida de 2.0.0 compara contra esta línea base: en la referencia, el eje de dominio con IA no baja y
sube en los documentos que van a la IA; ningún eje empeora más de 2 puntos; coste por documento enviado ≤ 1,5×.

| Medida | Herramienta | Necesita |
|---|---|---|
| Exactitud y cobertura por eje, por quién clasificó y confusiones | `measure_baseline.py` | Contexto de CALIDAD_VD + `referencia.xlsx` etiquetada |
| Tokens, coste y latencia por documento enviado a la IA | `measure_with_ai.py`: reglas + Sub-fase B en memoria con el cliente real; un transporte `httpx` anota `usage` y duración de cada llamada | Contexto de CALIDAD_VD, plantilla, proxy y virtual key en una variable de entorno |
| Tiempo de construcción (sin IA y con IA) | Duración del run en la web | Las dos construcciones |
| Salida `json_schema` estricta, `enum` de 150, caché de prefijo | `probe_litellm.py` (texto sintético) | Acceso al proxy y una virtual key en una variable de entorno |

## Procedimiento

1. **Referencia** (una vez): sobre el contexto actual de CALIDAD_VD (construido con su plantilla, solo reglas):

   ```
   python prepare_reference.py --project-root <raíz de CALIDAD_VD> --manifest <plantilla o taxonomy_manifest.md> \
       --out referencia.xlsx --size 150
   ```

   Muestra estratificada por dominio y sin clasificar (semilla 7). **Quien conoce el corpus** rellena `dominio_ok` y
   `tipo_ok` (desplegables del catálogo; `ninguno` si nada encaja) y, si puede, `marcos_ok` (marcos normativos
   separados por `;`, para medir las facetas de 2.0). Rutas relativas al proyecto; no sale del equipo.
2. **Medir 1.7.0 solo reglas**: `python measure_baseline.py --project-root <raíz> --reference referencia.xlsx
   --label "1.7.0 reglas" --json reglas.json`.
3. **Reglas + IA en memoria** (Sub-fase B, mismo catálogo y umbral, sin escribir en el proyecto):

   ```
   python measure_with_ai.py --project-root <raíz> --template <plantilla.md> --reference referencia.xlsx \
       --base-url http://localhost:4000 --model <alias> --key-env <VARIABLE> --label "1.7.1 reglas+IA" \
       [--path-map /mnt/documentation=C:/Desarrollo/documentation] --json ia.json
   ```

   Da exactitud por eje como `measure_baseline.py` y, de cada llamada, tokens de entrada y salida y duración (con una
   llamada de calentamiento aparte). El texto sale redactado (`ai_redact_credentials`, como en 1.7.0).
4. **Sondear el proxy**: `python probe_litellm.py --base-url <proxy> --model <alias de clasificación>` (la clave en
   `DOC_ORGANIZE_LITELLM_TAXONOMY_CLASSIFICATION_VIRTUAL_KEY`).
5. Pegar aquí las tablas y el JSON de la sonda.

## Resultados

### Clasificación

Corpus: CALIDAD_VD (213 documentos, `C:\Desarrollo\documentation\salida_vd\salida_vd`), catálogo de la plantilla
`taxonomia-multi-dimensional-normas-gobernanza-2` (8 dominios, 10 tipos de material). **No** es el `taxonomy_manifest.md`
de la carpeta (otro catálogo, sin usar en la construcción). Muestra de 150 (semilla 7).

**Referencia provisional**: la etiquetó Claude con el título, la ruta y un extracto de cada documento (sin ver lo que
asignó doc_organize) y criterios escritos (abajo). Está en el scratchpad de la sesión, no en el repositorio (nombres de
documentos reales). **Aceptada por el mantenedor**: 39 filas revisadas y 111 aceptadas sin cambios; las
correcciones respecto a la propuesta son pocas (la exactitud de dominio de reglas+IA pasa de 0,227 a 0,233; las demás
no se mueven).

Referencia aceptada (150 filas), medida el 2026-11-18 tras la revisión — **es la línea base del criterio de salida**:

| Configuración | Eje | Etiquetadas | Exactitud | Cobertura | Por quién |
|---|---|---|---|---|---|
| 1.6.0 reglas+IA (contexto actual, IA en 38 documentos) | dominio | 150 | **0,23** | 1,00 | reglas 0,22 · IA 0,33 |
| 1.6.0 reglas+IA (contexto actual) | tipo de material | 150 | **0,22** | 1,00 | reglas 0,20 · IA 0,33 |
| 1.7.1 reglas (en memoria, `measure_rules_only.py`, sin escribir en el proyecto) | dominio | 150 | **0,19** | 0,89 | reglas 0,19 |
| 1.7.1 reglas (en memoria) | tipo de material | 150 | **0,19** | 1,00 | reglas 0,19 |

Solo las 39 filas revisadas (muestra pequeña: orientativo):

| Configuración | Eje | Etiquetadas | Exactitud | Cobertura | Por quién |
|---|---|---|---|---|---|
| 1.6.0 reglas+IA | dominio | 39 | 0,26 | 1,00 | reglas 0,28 · IA 0,14 (7 docs) |
| 1.6.0 reglas+IA | tipo de material | 39 | 0,23 | 1,00 | reglas 0,22 · IA 0,29 |
| 1.7.1 reglas | dominio | 39 | 0,23 | 0,90 | reglas 0,23 |
| 1.7.1 reglas | tipo de material | 39 | 0,21 | 1,00 | reglas 0,21 |

La IA de 1.6.0 (Sub-fase B, solo para los 38 documentos que las reglas no resolvieron) sube unos 3-4 puntos sobre las
reglas solas en la referencia completa. Para 2.0, la referencia aceptada y la primera tabla son la base del criterio de
salida; la de las 39 revisadas es solo un contraste.

Confusiones más frecuentes (etiqueta → asignado):

- Dominio: `cumplimiento-legal → riesgos-amenazas` (22), `tecnologia-sistemas → riesgos-amenazas` (12),
  `gobernanza-liderazgo → riesgos-amenazas` (11), `cumplimiento-legal → gobernanza-liderazgo` (10),
  `gobernanza-liderazgo → cumplimiento-legal` (7-10). En las 39 revisadas manda la frontera
  `cumplimiento-legal ↔ gobernanza-liderazgo` (7 + 3). **`riesgos-amenazas` atrae lo que no es suyo** (83 de 213
  documentos): palabras como «riesgo», «amenaza» o «tratamiento» aparecen en casi cualquier texto de seguridad.
- Tipo de material: ninguna norma, ley o guía oficial se reconoce como `referencial-normativo`
  (→ `procedimiento-control` 25, `manual-sgsi` 19, `analisis-riesgo` 14). Las palabras clave de ese tipo («norma»,
  «ley», «ISO», «decreto») salen en todos los documentos internos, y los textos normativos usan las de los demás tipos.
- Lectura para 2.0: es justo el caso de las descripciones de etiqueta y del perfil del proyecto (G2) («una norma
  publicada por ISO, CCN o el BOE es referencial normativo aunque hable de procedimientos») y de los términos
  discriminantes (C3 del plan de facetas).

Criterios de la referencia provisional:
- Leyes, directivas, normas ISO y guías oficiales (CCN, INCIBE, Magerit) → `referencial-normativo`; dominio por el tema
  de la norma (riesgos: 31000, Magerit, 803; calidad y auditoría → `mejora-medicion`: 9001/9004/9000, 19011, 802, 815;
  servicios TI y configuración técnica → `tecnologia-sistemas`: 20000, guías CCN de Windows, Exchange, cloud, web;
  gobierno → `gobernanza-liderazgo`: 38500, 801, 821) y, sin tema claro, `cumplimiento-legal` (ENS, NIS2, DORA, CSRD,
  27001, 14001…).
- Documentos internos de VD → dominio por su tema; material: política, procedimiento, manual, plan o registro.
- Marcos normativos: solo los del catálogo (`ens`, `iso-27001`, `iso-9001`, `iso-20000`, `iso-14001`, `rgpd`,
  `lo-3-2018`…); `ninguno` si no aplica.

### Coste y tiempo

Medido el 2026-11-18 con `measure_with_ai.py` (1.7.1, plantilla de CALIDAD_VD, `DOC_ORGANIZE_LITELLM_ENRICHMENT_MODEL` =
`qwen2.5-coder:14b` local):

| Configuración | Documentos | Enviados a la IA | Tokens entrada / salida por documento enviado (media; p95) | Total entrada / salida | Coste | Duración |
|---|---|---|---|---|---|---|
| 1.7.1 reglas | 213 | — | — | — | 0 | 1,5 s (clasificación, `.json` locales) |
| 1.7.1 reglas+IA | 213 | **38** (36 con algún eje asignado, 0 fallos) | **1226 / 112** (1782 / 137) | 46 584 / 4259 | 0 (modelo local) | Sub-fase B: 1918 s; **50 s por llamada** (p50 54, p95 69) + 35 s de calentamiento |

- Exactitud con IA: dominio 0,23 (IA 0,33 en sus documentos), tipo 0,22: la misma que el contexto actual (1.6.0
  reglas+IA). Un documento salió con credenciales redactadas.
- **Base del criterio «coste ≤ 1,5×»**: ≤ 1840 tokens de entrada y ≤ 168 de salida de media por documento enviado.
- **El tiempo no es fiable como base**: la sonda dio 3-5 s por llamada parecida con el modelo cargado, y aquí 50 s,
  con el equipo ejecutando a la vez la batería de tests de M1. Para comparar tiempos en M10, repetir las dos mediciones
  en las mismas condiciones; los tokens no dependen de eso.
- Marcos normativos (eje que 1.7 ignora): sin valores (exhaustividad 0 contra `marcos_ok`). La primera medición del eje
  con reglas de 2.0 está en el PR #52 (M1).

### Proxy LiteLLM

Proxy local (`litellm-litellm-1`; la web lo usa como `http://host.docker.internal:4000`, desde el equipo es
`http://localhost:4000`). Alias `DOC_ORGANIZE_LITELLM_ENRICHMENT_MODEL` (no aparece en `/v1/models`, que solo lista
`qwen2.5-coder:14b`; responden igual). Texto sintético; la clave no se imprime.

| Modelo | `json_object` | `json_schema` estricto (150) | Respeta el `enum` | Caché de prefijo | Con `cache_control` |
|---|---|---|---|---|---|
| `DOC_ORGANIZE_LITELLM_ENRICHMENT_MODEL` (= `qwen2.5-coder:14b`, local) | Sí, 3,2 s (1121 + 18 tokens). **Sin esquema se inventa la clave** (`"dominio"` en lugar de `"domain"`) | **Sí**, 4,9 s | **Sí** | No se informa (`cached_tokens` nulo); 5688 tokens de prefijo en ~2 s con el modelo cargado | Igual (sin efecto visible) |

- Primera llamada con el modelo frío: 47 s; un prefijo de 5,7 k tokens en frío llegó al timeout de 120 s. Para G1, el
  timeout por defecto del cliente debe contemplar el arranque de un modelo local.
- Con un modelo local el coste en dinero es 0: el criterio «coste ≤ 1,5×» se mide en **tokens y tiempo**.

## Verificación de las herramientas

Prueba sintética (13 documentos en 3 carpetas, 10 en la muestra, un error de etiqueta a propósito): exactitud 0,9,
cobertura 0,8, la confusión `ciberseguridad → calidad` detectada. `prepare_reference.py` escribe desplegables del
catálogo y neutraliza fórmulas en las celdas de texto.
