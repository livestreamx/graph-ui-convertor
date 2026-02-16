from __future__ import annotations

from domain.services.block_graph_resolution import resolve_block_graph_edges


def test_resolve_block_graph_edges_keeps_local_edges_for_duplicate_source_block_id() -> None:
    block_graph = {"shared": ["target_beta", "target_epsilon"]}
    owners_by_block = {
        "shared": {"proc_beta", "proc_epsilon"},
        "target_beta": {"proc_beta"},
        "target_epsilon": {"proc_epsilon"},
    }
    procedure_graph = {
        "proc_beta": ["proc_gamma"],
        "proc_epsilon": ["proc_zeta"],
    }

    resolved = resolve_block_graph_edges(block_graph, owners_by_block, procedure_graph)
    resolved_pairs = {
        (
            edge.source_procedure_id,
            edge.source_block_id,
            edge.target_procedure_id,
            edge.target_block_id,
        )
        for edge in resolved
    }

    assert resolved_pairs == {
        ("proc_beta", "shared", "proc_beta", "target_beta"),
        ("proc_epsilon", "shared", "proc_epsilon", "target_epsilon"),
    }


def test_resolve_block_graph_edges_prefers_direct_procedure_edges() -> None:
    block_graph = {"alpha_router": ["shared_target"]}
    owners_by_block = {
        "alpha_router": {"proc_alpha"},
        "shared_target": {"proc_beta", "proc_epsilon"},
    }
    procedure_graph = {
        "proc_alpha": ["proc_beta"],
        "proc_beta": [],
        "proc_epsilon": [],
    }

    resolved = resolve_block_graph_edges(block_graph, owners_by_block, procedure_graph)

    assert len(resolved) == 1
    edge = resolved[0]
    assert edge.source_procedure_id == "proc_alpha"
    assert edge.target_procedure_id == "proc_beta"
