from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

from adapters.layout.grid import GridLayoutEngine
from domain.models import MarkupDocument
from domain.services.convert_excalidraw_to_markup import ExcalidrawToMarkupConverter
from domain.services.convert_markup_to_excalidraw import MarkupToExcalidrawConverter


def load_markup_fixture(name: str) -> MarkupDocument:
    fixture_path = Path(__file__).parent.parent / "examples" / "markup" / name
    return MarkupDocument.model_validate(json.loads(fixture_path.read_text()))


def normalize(document: MarkupDocument) -> Dict[str, Any]:
    normalized_procedures: List[Dict[str, Any]] = []
    for procedure in sorted(document.procedures, key=lambda p: p.procedure_id):
        normalized_procedures.append(
            {
                "procedure_id": procedure.procedure_id,
                "start_block_ids": sorted(procedure.start_block_ids),
                "end_block_ids": sorted(procedure.end_block_ids),
                "branches": {k: sorted(v) for k, v in sorted(procedure.branches.items())},
            }
        )
    return {
        "finedog_unit_id": document.finedog_unit_id,
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


def test_branch_metadata_persists() -> None:
    markup = load_markup_fixture("advanced.json")
    layout = GridLayoutEngine()
    forward = MarkupToExcalidrawConverter(layout)
    excal = forward.convert(markup)

    branch_edges = [
        element
        for element in excal.elements
        if element.get("type") == "arrow"
        and element.get("customData", {}).get("cjm", {}).get("edge_type") == "branch"
    ]
    assert branch_edges, "Branch edges should be rendered with metadata"


def test_branch_edges_match_markup() -> None:
    payload = {
        "finedog_unit_id": 11,
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
        assert meta.get("finedog_unit_id") == markup.finedog_unit_id
        assert meta.get("markup_type") == markup.markup_type


def test_roundtrip_from_example_json_fixture() -> None:
    markup = load_markup_fixture("yet_another.json")
    layout = GridLayoutEngine()
    forward = MarkupToExcalidrawConverter(layout)
    backward = ExcalidrawToMarkupConverter()

    excal = forward.convert(markup)
    reconstructed = backward.convert(excal.to_dict())

    assert normalize(reconstructed) == normalize(markup)


def test_roundtrip_with_links_fixture() -> None:
    markup = load_markup_fixture("with_links.json")
    layout = GridLayoutEngine()
    forward = MarkupToExcalidrawConverter(layout)
    backward = ExcalidrawToMarkupConverter()

    excal = forward.convert(markup)
    reconstructed = backward.convert(excal.to_dict())

    assert normalize(reconstructed) == normalize(markup)


def test_extra_block_names_not_rendered() -> None:
    payload = {
        "finedog_unit_id": 21,
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
        "finedog_unit_id": 22,
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
