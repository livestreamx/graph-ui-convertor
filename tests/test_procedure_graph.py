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


def test_no_procedure_edges_without_links() -> None:
    payload = {
        "finedog_unit_id": 11,
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
    excal = MarkupToExcalidrawConverter(GridLayoutEngine()).convert(markup)

    procedure_edges = [
        element
        for element in excal.elements
        if element.get("type") == "arrow"
        and element.get("customData", {}).get("cjm", {}).get("edge_type")
        in {"procedure_flow", "procedure_cycle"}
    ]
    assert not procedure_edges


def test_scenarios_describe_components() -> None:
    payload = {
        "finedog_unit_id": 12,
        "markup_type": "service",
        "procedures": [
            {
                "proc_id": "p1",
                "proc_name": "Первый сценарий",
                "start_block_ids": ["a"],
                "end_block_ids": ["b::end"],
                "branches": {"a": ["b"]},
            },
            {
                "proc_id": "p2",
                "proc_name": "Второй сценарий",
                "start_block_ids": ["c"],
                "end_block_ids": ["d::end", "e::end"],
                "branches": {"c": ["d", "e"]},
            },
        ],
        "procedure_graph": {},
    }
    markup = MarkupDocument.model_validate(payload)
    excal = MarkupToExcalidrawConverter(GridLayoutEngine()).convert(markup)

    titles = [
        element
        for element in excal.elements
        if element.get("type") == "text"
        and element.get("customData", {}).get("cjm", {}).get("role") == "scenario_title"
    ]
    bodies = [
        element
        for element in excal.elements
        if element.get("type") == "text"
        and element.get("customData", {}).get("cjm", {}).get("role") == "scenario_body"
    ]
    panels = [
        element
        for element in excal.elements
        if element.get("type") == "rectangle"
        and element.get("customData", {}).get("cjm", {}).get("role") == "scenario_panel"
    ]
    assert len(titles) == 2
    assert len(bodies) == 2
    assert len(panels) == 2
    title_by_index = {
        element.get("customData", {}).get("cjm", {}).get("scenario_index"): element
        for element in titles
    }
    body_by_index = {
        element.get("customData", {}).get("cjm", {}).get("scenario_index"): element
        for element in bodies
    }
    first_title = title_by_index[1].get("text", "")
    second_title = title_by_index[2].get("text", "")
    assert first_title.strip().startswith("Сценарий 1")
    assert second_title.strip().startswith("Сценарий 2")
    first_body = body_by_index[1].get("text", "")
    second_body = body_by_index[2].get("text", "")
    assert "Процедуры:" in first_body
    assert "- Первый сценарий (p1)" in first_body
    assert "Комплексность сценария:" in first_body
    assert "- Входы: 1" in first_body
    assert "- Выходы: 1" in first_body
    assert "- Ветвления: 1" in first_body
    assert "Процедуры:" in second_body
    assert "- Второй сценарий (p2)" in second_body
    assert "Комплексность сценария:" in second_body
    assert "- Входы: 1" in second_body
    assert "- Выходы: 2" in second_body
    assert "- Ветвления: 2" in second_body


def test_scenario_procedure_list_prioritizes_starts_when_trimmed() -> None:
    procedures = []
    for idx in range(1, 8):
        proc_id = f"p{idx}"
        proc = {
            "proc_id": proc_id,
            "proc_name": f"Proc {idx}",
            "end_block_ids": [f"b{idx}::end"],
            "branches": {f"a{idx}": [f"b{idx}"]},
        }
        if idx in {1, 7}:
            proc["start_block_ids"] = [f"a{idx}"]
        procedures.append(proc)
    procedure_graph = {f"p{idx}": [f"p{idx+1}"] for idx in range(1, 7)}

    payload = {
        "finedog_unit_id": 13,
        "markup_type": "service",
        "procedures": procedures,
        "procedure_graph": procedure_graph,
    }
    markup = MarkupDocument.model_validate(payload)
    excal = MarkupToExcalidrawConverter(GridLayoutEngine()).convert(markup)
    bodies = [
        element
        for element in excal.elements
        if element.get("type") == "text"
        and element.get("customData", {}).get("cjm", {}).get("role") == "scenario_body"
    ]
    assert len(bodies) == 1
    body_text = bodies[0].get("text", "")
    assert "- Proc 7 (p7)" in body_text
    assert "и еще 1" in body_text


def test_scenario_combinations_fallback_to_end_blocks() -> None:
    payload = {
        "finedog_unit_id": 14,
        "markup_type": "service",
        "procedures": [
            {
                "proc_id": "p1",
                "proc_name": "Без ветвлений",
                "start_block_ids": ["a"],
                "end_block_ids": ["b::end", "c::end"],
                "branches": {},
            }
        ],
        "procedure_graph": {},
    }
    markup = MarkupDocument.model_validate(payload)
    excal = MarkupToExcalidrawConverter(GridLayoutEngine()).convert(markup)
    body = next(
        element
        for element in excal.elements
        if element.get("type") == "text"
        and element.get("customData", {}).get("cjm", {}).get("role") == "scenario_body"
    )
    body_text = body.get("text", "")
    assert "- Ветвления: 1" in body_text


def test_scenario_combinations_use_procedure_graph_when_no_branches() -> None:
    payload = {
        "finedog_unit_id": 15,
        "markup_type": "service",
        "procedures": [
            {
                "proc_id": "root",
                "proc_name": "Root",
                "start_block_ids": ["a"],
                "end_block_ids": ["b::end"],
                "branches": {},
            },
            {
                "proc_id": "child_one",
                "proc_name": "Child One",
                "start_block_ids": ["c"],
                "end_block_ids": ["d::end"],
                "branches": {},
            },
            {
                "proc_id": "child_two",
                "proc_name": "Child Two",
                "start_block_ids": ["e"],
                "end_block_ids": ["f::end"],
                "branches": {},
            },
        ],
        "procedure_graph": {"root": ["child_one", "child_two"]},
    }
    markup = MarkupDocument.model_validate(payload)
    excal = MarkupToExcalidrawConverter(GridLayoutEngine()).convert(markup)
    body = next(
        element
        for element in excal.elements
        if element.get("type") == "text"
        and element.get("customData", {}).get("cjm", {}).get("role") == "scenario_body"
    )
    body_text = body.get("text", "")
    assert "- Ветвления: 2" in body_text


def test_cycle_layout_prefers_order_hint() -> None:
    payload = {
        "finedog_unit_id": 16,
        "markup_type": "service",
        "procedures": [
            {
                "proc_id": "close_gold_account",
                "start_block_ids": ["a"],
                "end_block_ids": ["b::end"],
                "branches": {"a": ["b"]},
            },
            {
                "proc_id": "product_gold_account",
                "start_block_ids": ["c"],
                "end_block_ids": ["d::end"],
                "branches": {"c": ["d"]},
            },
        ],
        "procedure_graph": {
            "close_gold_account": ["product_gold_account"],
            "product_gold_account": ["close_gold_account"],
        },
    }
    markup = MarkupDocument.model_validate(payload)
    plan = GridLayoutEngine().build_plan(markup)
    frames = {frame.procedure_id: frame for frame in plan.frames}
    assert frames["close_gold_account"].origin.x < frames["product_gold_account"].origin.x


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
