"""API pública (L-1, G1, G15): ``__all__`` resoluble, versión de los metadatos e importación ligera."""

import subprocess
import sys

from importlib.metadata import version
from pathlib import Path

import pytest

import doc_organize


def test_every_public_name_resolves() -> None:
    missing = [name for name in doc_organize.__all__ if not hasattr(doc_organize, name)]

    assert missing == []


def test_version_comes_from_package_metadata() -> None:
    assert doc_organize.__version__ == version("doc_organize")


def test_unknown_attribute_raises_attribute_error() -> None:
    with pytest.raises(AttributeError, match="no_existe"):
        doc_organize.no_existe  # noqa: B018 - se comprueba el error de acceso


def test_py_typed_marker_is_shipped() -> None:
    assert (Path(doc_organize.__file__).parent / "py.typed").is_file()


def test_importing_package_and_light_modules_does_not_load_docling() -> None:
    """Un consumidor (doc_organize_web) puede leer versión, modelos y diagnósticos sin cargar Docling ni torch."""
    code = (
        "import sys, doc_organize, doc_organize.core.models, doc_organize.core.exceptions, "
        "doc_organize.utils.gpu_detector, doc_organize.utils.av_detector, doc_organize.utils.office_detector; "
        "from doc_organize import ScanEvent, Project, detect_office_status; "
        "print(sorted(m for m in ('docling', 'torch') if m in sys.modules))"
    )
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True, timeout=120)

    assert result.stdout.strip() == "[]"


def test_importing_export_does_not_load_docling_nor_openpyxl() -> None:
    """`doc_organize.export` (L-7) no arrastra Docling, y `openpyxl` (extra `export`) solo se importa al escribir un Excel."""
    code = (
        "import sys, doc_organize.export; "
        "from doc_organize import write_project_zip, write_cache_xlsx, ExportStats, MissingDependencyError; "
        "print(sorted(m for m in ('docling', 'torch', 'openpyxl', 'doc_organize.web', 'doc_organize.auth') if m in sys.modules))"
    )
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True, timeout=120)

    assert result.stdout.strip() == "[]"


def test_output_layout_and_read_only_cache_do_not_load_docling() -> None:
    """La API de la web calcula rutas de salida y lee la caché sin Docling (L-10e, G20/G21)."""
    code = (
        "import sys, doc_organize.projects.layout, doc_organize.cache; "
        "from doc_organize import resolve_output_paths, resolve_images_dir, relative_source_path, CacheManager, "
        "CacheNotFoundError, ModelsNotAvailableError; "
        "print(sorted(m for m in ('docling', 'torch') if m in sys.modules))"
    )
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True, timeout=120)

    assert result.stdout.strip() == "[]"


def test_type_checking_imports_match_the_public_api() -> None:
    """El bloque `TYPE_CHECKING` de `__init__` (para mypy y los IDE) importa exactamente `_EXPORTS`, cada nombre desde su
    módulo. Si sobra uno, el IDE lo ofrece pero `from doc_organize import X` falla (pasó en M4.1 con `AiSettings`); si
    falta, mypy lo ve como `Any` (pasó con todo lo de 2.0: `LlmClient`, los agentes, la evaluación…)."""
    import ast

    from pathlib import Path

    tree = ast.parse(Path(doc_organize.__file__).read_text(encoding="utf-8"))
    block = next(node for node in tree.body if isinstance(node, ast.If) and getattr(node.test, "id", None) == "TYPE_CHECKING")
    imported = {alias.asname or alias.name: node.module for node in ast.walk(block) if isinstance(node, ast.ImportFrom) for alias in node.names}
    assert imported == doc_organize._EXPORTS


def test_every_public_name_is_listed_in_the_public_api_page() -> None:
    """`docs/api/publica.md` (grupos de nombres) cita cada nombre de `__all__`: en 2.2.0 le faltaban 78."""
    from pathlib import Path

    page = (Path(doc_organize.__file__).parents[2] / "docs" / "api" / "publica.md").read_text(encoding="utf-8")
    assert sorted(name for name in doc_organize._EXPORTS if f"`{name}`" not in page) == []


#: Lo que doc_organize_web importaba de submódulos hasta 2.3.0 (opción 2 de la revisión de la API, 2.4.0). Desde 2.4.0
#: es API pública: quitar o renombrar cualquiera es un cambio incompatible (versión mayor).
WEB_NAMES = (
    "AiError",
    "AiAuthError",
    "AiConnectionError",
    "AiConfigurationError",
    "UsageSourceError",
    "UsageSourceAuthError",
    "UsageSourceConnectionError",
    "ContextNotFoundError",
    "TaxonomyManifestError",
    "TaxonomyTemplateError",
    "ContextBuildRecord",
    "ContextChange",
    "UnclassifiedDocument",
    "LiteLLMUsageConfig",
    "DocumentProperties",
    "read_document_properties",
    "LiteLLMUsageClient",
    "draft_taxonomy",
    "render_prompt_preview",
    "legacy_variables",
    "compose_profile",
    "compose_profile_text",
    "parse_profile",
    "PROJECT_PROFILE_FILE",
    "render_taxonomy_manifest_markdown",
    "save_taxonomy_manifest",
    "select_document_sample",
    "load_context_history",
    "write_context_history_xlsx",
    "DECISIONS_FILE",
    "DEFAULT_REVIEW_LIMITS",
    "DEFAULT_DESIGN_LIMITS",
)


@pytest.mark.parametrize("name", WEB_NAMES)
def test_names_used_by_doc_organize_web_are_public(name: str) -> None:
    assert name in doc_organize.__all__
    assert getattr(doc_organize, name) is not None
