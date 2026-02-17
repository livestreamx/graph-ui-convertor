from __future__ import annotations

from typing import Any

from domain.models import CUSTOM_DATA_KEY

_EDGE_TYPES = {"branch", "branch_cycle", "block_graph", "block_graph_cycle"}


def extract_block_graph_view(scene_payload: dict[str, Any]) -> dict[str, Any]:
    elements = scene_payload.get("elements")
    if not isinstance(elements, list):
        return _empty_graph_payload()

    block_labels: dict[tuple[str, str], str] = {}
    for element in elements:
        if not isinstance(element, dict):
            continue
        metadata = _extract_metadata(element)
        if metadata.get("role") != "block_label":
            continue
        procedure_id = _as_text(metadata.get("procedure_id"))
        block_id = _as_text(metadata.get("block_id"))
        label = _as_text(element.get("text"))
        if not procedure_id or not block_id or not label:
            continue
        block_labels[(procedure_id, block_id)] = label

    nodes_by_id: dict[str, dict[str, Any]] = {}
    for element in elements:
        if not isinstance(element, dict):
            continue
        metadata = _extract_metadata(element)
        if metadata.get("role") != "block":
            continue
        procedure_id = _as_text(metadata.get("procedure_id"))
        block_id = _as_text(metadata.get("block_id"))
        if not procedure_id or not block_id:
            continue
        node_id = _node_id(procedure_id, block_id)
        if node_id in nodes_by_id:
            continue
        label = block_labels.get((procedure_id, block_id), block_id)
        nodes_by_id[node_id] = {
            "id": node_id,
            "procedure_id": procedure_id,
            "block_id": block_id,
            "label": label,
            "is_initial": metadata.get("block_graph_initial") is True,
        }

    edges: list[dict[str, Any]] = []
    seen_edge_ids: set[str] = set()
    for element in elements:
        if not isinstance(element, dict):
            continue
        metadata = _extract_metadata(element)
        if metadata.get("role") != "edge":
            continue
        edge_type = _as_text(metadata.get("edge_type"))
        if edge_type not in _EDGE_TYPES:
            continue
        source_procedure_id = _as_text(metadata.get("procedure_id"))
        source_block_id = _as_text(metadata.get("source_block_id"))
        target_block_id = _as_text(metadata.get("target_block_id"))
        target_procedure_id = _as_text(metadata.get("target_procedure_id")) or source_procedure_id
        if (
            not source_procedure_id
            or not source_block_id
            or not target_procedure_id
            or not target_block_id
        ):
            continue

        source_node_id = _node_id(source_procedure_id, source_block_id)
        target_node_id = _node_id(target_procedure_id, target_block_id)
        nodes_by_id.setdefault(
            source_node_id,
            {
                "id": source_node_id,
                "procedure_id": source_procedure_id,
                "block_id": source_block_id,
                "label": source_block_id,
                "is_initial": False,
            },
        )
        nodes_by_id.setdefault(
            target_node_id,
            {
                "id": target_node_id,
                "procedure_id": target_procedure_id,
                "block_id": target_block_id,
                "label": target_block_id,
                "is_initial": False,
            },
        )

        raw_edge_id = element.get("id")
        if isinstance(raw_edge_id, str) and raw_edge_id:
            edge_id = raw_edge_id
        else:
            edge_id = f"{source_node_id}->{target_node_id}:{edge_type}"
        if edge_id in seen_edge_ids:
            continue
        seen_edge_ids.add(edge_id)

        is_cycle = edge_type.endswith("_cycle") or metadata.get("is_cycle") is True
        edges.append(
            {
                "id": edge_id,
                "source": source_node_id,
                "target": target_node_id,
                "source_procedure_id": source_procedure_id,
                "target_procedure_id": target_procedure_id,
                "source_block_id": source_block_id,
                "target_block_id": target_block_id,
                "edge_type": edge_type,
                "is_cycle": is_cycle,
            }
        )

    nodes = sorted(
        nodes_by_id.values(),
        key=lambda node: (str(node["procedure_id"]), str(node["block_id"])),
    )
    edges_sorted = sorted(
        edges,
        key=lambda edge: (
            str(edge["source"]),
            str(edge["target"]),
            str(edge["edge_type"]),
            str(edge["id"]),
        ),
    )
    return {
        "nodes": nodes,
        "edges": edges_sorted,
        "meta": {
            "node_count": len(nodes),
            "edge_count": len(edges_sorted),
        },
    }


def _extract_metadata(element: dict[str, Any]) -> dict[str, Any]:
    custom_data = element.get("customData")
    if isinstance(custom_data, dict):
        metadata = custom_data.get(CUSTOM_DATA_KEY)
        if isinstance(metadata, dict):
            return metadata
    metadata = element.get(CUSTOM_DATA_KEY)
    if isinstance(metadata, dict):
        return metadata
    return {}


def _as_text(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if value is None:
        return ""
    return str(value).strip()


def _node_id(procedure_id: str, block_id: str) -> str:
    return f"{procedure_id}::{block_id}"


def _empty_graph_payload() -> dict[str, Any]:
    return {
        "nodes": [],
        "edges": [],
        "meta": {
            "node_count": 0,
            "edge_count": 0,
        },
    }
