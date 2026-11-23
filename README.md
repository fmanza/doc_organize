# doc_organize

> Escanea, convierte a Markdown/JSON, deduplica y cachea documentos — librería de
> Python y línea de comandos. La interfaz web es [doc_organize_web](https://github.com/fmanza/doc_organize_web).

## Descripción

`doc_organize` escanea carpetas de documentos (PDF, Word, Excel, PowerPoint,
imágenes), calcula su hash SHA-256, los convierte a Markdown + JSON con
[Docling](https://github.com/docling-project/docling) (con detección y
reprocesado de OCR), detecta y resuelve duplicados, y mantiene un caché
incremental para no reconvertir lo que no ha cambiado. Cada conjunto de trabajo
se organiza como un **proyecto**: una carpeta raíz propia con su conversión, su
caché y sus duplicados.

Sobre la conversión, el **contexto documental** clasifica cada documento según una taxonomía por **ejes** (dominio y
tipo de material, que organizan carpetas, y los que solo etiquetan, como el marco normativo), por reglas y, si se
quiere, con embeddings e IA a través de un LiteLLM Proxy; reorganiza una copia en carpetas y genera un sitio navegable
con Zensical, también para verlo sin conexión, y un paquete para subir a un chat o agente de IA.

> **2.2.0**: duplicados por **contenido** (`ContentDuplicateFinder`) sobre el Markdown ya convertido: mismo texto
> sin IA y, opcionalmente, contenido parecido con embeddings de la tarea de IA `dedup`. Guía:
> [Duplicados por contenido](docs/guides/duplicados_por_contenido.md). **2.1.0**: GitHub Copilot queda obsoleto (se
> retira en 3.0); el uso de IA se consulta en LiteLLM: [Hacia 3.0](docs/guides/migracion_3_0.md).

> **2.0.0**: taxonomía por ejes, un solo cliente de IA por tarea (`LlmClient`), decisiones humanas y cola de revisión,
> evaluación, versiones de un documento, semántica, agentes que proponen sin aplicar, sitio sin conexión y paquete para
> IA. Cambios incompatibles y cómo actualizar: [De 1.x a 2.0](docs/guides/migracion_2_0.md).

> **1.0.0 (L-11)**: la interfaz web integrada (`doc_organize.web`, `doc_organize.auth`, los subcomandos `web`,
> `tenant` y `user` del CLI y el extra `[web]`), obsoleta desde 0.14.0, se ha retirado. Usa [doc_organize_web](https://github.com/fmanza/doc_organize_web), que ofrece
> lo mismo (usuarios, tenants, roles y progreso en tiempo real) sobre esta librería. El CLI de `scan`, `project`,
> `deduplicate` y `export` no cambia. Guía: [De la web integrada a doc_organize_web](docs/guides/migracion_web.md);
> cambios incompatibles: [CHANGELOG](CHANGELOG.md#100rc1---2026-11-05).

## Requisitos

- Python 3.12+
- Para convertir Excel legado (`.xls`, distinto de `.xlsx`): LibreOffice
  instalado y accesible en el `PATH` como `soffice` — ver
  [instalación](docs/guides/installation.md#excel-legado-xls-libreoffice-opcional).

## Instalación

```bash
pip install doc_organize            # núcleo: CLI, OCR en CPU incluido
pip install doc_organize[export]    # + Excel de caché, de errores y del contexto (`export cache-xlsx`/`errors-xlsx`/`context-xlsx`)
pip install doc_organize[context]   # + contexto documental (manifiestos, plantillas y prompts)
pip install doc_organize[ai]        # + IA vía LiteLLM Proxy (ver docs/guides/litellm_proxy_setup.md)
pip install doc_organize[site]      # + sitio navegable con Zensical
pip install doc_organize[ocr-gpu]   # + OCR acelerado por GPU NVIDIA (EasyOCR)
pip install doc_organize[av]        # + audio/vídeo (Whisper; requiere ffmpeg y Python 3.12-3.13)
```

### Desarrollo

```bash
python -m venv .venv
source .venv/bin/activate  # En Windows: .venv\Scripts\activate

pip install -e ".[dev,docs]"
```

## Uso básico

```bash
# Crear un proyecto, apartar duplicados por fichero y escanear una carpeta
python -m doc_organize project create "Mi Proyecto" --location /ruta/a/workspaces
python -m doc_organize deduplicate --project "Mi Proyecto" --paths /ruta/a/documentos
python -m doc_organize scan --project "Mi Proyecto" --paths /ruta/a/documentos

# Exportar: ZIP de Conversión/ + cache_export.json, y Excel de caché o de errores (extra [export])
python -m doc_organize export zip --project "Mi Proyecto" --preview
python -m doc_organize export zip --project "Mi Proyecto" -o export.zip
python -m doc_organize export errors-xlsx --output-root /ruta/salidas --state-root /ruta/estado -o errores.xlsx

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
zensical serve    # documentación local (http://127.0.0.1:8000)
zensical build --strict    # sitio estático en ./site
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
# Output: doc_organize-docs-2.2.0.zip: OK
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
│   ├── dedup/              # DeduplicationManager, ContentDuplicateFinder (Nivel 2)
│   ├── cache/               # CacheManager, SQLite+WAL (Nivel 2)
│   ├── projects/             # ProjectRegistry (Nivel 2)
│   ├── security/          # redacción de credenciales, Markdown no confiable (Nivel 2)
│   ├── ai/                 # LlmClient, AiSettings, prompts, caché, embeddings, agentes (Nivel 2)
│   ├── scan/                   # ScanCommand: orquestación del escaneo (Nivel 3)
│   ├── context/               # contexto por ejes, reorganización, sitio, decisiones, agentes (Nivel 3)
│   ├── export/                 # ZIP, Excel y paquete para IA de un proyecto (Nivel 3)
│   ├── diagnostics.py            # check_environment: diagnóstico del entorno
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
