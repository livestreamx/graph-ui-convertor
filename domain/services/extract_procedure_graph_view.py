from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from domain.models import END_TYPE_DEFAULT, MarkupDocument


def extract_procedure_graph_view(document: MarkupDocument) -> dict[str, Any]:
    procedure_stats_by_id = _build_procedure_stats(document)
    procedure_name_by_id = {
        procedure.procedure_id: (procedure.procedure_name or procedure.procedure_id)
        for procedure in document.procedures
    }
    adjacency = _normalize_adjacency(document.procedure_graph, set(procedure_name_by_id.keys()))

    nodes: list[dict[str, Any]] = []
    for procedure_id in sorted(adjacency):
        procedure_meta = document.procedure_meta.get(procedure_id, {})
        stats = _resolve_node_stats(
            procedure_stats_by_id.get(procedure_id, {}),
            procedure_meta,
        )
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
                "procedure_count": _as_int(stats.get("procedure_count")),
                "start_count": _as_int(stats.get("start_count")),
                "branch_count": _as_int(stats.get("branch_count")),
                "end_count": _as_int(stats.get("end_count")),
                "postpone_count": _as_int(stats.get("postpone_count")),
                "end_type_counts": _as_end_type_counts(stats.get("end_type_counts")),
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


def _build_procedure_stats(document: MarkupDocument) -> dict[str, dict[str, object]]:
    stats: dict[str, dict[str, object]] = {}
    for procedure in document.procedures:
        start_count = len({str(block_id) for block_id in procedure.start_block_ids})
        branch_count = sum(len(set(targets)) for targets in procedure.branches.values())
        end_type_counts: dict[str, int] = {}
        for block_id in procedure.end_block_ids:
            end_type = procedure.end_block_types.get(block_id, END_TYPE_DEFAULT)
            end_type_counts[end_type] = end_type_counts.get(end_type, 0) + 1
        postpone_count = _as_int(end_type_counts.get("postpone", 0))
        total_end_count = sum(end_type_counts.values())
        stats[procedure.procedure_id] = {
            "procedure_count": 1,
            "start_count": start_count,
            "branch_count": branch_count,
            "end_count": max(0, total_end_count - postpone_count),
            "postpone_count": postpone_count,
            "end_type_counts": dict(sorted(end_type_counts.items())),
        }
    return stats


def _resolve_node_stats(
    base_stats: Mapping[str, object],
    procedure_meta: Mapping[str, object],
) -> dict[str, object]:
    procedure_count = _as_int(base_stats.get("procedure_count")) or 1
    start_count = _as_int(base_stats.get("start_count"))
    branch_count = _as_int(base_stats.get("branch_count"))
    end_count = _as_int(base_stats.get("end_count"))
    postpone_count = _as_int(base_stats.get("postpone_count"))
    end_type_counts = _as_end_type_counts(base_stats.get("end_type_counts"))

    graph_stats = procedure_meta.get("graph_stats")
    if not isinstance(graph_stats, Mapping):
        return {
            "procedure_count": procedure_count,
            "start_count": start_count,
            "branch_count": branch_count,
            "end_count": end_count,
            "postpone_count": postpone_count,
            "end_type_counts": end_type_counts,
        }

    meta_procedure_count = _as_int(procedure_meta.get("procedure_count"))
    if meta_procedure_count > 0:
        procedure_count = meta_procedure_count

    if start_count <= 0:
        start_count = _as_int(graph_stats.get("start"))
    if branch_count <= 0:
        branch_count = _as_int(graph_stats.get("branch"))

    postpone_from_end_types = _as_int(end_type_counts.get("postpone", 0))
    end_from_end_types = max(0, sum(end_type_counts.values()) - postpone_from_end_types)

    if end_count <= 0:
        end_count = end_from_end_types
    if postpone_count <= 0:
        postpone_count = postpone_from_end_types

    if end_count <= 0:
        end_count = _as_int(graph_stats.get("end"))
    if postpone_count <= 0:
        postpone_count = _as_int(graph_stats.get("postpone"))

    return {
        "procedure_count": procedure_count,
        "start_count": start_count,
        "branch_count": branch_count,
        "end_count": end_count,
        "postpone_count": postpone_count,
        "end_type_counts": end_type_counts,
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


def _as_int(value: object) -> int:
    if isinstance(value, int):
        return value
    if value is None:
        return 0
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return 0


def _as_end_type_counts(value: object) -> dict[str, int]:
    if not isinstance(value, Mapping):
        return {}
    result: dict[str, int] = {}
    for raw_type, raw_count in value.items():
        end_type = _as_text(raw_type)
        if not end_type:
            continue
        count = _as_int(raw_count)
        if count <= 0:
            continue
        result[end_type] = count
    return dict(sorted(result.items()))
