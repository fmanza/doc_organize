---
applyTo: "tests/**"
---
# Tests

> **TL;DR** — Pytest, fixtures mínimas, sin red ni servicios externos. Test-first en hotfix (reproduce el bug antes de corregirlo), snapshot o asserts clave para docs generados. Si el cambio toca API pública, añadir test de integración. Tests rápidos y deterministas.

- Añade tests para toda nueva funcionalidad.
- Prefiere fixtures pequeñas: documentos de prueba mínimos generados en el propio test (p.ej. con matplotlib/PIL, ver `tests/conftest.py::native_pdf`/`scanned_pdf`) en vez de archivos binarios grandes versionados.
- Si hay generación de docs, usa snapshot testing o asserts sobre fragmentos clave.
- Evita depender de red; Docling corre localmente con modelos ya descargados — no mockear su conversión (usar documentos de fixture reales), pero evitar tests que requieran descargar modelos nuevos.
- Para refactors, añade tests antes de cambiar código.
- Para hotfixes, añade tests que reproduzcan el bug antes de corregirlo.
- Usa pytest y sigue su convención de nombres (`test_*.py` y `def test_*`).
- Si el cambio afecta a la API pública, añade tests de integración que validen el comportamiento esperado.
- Para cambios de seguridad, añade tests que verifiquen la mitigación del riesgo.
- Mantén los tests rápidos y deterministas; evita pruebas que puedan fallar por factores externos.
- Antes de finalizar cualquier cambio, ejecuta `mypy src`, `ruff check src tests` y los tests de documentación; corrige cualquier rotura restante hasta dejar la validación en verde.

## Cobertura arquitectónica mínima
- Valida contratos comunes con tests parametrizados por implementación (p.ej. distintos motores de OCR).
- Verifica `LSP`: cualquier implementación concreta debe pasar la misma suite de contrato.
- Verifica `OCP`: al agregar un motor de OCR o formato nuevo, no debe romper los tests existentes.
- Verifica `SRP`: cambios en `converter/` no deben romper tests de `scanner/`, `dedup/` o `cache/`, y viceversa.
- Si se usa `Factory` (p.ej. `DocumentConverter._get_docling`), prueba resolución de configuraciones válidas e inválidas.
- Si se usa caché (`CacheManager`), prueba consistencia (sin duplicados) e invalidación cuando aplique — ver `test_cache_manager.py::test_save_entries_upserts_existing_row`.
