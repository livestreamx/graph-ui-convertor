from __future__ import annotations

from typing import Any, cast

from adapters.layout.grid import GridLayoutEngine
from domain.models import END_TYPE_COLORS, MarkupDocument
from domain.services.convert_excalidraw_to_markup import ExcalidrawToMarkupConverter
from domain.services.convert_markup_to_excalidraw import MarkupToExcalidrawConverter


def test_end_type_roundtrip_and_service_name() -> None:
    payload = {
        "markup_type": "service",
        "finedog_unit_meta": {
            "service_name": "Test Service",
            "criticality_level": "BC",
            "team_id": 101,
            "team_name": "Support Core",
        },
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
    assert reconstructed.criticality_level == "BC"
    assert reconstructed.team_id == 101
    assert reconstructed.team_name == "Support Core"
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
    procedures = cast(list[dict[str, Any]], serialized["procedures"])
    assert procedures[0]["end_block_ids"] == ["b::exit", "c::intermediate"]
    meta = cast(dict[str, Any], serialized.get("finedog_unit_meta"))
    assert meta["criticality_level"] == "BC"
    assert meta["team_id"] == 101
    assert meta["team_name"] == "Support Core"


def test_skip_empty_procedures_in_excalidraw() -> None:
    payload = {
        "markup_type": "service",
        "procedures": [
            {"proc_id": "empty"},
            {
                "proc_id": "with_blocks",
                "start_block_ids": ["a"],
                "end_block_ids": ["b::end"],
                "branches": {"a": ["b"]},
            },
        ],
    }
    markup = MarkupDocument.model_validate(payload)
    excal = MarkupToExcalidrawConverter(GridLayoutEngine()).convert(markup)

    frame_procs = {
        element.get("customData", {}).get("cjm", {}).get("procedure_id")
        for element in excal.elements
        if element.get("type") == "frame"
    }
    assert "empty" not in frame_procs
    assert "with_blocks" in frame_procs
