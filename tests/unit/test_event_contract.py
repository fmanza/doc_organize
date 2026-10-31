"""Contrato de los eventos de progreso (L-6b, hueco G7 de doc_organize_web).

`data/event_contract.json` fija la versión del esquema, las claves de `to_dict()` y los tipos de evento. Si este test
falla, el cambio rompe a los consumidores (SSE de doc_organize_web, historiales guardados): sube
`EVENT_SCHEMA_VERSION` si cambian campos o significados, y actualiza el JSON a propósito. Añadir un tipo de evento
nuevo solo exige añadirlo al JSON.
"""

import json

from pathlib import Path

import pytest

from doc_organize import ContextBuildEvent, ContextDeleteEvent, DedupEvent, ScanEvent
from doc_organize.core.models import EVENT_SCHEMA_VERSION, ScanEventType

CONTRACT = json.loads((Path(__file__).parent / "data" / "event_contract.json").read_text(encoding="utf-8"))
EVENTS = {"ScanEvent": ScanEvent, "DedupEvent": DedupEvent, "ContextBuildEvent": ContextBuildEvent, "ContextDeleteEvent": ContextDeleteEvent}


def test_schema_version_matches_contract() -> None:
    assert EVENT_SCHEMA_VERSION == CONTRACT["schema_version"]


@pytest.mark.parametrize("name", sorted(EVENTS))
def test_event_types_match_contract(name: str) -> None:
    event_type = EVENTS[name].model_fields["event"].annotation

    assert [member.value for member in event_type] == CONTRACT["events"][name]


@pytest.mark.parametrize("name", sorted(EVENTS))
def test_to_dict_shape_is_stable_and_json_safe(name: str) -> None:
    model = EVENTS[name]
    first_type = next(iter(model.model_fields["event"].annotation))
    payload = model(event=first_type, data={"path": Path("/tmp/x.pdf"), "total": 3}).to_dict()

    assert list(payload) == CONTRACT["keys"]
    assert payload["schema_version"] == CONTRACT["schema_version"]
    assert payload["event"] == first_type.value
    assert json.loads(json.dumps(payload)) == payload  # todo serializable en JSON


def test_str_of_event_type_is_unchanged() -> None:
    """Decisión UP042 de `pyproject.toml`: `class X(str, Enum)` se mantiene (no `StrEnum`)."""
    assert ScanEventType.COMPLETED == "completed"
    assert ScanEventType.COMPLETED.value == "completed"
