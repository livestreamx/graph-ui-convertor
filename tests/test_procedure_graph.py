from __future__ import annotations

from adapters.layout.grid import GridLayoutEngine
from domain.models import MarkupDocument
from domain.services.convert_excalidraw_to_markup import ExcalidrawToMarkupConverter
from domain.services.convert_markup_to_excalidraw import MarkupToExcalidrawConverter


def _sample_markup() -> MarkupDocument:
    payload = {
        "finedog_unit_id": 42,
        "markup_type": "service",
        "procedures": [
            {
                "proc_id": "p1",
                "start_block_ids": ["a"],
                "end_block_ids": ["b::end"],
                "branches": {"a": ["b"]},
                "block_id_to_block_name": {"a": "Start A", "b": "End B"},
            },
            {
                "proc_id": "p2",
                "start_block_ids": ["c"],
                "end_block_ids": ["d::exit"],
                "branches": {"c": ["d"]},
            },
        ],
        "procedure_graph": {"p2": ["p1"]},
    }
    return MarkupDocument.model_validate(payload)


def test_procedure_graph_orders_frames_and_edges() -> None:
    markup = _sample_markup()
    layout = GridLayoutEngine()
    plan = layout.build_plan(markup)
    frames = {frame.procedure_id: frame for frame in plan.frames}

    assert frames["p2"].origin.x < frames["p1"].origin.x

    excal = MarkupToExcalidrawConverter(layout).convert(markup)
    procedure_edges = [
        element
        for element in excal.elements
        if element.get("type") == "arrow"
        and element.get("customData", {}).get("cjm", {}).get("edge_type") == "procedure_flow"
    ]
    assert any(
        edge.get("customData", {}).get("cjm", {}).get("procedure_id") == "p2"
        and edge.get("customData", {}).get("cjm", {}).get("target_procedure_id") == "p1"
        for edge in procedure_edges
    )

    reconstructed = ExcalidrawToMarkupConverter().convert(excal.to_dict())
    assert reconstructed.procedure_graph.get("p2") == ["p1"]


def test_block_name_mapping_roundtrip() -> None:
    markup = _sample_markup()
    excal = MarkupToExcalidrawConverter(GridLayoutEngine()).convert(markup)

    labels = [
        element
        for element in excal.elements
        if element.get("type") == "text"
        and element.get("customData", {}).get("cjm", {}).get("role") == "block_label"
    ]
    label_for_a = next(
        label
        for label in labels
        if label.get("customData", {}).get("cjm", {}).get("block_id") == "a"
    )
    label_text = label_for_a.get("text", "").replace("\n", " ").strip()
    assert label_text == "Start A"
    assert label_for_a.get("customData", {}).get("cjm", {}).get("block_name") == "Start A"

    reconstructed = ExcalidrawToMarkupConverter().convert(excal.to_dict())
    proc = next(proc for proc in reconstructed.procedures if proc.procedure_id == "p1")
    assert proc.block_id_to_block_name["a"] == "Start A"
    assert proc.block_id_to_block_name["b"] == "End B"
