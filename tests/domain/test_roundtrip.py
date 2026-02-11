from __future__ import annotations

from typing import Any

import pytest

from adapters.layout.grid import GridLayoutEngine
from domain.models import MarkupDocument
from domain.services.convert_excalidraw_to_markup import ExcalidrawToMarkupConverter
from domain.services.convert_markup_to_excalidraw import MarkupToExcalidrawConverter
from tests.helpers.markup_fixtures import load_markup_fixture


def normalize(document: MarkupDocument) -> dict[str, Any]:
    normalized_procedures: list[dict[str, Any]] = []
    ignore_branch_targets = bool(document.block_graph)
    for procedure in sorted(document.procedures, key=lambda p: p.procedure_id):
        branches = {k: sorted(v) for k, v in sorted(procedure.branches.items())}
        if ignore_branch_targets and branches:
            branches = {key: [] for key in branches}
        normalized_procedures.append(
            {
                "procedure_id": procedure.procedure_id,
                "start_block_ids": sorted(procedure.start_block_ids),
                "end_block_ids": sorted(procedure.end_block_ids),
                "branches": branches or {},
            }
        )
    return {
        "markup_type": document.markup_type,
        "procedures": normalized_procedures,
    }


def test_roundtrip_preserves_structure() -> None:
    markup = load_markup_fixture("basic.json")
    layout = GridLayoutEngine()
    forward = MarkupToExcalidrawConverter(layout)
    backward = ExcalidrawToMarkupConverter()

    excal = forward.convert(markup)
    reconstructed = backward.convert(excal.to_dict())

    assert normalize(reconstructed) == normalize(markup)


def test_block_graph_metadata_persists() -> None:
    markup = load_markup_fixture("complex_graph.json")
    layout = GridLayoutEngine()
    forward = MarkupToExcalidrawConverter(layout)
    excal = forward.convert(markup)

    block_graph_edges = [
        element
        for element in excal.elements
        if element.get("type") == "arrow"
        and element.get("customData", {}).get("cjm", {}).get("edge_type")
        in {"block_graph", "block_graph_cycle"}
    ]
    assert block_graph_edges, "Block graph edges should be rendered with metadata"


def test_branch_edges_match_markup() -> None:
    payload = {
        "markup_type": "service",
        "procedures": [
            {
                "proc_id": "p1",
                "start_block_ids": ["a"],
                "end_block_ids": ["d::end"],
                "branches": {"a": ["b", "c"], "b": ["d"], "c": ["a"]},
            }
        ],
    }
    markup = MarkupDocument.model_validate(payload)
    excal = MarkupToExcalidrawConverter(GridLayoutEngine()).convert(markup)

    branch_edges = [
        element
        for element in excal.elements
        if element.get("type") == "arrow"
        and element.get("customData", {}).get("cjm", {}).get("edge_type")
        in {"branch", "branch_cycle"}
    ]
    expected_count = sum(len(targets) for targets in markup.procedures[0].branches.values())
    edge_pairs = {
        (
            element.get("customData", {}).get("cjm", {}).get("procedure_id"),
            element.get("customData", {}).get("cjm", {}).get("source_block_id"),
            element.get("customData", {}).get("cjm", {}).get("target_block_id"),
        )
        for element in branch_edges
    }
    expected_pairs = {
        ("p1", source, target)
        for source, targets in markup.procedures[0].branches.items()
        for target in targets
    }

    assert len(branch_edges) == expected_count
    assert edge_pairs == expected_pairs


def test_metadata_contains_globals() -> None:
    markup = load_markup_fixture("basic.json")
    excal = MarkupToExcalidrawConverter(GridLayoutEngine()).convert(markup)

    for element in excal.elements:
        meta = element.get("customData", {}).get("cjm", {})
        assert meta.get("schema_version") == "1.0"
        assert meta.get("markup_type") == markup.markup_type


def test_service_name_title_rendered_above_frames() -> None:
    payload = {
        "markup_type": "service",
        "finedog_unit_meta": {"service_name": "Billing Flow"},
        "procedures": [
            {
                "proc_id": "p1",
                "start_block_ids": ["a"],
                "end_block_ids": ["b"],
                "branches": {"a": ["b"]},
            }
        ],
    }
    markup = MarkupDocument.model_validate(payload)
    excal = MarkupToExcalidrawConverter(GridLayoutEngine()).convert(markup)

    title_panels = [
        element
        for element in excal.elements
        if element.get("customData", {}).get("cjm", {}).get("role") == "diagram_title_panel"
    ]
    title_texts = [
        element
        for element in excal.elements
        if element.get("customData", {}).get("cjm", {}).get("role") == "diagram_title"
    ]
    assert len(title_panels) == 1
    assert title_texts
    assert "[service] Billing Flow" in title_texts[0].get("text", "")

    frame_min_y = min(
        element.get("y", 0.0) for element in excal.elements if element.get("type") == "frame"
    )
    panel = title_panels[0]
    panel_bottom = panel.get("y", 0.0) + panel.get("height", 0.0)
    assert panel_bottom < frame_min_y


