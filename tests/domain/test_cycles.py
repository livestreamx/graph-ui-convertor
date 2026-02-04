from __future__ import annotations

import json
from itertools import pairwise
from pathlib import Path
from typing import Any

import pytest

from adapters.layout.grid import GridLayoutEngine
from domain.models import MarkupDocument
from domain.services.convert_excalidraw_to_markup import ExcalidrawToMarkupConverter
from domain.services.convert_markup_to_excalidraw import MarkupToExcalidrawConverter


def _repo_root() -> Path:
    for parent in Path(__file__).resolve().parents:
        if (parent / "examples" / "markup").exists():
            return parent
    raise RuntimeError("Repository root not found")


def _arrow_endpoint(arrow: dict[str, Any], index: int) -> tuple[float, float]:
    points = arrow.get("points", [])
    return (
        arrow.get("x", 0.0) + points[index][0],
        arrow.get("y", 0.0) + points[index][1],
    )


def _is_orthogonal(points: list[list[float]]) -> bool:
    if len(points) < 2:
        return False
    for (x1, y1), (x2, y2) in pairwise(points):
        if x1 != x2 and y1 != y2:
            return False
    return True


def test_branch_cycle_edges_are_marked_and_roundtrip() -> None:
    payload = {
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
    branch_edges = [
        element
        for element in excal.elements
        if element.get("type") == "arrow"
        and element.get("customData", {}).get("cjm", {}).get("edge_type") == "branch"
    ]
    blocks = {
        element.get("customData", {}).get("cjm", {}).get("block_id"): element
        for element in excal.elements
        if element.get("type") == "rectangle"
        and element.get("customData", {}).get("cjm", {}).get("role") == "block"
    }
    assert cycle_edges
    assert not branch_edges
    assert all(edge.get("text") == "ЦИКЛ" for edge in cycle_edges)
    assert all(edge.get("strokeColor") == "#d32f2f" for edge in cycle_edges)
    assert all(edge.get("strokeStyle") == "dashed" for edge in cycle_edges)
    assert all(edge.get("strokeWidth") == 1 for edge in cycle_edges)
    assert all(len(edge.get("points", [])) > 2 for edge in cycle_edges)
    assert all(edge.get("endArrowhead") == "arrow" for edge in cycle_edges)
    assert all(edge.get("startArrowhead") is None for edge in cycle_edges)
    assert all(_is_orthogonal(edge.get("points", [])) for edge in cycle_edges)
    for edge in cycle_edges:
        meta = edge.get("customData", {}).get("cjm", {})
        source = blocks.get(meta.get("source_block_id"))
        target = blocks.get(meta.get("target_block_id"))
        assert source and target
        start = _arrow_endpoint(edge, 0)
        end = _arrow_endpoint(edge, -1)
        assert start[0] == pytest.approx(source.get("x", 0.0) + source.get("width", 0.0) / 2)
        assert start[1] == pytest.approx(source.get("y", 0.0))
        assert end[0] == pytest.approx(target.get("x", 0.0) + target.get("width", 0.0) / 2)
        assert end[1] == pytest.approx(target.get("y", 0.0))

    reconstructed = ExcalidrawToMarkupConverter().convert(excal.to_dict())
    proc = reconstructed.procedures[0]
    branches = {key: sorted(values) for key, values in proc.branches.items()}
    assert branches == {"a": ["b"], "b": ["a"]}


def test_procedure_cycle_edges_are_marked_and_roundtrip() -> None:
    payload = {
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
    flow_edges = [
        element
        for element in excal.elements
        if element.get("type") == "arrow"
        and element.get("customData", {}).get("cjm", {}).get("edge_type") == "procedure_flow"
    ]
    frames = {
        element.get("customData", {}).get("cjm", {}).get("procedure_id"): element
        for element in excal.elements
        if element.get("type") == "frame"
        and element.get("customData", {}).get("cjm", {}).get("role") == "frame"
    }
    assert cycle_edges
    assert flow_edges
    assert len(cycle_edges) == 1
    assert len(flow_edges) == 1
    assert all(edge.get("strokeStyle") != "dashed" for edge in flow_edges)
    assert all(edge.get("text") == "ЦИКЛ" for edge in cycle_edges)
    assert all(edge.get("strokeColor") == "#d32f2f" for edge in cycle_edges)
    assert all(edge.get("strokeStyle") == "dashed" for edge in cycle_edges)
    assert all(edge.get("strokeWidth") == 2 for edge in cycle_edges)
    assert all(len(edge.get("points", [])) > 2 for edge in cycle_edges)
    assert all(edge.get("endArrowhead") == "arrow" for edge in cycle_edges)
    assert all(edge.get("startArrowhead") is None for edge in cycle_edges)
    for edge in cycle_edges:
        meta = edge.get("customData", {}).get("cjm", {})
        source = frames.get(meta.get("procedure_id"))
        target = frames.get(meta.get("target_procedure_id"))
        assert source and target
        start = _arrow_endpoint(edge, 0)
        end = _arrow_endpoint(edge, -1)
        source_x = source.get("x", 0.0)
        target_x = target.get("x", 0.0)
        assert source_x > target_x
        assert start[0] == pytest.approx(source_x + source.get("width", 0.0) / 2)
        assert start[1] == pytest.approx(source.get("y", 0.0) + source.get("height", 0.0))
        assert end[0] == pytest.approx(target_x)
        assert end[1] == pytest.approx(target.get("y", 0.0) + target.get("height", 0.0) / 2)

    reconstructed = ExcalidrawToMarkupConverter().convert(excal.to_dict())
    graph = reconstructed.procedure_graph
    assert set(graph.get("p1", [])) == {"p2"}
    assert set(graph.get("p2", [])) == {"p1"}


def test_example_procedure_graph_contains_cycle() -> None:
    example_path = _repo_root() / "examples" / "markup" / "complex_graph.json"
    payload = json.loads(example_path.read_text(encoding="utf-8"))
    graph = payload.get("procedure_graph", {})
    assert graph.get("proc_alpha") == ["proc_beta"]
    assert graph.get("proc_beta") == ["proc_gamma", "proc_delta"]
    assert graph.get("proc_gamma") == ["proc_delta", "proc_alpha"]
    assert graph.get("proc_delta") == ["proc_epsilon"]
    assert graph.get("proc_epsilon") == ["proc_zeta", "proc_c"]
    assert graph.get("proc_zeta") == []
    assert graph.get("proc_c") == []
