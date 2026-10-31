# doc_organize

> Escanea, convierte a Markdown/JSON, deduplica y cachea documentos — por línea de
> comandos o desde una interfaz web opcional con autenticación multi-usuario y
> multi-tenant.

## Descripción

`doc_organize` escanea carpetas de documentos (PDF, Word, Excel, PowerPoint,
imágenes), calcula su hash SHA-256, los convierte a Markdown + JSON con
[Docling](https://github.com/docling-project/docling) (con detección y
reprocesado de OCR), detecta y resuelve duplicados, y mantiene un caché
incremental para no reconvertir lo que no ha cambiado. Cada conjunto de trabajo
se organiza como un **proyecto**: una carpeta raíz propia con su conversión, su
caché y sus duplicados.

Incluye una interfaz web opcional (extra `[web]`) con progreso en tiempo real
por WebSocket; en modo no-loopback exige autenticación por usuario con soporte
multi-tenant (varias organizaciones, cada una con sus propios usuarios y
proyectos, aisladas entre sí).

## Requisitos

- Python 3.12+
- Para convertir Excel legado (`.xls`, distinto de `.xlsx`): LibreOffice
  instalado y accesible en el `PATH` como `soffice` — ver
  [instalación](docs/guides/installation.md#excel-legado-xls-libreoffice-opcional).

## Instalación

```bash
pip install doc_organize            # núcleo: CLI, OCR en CPU incluido
pip install doc_organize[web]       # + interfaz web
```

### Desarrollo

```bash
python -m venv .venv
source .venv/bin/activate  # En Windows: .venv\Scripts\activate

pip install -e ".[dev,web,docs]"
```

## Uso básico

```bash
# Crear un proyecto y escanear una carpeta
python -m doc_organize project create "Mi Proyecto" --location /ruta/a/workspaces
python -m doc_organize scan --project "Mi Proyecto" --paths /ruta/a/documentos

# Interfaz web (loopback, sin autenticación)
pip install doc_organize[web]
python -m doc_organize web
```

Ver la [documentación completa](https://fmanza.github.io/doc_organize) —
[instalación](docs/guides/installation.md), [inicio rápido](docs/guides/quick_start.md)
y [funcionalidad por módulo](docs/functional/index.md).

## Testing

```bash
python -m pytest                    # todos los tests
python -m pytest -m "not slow"      # sin los de integración con Docling real
python -m pytest --cov=src          # con cobertura
```

## Linting y type checking

```bash
python -m ruff check src tests
python -m ruff format src tests
python -m mypy src
```

## Documentación

```bash
mkdocs serve    # documentación local (http://127.0.0.1:8000)
mkdocs build    # sitio estático en ./site
```

### Descarga Offline

La documentación completa se empaqueta automáticamente en ZIP con checksums para distribución offline:

```bash
# Generar ZIP manualmente
python scripts/build_docs_zip.py

# Resultado:
# - dist/doc_organize-docs-{version}.zip
# - dist/doc_organize-docs-{version}.zip.sha256
# - dist/CHECKSUMS.txt (histórico de builds)
```

**Descarga en Releases:** https://github.com/fmanza/doc_organize/releases (busca tags `docs-v*`)

**Verificación de integridad:**
```bash
sha256sum -c doc_organize-docs-*.zip.sha256
# Output: doc_organize-docs-0.3.0.zip: OK
```

## Estructura del proyecto

```
doc_organize/
├── src/doc_organize/
│   ├── core/            # modelos, excepciones, constantes (Nivel 1)
│   ├── utils/            # hash_file, safe_path_join, logging (Nivel 1)
│   ├── validators/       # FolderValidator, ProjectValidator (Nivel 2)
│   ├── scanner/           # DocumentScanner (Nivel 2)
│   ├── converter/         # DocumentConverter, OCRScheduler (Nivel 2)
│   ├── dedup/              # DeduplicationManager (Nivel 2)
│   ├── cache/               # CacheManager, SQLite+WAL (Nivel 2)
│   ├── projects/             # ProjectRegistry (Nivel 2)
│   ├── auth/                  # AuthStore: usuarios/tenants/sesiones (Nivel 2)
│   ├── scan/                   # ScanCommand: orquestación compartida CLI/web (Nivel 3)
│   ├── web/                     # interfaz web opcional, FastAPI (Nivel 3, extra [web])
│   └── main.py                   # CLI (Nivel 3)
├── tests/
│   ├── unit/
│   └── conftest.py
├── docs/
├── pyproject.toml
└── README.md
```

## Commits

Usar [Conventional Commits](https://www.conventionalcommits.org/):

```
feat:     nueva funcionalidad
fix:      corrección de bug
refactor: cambio sin impacto funcional
test:     solo tests
docs:     solo documentación
chore:    mantenimiento
```

## Contacto

Autor: Paco Manzano — fmanzano.trabajo@gmail.com

## Licencia

MIT License. Ver LICENSE para más detalles.
