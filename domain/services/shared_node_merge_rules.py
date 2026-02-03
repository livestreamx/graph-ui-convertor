from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from itertools import combinations


@dataclass(frozen=True)
class ServiceNodeState:
    service_key: str
    procedure_ids: frozenset[str]
    incoming_by_proc: Mapping[str, int]
    outgoing_by_proc: Mapping[str, int]

    def is_singleton(self, proc_id: str) -> bool:
        return len(self.procedure_ids) == 1 and proc_id in self.procedure_ids

    def is_start(self, proc_id: str) -> bool:
        return self.incoming_by_proc.get(proc_id, 0) == 0 and proc_id in self.procedure_ids

    def is_end(self, proc_id: str) -> bool:
        return self.outgoing_by_proc.get(proc_id, 0) == 0 and proc_id in self.procedure_ids


def build_service_node_state(
    service_key: str,
    procedure_ids: Iterable[str],
    adjacency: Mapping[str, Iterable[str]],
) -> ServiceNodeState:
    nodes = set(procedure_ids)
    incoming: dict[str, int] = defaultdict(int)
    outgoing: dict[str, int] = defaultdict(int)

    for source, raw_targets in adjacency.items():
        nodes.add(source)
        targets = list(raw_targets)
        outgoing[source] += len(targets)
        for target in targets:
            nodes.add(target)
            incoming[target] += 1

    for node in nodes:
        incoming.setdefault(node, 0)
        outgoing.setdefault(node, 0)

    return ServiceNodeState(
        service_key=service_key,
        procedure_ids=frozenset(nodes),
        incoming_by_proc=incoming,
        outgoing_by_proc=outgoing,
    )


def collect_pair_merge_nodes(
    states: Mapping[str, ServiceNodeState],
    *,
    merge_selected_markups: bool,
) -> dict[tuple[str, str], set[str]]:
    proc_to_services: dict[str, set[str]] = {}
    for service_key, state in states.items():
        for proc_id in state.procedure_ids:
            proc_to_services.setdefault(proc_id, set()).add(service_key)

    pair_nodes: dict[tuple[str, str], set[str]] = {}
    for proc_id, service_keys in proc_to_services.items():
        if len(service_keys) < 2:
            continue
        for left_key, right_key in combinations(sorted(service_keys), 2):
            left_state = states.get(left_key)
            right_state = states.get(right_key)
            if left_state is None or right_state is None:
                continue
            if not should_merge_shared_node(
                proc_id,
                left_state,
                right_state,
                merge_selected_markups=merge_selected_markups,
            ):
                continue
            pair = _pair_key(left_key, right_key)
            pair_nodes.setdefault(pair, set()).add(proc_id)
    return pair_nodes


def collect_merge_node_ids(
    states: Mapping[str, ServiceNodeState],
    *,
    merge_selected_markups: bool,
) -> set[str]:
    merge_nodes: set[str] = set()
    for nodes in collect_pair_merge_nodes(
        states,
        merge_selected_markups=merge_selected_markups,
    ).values():
        merge_nodes.update(nodes)
    return merge_nodes


def should_merge_shared_node(
    proc_id: str,
    left_state: ServiceNodeState,
    right_state: ServiceNodeState,
    *,
    merge_selected_markups: bool,
) -> bool:
    if merge_selected_markups:
        return True

    if left_state.is_singleton(proc_id) or right_state.is_singleton(proc_id):
        return True

    left_end_right_start = left_state.is_end(proc_id) and right_state.is_start(proc_id)
    right_end_left_start = right_state.is_end(proc_id) and left_state.is_start(proc_id)
    if left_end_right_start or right_end_left_start:
        return False

    return True


def _pair_key(left: str, right: str) -> tuple[str, str]:
    return (left, right) if left <= right else (right, left)
