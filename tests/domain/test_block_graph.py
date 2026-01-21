from __future__ import annotations

from adapters.layout.grid import GridLayoutEngine
from domain.models import MarkupDocument
from domain.services.convert_excalidraw_to_markup import ExcalidrawToMarkupConverter
from domain.services.convert_markup_to_excalidraw import MarkupToExcalidrawConverter


def test_block_graph_edges_render_between_blocks() -> None:
    payload = {
        "markup_type": "service",
        "procedures": [
            {
                "proc_id": "p1",
                "start_block_ids": ["a_start"],
                "end_block_ids": ["a_end::end"],
                "branches": {"a_start": ["a_end"]},
            },
            {
                "proc_id": "p2",
                "start_block_ids": ["b_start"],
                "end_block_ids": ["b_end::end"],
                "branches": {"b_start": ["b_end"]},
            },
        ],
        "procedure_graph": {"p1": ["p2"], "p2": []},
        "block_graph": {"a_end": ["b_start"]},
    }
    markup = MarkupDocument.model_validate(payload)
    excal = MarkupToExcalidrawConverter(GridLayoutEngine()).convert(markup)

    block_edges = [
        element
        for element in excal.elements
        if element.get("type") == "arrow"
        and element.get("customData", {}).get("cjm", {}).get("edge_type")
        in {"block_graph", "block_graph_cycle"}
    ]
    procedure_edges = [
        element
        for element in excal.elements
        if element.get("type") == "arrow"
        and element.get("customData", {}).get("cjm", {}).get("edge_type")
        in {"procedure_flow", "procedure_cycle"}
    ]
    assert block_edges
    assert not procedure_edges
    meta = block_edges[0].get("customData", {}).get("cjm", {})
    assert meta.get("source_block_id") == "a_end"
    assert meta.get("target_block_id") == "b_start"

    reconstructed = ExcalidrawToMarkupConverter().convert(excal.to_dict())
    assert reconstructed.block_graph.get("a_end") == ["b_start"]
    assert "b_start" in reconstructed.block_graph
    assert reconstructed.procedure_graph.get("p1") == ["p2"]
