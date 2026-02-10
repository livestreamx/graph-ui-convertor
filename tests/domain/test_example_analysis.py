from __future__ import annotations

from collections import Counter
from typing import Any

import pytest

from adapters.layout.grid import GridLayoutEngine
from domain.services.convert_markup_to_excalidraw import MarkupToExcalidrawConverter
from tests.helpers.markup_fixtures import load_expected_fixture, load_markup_fixture


def _meta(element: dict[str, Any]) -> dict[str, Any]:
    custom_data = element.get("customData")
    if not isinstance(custom_data, dict):
        return {}
    cjm = custom_data.get("cjm")
    if not isinstance(cjm, dict):
        return {}
    return cjm


@pytest.mark.parametrize(
    "name", ["basic.json", "complex_graph.json", "graphs_set.json", "forest.json"]
)
def test_example_rendering_matches_expected_counts(name: str) -> None:
    markup = load_markup_fixture(name)
    expected = load_expected_fixture(name)

    excal = MarkupToExcalidrawConverter(GridLayoutEngine()).convert(markup)

    frames = [e for e in excal.elements if _meta(e).get("role") == "frame"]
    blocks = [e for e in excal.elements if _meta(e).get("role") == "block"]
    start_marker_keys = {
        (_meta(e).get("procedure_id"), _meta(e).get("block_id"), _meta(e).get("end_type"))
        for e in excal.elements
        if _meta(e).get("role") == "start_marker"
    }
    end_marker_keys = {
        (_meta(e).get("procedure_id"), _meta(e).get("block_id"), _meta(e).get("end_type"))
        for e in excal.elements
        if _meta(e).get("role") == "end_marker"
    }

    counts = expected.get("counts", {})
    assert len(frames) == counts.get("procedures")
    assert len(blocks) == counts.get("blocks")
    assert len(start_marker_keys) == counts.get("starts")
    assert len(end_marker_keys) == counts.get("ends")

    edge_counts: Counter[str] = Counter()
    for element in excal.elements:
        if element.get("type") != "arrow":
            continue
        edge_type = _meta(element).get("edge_type")
        if isinstance(edge_type, str):
            edge_counts[edge_type] += 1

    expected_edges = expected.get("edges", {})
    for edge_type, expected_count in expected_edges.items():
        assert edge_counts.get(edge_type, 0) == expected_count

    proc_graph_expected = expected.get("procedure_graph")
    if isinstance(proc_graph_expected, dict):
        proc_edge_count = sum(len(values) for values in markup.procedure_graph.values())
        if markup.block_graph:
            layout_engine = GridLayoutEngine()
            block_graph_nodes = layout_engine._block_graph_nodes(markup)
            owned_blocks_by_proc = layout_engine._resolve_owned_blocks(markup, block_graph_nodes)
            procedures = [
                proc for proc in markup.procedures if owned_blocks_by_proc.get(proc.procedure_id)
            ]
            inferred = layout_engine._infer_procedure_graph_from_block_graph(
                markup.block_graph, procedures, owned_blocks_by_proc
            )
            merged: dict[str, list[str]] = {proc.procedure_id: [] for proc in procedures}
            for graph in (markup.procedure_graph, inferred):
                for parent, children in graph.items():
                    if parent not in merged:
                        continue
                    for child in children:
                        if child in merged and child != parent and child not in merged[parent]:
                            merged[parent].append(child)
            proc_edge_count = sum(len(values) for values in merged.values())
        assert proc_edge_count == proc_graph_expected.get("edges")

    block_graph_expected = expected.get("block_graph", {})
    block_graph_edges = [
        element
        for element in excal.elements
        if element.get("type") == "arrow"
        and _meta(element).get("edge_type") in {"block_graph", "block_graph_cycle"}
    ]
    cycle_edges = [
        element
        for element in block_graph_edges
        if _meta(element).get("edge_type") == "block_graph_cycle"
    ]
    cross_proc_edges = [
        element
        for element in block_graph_edges
        if _meta(element).get("procedure_id") != _meta(element).get("target_procedure_id")
    ]

    assert len(block_graph_edges) == block_graph_expected.get("edges")
    assert len(cycle_edges) == block_graph_expected.get("cycle_edges")
    assert len(cross_proc_edges) == block_graph_expected.get("cross_procedure_edges")

    expected_cycle_pairs = {
        (pair[0], pair[1])
        for pair in block_graph_expected.get("cycle_pairs", [])
        if isinstance(pair, list) and len(pair) == 2
    }
    actual_cycle_pairs = {
        (
            _meta(element).get("source_block_id"),
            _meta(element).get("target_block_id"),
        )
        for element in cycle_edges
    }
    assert actual_cycle_pairs == expected_cycle_pairs

    end_type_counts: Counter[str] = Counter()
    for _proc_id, _block_id, end_type in end_marker_keys:
        normalized = end_type if isinstance(end_type, str) else "end"
        end_type_counts[normalized] += 1

    expected_end_types = expected.get("end_types", {})
    for end_type, expected_count in expected_end_types.items():
        assert end_type_counts.get(end_type, 0) == expected_count


def test_examples_share_blocks_for_cross_team_merge() -> None:
    basic = load_markup_fixture("basic.json")
    graphs_set = load_markup_fixture("graphs_set.json")

    basic_pairs = {
        (proc.procedure_id, block_id) for proc in basic.procedures for block_id in proc.block_ids()
    }
    graphs_pairs = {
        (proc.procedure_id, block_id)
        for proc in graphs_set.procedures
        for block_id in proc.block_ids()
    }
    overlap = basic_pairs & graphs_pairs

    expected_overlap = {
        ("proc_shared_intake", "intake_start"),
        ("proc_shared_intake", "intake_collect"),
        ("proc_shared_routing", "route_review"),
        ("proc_shared_routing", "route_recheck"),
    }
    assert expected_overlap.issubset(overlap)

    assert basic.team_id is not None
    assert basic.team_name
    assert graphs_set.team_id is not None
    assert graphs_set.team_name
    assert basic.team_id != graphs_set.team_id


@pytest.mark.parametrize(
    ("name", "expected_bot_share", "expected_multi_share"),
    [
        ("basic.json", 0.0, 0.0),
        ("complex_graph.json", 0.0, 0.0),
        ("forest.json", 0.0, 0.0),
        ("graphs_set.json", 1 / 10, 1 / 10),
    ],
)
def test_examples_bot_multi_procedure_shares(
    name: str, expected_bot_share: float, expected_multi_share: float
) -> None:
    markup = load_markup_fixture(name)
    total = len(markup.procedures)
    assert total > 0

    bot_count = sum(1 for proc in markup.procedures if "bot" in proc.procedure_id.lower())
    multi_count = sum(1 for proc in markup.procedures if "multi" in proc.procedure_id.lower())

    assert bot_count / total == expected_bot_share
    assert multi_count / total == expected_multi_share
