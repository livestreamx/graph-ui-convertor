from __future__ import annotations

from typing import Any, cast

from adapters.layout.grid import GridLayoutEngine
from domain.models import END_TYPE_COLORS, END_TYPE_TURN_OUT, MarkupDocument
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
                "end_block_ids": ["b::exit", "c::intermediate", "d::postpone"],
                "branches": {"a": ["b"], "b": ["c"], "c": ["d"]},
            }
        ],
    }

    markup = MarkupDocument.model_validate(payload)
    procedure = markup.procedures[0]
    assert procedure.end_block_ids == ["b", "c", "d"]
    assert procedure.end_block_types["b"] == "exit"
    assert procedure.end_block_types["c"] == "intermediate"
    assert procedure.end_block_types["d"] == "postpone"

    excal = MarkupToExcalidrawConverter(GridLayoutEngine()).convert(markup)
    reconstructed = ExcalidrawToMarkupConverter().convert(excal.to_dict())
    reconstructed_proc = reconstructed.procedures[0]

    assert reconstructed.service_name == "Test Service"
    assert reconstructed.criticality_level == "BC"
    assert reconstructed.team_id == 101
    assert reconstructed.team_name == "Support Core"
    assert reconstructed_proc.end_block_types["b"] == "exit"
    assert reconstructed_proc.end_block_types["c"] == "intermediate"
    assert reconstructed_proc.end_block_types["d"] == "postpone"

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
    assert END_TYPE_COLORS["postpone"] in colors

    serialized = markup.to_markup_dict()
    procedures = cast(list[dict[str, Any]], serialized["procedures"])
    assert procedures[0]["end_block_ids"] == ["b::exit", "c::intermediate", "d::postpone"]
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


def test_turn_out_end_markers_are_implicit_from_branches() -> None:
    payload = {
        "markup_type": "service",
        "procedures": [
            {
                "proc_id": "p1",
                "start_block_ids": ["a"],
                "end_block_ids": [],
                "branches": {"a": ["b"], "b": ["c"]},
            }
        ],
    }
    markup = MarkupDocument.model_validate(payload)
    excal = MarkupToExcalidrawConverter(GridLayoutEngine()).convert(markup)

    turn_out_markers = [
        element
        for element in excal.elements
        if element.get("type") == "ellipse"
        and element.get("customData", {}).get("cjm", {}).get("role") == "end_marker"
        and element.get("customData", {}).get("cjm", {}).get("end_type") == END_TYPE_TURN_OUT
    ]
    turn_out_blocks = {
        marker.get("customData", {}).get("cjm", {}).get("block_id") for marker in turn_out_markers
    }
    assert turn_out_blocks == {"a", "b"}

    reconstructed = ExcalidrawToMarkupConverter().convert(excal.to_dict())
    reconstructed_proc = reconstructed.procedures[0]
    assert "a" not in reconstructed_proc.end_block_ids
    assert "b" not in reconstructed_proc.end_block_ids


def test_turn_out_markers_skip_terminal_end_blocks() -> None:
    payload = {
        "markup_type": "service",
        "procedures": [
            {
                "proc_id": "p1",
                "start_block_ids": ["a"],
                "end_block_ids": ["b::end"],
                "branches": {"a": ["b"], "b": ["c"]},
            }
        ],
    }
    markup = MarkupDocument.model_validate(payload)
    excal = MarkupToExcalidrawConverter(GridLayoutEngine()).convert(markup)

    turn_out_blocks = {
        element.get("customData", {}).get("cjm", {}).get("block_id")
        for element in excal.elements
        if element.get("type") == "ellipse"
        and element.get("customData", {}).get("cjm", {}).get("role") == "end_marker"
        and element.get("customData", {}).get("cjm", {}).get("end_type") == END_TYPE_TURN_OUT
    }
    assert turn_out_blocks == {"a"}


def test_turn_out_markers_allow_intermediate_non_terminal_blocks() -> None:
    payload = {
        "markup_type": "service",
        "procedures": [
            {
                "proc_id": "p1",
                "start_block_ids": ["a"],
                "end_block_ids": ["b::intermediate"],
                "branches": {"a": ["b"], "b": ["c"]},
            }
        ],
    }
    markup = MarkupDocument.model_validate(payload)
    excal = MarkupToExcalidrawConverter(GridLayoutEngine()).convert(markup)

    turn_out_blocks = {
        element.get("customData", {}).get("cjm", {}).get("block_id")
        for element in excal.elements
        if element.get("type") == "ellipse"
        and element.get("customData", {}).get("cjm", {}).get("role") == "end_marker"
        and element.get("customData", {}).get("cjm", {}).get("end_type") == END_TYPE_TURN_OUT
    }
    assert turn_out_blocks == {"a", "b"}


def test_default_end_marker_color_is_applied() -> None:
    payload = {
        "markup_type": "service",
        "procedures": [
            {
                "proc_id": "p1",
                "start_block_ids": ["a"],
                "end_block_ids": ["b::end"],
                "branches": {"a": ["b"]},
            }
        ],
    }
    markup = MarkupDocument.model_validate(payload)
    excal = MarkupToExcalidrawConverter(GridLayoutEngine()).convert(markup)

    end_markers = [
        element
        for element in excal.elements
        if element.get("type") == "ellipse"
        and element.get("customData", {}).get("cjm", {}).get("role") == "end_marker"
        and element.get("customData", {}).get("cjm", {}).get("end_type") == "end"
    ]
    assert end_markers
    assert all(element.get("backgroundColor") == END_TYPE_COLORS["end"] for element in end_markers)
