# BASELINE — Línea base de la clasificación (hito M0 del plan único 2.0.0)

Estado: **herramientas listas; medición pendiente** del corpus CALIDAD_VD y de la referencia etiquetada a mano (U6).
Fecha: 2026-11-18. Versión medida: doc_organize **1.7.0** (igual que 1.6.0 en clasificación: 1.7.0 solo redacta lo que
sale hacia la IA).

## Qué se mide y para qué

El criterio de salida de 2.0.0 compara contra esta línea base: en la referencia, el eje de dominio con IA no baja y
sube en los documentos que van a la IA; ningún eje empeora más de 2 puntos; coste por documento enviado ≤ 1,5×.

| Medida | Herramienta | Necesita |
|---|---|---|
| Exactitud y cobertura por eje, por quién clasificó y confusiones | `measure_baseline.py` | Contexto de CALIDAD_VD + `referencia.xlsx` etiquetada |
| Tokens, coste y latencia por documento enviado a la IA | Uso de LiteLLM del run (página «Uso de IA» de la web o `LiteLLMUsageClient`) + `ai_documents_sent` del contexto | Construcción con IA sobre CALIDAD_VD |
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
3. **Reconstruir con IA** (Sub-fase B, mismo catálogo) y medir: `--label "1.7.0 reglas+IA"`. Anotar del run:
   documentos enviados, tokens de entrada y salida, coste (LiteLLM) y duración.
4. **Sondear el proxy**: `python probe_litellm.py --base-url <proxy> --model <alias de clasificación>` (la clave en
   `DOC_ORGANIZE_LITELLM_TAXONOMY_CLASSIFICATION_VIRTUAL_KEY`).
5. Pegar aquí las tablas y el JSON de la sonda.

## Resultados

### Clasificación (pendiente)

| Configuración | Eje | Etiquetadas | Exactitud | Cobertura | Por quién |
|---|---|---|---|---|---|
| 1.7.0 reglas | dominio | | | | |
| 1.7.0 reglas | tipo de material | | | | |
| 1.7.0 reglas+IA | dominio | | | | |
| 1.7.0 reglas+IA | tipo de material | | | | |

### Coste y tiempo (pendiente)

| Configuración | Documentos | Enviados a la IA | Tokens entrada / salida | Coste | Duración |
|---|---|---|---|---|---|
| 1.7.0 reglas | | — | — | — | |
| 1.7.0 reglas+IA | | | | | |

### Proxy LiteLLM (pendiente)

| Modelo | `json_object` | `json_schema` estricto (150) | Respeta el `enum` | Caché de prefijo | Con `cache_control` |
|---|---|---|---|---|---|
| | | | | | |

## Verificación de las herramientas

Prueba sintética (13 documentos en 3 carpetas, 10 en la muestra, un error de etiqueta a propósito): exactitud 0,9,
cobertura 0,8, la confusión `ciberseguridad → calidad` detectada. `prepare_reference.py` escribe desplegables del
catálogo y neutraliza fórmulas en las celdas de texto.
