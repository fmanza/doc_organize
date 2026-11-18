# M2 — Rendimiento de la construcción (B del plan único 2.0.0)

Fecha: 2026-11-18. Herramienta: `measure_build.py` (construye en una carpeta temporal; del proyecto real solo lee los
`.json` y los originales). «Antes» = `feature/2.0` con M1 (worktree, `PYTHONPATH`); «después» = rama de M2-B.

Corpus: CALIDAD_VD, 213 documentos, plantilla de normas y gobernanza (5 ejes). Latencia simulada de carpeta de red:
20 ms por lectura de un `.json` (en el hilo que lee). IA: cliente falso de 0,5 s por llamada; 38 documentos van a la
Sub-fase B.

| Medida | Antes | Después | Objetivo del plan |
|---|---|---|---|
| Construcción sin IA | 13,1 s | **3,5 s (−73 %)** | −30 % o más en red |
| Con IA, `ai_concurrency=1` | 32,1 s | 23,5 s | — (mismas llamadas y orden) |
| Con IA, `ai_concurrency=4` | — | **8,6 s**; fase de IA de 19 s a 5,0 s (**3,8×**) | ≥ 2,5× en las fases de IA |

- Sin IA, cada `.json` se lee una vez (antes, dos: clasificar e idioma, y una tercera para los sin clasificar) y con
  `properties_concurrency` lecturas a la vez (antes, de una en una).
- La clasificación de CALIDAD_VD con reglas es idéntica (`measure_rules_only.py`).
- El tiempo con IA real depende del proveedor: con un modelo local en una sola GPU, varias llamadas a la vez pueden no
  acelerar nada (las encola el servidor). Por eso `ai_concurrency=1` sigue siendo el valor por defecto.
