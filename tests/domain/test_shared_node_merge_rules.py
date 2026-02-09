from __future__ import annotations

from domain.services.shared_node_merge_rules import (
    ServiceNodeState,
    build_service_node_state,
    collect_merge_node_ids,
    collect_pair_merge_nodes,
)


def _state(service_key: str, adjacency: dict[str, list[str]]) -> ServiceNodeState:
    proc_ids = set(adjacency.keys())
    for targets in adjacency.values():
        proc_ids.update(targets)
    return build_service_node_state(service_key, proc_ids, adjacency)


def test_collect_pair_merge_nodes_uses_all_shared_nodes_by_default() -> None:
    states = {
        "left": _state(
            "left",
            {
                "shared_a": ["shared_b"],
                "shared_b": ["shared_c"],
                "shared_c": ["shared_d"],
                "shared_d": [],
                "left_only": [],
            },
        ),
        "right": _state(
            "right",
            {
                "shared_a": ["shared_b"],
                "shared_b": ["shared_c"],
                "shared_c": ["shared_d"],
                "shared_d": [],
                "right_only": [],
            },
        ),
    }

    pair_nodes = collect_pair_merge_nodes(
        states,
        merge_selected_markups=True,
        merge_node_min_chain_size=1,
    )

    assert pair_nodes[("left", "right")] == {"shared_a", "shared_b", "shared_c", "shared_d"}
    assert collect_merge_node_ids(
        states,
        merge_selected_markups=True,
        merge_node_min_chain_size=1,
    ) == {"shared_a", "shared_b", "shared_c", "shared_d"}


def test_collect_pair_merge_nodes_returns_non_overlapping_chain_representatives() -> None:
    states = {
        "left": _state(
            "left",
            {
                "shared_a": ["shared_b"],
                "shared_b": ["shared_c"],
                "shared_c": ["shared_d"],
                "shared_d": [],
            },
        ),
        "right": _state(
            "right",
            {
                "shared_a": ["shared_b"],
                "shared_b": ["shared_c"],
                "shared_c": ["shared_d"],
                "shared_d": [],
            },
        ),
    }

    pair_nodes = collect_pair_merge_nodes(
        states,
        merge_selected_markups=True,
        merge_node_min_chain_size=2,
    )
    assert pair_nodes[("left", "right")] == {"shared_a", "shared_c"}
    assert collect_merge_node_ids(
        states,
        merge_selected_markups=True,
        merge_node_min_chain_size=2,
    ) == {"shared_a", "shared_c"}


def test_collect_pair_merge_nodes_disables_merge_nodes_when_threshold_is_zero() -> None:
    states = {
        "left": _state("left", {"shared": []}),
        "right": _state("right", {"shared": []}),
    }

    assert (
        collect_pair_merge_nodes(
            states,
            merge_selected_markups=True,
            merge_node_min_chain_size=0,
        )
        == {}
    )
    assert (
        collect_merge_node_ids(
            states,
            merge_selected_markups=True,
            merge_node_min_chain_size=0,
        )
        == set()
    )


def test_collect_pair_merge_nodes_ignores_singletons_when_threshold_requires_chain() -> None:
    states = {
        "left": _state("left", {"shared": [], "left_only": []}),
        "right": _state("right", {"shared": [], "right_only": []}),
    }

    assert (
        collect_pair_merge_nodes(
            states,
            merge_selected_markups=True,
            merge_node_min_chain_size=2,
        )
        == {}
    )


def test_collect_pair_merge_nodes_ignores_cycles_for_chain_thresholds() -> None:
    states = {
        "left": _state(
            "left",
            {
                "cycle_a": ["cycle_b"],
                "cycle_b": ["cycle_c"],
                "cycle_c": ["cycle_a"],
                "linear_x": ["linear_y"],
                "linear_y": ["linear_z"],
                "linear_z": [],
            },
        ),
        "right": _state(
            "right",
            {
                "cycle_a": ["cycle_b"],
                "cycle_b": ["cycle_c"],
                "cycle_c": ["cycle_a"],
                "linear_x": ["linear_y"],
                "linear_y": ["linear_z"],
                "linear_z": [],
            },
        ),
    }

    pair_nodes = collect_pair_merge_nodes(
        states,
        merge_selected_markups=True,
        merge_node_min_chain_size=2,
    )
    assert pair_nodes[("left", "right")] == {"linear_x"}


def test_collect_pair_merge_nodes_treats_branch_nodes_as_chain_boundaries() -> None:
    states = {
        "left": _state(
            "left",
            {
                "entry": ["fork"],
                "fork": ["left_1", "right_1"],
                "left_1": ["left_2"],
                "left_2": [],
                "right_1": ["right_2"],
                "right_2": [],
            },
        ),
        "right": _state(
            "right",
            {
                "entry": ["fork"],
                "fork": ["left_1", "right_1"],
                "left_1": ["left_2"],
                "left_2": [],
                "right_1": ["right_2"],
                "right_2": [],
            },
        ),
    }

    pair_nodes = collect_pair_merge_nodes(
        states,
        merge_selected_markups=True,
        merge_node_min_chain_size=2,
    )
    assert pair_nodes[("left", "right")] == {"left_1", "right_1"}
