"""
Versiones de un mismo documento (2.0.0, F5): `Manual_Calidad_v1.2.docx` y `Manual_Calidad_v1.3.docx` son el mismo
documento en dos versiones, no dos documentos.

La detección es **conservadora** (R-F5-1, R-F5-4): solo cuenta un marcador **explícito** de versión en el nombre
(`v1.2`, `_v3`, `ver 3`, `rev2`, `versión 1.4`, `ed. 2`, `edición 2`); las fechas no son versiones (`Acta_2023` y
`Acta_2024` son documentos distintos) y un «número de versión» con forma de año (`ISO_9001_v2015`) tampoco. Dos
ficheros son versiones del mismo documento solo si están en la misma carpeta, tienen la misma extensión (salvo
`across_extensions`) y el resto del nombre coincide exactamente (sin distinguir mayúsculas, acentos ni separadores).

La vigente que se propone es la versión más alta (comparación numérica por componentes: `1.10 > 1.9`); la confirma una
persona con una decisión `set_current_version` (R-F5-2).
"""

from __future__ import annotations

import re

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import PurePosixPath

from pydantic import BaseModel, Field

from doc_organize.context.evaluation import document_keys
from doc_organize.core.models import (
    ClassificationDecision,
    ConversionResult,
    DecisionIssue,
    DecisionIssueReason,
    DocumentVersionGroup,
    DomainDocument,
    UnclassifiedDocument,
    VersionsMode,
)
from doc_organize.utils.folding import fold

#: Marcador de versión: la palabra (`v`, `ver`, `version`, `versión`, `rev`, `revision`, `revisión`, `ed`, `edicion`,
#: `edición`), pegada al número o con un punto y/o un espacio (`v1.2`, `ver 3`, `ed. 2`; no `ED_2`), seguida del
#: número (`1`, `1.2`, `1.2.3`), y separada del resto del nombre por un separador o el principio/fin del nombre.
_MARKER = re.compile(
    r"(?:^|(?<=[\s_\-.()\[\]]))"
    r"(?P<word>v|ver|version|versi[oó]n|rev|revision|revisi[oó]n|ed|edicion|edici[oó]n)"
    r"\.?\s?(?P<number>\d+(?:[.,]\d+){0,3})"
    r"(?=$|[\s_\-()\[\]]|\.(?!\d))",
    re.IGNORECASE,
)
_YEAR = range(1900, 2101)


class VersionMember(BaseModel):
    """Un fichero de un grupo de versiones."""

    source_path: str
    version: str = Field(..., description="Versión tal como aparece en el nombre (`1.2`)")
    is_current: bool = False


class VersionGroup(BaseModel):
    """Las versiones de un mismo documento.

    Attributes:
        key (str): Carpeta y nombre sin el marcador de versión, normalizados (identifica el grupo).
        members (list[VersionMember]): Los ficheros, de la versión más baja a la más alta.
        current (str): `source_path` de la vigente (la más alta, o la que decidió una persona).
    """

    key: str
    members: list[VersionMember]
    current: str

    def with_current(self, source_path: str) -> VersionGroup:
        """El grupo con `source_path` como vigente (una decisión `set_current_version`)."""
        members = [member.model_copy(update={"is_current": member.source_path == source_path}) for member in self.members]
        return self.model_copy(update={"members": members, "current": source_path})


def parse_version(file_name: str) -> tuple[str, tuple[int, ...], str] | None:
    """El nombre sin el marcador de versión (normalizado), la versión como números y como texto; `None` si el nombre no
    lleva un marcador explícito (o lleva más de uno, o el número parece un año).

    Example:
        >>> parse_version("Manual_Calidad_v1.2.docx")
        ('manual calidad', (1, 2), '1.2')
        >>> parse_version("ISO_9001_v2015.pdf") is None, parse_version("Acta_2023.docx") is None
        (True, True)
    """
    stem = PurePosixPath(file_name.replace("\\", "/")).stem
    matches = list(_MARKER.finditer(stem))
    if len(matches) != 1:
        return None
    match = matches[0]
    text = match.group("number").replace(",", ".")
    numbers = tuple(int(part) for part in text.split("."))
    if len(numbers) == 1 and numbers[0] in _YEAR:
        return None
    base = fold(stem[: match.start()] + " " + stem[match.end() :])
    if not base:
        return None
    return base, numbers, text


def detect_document_versions(source_paths: Iterable[str], *, across_extensions: bool = False) -> list[VersionGroup]:
    """Los grupos de versiones entre `source_paths` (solo grupos de dos o más ficheros con versiones distintas).

    Args:
        source_paths: Rutas de los originales.
        across_extensions: Agrupar también entre extensiones (`Manual_v2.docx` con `Manual_v3.pdf`); por defecto no.

    Example:
        >>> [group] = detect_document_versions(["/d/Manual_v1.2.docx", "/d/Manual_v1.10.docx", "/d/Otro.docx"])
        >>> print(group.current)
        /d/Manual_v1.10.docx
    """
    candidates: dict[tuple[str, str, str], list[tuple[tuple[int, ...], str, str]]] = {}
    for source_path in source_paths:
        path = PurePosixPath(source_path.replace("\\", "/"))
        parsed = parse_version(path.name)
        if parsed is None:
            continue
        base, numbers, text = parsed
        extension = "" if across_extensions else path.suffix.lower()
        candidates.setdefault((str(path.parent).lower(), base, extension), []).append((numbers, text, source_path))
    groups = []
    for (folder, base, extension), members in sorted(candidates.items()):
        if len({_padded(numbers) for numbers, _, _ in members}) < 2:
            continue  # una sola versión (o la misma en dos formatos): nada que elegir
        members.sort(key=lambda member: (_padded(member[0]), member[2]))
        current = members[-1][2]
        groups.append(
            VersionGroup(
                key=f"{folder}/{base}" + (f"{extension}" if extension else ""),
                members=[VersionMember(source_path=path, version=text, is_current=path == current) for _, text, path in members],
                current=current,
            )
        )
    return groups


