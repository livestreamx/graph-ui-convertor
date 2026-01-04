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


def test_proc_name_used_for_frame_label_and_roundtrip() -> None:
    payload = {
        "finedog_unit_id": 7,
        "markup_type": "service",
        "procedures": [
            {
                "proc_id": "proc_internal",
                "proc_name": "Human Friendly Procedure",
                "start_block_ids": ["a"],
                "end_block_ids": ["b::end"],
                "branches": {"a": ["b"]},
            }
        ],
    }
    markup = MarkupDocument.model_validate(payload)
    excal = MarkupToExcalidrawConverter(GridLayoutEngine()).convert(markup)

    frame = next(
        element
        for element in excal.elements
        if element.get("type") == "frame"
        and element.get("customData", {}).get("cjm", {}).get("procedure_id") == "proc_internal"
    )
    assert frame.get("name") == "Human Friendly Procedure (proc_internal)"

    reconstructed = ExcalidrawToMarkupConverter().convert(excal.to_dict())
    proc = reconstructed.procedures[0]
    assert proc.procedure_name == "Human Friendly Procedure"


def test_disconnected_procedure_graphs_are_separated() -> None:
    payload = {
        "finedog_unit_id": 8,
        "markup_type": "service",
        "procedures": [
            {
                "proc_id": "p1",
                "start_block_ids": ["a"],
                "end_block_ids": ["b::end"],
                "branches": {"a": ["b"]},
            },
            {
                "proc_id": "p2",
                "start_block_ids": ["c"],
                "end_block_ids": ["d::end"],
                "branches": {"c": ["d"]},
            },
        ],
        "procedure_graph": {},
    }
    markup = MarkupDocument.model_validate(payload)
    plan = GridLayoutEngine().build_plan(markup)
    frames = {frame.procedure_id: frame for frame in plan.frames}
    assert frames["p1"].origin.y != frames["p2"].origin.y


def test_separators_drawn_between_disconnected_components() -> None:
    payload = {
        "finedog_unit_id": 10,
        "markup_type": "service",
        "procedures": [
            {
                "proc_id": "alpha",
                "start_block_ids": ["a"],
                "end_block_ids": ["b::end"],
                "branches": {"a": ["b"]},
            },
            {
                "proc_id": "beta",
                "start_block_ids": ["c"],
                "end_block_ids": ["d::end"],
                "branches": {"c": ["d"]},
            },
        ],
        "procedure_graph": {},
    }
    markup = MarkupDocument.model_validate(payload)
    layout = GridLayoutEngine()
    excal = MarkupToExcalidrawConverter(layout).convert(markup)

    separators = [
        element
        for element in excal.elements
        if element.get("type") == "line"
        and element.get("customData", {}).get("cjm", {}).get("role") == "separator"
    ]
    assert separators

    frames = [
        element
        for element in excal.elements
        if element.get("type") == "frame"
        and element.get("customData", {}).get("cjm", {}).get("role") == "frame"
    ]
    assert len(frames) == 2
    top_frame = min(frames, key=lambda frame: frame.get("y", 0.0))
    bottom_frame = max(frames, key=lambda frame: frame.get("y", 0.0))
    top_bottom = top_frame.get("y", 0.0) + top_frame.get("height", 0.0)
    bottom_top = bottom_frame.get("y", 0.0)

    separator = separators[0]
    points = separator.get("points", [])
    start_y = separator.get("y", 0.0) + points[0][1]
    end_y = separator.get("y", 0.0) + points[-1][1]
    assert start_y == end_y
    assert start_y > top_bottom
    assert start_y < bottom_top
    assert start_y - top_bottom >= layout.config.separator_padding
    assert bottom_top - start_y >= layout.config.separator_padding


def test_multiple_dependencies_stack_vertically() -> None:
    payload = {
        "finedog_unit_id": 9,
        "markup_type": "service",
        "procedures": [
            {
                "proc_id": "root",
                "start_block_ids": ["a"],
                "end_block_ids": ["b::end"],
                "branches": {"a": ["b"]},
            },
            {
                "proc_id": "child_one",
                "start_block_ids": ["c"],
                "end_block_ids": ["d::end"],
                "branches": {"c": ["d"]},
            },
            {
                "proc_id": "child_two",
                "start_block_ids": ["e"],
                "end_block_ids": ["f::end"],
                "branches": {"e": ["f"]},
            },
        ],
        "procedure_graph": {"root": ["child_one", "child_two"]},
    }
    markup = MarkupDocument.model_validate(payload)
    plan = GridLayoutEngine().build_plan(markup)
    frames = {frame.procedure_id: frame for frame in plan.frames}
    assert frames["child_one"].origin.x == frames["child_two"].origin.x
    assert frames["child_one"].origin.y != frames["child_two"].origin.y
