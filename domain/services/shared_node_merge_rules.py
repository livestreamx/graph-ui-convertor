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
    incoming_sources_by_proc: Mapping[str, frozenset[str]]
    outgoing_targets_by_proc: Mapping[str, frozenset[str]]

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
    incoming_sources: dict[str, set[str]] = defaultdict(set)
    outgoing_targets: dict[str, set[str]] = defaultdict(set)

    for source, raw_targets in adjacency.items():
        nodes.add(source)
        targets = list(raw_targets)
        outgoing[source] += len(targets)
        outgoing_targets.setdefault(source, set()).update(targets)
        for target in targets:
            nodes.add(target)
            incoming[target] += 1
            incoming_sources.setdefault(target, set()).add(source)

    for node in nodes:
        incoming.setdefault(node, 0)
        outgoing.setdefault(node, 0)
        incoming_sources.setdefault(node, set())
        outgoing_targets.setdefault(node, set())

    return ServiceNodeState(
        service_key=service_key,
        procedure_ids=frozenset(nodes),
        incoming_by_proc=incoming,
        outgoing_by_proc=outgoing,
        incoming_sources_by_proc={
            proc_id: frozenset(sorted(sources)) for proc_id, sources in incoming_sources.items()
        },
        outgoing_targets_by_proc={
            proc_id: frozenset(sorted(targets)) for proc_id, targets in outgoing_targets.items()
        },
    )


def collect_pair_merge_nodes(
    states: Mapping[str, ServiceNodeState],
    *,
    merge_selected_markups: bool,
    merge_node_min_chain_size: int = 1,
) -> dict[tuple[str, str], set[str]]:
    pair_chunks = collect_pair_merge_node_chunks(
        states,
        merge_selected_markups=merge_selected_markups,
        merge_node_min_chain_size=merge_node_min_chain_size,
    )
    pair_nodes: dict[tuple[str, str], set[str]] = {}
    for pair, chunks in pair_chunks.items():
        representatives = {chunk[0] for chunk in chunks if chunk}
        if representatives:
            pair_nodes[pair] = representatives
    return pair_nodes


def collect_pair_merge_node_chunks(
    states: Mapping[str, ServiceNodeState],
    *,
    merge_selected_markups: bool,
    merge_node_min_chain_size: int = 1,
) -> dict[tuple[str, str], list[tuple[str, ...]]]:
    if merge_node_min_chain_size <= 0:
        return {}

    pair_candidates = _collect_pair_candidates(
        states,
        merge_selected_markups=merge_selected_markups,
    )
    pair_chunks: dict[tuple[str, str], list[tuple[str, ...]]] = {}
    for pair, proc_ids in pair_candidates.items():
        left_state = states.get(pair[0])
        right_state = states.get(pair[1])
        if left_state is None or right_state is None:
            continue
        chunks = _collect_chain_merge_chunks(
            proc_ids,
            left_state,
            right_state,
            merge_node_min_chain_size=merge_node_min_chain_size,
        )
        if chunks:
            pair_chunks[pair] = chunks
    return pair_chunks


def collect_merge_node_ids(
    states: Mapping[str, ServiceNodeState],
    *,
    merge_selected_markups: bool,
    merge_node_min_chain_size: int = 1,
) -> set[str]:
    if merge_node_min_chain_size <= 0:
        return set()

    merge_nodes: set[str] = set()
    for chunks in collect_pair_merge_node_chunks(
        states,
        merge_selected_markups=merge_selected_markups,
        merge_node_min_chain_size=merge_node_min_chain_size,
    ).values():
        for chunk in chunks:
            merge_nodes.update(chunk)
    return merge_nodes


def _collect_pair_candidates(
    states: Mapping[str, ServiceNodeState],
    *,
    merge_selected_markups: bool,
) -> dict[tuple[str, str], set[str]]:
    proc_to_services: dict[str, set[str]] = {}
    for service_key, state in states.items():
        for proc_id in state.procedure_ids:
            proc_to_services.setdefault(proc_id, set()).add(service_key)

    pair_candidates: dict[tuple[str, str], set[str]] = {}
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
            pair_candidates.setdefault(pair, set()).add(proc_id)
    return pair_candidates


def should_merge_shared_node(
    proc_id: str,
    left_state: ServiceNodeState,
    right_state: ServiceNodeState,
    *,
    merge_selected_markups: bool,
) -> bool:
    _ = (proc_id, left_state, right_state, merge_selected_markups)
    return True


def _pair_key(left: str, right: str) -> tuple[str, str]:
    return (left, right) if left <= right else (right, left)


def _collect_chain_merge_nodes(
    proc_ids: set[str],
    left_state: ServiceNodeState,
    right_state: ServiceNodeState,
    *,
    merge_node_min_chain_size: int,
) -> set[str]:
    chunks = _collect_chain_merge_chunks(
        proc_ids,
        left_state,
        right_state,
        merge_node_min_chain_size=merge_node_min_chain_size,
    )
    return {chunk[0] for chunk in chunks if chunk}


