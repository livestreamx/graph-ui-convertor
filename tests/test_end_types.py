from __future__ import annotations

from adapters.layout.grid import GridLayoutEngine
from domain.models import END_TYPE_COLORS, MarkupDocument
from domain.services.convert_excalidraw_to_markup import ExcalidrawToMarkupConverter
from domain.services.convert_markup_to_excalidraw import MarkupToExcalidrawConverter


def test_end_type_roundtrip_and_service_name() -> None:
    payload = {
        "finedog_unit_id": 9001,
        "markup_type": "service",
        "finedog_unit_meta": {"service_name": "Test Service"},
        "procedures": [
            {
                "proc_id": "p1",
                "start_block_ids": ["a"],
                "end_block_ids": ["b::exit", "c::intermediate"],
                "branches": {"a": ["b"], "b": ["c"]},
            }
        ],
    }

    markup = MarkupDocument.model_validate(payload)
    procedure = markup.procedures[0]
    assert procedure.end_block_ids == ["b", "c"]
    assert procedure.end_block_types["b"] == "exit"
    assert procedure.end_block_types["c"] == "intermediate"

    excal = MarkupToExcalidrawConverter(GridLayoutEngine()).convert(markup)
    reconstructed = ExcalidrawToMarkupConverter().convert(excal.to_dict())
    reconstructed_proc = reconstructed.procedures[0]

    assert reconstructed.service_name == "Test Service"
    assert reconstructed_proc.end_block_types["b"] == "exit"
    assert reconstructed_proc.end_block_types["c"] == "intermediate"

    marker_elements = [
        element
        for element in excal.elements
        if element.get("type") == "ellipse"
        and element.get("customData", {}).get("cjm", {}).get("role") == "end_marker"
    ]
    assert marker_elements
    colors = {element.get("backgroundColor") for element in marker_elements}
    assert END_TYPE_COLORS["exit"] in colors
    assert END_TYPE_COLORS["intermediate"] in colors

    serialized = markup.to_markup_dict()
    assert serialized["procedures"][0]["end_block_ids"] == ["b::exit", "c::intermediate"]
