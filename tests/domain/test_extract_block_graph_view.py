from __future__ import annotations

from adapters.layout.grid import GridLayoutEngine
from domain.models import MarkupDocument
from domain.services.convert_markup_to_excalidraw import MarkupToExcalidrawConverter
from domain.services.extract_block_graph_view import extract_block_graph_view


def test_extract_block_graph_view_uses_block_graph_edges_only() -> None:
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
    scene_payload = MarkupToExcalidrawConverter(GridLayoutEngine()).convert(markup).to_dict()

    graph_payload = extract_block_graph_view(scene_payload)

    edges = graph_payload["edges"]
    assert len(edges) == 1
    edge = edges[0]
    assert edge["edge_type"] == "block_graph"
    assert edge["source"] == "p1::a_end"
    assert edge["target"] == "p2::b_start"
    assert graph_payload["meta"]["node_count"] >= 4
    assert graph_payload["meta"]["edge_count"] == 1


def test_extract_block_graph_view_uses_branch_edges_when_block_graph_is_absent() -> None:
    payload = {
        "markup_type": "service",
        "procedures": [
            {
                "proc_id": "p1",
                "start_block_ids": ["a"],
                "end_block_ids": ["c::end"],
                "branches": {"a": ["b"], "b": ["c"]},
            }
        ],
    }
    markup = MarkupDocument.model_validate(payload)
    scene_payload = MarkupToExcalidrawConverter(GridLayoutEngine()).convert(markup).to_dict()

    graph_payload = extract_block_graph_view(scene_payload)

    edge_types = {edge["edge_type"] for edge in graph_payload["edges"]}
    assert edge_types == {"branch"}
    assert graph_payload["meta"]["node_count"] == 3
    assert graph_payload["meta"]["edge_count"] == 2