def apply_current_choices(groups: list[VersionGroup], chosen: Mapping[str, str]) -> list[VersionGroup]:
    """`groups` con la vigente que decidió una persona: `chosen` es `source_path` elegido → (cualquier valor). Un
    `source_path` que no está en ningún grupo se ignora (quien llama lo informa)."""
    by_member = {member.source_path: index for index, group in enumerate(groups) for member in group.members}
    result = list(groups)
    for source_path in chosen:
        index = by_member.get(source_path)
        if index is not None:
            result[index] = result[index].with_current(source_path)
    return result


@dataclass
class VersionOutcome:
    """Lo que decidió la construcción sobre las versiones (`resolve_versions`)."""

    groups: list[DocumentVersionGroup] = field(default_factory=list)
    superseded: list[str] = field(default_factory=list)
    applied: int = 0
    stale: list[DecisionIssue] = field(default_factory=list)
    orphan: list[DecisionIssue] = field(default_factory=list)

    def member(self, source_path: str) -> tuple[DocumentVersionGroup, str] | None:
        """El grupo y la versión de `source_path`, o `None` si no está en ningún grupo."""
        for group in self.groups:
            if source_path in group.members:
                return group, group.versions[group.members.index(source_path)]
        return None


def resolve_versions(
    documents: Sequence[ConversionResult],
    mode: VersionsMode,
    decisions: Sequence[ClassificationDecision] = (),
    *,
    roots: Sequence[str] | None = None,
) -> VersionOutcome:
    """Los grupos de versiones de `documents` con la vigente (la más alta o la que decidió una persona con
    `set_current_version`) y, con `current_only`, las versiones antiguas que no entran. Con `all` no hace nada."""
    outcome = VersionOutcome()
    if mode == "all":
        return outcome
    groups = detect_document_versions(document.source_path for document in documents)
    keys = document_keys([document.source_path for document in documents], roots)
    by_key = {keys[document.source_path]: document for document in documents}
    grouped = {member.source_path for group in groups for member in group.members}
    confirmed: set[str] = set()
    for decision in decisions:
        if decision.action != "set_current_version":
            continue
        document = by_key.get(decision.document_key)
        issue = _version_issue(decision, document, grouped)
        if issue is not None:
            (outcome.orphan if issue.reason == "missing_document" else outcome.stale).append(issue)
            continue
        assert document is not None
        groups = apply_current_choices(groups, {document.source_path: decision.id})
        confirmed.add(document.source_path)
        outcome.applied += 1
    outcome.groups = [
        DocumentVersionGroup(
            key=_relative_group_key(group, keys),
            members=[member.source_path for member in group.members],
            versions=[member.version for member in group.members],
            current=group.current,
            confirmed=group.current in confirmed,
        )
        for group in groups
    ]
    if mode == "current_only":
        outcome.superseded = sorted(path for group in outcome.groups for path in group.members if path != group.current)
    return outcome


def mark_versions(documents: Iterable[DomainDocument | UnclassifiedDocument], outcome: VersionOutcome) -> None:
    """Pone `version`, `version_group` e `is_current` a los documentos que están en algún grupo."""
    for document in documents:
        found = outcome.member(document.source_path)
        if found is not None:
            group, version = found
            document.version, document.version_group, document.is_current = version, group.key, group.current == document.source_path


def _relative_group_key(group: VersionGroup, keys: Mapping[str, str]) -> str:
    """La clave del grupo con la carpeta relativa a la raíz de escaneo (como las claves de los documentos), en vez de la
    ruta absoluta: estable entre equipos y contenedores (2.0.0, petición de la web)."""
    folder = str(PurePosixPath(group.current.replace("\\", "/")).parent).lower()
    suffix = group.key[len(folder) :] if group.key.startswith(folder) else "/" + group.key.rsplit("/", 1)[-1]
    relative = str(PurePosixPath(keys.get(group.current, PurePosixPath(group.current).name)).parent).lower()
    return suffix.lstrip("/") if relative in ("", ".") else relative + suffix


def _version_issue(decision: ClassificationDecision, document: ConversionResult | None, grouped: set[str]) -> DecisionIssue | None:
    def issue(reason: DecisionIssueReason) -> DecisionIssue:
        return DecisionIssue(decision_id=decision.id, document_key=decision.document_key, reason=reason)

    if document is None:
        return issue("missing_document")
    if decision.source_sha256 and document.source_sha256 and decision.source_sha256 != document.source_sha256:
        return issue("source_changed")
    if document.source_path not in grouped:
        return issue("not_versioned")
    return None


def _padded(numbers: tuple[int, ...]) -> tuple[int, ...]:
    """`(1, 2)` y `(1, 2, 0)` son la misma versión."""
    trimmed = list(numbers)
    while len(trimmed) > 1 and trimmed[-1] == 0:
        trimmed.pop()
    return tuple(trimmed)


__all__ = [
    "VersionGroup",
    "VersionMember",
    "VersionOutcome",
    "apply_current_choices",
    "detect_document_versions",
    "mark_versions",
    "parse_version",
    "resolve_versions",
]