def _collect_chain_merge_chunks(
    proc_ids: set[str],
    left_state: ServiceNodeState,
    right_state: ServiceNodeState,
    *,
    merge_node_min_chain_size: int,
) -> list[tuple[str, ...]]:
    if merge_node_min_chain_size <= 1:
        return [(proc_id,) for proc_id in sorted(proc_ids, key=str.lower)]

    shared_proc_ids = set(proc_ids)
    if len(shared_proc_ids) < merge_node_min_chain_size:
        return []

    common_forward, common_backward = _shared_edges(
        shared_proc_ids,
        left_state,
        right_state,
    )
    cyclic_nodes = _cycle_nodes(shared_proc_ids, common_forward)
    acyclic_nodes = shared_proc_ids - cyclic_nodes
    if len(acyclic_nodes) < merge_node_min_chain_size:
        return []

    acyclic_forward: dict[str, set[str]] = {proc_id: set() for proc_id in acyclic_nodes}
    acyclic_backward: dict[str, set[str]] = {proc_id: set() for proc_id in acyclic_nodes}
    for source in acyclic_nodes:
        for target in common_forward.get(source, set()):
            if target not in acyclic_nodes:
                continue
            acyclic_forward[source].add(target)
            acyclic_backward[target].add(source)

    # Strictly linear chains only: branching/merge nodes act as chain boundaries.
    linear_nodes = {
        proc_id
        for proc_id in acyclic_nodes
        if len(acyclic_backward.get(proc_id, set())) <= 1
        and len(acyclic_forward.get(proc_id, set())) <= 1
    }
    if len(linear_nodes) < merge_node_min_chain_size:
        return []

    linear_forward: dict[str, set[str]] = {proc_id: set() for proc_id in linear_nodes}
    linear_backward: dict[str, set[str]] = {proc_id: set() for proc_id in linear_nodes}
    for source in linear_nodes:
        for target in acyclic_forward.get(source, set()):
            if target not in linear_nodes:
                continue
            linear_forward[source].add(target)
            linear_backward[target].add(source)

    chain_runs = _linear_runs(linear_nodes, linear_forward, linear_backward)
    selected_chunks: list[tuple[str, ...]] = []
    for run in chain_runs:
        if len(run) < merge_node_min_chain_size:
            continue
        for offset in range(0, len(run), merge_node_min_chain_size):
            chunk = run[offset : offset + merge_node_min_chain_size]
            if len(chunk) < merge_node_min_chain_size:
                break
            selected_chunks.append(tuple(chunk))
    return selected_chunks


def _shared_edges(
    proc_ids: set[str],
    left_state: ServiceNodeState,
    right_state: ServiceNodeState,
) -> tuple[dict[str, set[str]], dict[str, set[str]]]:
    common_forward: dict[str, set[str]] = {proc_id: set() for proc_id in proc_ids}
    common_backward: dict[str, set[str]] = {proc_id: set() for proc_id in proc_ids}
    for proc_id in proc_ids:
        left_targets = left_state.outgoing_targets_by_proc.get(proc_id, frozenset())
        right_targets = right_state.outgoing_targets_by_proc.get(proc_id, frozenset())
        shared_targets = (set(left_targets) & set(right_targets)) & proc_ids
        for target in shared_targets:
            common_forward[proc_id].add(target)
            common_backward[target].add(proc_id)
    return common_forward, common_backward


def _cycle_nodes(
    proc_ids: set[str],
    forward_edges: Mapping[str, set[str]],
) -> set[str]:
    index = 0
    indices: dict[str, int] = {}
    lowlink: dict[str, int] = {}
    stack: list[str] = []
    on_stack: set[str] = set()
    cycle_nodes: set[str] = set()

    def strongconnect(node_id: str) -> None:
        nonlocal index
        indices[node_id] = index
        lowlink[node_id] = index
        index += 1
        stack.append(node_id)
        on_stack.add(node_id)

        for target in sorted(forward_edges.get(node_id, set()), key=str.lower):
            if target not in indices:
                strongconnect(target)
                lowlink[node_id] = min(lowlink[node_id], lowlink[target])
            elif target in on_stack:
                lowlink[node_id] = min(lowlink[node_id], indices[target])

        if lowlink[node_id] != indices[node_id]:
            return

        component: list[str] = []
        while stack:
            member = stack.pop()
            on_stack.discard(member)
            component.append(member)
            if member == node_id:
                break
        if len(component) > 1:
            cycle_nodes.update(component)
            return
        if component:
            member = component[0]
            if member in forward_edges.get(member, set()):
                cycle_nodes.add(member)

    for node_id in sorted(proc_ids, key=str.lower):
        if node_id in indices:
            continue
        strongconnect(node_id)
    return cycle_nodes


def _linear_runs(
    proc_ids: set[str],
    forward_edges: Mapping[str, set[str]],
    backward_edges: Mapping[str, set[str]],
) -> list[list[str]]:
    if not proc_ids:
        return []

    starts = sorted(
        (proc_id for proc_id in proc_ids if len(backward_edges.get(proc_id, set())) == 0),
        key=str.lower,
    )
    visited: set[str] = set()
    runs: list[list[str]] = []
    for start_id in starts:
        if start_id in visited:
            continue
        run: list[str] = []
        current = start_id
        while current not in visited:
            visited.add(current)
            run.append(current)
            next_ids = sorted(forward_edges.get(current, set()), key=str.lower)
            if len(next_ids) != 1:
                break
            next_id = next_ids[0]
            if next_id in visited:
                break
            current = next_id
        if run:
            runs.append(run)

    for node_id in sorted(proc_ids - visited, key=str.lower):
        tail_run: list[str] = []
        current = node_id
        while current not in visited:
            visited.add(current)
            tail_run.append(current)
            next_ids = sorted(forward_edges.get(current, set()), key=str.lower)
            if len(next_ids) != 1:
                break
            next_id = next_ids[0]
            if next_id in visited:
                break
            current = next_id
        if tail_run:
            runs.append(tail_run)
    return runs
