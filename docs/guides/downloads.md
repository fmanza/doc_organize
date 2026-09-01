# 📥 Descarga de Documentación Offline

La documentación completa de `doc_organize` está disponible para descarga en formato ZIP, permitiendo acceso offline con búsqueda integrada y funcionalidad completa.

## 📦 Descargar

Todas las versiones de documentación offline están publicadas en **GitHub Releases** bajo tags `docs-v*`:

**→ [Ir a Releases](https://github.com/fmanza/doc_organize/releases)**

### Versión Actual

Descarga el ZIP más reciente:

```bash
# Busca el release más reciente con tag docs-v* en:
# https://github.com/fmanza/doc_organize/releases
```

**Contenido del ZIP:**
- ✅ Documentación HTML completa (compilada con MkDocs)
- ✅ Diagramas Mermaid (renderizados como SVG)
- ✅ Ejemplos de código ejecutables
- ✅ Referencia API completa
- ✅ **Búsqueda offline** (`search_index.json` incluido)
- ✅ Diseño responsive (funciona en móvil, tablet, desktop)

**Tamaño:** ~0.9 MB (comprimido)

---

## 🔐 Verificación de Integridad

Cada release incluye un archivo SHA256 para validar que el ZIP no fue alterado:

### En Linux/macOS

```bash
# Descargar ambos archivos (ZIP + .sha256)
# Verificar integridad
sha256sum -c doc_organize-docs-*.zip.sha256
# Salida esperada: doc_organize-docs-0.4.0.zip: OK
```

### En Windows

```powershell
# PowerShell
Get-FileHash doc_organize-docs-*.zip -Algorithm SHA256

# Comparar con el valor en el archivo .sha256
# (deben coincidir)
```

### Cálculo Manual

Si prefieres verificar manualmente el checksum:

```bash
# Linux/macOS
sha256sum doc_organize-docs-*.zip

# Windows (PowerShell)
(Get-FileHash .\doc_organize-docs-*.zip -Algorithm SHA256).Hash
```

Luego compara el resultado con el contenido del archivo `.sha256`.

---

## 🚀 Cómo Usar

### 1. Descargar y Extraer

```bash
# Descargar desde GitHub Releases
# (el navegador típicamente lo guarda en ~/Downloads)

# Extraer
unzip doc_organize-docs-*.zip
cd doc_organize-docs-*/

# Abrir en navegador
# Linux/macOS:
open index.html
# o simplemente:
python -m http.server 8000
# Visita: http://localhost:8000

# Windows:
start index.html
```

### 2. Usar la Búsqueda Offline

1. Abre `index.html` en tu navegador
2. Haz clic en el ícono de búsqueda (lupa 🔍)
3. Escribe tu término de búsqueda
4. Los resultados se cargan instantáneamente desde `search_index.json`

**Nota:** La búsqueda funciona sin conexión a internet una vez descargada.

### 3. Navegar la Documentación

- **Sidebar izquierdo:** Navegación jerárquica por secciones
- **Breadcrumb arriba:** Ruta actual en la documentación
- **Tabla de contenidos (TOC):** Si la página es larga, aparece a la derecha
- **Móvil:** El sidebar se colapsa; úsalo desde el ícono ☰

---

## 📋 Histórico de Builds

Para auditoría y trazabilidad, el archivo `CHECKSUMS.txt` en Releases contiene el histórico de todas las builds:

```
SHA256                                                  Filename               Timestamp
a1b2c3d4e5f6...                                         doc_organize-docs-0.4.0.zip  2026-09-01T12:34:56.789123
b2c3d4e5f6a7...                                         doc_organize-docs-0.3.1.zip  2026-08-30T10:20:30.123456
```

Descarga desde el mismo Release o accede al archivo de histórico.

---

## 🔄 Actualizaciones

Cada vez que se actualiza la documentación en `main` o `develop`, se genera automáticamente un nuevo ZIP:

1. **Trigger:** Push a `main`/`develop` que afecte `docs/`, `mkdocs.yml` o `pyproject.toml`
2. **CI/CD:** GitHub Actions ejecuta automáticamente:
   - `mkdocs build --strict` (construye HTML)
   - `python scripts/build_docs_zip.py` (crea ZIP + checksums)
   - Publica nuevo Release con tag `docs-v{version}`
3. **Descarga:** El nuevo ZIP está disponible en Releases inmediatamente

**Workflow:** [`.github/workflows/docs-zip-release.yml`](https://github.com/fmanza/doc_organize/blob/develop/.github/workflows/docs-zip-release.yml)

---

## 📚 Alternativas

### Documentación Online

Si prefieres consultar en línea sin descargar:

**→ [Documentación Online](https://fmanza.github.io/doc_organize/)**

- ✅ Siempre actualizada
- ✅ Búsqueda más rápida (indexada en el servidor)
- ✅ Requiere conexión a internet

### Construir Localmente

Si estás desarrollando o quieres la versión más reciente del repositorio:

```bash
# Clone el repositorio
git clone https://github.com/fmanza/doc_organize.git
cd doc_organize

# Instala dependencias de documentación
pip install -e ".[docs]"

# Construye la documentación
mkdocs build

# Abre en navegador
open site/index.html  # macOS
# o
xdg-open site/index.html  # Linux
# o
start site/index.html  # Windows
```

---

## 🆘 Solución de Problemas

### El ZIP no abre
- **Causa:** Archivo corrupto o descarga incompleta
- **Solución:** 
  - Verifica el checksum SHA256 (ver § "Verificación de Integridad")
  - Descarga nuevamente desde Releases

### La búsqueda no funciona
- **Causa:** `search_index.json` no cargó
- **Solución:**
  - Asegúrate de que el servidor HTTP esté ejecutándose:
    ```bash
    python -m http.server 8000  # desde el directorio extracto
    ```
  - La búsqueda desde `file://` (abrir directamente en navegador) no funciona por restricciones CORS
  - Usa un servidor HTTP local como se muestra arriba

### Versión desactualizada
- **Causa:** Descargaste una versión antigua
- **Solución:**
  - Ve a Releases y descarga el tag más reciente (`docs-v` con el número más alto)
  - O construye localmente desde el repositorio

---

## 💾 Almacenamiento

### Requisitos de Espacio

- **ZIP comprimido:** ~0.9 MB
- **Extracto descomprimido:** ~5-10 MB (según versión)
- **Total:** ~11 MB máximo

### Ubicación Recomendada

```bash
# Linux/macOS
~/Documents/doc_organize-docs/

# Windows
C:\Users\YourUsername\Documents\doc_organize-docs\
```

---

## 🔗 Enlaces Relacionados

- [Documentación Online](https://fmanza.github.io/doc_organize/)
- [GitHub Releases](https://github.com/fmanza/doc_organize/releases)
- [PyPI Package](https://pypi.org/project/doc-organize/)
- [GitHub Repository](https://github.com/fmanza/doc_organize)
- [Issues & Features](https://github.com/fmanza/doc_organize/issues)

---

**Última actualización:** 2026-09-01  
**Generado por:** `scripts/build_docs_zip.py`  
**Flujo CI/CD:** `.github/workflows/docs-zip-release.yml`
