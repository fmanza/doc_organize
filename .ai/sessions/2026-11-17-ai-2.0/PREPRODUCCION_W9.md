# Preproducción de la 2.0 (W9) — 2026-11-20

Prueba de doc_organize_web 2.0 (rama `feature/2.0`) con doc_organize **2.0.0rc3** sobre datos reales, sin tocar
producción ni los documentos, siguiendo `docs/guides/preproduccion_2_0.md` de la web. Aquí solo hay recuentos: ni
nombres de documentos ni rutas.

## Entorno

- Producción: web con doc_organize 1.6.0, base de datos en la revisión `0014`. No se paró ni se cambió.
- Instancia aislada `dow-preprod` (otro proyecto de Compose, sus volúmenes, puerto 18090), con secretos propios
  generados para ella y los modelos de Docling copiados del volumen de producción montado de solo lectura.
- Origen: la carpeta de entrada de VD del mantenedor, montada **de solo lectura** (`/mnt/origen`). Salidas en una
  carpeta nueva y vacía.
- IA: el LiteLLM local; clasificar y describir con `qwen2.5-coder:14b` (`num_ctx` 8192).

## Resultados

| Prueba | Resultado |
|---|---|
| Migraciones de ida y vuelta (copia de la BD real, `app.cli backup` en el tmpfs del contenedor) | `0014` → `0023` → `0014`: 21 tablas comparadas, **0 distintas**. Ninguna copia quedó en el contenedor ni en el equipo |
| Diagnóstico (con los modelos de IA) | **0 errores**; avisos: sin GPU, sin LibreOffice, sin el extra `av` |
| Escaneo y conversión | 213 escaneados, 213 convertidos, **0 errores** |
| Contexto (plantilla `calidad`, IA para lo que las reglas no clasifican) | 0 sin clasificar; con plazo de IA de 120 s: 36 llamadas + 3 de la caché, **38 de 39** documentos clasificados por la IA, 1 respuesta que no era el JSON esperado, sin paradas |
| Excel del contexto | generado; SHA-256 de la descarga comprobado |
| Sitio sin conexión (ZIP, 15,6 MB) | SHA-256 coincide; **solo** 215 páginas HTML, 2 JS con sus licencias, `llms.txt` y `sitemap.xml`: ningún original ni `.json` de conversión |
| Paquete para IA (ZIP, 4,4 MB) | SHA-256 coincide |

## Hallazgos y correcciones

1. **Fuga del sitio sin conexión** (E2E de W9, antes de la preproducción): con la rc1 y la rc2 el ZIP llevaba la copia
   de cada original y su `.json` de conversión sin redactar. Corregido en la librería (#91, `exclude_docs`,
   `include_originals=`) y publicado como **2.0.0rc3**; la preproducción lo confirma.
2. **Plazo de IA de la web demasiado corto**: con 30 s (el valor por defecto de la web), tres clasificaciones seguidas
   pasaron del plazo y el corte por conexión dejó 33 de 39 documentos sin IA. La web pasa a **120 s** por defecto
   (doc_organize_web #96), el mismo valor que `AiSettings.timeout_s`. La guía del proxy de la librería documenta
   `num_ctx` y los plazos para modelos locales.
3. La web no tenía los secretos de Docker en una copia nueva del repositorio (están fuera de git): `up.sh` arranca la
   web en bucle hasta generarlos con `scripts/generate_secrets.py`. A documentar en el runbook.

## Decisión

El mantenedor da por buena la preproducción con esta carpeta (la de 3104 ficheros no se pasa) y autoriza la
publicación simultánea de 2.0.0.