def test_service_name_title_skipped_without_name() -> None:
    payload = {
        "markup_type": "service",
        "procedures": [
            {
                "proc_id": "p1",
                "start_block_ids": ["a"],
                "end_block_ids": ["b"],
                "branches": {"a": ["b"]},
            }
        ],
    }
    markup = MarkupDocument.model_validate(payload)
    excal = MarkupToExcalidrawConverter(GridLayoutEngine()).convert(markup)

    title_elements = [
        element
        for element in excal.elements
        if element.get("customData", {}).get("cjm", {}).get("role")
        in {"diagram_title", "diagram_title_panel", "diagram_title_rule"}
    ]
    assert not title_elements


@pytest.mark.parametrize("fixture_name", ["complex_graph.json", "graphs_set.json", "forest.json"])
def test_roundtrip_fixture(fixture_name: str) -> None:
    markup = load_markup_fixture(fixture_name)
    layout = GridLayoutEngine()
    forward = MarkupToExcalidrawConverter(layout)
    backward = ExcalidrawToMarkupConverter()

    excal = forward.convert(markup)
    reconstructed = backward.convert(excal.to_dict())

    assert normalize(reconstructed) == normalize(markup)


def test_complex_graph_has_epsilon_variant_to_proc_c() -> None:
    markup = load_markup_fixture("complex_graph.json")
    proc_graph = markup.procedure_graph

    assert "proc_c" in proc_graph.get("proc_epsilon", [])

    proc_c = next(proc for proc in markup.procedures if proc.procedure_id == "proc_c")
    assert "c_postpone" in proc_c.end_block_ids
    assert proc_c.end_block_types.get("c_postpone") == "postpone"
    assert proc_c.branches.get("c_hub") == ["c_postpone"]


def test_graphs_set_contains_proc_c_merge_node() -> None:
    markup = load_markup_fixture("graphs_set.json")
    proc_c = next(proc for proc in markup.procedures if proc.procedure_id == "proc_c")

    assert proc_c.branches.get("c_route") == ["c_left", "c_right"]
    assert proc_c.branches.get("c_left") == ["c_hub"]
    assert proc_c.branches.get("c_right") == ["c_hub"]


def test_extra_block_names_not_rendered() -> None:
    payload = {
        "markup_type": "service",
        "procedures": [
            {
                "proc_id": "p1",
                "start_block_ids": ["a"],
                "end_block_ids": ["b::end"],
                "branches": {"a": ["b"]},
                "block_id_to_block_name": {"a": "Alpha", "ghost": "Ghost"},
            }
        ],
    }
    markup = MarkupDocument.model_validate(payload)
    excal = MarkupToExcalidrawConverter(GridLayoutEngine()).convert(markup)

    ghost_elements = [
        element
        for element in excal.elements
        if element.get("customData", {}).get("cjm", {}).get("block_id") == "ghost"
        or element.get("customData", {}).get("cjm", {}).get("block_name") == "Ghost"
    ]
    assert not ghost_elements


def test_first_frame_centered_on_origin() -> None:
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

    frame = next(
        element
        for element in excal.elements
        if element.get("type") == "frame"
        and element.get("customData", {}).get("cjm", {}).get("procedure_id") == "p1"
    )
    center_x = frame.get("x", 0.0) + frame.get("width", 0.0) / 2
    center_y = frame.get("y", 0.0) + frame.get("height", 0.0) / 2
    assert abs(center_x) < 1e-6
    assert abs(center_y) < 1e-6


def test_arrow_bindings_attach_to_elements() -> None:
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

    elements_by_id = {element.get("id"): element for element in excal.elements}
    arrows = [element for element in excal.elements if element.get("type") == "arrow"]
    assert arrows
    for arrow in arrows:
        for binding_key in ("startBinding", "endBinding"):
            binding = arrow.get(binding_key) or {}
            target_id = binding.get("elementId")
            if not target_id:
                continue
            target = elements_by_id.get(target_id)
            assert target is not None
            bound = {item.get("id") for item in target.get("boundElements", [])}
            assert arrow.get("id") in bound


def test_excalidraw_edges_render_behind_shapes() -> None:
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

    edge_indices = [
        idx for idx, element in enumerate(excal.elements) if element.get("type") == "arrow"
    ]
    non_edge_indices = [
        idx for idx, element in enumerate(excal.elements) if element.get("type") != "arrow"
    ]
    assert edge_indices
    assert non_edge_indices
    assert max(edge_indices) < min(non_edge_indices)
