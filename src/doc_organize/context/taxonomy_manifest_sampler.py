"""
Selección de una muestra representativa de documentos ya convertidos, para pedir a la IA un
borrador de manifiesto de taxonomía (`ai.taxonomy_manifest_draft_client`).
"""

from collections.abc import Sequence
from pathlib import Path, PurePath

from doc_organize.ai.taxonomy_manifest_draft_client import SampledDocument
from doc_organize.context.domain_classifier import read_conversion_json
from doc_organize.core.models import ConversionResult
from doc_organize.projects.layout import relative_source_path
from doc_organize.utils.logging import get_logger

logger = get_logger(__name__)


def _folder_display(source_path: str, roots: Sequence[str] | None = None) -> str:
    """Hasta 2 niveles de carpeta contenedora de `source_path` (p. ej. "Ciberseguridad/Politicas"),
    nunca la ruta absoluta completa -- evita enviar la estructura de disco local del servidor
    (usuario, unidad...) al LiteLLM Proxy, y da más señal que solo el nombre de la carpeta
    inmediata cuando la taxonomía real está anidada en 2 niveles.

    Con `roots` (L-3d), las carpetas se cuentan desde la raíz escaneada que contiene el documento
    (gana la más profunda, mismo criterio que `relative_source_path`, G23) y nunca se muestra nada
    por encima de ella: un documento en la propia raíz da `""`, y uno que no cuelga de ninguna
    raíz también (no se sabe qué es seguro mostrar). Un `source_path` ya relativo (el `.json` de
    0.12.0+) se toma tal cual, relativo a su raíz.
    """
    if roots is not None:
        # `relative_source_path` da solo el nombre del fichero si no cuelga de ninguna raíz: carpeta "".
        relative = relative_source_path(source_path, roots) if PurePath(source_path).is_absolute() else source_path
        folder_parts = [part for part in PurePath(relative).parts[:-1] if part not in ("", ".", "..")]
        return "/".join(folder_parts[-2:])
    parent = Path(source_path).parent
    grandparent_name = parent.parent.name
    return f"{grandparent_name}/{parent.name}" if grandparent_name else parent.name


def _select_candidates(documents: list[ConversionResult], sample_size: int, roots: Sequence[str] | None = None) -> list[ConversionResult]:
    """Selecciona hasta `sample_size` documentos de `documents`, repartidos entre carpetas
    contenedoras (round-robin determinista) para que la IA vea diversidad de carpetas/dominios
    reales en vez de los primeros N documentos alfabéticos de una única carpeta.

    Sin aleatoriedad -- mismo criterio de determinismo que el resto de doc_organize (orden
    estable entre llamadas con el mismo conjunto de documentos).
    """
    by_folder: dict[str, list[ConversionResult]] = {}
    for document in documents:
        by_folder.setdefault(_folder_display(document.source_path, roots), []).append(document)
    for group in by_folder.values():
        group.sort(key=lambda document: document.source_path)

    ordered_folders = sorted(by_folder)
    selected: list[ConversionResult] = []
    round_index = 0
    while len(selected) < sample_size:
        added_this_round = False
        for folder in ordered_folders:
            group = by_folder[folder]
            if round_index < len(group):
                selected.append(group[round_index])
                added_this_round = True
                if len(selected) >= sample_size:
                    break
        if not added_this_round:
            break
        round_index += 1
    return selected


async def select_document_sample(documents: list[ConversionResult], sample_size: int, *, roots: Sequence[str] | None = None) -> list[SampledDocument]:
    """Selecciona y lee hasta `sample_size` documentos de `documents` para pedir un borrador de
    manifiesto de taxonomía por IA.

    Lee `chunks`/`title` del `.json` de conversión con `read_conversion_json()` — mismo criterio
    que `DomainClassifier`/`ContextBuilder` (nunca reparsea el `.md`). Un documento cuyo `.json`
    no se puede leer se descarta de la muestra en vez de bloquear la generación del borrador
    (mismo criterio que un artefacto incompleto en `DomainClassifier.classify()`) — por eso la
    muestra final puede tener menos de `sample_size` documentos.

    Args:
        documents: Documentos ya convertidos con éxito del proyecto.
        sample_size: Tope de documentos a incluir en la muestra.
        roots: Raíces escaneadas del proyecto (L-3d). Con ellas, la carpeta de cada documento es
            relativa a la raíz que lo contiene y nunca muestra nombres por encima de ella (p. ej.
            las carpetas del punto de montaje). `None` (por defecto): hasta 2 carpetas
            contenedoras de `source_path`, como antes de 0.14.0.

    Returns:
        Hasta `sample_size` `SampledDocument`, repartidos entre carpetas contenedoras
        (`_select_candidates`) y en orden determinista.
    """
    candidates = _select_candidates(documents, sample_size, roots)
    sample: list[SampledDocument] = []
    for document in candidates:
        if not document.json_path:
            continue
        chunks_result = await read_conversion_json(document.json_path)
        if chunks_result is None:
            continue
        chunks_text, title = chunks_result
        sample.append(SampledDocument(folder=_folder_display(document.source_path, roots), title=title, chunks_text=chunks_text))
    return sample


__all__ = ["select_document_sample"]
