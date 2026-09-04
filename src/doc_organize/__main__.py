"""Permite ejecutar `python -m doc_organize ...`."""

import sys

from doc_organize.main import main

if __name__ == "__main__":  # pragma: no cover
    # Solo ejecutable como proceso real (`python -m doc_organize ...`), no
    # importando este módulo -- `main()` en sí ya tiene cobertura completa vía
    # llamada directa en `tests/unit/test_main.py`; esta línea es el shim de
    # entrypoint, no lógica propia (maturity-assessment, sesión 2026-09-03/04).
    sys.exit(main())
