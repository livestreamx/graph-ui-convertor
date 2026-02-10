from __future__ import annotations

from domain.services.graph_metrics import compute_graph_metrics
from tests.helpers.markup_fixtures import load_markup_fixture


def test_basic_block_graph_metrics() -> None:
    document = load_markup_fixture("basic.json")
    metrics = compute_graph_metrics(document.block_graph)

    assert metrics.directed is True
    assert metrics.is_acyclic is False
    assert metrics.weakly_connected is True
    assert metrics.vertices == 19
    assert metrics.edges == 21
    assert metrics.sources == {"intake_start"}
    assert metrics.sinks == {"final_end"}
    expected_branch_nodes = {"handoff_check", "route_recheck", "route_branch"}
    assert metrics.branch_nodes == expected_branch_nodes, "out_degree=" f"{metrics.out_degree}"
    branching_count = len(metrics.branch_nodes)
    assert branching_count == 3, (
        "branch_nodes=" f"{sorted(metrics.branch_nodes)} out_degree={metrics.out_degree}"
    )
    assert len(metrics.merge_nodes) == 3
    assert metrics.cycle_path is not None
    assert {"route_review", "route_recheck"}.issubset(set(metrics.cycle_path))
    assert metrics.cycle_count == 1


def test_complex_graph_cycle_count() -> None:
    document = load_markup_fixture("complex_graph.json")
    metrics = compute_graph_metrics(document.block_graph)

    assert metrics.is_acyclic is False
    assert metrics.cycle_count == 2
