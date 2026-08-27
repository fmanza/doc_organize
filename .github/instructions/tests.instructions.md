---
applyTo: "tests/**"
---
# Tests

> **TL;DR** — Pytest, fixtures mínimas, sin red ni servicios externos. Test-first en hotfix (reproduce el bug antes de corregirlo), snapshot o asserts clave para docs generados. Si el cambio toca API pública, añadir test de integración. Tests rápidos y deterministas.

- Añade tests para toda nueva funcionalidad.
- Prefiere fixtures pequeñas y datos de esquema mínimos (tablas/relaciones pequeñas).
- Si hay generación de docs, usa snapshot testing o asserts sobre fragmentos clave.
- Evita depender de red; si necesitas BD, usa contenedor/local opcional o mocks.
- Para refactors, añade tests antes de cambiar código.
- Para hotfixes, añade tests que reproduzcan el bug antes de corregirlo.
- Usa pytest y sigue su convención de nombres (`test_*.py` y `def test_*`).
- Si el cambio afecta a la API pública, añade tests de integración que validen el comportamiento esperado.
- Para cambios de seguridad, añade tests que verifiquen la mitigación del riesgo.
- Mantén los tests rápidos y deterministas; evita pruebas que puedan fallar por factores externos.
- Antes de finalizar cualquier cambio, ejecuta `mypy src`, `ruff check src tests` y los tests de documentación; corrige cualquier rotura restante hasta dejar la validación en verde.

## Cobertura arquitectónica mínima
- Valida contratos comunes con tests parametrizados por implementación (sync/async y por motor).
- Verifica `LSP`: cualquier implementación concreta debe pasar la misma suite de contrato.
- Verifica `OCP`: al agregar motor/formato nuevo, no debe romper tests existentes de motores previos.
- Verifica `SRP`: cambios en render no deben romper tests de introspección y viceversa.
- Si se usa `Factory` o `Registry`, prueba resolución de implementaciones válidas e inválidas.
- Si se usa `Identity Map` o cache, prueba consistencia (sin duplicados) e invalidación cuando aplique.
- Si se introduce `Query Object` o `Repository`, prueba que el SQL/consulta queda encapsulado y tipado.
