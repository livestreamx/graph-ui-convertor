from __future__ import annotations

import json
from pathlib import Path

from domain.models import MarkupDocument
from domain.services.graph_metrics import compute_graph_metrics


def _repo_root() -> Path:
    for parent in Path(__file__).resolve().parents:
        if (parent / "pyproject.toml").exists():
            return parent
    raise RuntimeError("Repository root not found")


def test_basic_block_graph_metrics() -> None:
    payload = json.loads(
        (_repo_root() / "examples" / "markup" / "basic.json").read_text(encoding="utf-8")
    )
    document = MarkupDocument.model_validate(payload)
    metrics = compute_graph_metrics(document.block_graph)

    assert metrics.directed is True
    assert metrics.is_acyclic is False
    assert metrics.weakly_connected is True
    assert metrics.vertices == 14
    assert metrics.edges == 15
    assert metrics.sources == {"intake_start"}
    assert metrics.sinks == {"final_end"}
    expected_branch_nodes = {"route_recheck", "route_branch"}
    assert metrics.branch_nodes == expected_branch_nodes, "out_degree=" f"{metrics.out_degree}"
    branching_count = len(metrics.branch_nodes)
    assert branching_count == 2, (
        "branch_nodes=" f"{sorted(metrics.branch_nodes)} out_degree={metrics.out_degree}"
    )
    assert len(metrics.merge_nodes) == 2
    assert metrics.cycle_path is not None
    assert {"route_review", "route_recheck"}.issubset(set(metrics.cycle_path))
    assert metrics.cycle_count == 1


def test_complex_graph_cycle_count() -> None:
    payload = json.loads(
        (_repo_root() / "examples" / "markup" / "complex_graph.json").read_text(encoding="utf-8")
    )
    document = MarkupDocument.model_validate(payload)
    metrics = compute_graph_metrics(document.block_graph)

    assert metrics.is_acyclic is False
    assert metrics.cycle_count == 2
