from __future__ import annotations

from adapters.layout.grid import GridLayoutEngine
from domain.models import MarkupDocument
from domain.services.convert_excalidraw_to_markup import ExcalidrawToMarkupConverter
from domain.services.convert_markup_to_excalidraw import MarkupToExcalidrawConverter


def test_branch_cycle_edges_are_marked_and_roundtrip() -> None:
    payload = {
        "finedog_unit_id": 1,
        "markup_type": "service",
        "procedures": [
            {
                "proc_id": "p1",
                "start_block_ids": ["a"],
                "end_block_ids": ["b::end"],
                "branches": {"a": ["b"], "b": ["a"]},
            }
        ],
    }
    markup = MarkupDocument.model_validate(payload)
    excal = MarkupToExcalidrawConverter(GridLayoutEngine()).convert(markup)

    cycle_edges = [
        element
        for element in excal.elements
        if element.get("type") == "arrow"
        and element.get("customData", {}).get("cjm", {}).get("edge_type") == "branch_cycle"
    ]
    assert cycle_edges
    assert all(edge.get("text") == "ЦИКЛ" for edge in cycle_edges)
    assert all(edge.get("strokeColor") == "#d32f2f" for edge in cycle_edges)
    assert all(edge.get("strokeStyle") == "dashed" for edge in cycle_edges)
    assert all(len(edge.get("points", [])) > 2 for edge in cycle_edges)

    reconstructed = ExcalidrawToMarkupConverter().convert(excal.to_dict())
    proc = reconstructed.procedures[0]
    branches = {key: sorted(values) for key, values in proc.branches.items()}
    assert branches == {"a": ["b"], "b": ["a"]}


def test_procedure_cycle_edges_are_marked_and_roundtrip() -> None:
    payload = {
        "finedog_unit_id": 2,
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
        "procedure_graph": {"p1": ["p2"], "p2": ["p1"]},
    }
    markup = MarkupDocument.model_validate(payload)
    excal = MarkupToExcalidrawConverter(GridLayoutEngine()).convert(markup)

    cycle_edges = [
        element
        for element in excal.elements
        if element.get("type") == "arrow"
        and element.get("customData", {}).get("cjm", {}).get("edge_type") == "procedure_cycle"
    ]
    assert cycle_edges
    assert all(edge.get("text") == "ЦИКЛ" for edge in cycle_edges)
    assert all(edge.get("strokeColor") == "#d32f2f" for edge in cycle_edges)
    assert all(edge.get("strokeStyle") == "dashed" for edge in cycle_edges)
    assert all(len(edge.get("points", [])) > 2 for edge in cycle_edges)

    reconstructed = ExcalidrawToMarkupConverter().convert(excal.to_dict())
    graph = reconstructed.procedure_graph
    assert set(graph.get("p1", [])) == {"p2"}
    assert set(graph.get("p2", [])) == {"p1"}
