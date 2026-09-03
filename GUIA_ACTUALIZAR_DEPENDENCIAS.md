# Guía: Actualizar Paquetes en Entorno Virtual Python

## Introducción

Esta guía proporciona el flujo completo para mantener actualizado un entorno virtual Python con un `pyproject.toml` configurado correctamente.

---

## 1. Activar el entorno virtual

### En Windows (PowerShell)
```powershell
.\.venv\Scripts\Activate.ps1
```

### En Windows (cmd.exe)
```cmd
.\.venv\Scripts\activate.bat
```

### En Linux/macOS
```bash
source .venv/bin/activate
```

---

## 2. Actualizar pip y setuptools

```bash
python -m pip install --upgrade pip setuptools wheel
```

**Recomendación**: Ejecuta esto regularmente para mantener las herramientas de construcción actualizadas.

---

## 3. Instalar/actualizar dependencias desde pyproject.toml

### Opción A: Instalación básica (recomendado para desarrollo)

Instala dependencias principales más dependencias de desarrollo:

```bash
# Instala dependencias principales + dev
pip install -e ".[dev]"

# O si necesitas otros extras (docs, web, etc.)
pip install -e ".[dev,docs,web]"
```

**Nota**: La opción `-e` instala el paquete en modo "editable", perfecto para desarrollo.

### Opción B: Actualizar solo dependencias existentes

Fuerza reinstalación/actualización a versiones más recientes:

```bash
pip install --upgrade -e ".[dev]"
```

### Opción C: Actualizar paquete específico

```bash
pip install --upgrade nombre-paquete
```

**Ejemplo**:
```bash
pip install --upgrade docling pandas pytest
```

---

## 4. Verificar que todo está instalado correctamente

```bash
# Listar todos los paquetes instalados
pip list

# Detectar conflictos de dependencias
pip check
```

---

## 5. Ejecutar tests para validar

```bash
# Ejecutar tests básicos
pytest

# Ejecutar con cobertura de código
pytest --cov=src

# Ejecutar con reporte HTML detallado
pytest --cov=src --cov-report=html
```

---

## Para el proyecto doc_organize

### Pasos específicos para este proyecto

En PowerShell:

```powershell
# 1. Activar entorno virtual
.\.venv\Scripts\Activate.ps1

# 2. Actualizar pip y herramientas
python -m pip install --upgrade pip setuptools wheel

# 3. Instalar todas las dependencias (incluyendo dev, web y docs)
pip install -e ".[dev,web,docs]"

# 4. Verificar instalación
pip list
pip check

# 5. Ejecutar tests para validar
pytest

# 6. Validar type-checking
mypy src

# 7. Validar linting
ruff check src tests
```

### Dependencias por grupo en doc_organize

**Dependencias principales**:
- `docling[rapidocr]>=2.0.0` — Extracción de contenido de documentos
- `pydantic>=2.0` — Validación de datos
- `aiofiles>=23.0` — Operaciones async de archivos
- `aiosqlite>=0.19` — SQLite asincrónico
- `pillow>=10.0` — Procesamiento de imágenes
- `pandas>=2.0` — Análisis de datos
- `python-magic-bin>=0.4` (Windows) / `python-magic>=0.4` (Unix)
- `tzdata>=2024.1` — Información de zonas horarias

**Grupo dev** (desarrollo y testing):
```bash
pip install -e ".[dev]"
```

**Grupo web** (servidor web):
```bash
pip install -e ".[web]"
```

**Grupo docs** (generación de documentación):
```bash
pip install -e ".[docs]"
```

**Grupo ocr-gpu** (OCR con GPU):
```bash
pip install -e ".[ocr-gpu]"
```

**Grupo av** (audio/video):
```bash
pip install -e ".[av]"
```

---

## Mejores Prácticas

### ✅ Usar versionado adecuado

El `pyproject.toml` usa especificadores de versión flexibles:
- `>=2.0.0` — Permite versiones 2.0.0 y superiores (incluyendo mayores)
- `>=2.0.0,<3.0` — Permite solo versiones 2.x (recomendado para estabilidad)

**Recomendación**: Considera ajustar especificadores para dependencias críticas.

### ✅ Crear archivo lock (reproducibilidad)

Para garantizar reproducibilidad total en entornos de producción:

#### Con `pip-tools`:
```bash
pip install pip-tools
pip-compile pyproject.toml -o requirements.txt
pip install -r requirements.txt
```

#### Con `uv` (más rápido, moderno):
```bash
pip install uv
uv pip compile pyproject.toml -o requirements.txt
uv pip install -r requirements.txt
```

### ✅ Auditar vulnerabilidades

Detecta CVEs (vulnerabilidades conocidas) en dependencias:

```bash
# Usando pip-audit
pip install pip-audit
pip-audit

# Usando safety
pip install safety
safety check
```

### ✅ Validar antes de commit

Antes de hacer commit de cambios:

```powershell
# Windows PowerShell
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
pip check
mypy src
ruff check src tests
pytest
```

---

## Troubleshooting

### Problema: "No such file or directory: '.venv/Scripts/Activate.ps1'"

**Solución**: El entorno virtual no existe. Créalo:

```bash
python -m venv .venv
```

### Problema: "pip: command not found"

**Solución**: Asegúrate de que el entorno virtual está activado.

### Problema: Conflictos de dependencias

**Diagnóstico**:
```bash
pip check
```

**Solución**: Actualiza pip y setuptools, luego reinstala:

```bash
python -m pip install --upgrade pip setuptools
pip install -e ".[dev]" --force-reinstall
```

### Problema: Tests fallan después de actualizar

**Solución**: Limpia caché de pytest y reinicia:

```bash
pytest --cache-clear
pytest
```

---

## Comandos Útiles Resumidos

```bash
# Activar entorno
.\.venv\Scripts\Activate.ps1

# Instalar todo
pip install -e ".[dev,web,docs]"

# Actualizar todo
pip install --upgrade -e ".[dev,web,docs]"

# Listar paquetes
pip list

# Verificar conflictos
pip check

# Ejecutar tests con cobertura
pytest --cov=src --cov-report=html

# Validar tipos
mypy src

# Linting
ruff check src tests

# Formateo automático
ruff format src tests
```

---

## Referencias

- [pyproject.toml oficial](https://packaging.python.org/en/latest/specifications/pyproject-toml/)
- [pip documentation](https://pip.pypa.io/)
- [setuptools documentation](https://setuptools.pypa.io/)
- [pytest documentation](https://docs.pytest.org/)
- [pip-tools](https://github.com/jazzband/pip-tools)
- [uv (Astral Python package manager)](https://astral.sh/uv/)

---

*Última actualización: 2026-09-03*
