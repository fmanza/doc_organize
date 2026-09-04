# TRACEABILITY: Resumen de Sesión

## Sesión
- **Fecha**: 2026-09-04
- **Tipo**: `hotfix` — extra de packaging incompleto
- **Rama**: `develop`
- **Estado**: ✅ COMPLETADA

## Objetivo
El usuario reportó que escanear con OCR fallaba con
`EasyOCR is not installed. Please install it via 'pip install easyocr'`. Se
pidió explicar la causa y actualizar el proyecto para tenerla en cuenta.

## Investigación previa
`--use-ocr --use-gpu` (`src/doc_organize/converter/converter.py:97-101`) fuerza
`EasyOcrOptions(use_gpu=True)` en Docling. El extra `ocr-gpu` de
`pyproject.toml` (pensado exactamente para habilitar esta ruta, documentado en
`docs/guides/installation.md` y `.ai/product.md`) instalaba `torch`/
`torchvision`/`opencv-python` pero **nunca `easyocr`**, el paquete que Docling
realmente importa. Seguir la documentación oficial del proyecto
(`pip install .[ocr-gpu]` + `--use-gpu`) reproducía el error tal cual. No es
un problema de uso del usuario, es un extra de `pyproject.toml` incompleto.

`src/doc_organize/utils/gpu_detector.py` (detección para deshabilitar el
checkbox "OCR con GPU" en el menú Escaneo) solo comprueba `torch`/CUDA vía
`find_spec` — no comprobaba `easyocr` por separado. No se ha tocado: una vez
el extra instala ambos paquetes juntos, sigue siendo coherente (si en el
futuro alguien tiene `torch` instalado por otro motivo sin el extra completo,
seguiría sin detectar el hueco — riesgo residual documentado abajo).

## Cambios Ejecutados

### ✅ 1. Extra `ocr-gpu` completo
**Archivo(s)**: `pyproject.toml`.
**Descripción**: añadido `easyocr>=1.7` al extra `ocr-gpu` (junto a
`torch`/`torchvision`/`opencv-python` ya existentes).
**Status**: ✅ `python -c "import tomllib; tomllib.load(...)"` — parseo
correcto. No se ha podido verificar instalación real en este entorno (ver
Riesgos Residuales, bloqueo de Windows con `cv2.pyd` por procesos
`doc_organize web` corriendo desde el mismo `.venv`).

### ✅ 2. Documentación sincronizada
**Archivo(s)**: `docs/guides/installation.md`, `.ai/product.md`,
`CHANGELOG.md`.
**Descripción**: ambos ficheros listaban los paquetes que instala el extra
`ocr-gpu` sin `easyocr` — corregido a
`torch`/`torchvision`/`opencv-python`/`easyocr`. Entrada `Fixed` en
`CHANGELOG.md` bajo `[Unreleased]`.
**Status**: ✅ `mkdocs build --strict` limpio (sin warnings de links rotos).

---

## Impacto

### Código
- **Archivos modificados**: 4 — `pyproject.toml`, `docs/guides/installation.md`,
  `.ai/product.md`, `CHANGELOG.md`. Ningún fichero de `src/` ni `tests/`
  tocado (no era un bug de lógica, era un extra de packaging incompleto).
- **Cambios funcionales**: no en tiempo de ejecución del código ya instalado;
  sí en qué instala `pip install .[ocr-gpu]` a partir de ahora.

### Compatibilidad
- **BREAKING**: ninguno.
- **NO BREAKING**: añade una dependencia a un extra opcional ya existente;
  quien no instale `[ocr-gpu]` no se ve afectado.

---

## Verificación
```
python -c "import tomllib; tomllib.load(open('pyproject.toml','rb'))"   → OK (parseo válido)
python -m mkdocs build --strict                                          → build limpio, sin warnings
```
No se ejecutó `pytest`/`ruff`/`mypy`: no se tocó código de `src/`/`tests/`.
No se pudo verificar `pip install -e ".[ocr-gpu]"` end-to-end en este entorno
(ver Riesgos Residuales).

---

## Riesgos Residuales

| Riesgo | Mitigación | Status |
|--------|-----------|--------|
| No verificado un `pip install -e ".[ocr-gpu]"` real tras el fix (entorno Windows con procesos `doc_organize web` bloqueando `.venv/Lib/site-packages/cv2/cv2.pyd`) | Usuario cerrará los procesos manualmente y reintentará; pendiente confirmación de que instala sin error | Pendiente de confirmación del usuario |
| `gpu_detector.detect_gpu_status()` solo comprueba `torch`/CUDA, no `easyocr` en sí | Aceptable mientras el extra instale ambos atómicamente; si diverge de nuevo, el checkbox "OCR con GPU" podría activarse sin `easyocr` instalado | Aceptado |

---

## Siguientes Pasos (Recomendado)
1. Usuario reintenta `pip install -e ".[web,ocr-gpu]"` tras cerrar los procesos
   `doc_organize web` que bloqueaban `.venv` (Windows `WinError 5`).
2. Confirmar con un escaneo real (`--use-ocr --use-gpu`) que EasyOCR carga sin
   error.
3. Commit + push a GitHub (mensaje preparado en esta misma sesión).

---

## Directrices para Futuras IAs

- **[El extra `ocr-gpu` de `pyproject.toml` debe instalar `easyocr` junto a
  `torch`/`torchvision`/`opencv-python`]**: antes de este fix (2026-09-04) solo
  instalaba los tres primeros — Docling importa `easyocr` directamente
  (`EasyOcrOptions`, `src/doc_organize/converter/converter.py:101`), no es un
  transitivo de `torch`. Si se vuelve a tocar este extra, verificar que los
  cuatro paquetes siguen juntos.
- **[En Windows, `pip install`/reinstalación de paquetes con `.pyd`/`.dll`
  nativos (`opencv-python`, `torch`) falla con `WinError 5: Acceso denegado`
  si hay un proceso Python del mismo `.venv` corriendo]**: el proceso mantiene
  el archivo cargado y bloqueado. Diagnóstico rápido:
  `Get-CimInstance Win32_Process -Filter "name='python.exe'" | Select ProcessId,ExecutablePath,CommandLine`
  para identificar cuál `.venv` usa cada proceso antes de pedir cerrarlo.
- **[`gpu_detector.detect_gpu_status()` no es una fuente de verdad sobre
  `easyocr`]**: solo indica si `torch` es importable y si CUDA está activo
  (`find_spec("torch")` + `torch.cuda.is_available()`). Asume que el extra
  `ocr-gpu` se instaló completo; no fallará el checkbox si falta `easyocr`
  específicamente.

---

## Veredicto

### 🟢 COMPLETADA (fix de packaging + docs; verificación end-to-end pendiente del usuario)

**Criterios**:
- ✅ Causa raíz identificada y corregida en `pyproject.toml`
- ✅ Documentación (`installation.md`, `product.md`, `CHANGELOG.md`) sincronizada
- ✅ `mkdocs build --strict` limpio
- ⬜ `pip install -e ".[ocr-gpu]"` verificado end-to-end (bloqueado por
  procesos Windows en esta sesión, pendiente de reintento del usuario)
- ⬜ Commit/push: pendiente de confirmación del usuario

**Evidencia**:
- Branch: `develop`
- Commits: pendiente (mensaje preparado, no ejecutado aún)

**Sesión cerrada**: 2026-09-04
