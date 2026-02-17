from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from domain.models import MarkupDocument


def extract_procedure_graph_view(document: MarkupDocument) -> dict[str, Any]:
    procedure_name_by_id = {
        procedure.procedure_id: (procedure.procedure_name or procedure.procedure_id)
        for procedure in document.procedures
    }
    adjacency = _normalize_adjacency(document.procedure_graph, set(procedure_name_by_id.keys()))

    nodes: list[dict[str, Any]] = []
    for procedure_id in sorted(adjacency):
        procedure_meta = document.procedure_meta.get(procedure_id, {})
        services = procedure_meta.get("services")
        merge_entity_count = len(services) if isinstance(services, list) else 0
        nodes.append(
            {
                "id": procedure_id,
                "procedure_id": procedure_id,
                "label": procedure_name_by_id.get(procedure_id, procedure_id),
                "team_name": _as_text(procedure_meta.get("team_name")),
                "service_name": _as_text(procedure_meta.get("service_name")),
                "source_procedure_id": _as_text(procedure_meta.get("source_procedure_id"))
                or procedure_id,
                "is_merge_node": procedure_meta.get("is_intersection") is True,
                "merge_entity_count": merge_entity_count,
            }
        )

    path_cache: dict[tuple[str, str], bool] = {}
    adjacency_sets = {source: set(targets) for source, targets in adjacency.items()}
    edges: list[dict[str, Any]] = []
    for source in sorted(adjacency):
        for target in adjacency.get(source, []):
            is_cycle = source == target or _path_exists(
                adjacency,
                start=target,
                goal=source,
                cache=path_cache,
            )
            is_reverse = _is_reverse_edge(source, target, adjacency_sets)
            edges.append(
                {
                    "id": f"{source}->{target}",
                    "source": source,
                    "target": target,
                    "edge_type": ("procedure_graph_cycle" if is_reverse else "procedure_graph"),
                    "is_cycle": is_cycle,
                }
            )

    merge_node_count = sum(1 for node in nodes if node["is_merge_node"])
    return {
        "nodes": nodes,
        "edges": edges,
        "meta": {
            "node_count": len(nodes),
            "edge_count": len(edges),
            "merge_node_count": merge_node_count,
        },
    }


def _normalize_adjacency(
    procedure_graph: Mapping[str, list[str]],
    known_ids: set[str],
) -> dict[str, list[str]]:
    adjacency: dict[str, list[str]] = {proc_id: [] for proc_id in known_ids}
    for raw_source, raw_targets in procedure_graph.items():
        source = _as_text(raw_source)
        if not source:
            continue
        targets = adjacency.setdefault(source, [])
        seen_targets = set(targets)
        for raw_target in raw_targets:
            target = _as_text(raw_target)
            if not target or target in seen_targets:
                continue
            seen_targets.add(target)
            targets.append(target)
            adjacency.setdefault(target, [])
    return adjacency


def _path_exists(
    adjacency: Mapping[str, list[str]],
    *,
    start: str,
    goal: str,
    cache: dict[tuple[str, str], bool],
) -> bool:
    cache_key = (start, goal)
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    stack = [start]
    visited: set[str] = set()
    while stack:
        current = stack.pop()
        if current == goal:
            cache[cache_key] = True
            return True
        if current in visited:
            continue
        visited.add(current)
        for next_node in adjacency.get(current, []):
            if next_node not in visited:
                stack.append(next_node)

    cache[cache_key] = False
    return False


def _is_reverse_edge(
    source: str,
    target: str,
    adjacency_sets: Mapping[str, set[str]],
) -> bool:
    if source == target:
        return False
    has_opposite = source in adjacency_sets.get(target, set())
    if not has_opposite:
        return False
    return source > target


def _as_text(value: object) -> str:
    if isinstance(value, str):
        return value.strip()
    if value is None:
        return ""
    return str(value).strip()
