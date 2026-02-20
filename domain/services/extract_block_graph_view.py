from __future__ import annotations

from typing import Any

from domain.models import CUSTOM_DATA_KEY

_EDGE_TYPES = {"branch", "branch_cycle", "block_graph", "block_graph_cycle"}
_BLOCK_GRAPH_EDGE_TYPES = {"block_graph", "block_graph_cycle"}
_BRANCH_EDGE_TYPES = {"branch", "branch_cycle"}


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

    block_nodes_by_id: dict[str, dict[str, Any]] = {}
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
        if node_id in block_nodes_by_id:
            continue
        label = block_labels.get((procedure_id, block_id)) or block_id
        source_procedure_id = _as_text(metadata.get("source_procedure_id")) or procedure_id
        block_nodes_by_id[node_id] = {
            "id": node_id,
            "procedure_id": procedure_id,
            "source_procedure_id": source_procedure_id,
            "block_id": block_id,
            "label": label,
            "is_initial": metadata.get("block_graph_initial") is True,
            "end_block_type": _as_text(metadata.get("end_block_type")),
        }

    raw_edges: list[dict[str, Any]] = []
    for element in elements:
        if not isinstance(element, dict):
            continue
        metadata = _extract_metadata(element)
        if metadata.get("role") != "edge":
            continue
        edge_type = _as_text(metadata.get("edge_type"))
        if edge_type not in _EDGE_TYPES:
            continue
        source_procedure_id = _as_text(metadata.get("source_procedure_id")) or _as_text(
            metadata.get("procedure_id")
        )
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

        raw_edge_id = element.get("id")
        if isinstance(raw_edge_id, str) and raw_edge_id:
            edge_id = raw_edge_id
        else:
            edge_id = f"{source_procedure_id}::{source_block_id}->{target_procedure_id}::{target_block_id}:{edge_type}"
        is_cycle = edge_type.endswith("_cycle") or metadata.get("is_cycle") is True
        raw_edges.append(
            {
                "id": edge_id,
                "source": _node_id(source_procedure_id, source_block_id),
                "target": _node_id(target_procedure_id, target_block_id),
                "source_procedure_id": source_procedure_id,
                "target_procedure_id": target_procedure_id,
                "source_block_id": source_block_id,
                "target_block_id": target_block_id,
                "edge_type": edge_type,
                "is_cycle": is_cycle,
            }
        )

    if not raw_edges:
        return _empty_graph_payload()

    edge_types = {str(edge["edge_type"]) for edge in raw_edges}
    if edge_types & _BLOCK_GRAPH_EDGE_TYPES:
        allowed_edge_types = _BLOCK_GRAPH_EDGE_TYPES
    else:
        allowed_edge_types = _BRANCH_EDGE_TYPES

    nodes_by_id: dict[str, dict[str, Any]] = {}
    edges: list[dict[str, Any]] = []
    seen_edge_ids: set[str] = set()
    for edge in raw_edges:
        edge_type = str(edge["edge_type"])
        if edge_type not in allowed_edge_types:
            continue
        edge_id = str(edge["id"])
        if edge_id in seen_edge_ids:
            continue
        seen_edge_ids.add(edge_id)

        source_node_id = str(edge["source"])
        target_node_id = str(edge["target"])
        source_procedure_id = str(edge["source_procedure_id"])
        target_procedure_id = str(edge["target_procedure_id"])
        source_block_id = str(edge["source_block_id"])
        target_block_id = str(edge["target_block_id"])

        source_node = block_nodes_by_id.get(source_node_id)
        if source_node is None:
            source_node = {
                "id": source_node_id,
                "procedure_id": source_procedure_id,
                "source_procedure_id": source_procedure_id,
                "block_id": source_block_id,
                "label": block_labels.get((source_procedure_id, source_block_id))
                or source_block_id,
                "is_initial": False,
                "end_block_type": "",
            }
        target_node = block_nodes_by_id.get(target_node_id)
        if target_node is None:
            target_node = {
                "id": target_node_id,
                "procedure_id": target_procedure_id,
                "source_procedure_id": target_procedure_id,
                "block_id": target_block_id,
                "label": block_labels.get((target_procedure_id, target_block_id))
                or target_block_id,
                "is_initial": False,
                "end_block_type": "",
            }

        nodes_by_id[source_node_id] = source_node
        nodes_by_id[target_node_id] = target_node
        edges.append(edge)

    if not edges:
        return _empty_graph_payload()

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
