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


def test_metadata_contains_globals() -> None:
    markup = load_markup_fixture("basic.json")
    excal = MarkupToExcalidrawConverter(GridLayoutEngine()).convert(markup)

    for element in excal.elements:
        meta = element.get("customData", {}).get("cjm", {})
        assert meta.get("schema_version") == "1.0"
        assert meta.get("finedog_unit_id") == markup.finedog_unit_id
        assert meta.get("markup_type") == markup.markup_type


def test_roundtrip_from_example_json_fixture() -> None:
    markup = load_markup_fixture("from_example_json.json")
    layout = GridLayoutEngine()
    forward = MarkupToExcalidrawConverter(layout)
    backward = ExcalidrawToMarkupConverter()

    excal = forward.convert(markup)
    reconstructed = backward.convert(excal.to_dict())

    assert normalize(reconstructed) == normalize(markup)
