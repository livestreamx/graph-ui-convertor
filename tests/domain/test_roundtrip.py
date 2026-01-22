from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from adapters.layout.grid import GridLayoutEngine
from domain.models import MarkupDocument
from domain.services.convert_excalidraw_to_markup import ExcalidrawToMarkupConverter
from domain.services.convert_markup_to_excalidraw import MarkupToExcalidrawConverter


def repo_root() -> Path:
    for parent in Path(__file__).resolve().parents:
        if (parent / "pyproject.toml").exists():
            return parent
    raise RuntimeError("Repository root not found")


def load_markup_fixture(name: str) -> MarkupDocument:
    fixture_path = repo_root() / "examples" / "markup" / name
    return MarkupDocument.model_validate(json.loads(fixture_path.read_text(encoding="utf-8")))


def _branches_from_block_graph(document: MarkupDocument) -> dict[str, dict[str, list[str]]]:
    proc_for_block: dict[str, str] = {}
    duplicates: set[str] = set()
    for procedure in document.procedures:
        for block_id in procedure.block_ids():
            existing_proc = proc_for_block.get(block_id)
            if existing_proc and existing_proc != procedure.procedure_id:
                duplicates.add(block_id)
            elif not existing_proc:
                proc_for_block[block_id] = procedure.procedure_id

    branches: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
    for source, targets in document.block_graph.items():
        if source in duplicates:
            continue
        source_proc = proc_for_block.get(source)
        if not source_proc:
            continue
        for target in targets:
            if target in duplicates:
                continue
            target_proc = proc_for_block.get(target)
            if target_proc != source_proc:
                continue
            branches[source_proc][source].add(target)

    return {
        proc_id: {source: sorted(values) for source, values in sorted(proc_branches.items())}
        for proc_id, proc_branches in branches.items()
    }


def normalize(document: MarkupDocument) -> dict[str, Any]:
    derived_branches: dict[str, dict[str, list[str]]] | None = None
    if document.block_graph:
        derived_branches = _branches_from_block_graph(document)
    normalized_procedures: list[dict[str, Any]] = []
    for procedure in sorted(document.procedures, key=lambda p: p.procedure_id):
        if derived_branches is None:
            branches = {k: sorted(v) for k, v in sorted(procedure.branches.items())}
        else:
            branches = derived_branches.get(procedure.procedure_id, {})
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
    markup = load_markup_fixture("complex-graph.json")
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
    assert "Billing Flow" in title_texts[0].get("text", "")

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


def test_roundtrip_complex_graph_fixture() -> None:
    markup = load_markup_fixture("complex-graph.json")
    layout = GridLayoutEngine()
    forward = MarkupToExcalidrawConverter(layout)
    backward = ExcalidrawToMarkupConverter()

    excal = forward.convert(markup)
    reconstructed = backward.convert(excal.to_dict())

    assert normalize(reconstructed) == normalize(markup)


def test_roundtrip_graphs_set_fixture() -> None:
    markup = load_markup_fixture("graphs_set.json")
    layout = GridLayoutEngine()
    forward = MarkupToExcalidrawConverter(layout)
    backward = ExcalidrawToMarkupConverter()

    excal = forward.convert(markup)
    reconstructed = backward.convert(excal.to_dict())

    assert normalize(reconstructed) == normalize(markup)


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
