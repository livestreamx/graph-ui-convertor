from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass


@dataclass(frozen=True)
class GraphData:
    vertices: set[str]
    adjacency: dict[str, list[str]]


@dataclass(frozen=True)
class GraphMetrics:
    directed: bool
    vertices: int
    edges: int
    in_degree: dict[str, int]
    out_degree: dict[str, int]
    sources: set[str]
    sinks: set[str]
    branch_nodes: set[str]
    merge_nodes: set[str]
    is_acyclic: bool
    cycle_path: list[str] | None
    cycle_count: int
    weakly_connected: bool


def build_directed_graph(adjacency: Mapping[str, Iterable[str]]) -> GraphData:
    vertices: set[str] = set(adjacency.keys())
    for targets in adjacency.values():
        vertices.update(str(target) for target in targets)

    normalized: dict[str, list[str]] = {node: [] for node in vertices}
    for source, targets in adjacency.items():
        seen: set[str] = set()
        unique_targets: list[str] = []
        for target in targets:
            target_id = str(target)
            if target_id in seen:
                continue
            seen.add(target_id)
            unique_targets.append(target_id)
        normalized.setdefault(str(source), []).extend(unique_targets)

    return GraphData(vertices=vertices, adjacency=normalized)


def compute_graph_metrics(adjacency: Mapping[str, Iterable[str]]) -> GraphMetrics:
    graph = build_directed_graph(adjacency)
    in_degree = {node: 0 for node in graph.vertices}
    out_degree = {node: len(graph.adjacency.get(node, [])) for node in graph.vertices}
    for _source, targets in graph.adjacency.items():
        for target in targets:
            in_degree[target] = in_degree.get(target, 0) + 1

    sources = {node for node, deg in in_degree.items() if deg == 0}
    sinks = {node for node, deg in out_degree.items() if deg == 0}
    branch_nodes = {node for node, deg in out_degree.items() if deg > 1}
    merge_nodes = {node for node, deg in in_degree.items() if deg > 1}
    edges = sum(out_degree.values())
    cycle_path = _find_cycle_path(graph.adjacency)
    is_acyclic = cycle_path is None
    cycle_count = _count_cycles(graph.adjacency)
    weakly_connected = _is_weakly_connected(graph.vertices, graph.adjacency)

    return GraphMetrics(
        directed=True,
        vertices=len(graph.vertices),
        edges=edges,
        in_degree=in_degree,
        out_degree=out_degree,
        sources=sources,
        sinks=sinks,
        branch_nodes=branch_nodes,
        merge_nodes=merge_nodes,
        is_acyclic=is_acyclic,
        cycle_path=cycle_path,
        cycle_count=cycle_count,
        weakly_connected=weakly_connected,
    )


def _find_cycle_path(adjacency: Mapping[str, list[str]]) -> list[str] | None:
    color: dict[str, int] = {node: 0 for node in adjacency}
    stack: list[str] = []

    def dfs(node: str) -> list[str] | None:
        color[node] = 1
        stack.append(node)
        for neighbor in adjacency.get(node, []):
            if color.get(neighbor, 0) == 0:
                found = dfs(neighbor)
                if found:
                    return found
            elif color.get(neighbor) == 1:
                try:
                    idx = stack.index(neighbor)
                except ValueError:
                    idx = 0
                return stack[idx:] + [neighbor]
        stack.pop()
        color[node] = 2
        return None

    for node in adjacency:
        if color[node] == 0:
            cycle = dfs(node)
            if cycle:
                return cycle
    return None


def _count_cycles(adjacency: Mapping[str, list[str]]) -> int:
    nodes = set(adjacency.keys())
    for targets in adjacency.values():
        nodes.update(targets)
    if not nodes:
        return 0

    index = 0
    indices: dict[str, int] = {}
    lowlinks: dict[str, int] = {}
    stack: list[str] = []
    on_stack: set[str] = set()
    components: list[list[str]] = []

    def strongconnect(node: str) -> None:
        nonlocal index
        indices[node] = index
        lowlinks[node] = index
        index += 1
        stack.append(node)
        on_stack.add(node)

        for child in adjacency.get(node, []):
            if child not in indices:
                strongconnect(child)
                lowlinks[node] = min(lowlinks[node], lowlinks[child])
            elif child in on_stack:
                lowlinks[node] = min(lowlinks[node], indices[child])

        if lowlinks[node] == indices[node]:
            component: list[str] = []
            while True:
                current = stack.pop()
                on_stack.remove(current)
                component.append(current)
                if current == node:
                    break
            components.append(component)

    for node in nodes:
        if node not in indices:
            strongconnect(node)

    cycle_count = 0
    for component in components:
        if len(component) > 1:
            cycle_count += 1
            continue
        node = component[0]
        if node in adjacency.get(node, []):
            cycle_count += 1
    return cycle_count


def _is_weakly_connected(vertices: set[str], adjacency: Mapping[str, list[str]]) -> bool:
    if not vertices:
        return True
    undirected: dict[str, set[str]] = {node: set() for node in vertices}
    for source, targets in adjacency.items():
        for target in targets:
            undirected.setdefault(source, set()).add(target)
            undirected.setdefault(target, set()).add(source)

    start = next(iter(vertices))
    stack = [start]
    visited: set[str] = set()
    while stack:
        node = stack.pop()
        if node in visited:
            continue
        visited.add(node)
        stack.extend(undirected.get(node, set()) - visited)
    return visited == vertices
