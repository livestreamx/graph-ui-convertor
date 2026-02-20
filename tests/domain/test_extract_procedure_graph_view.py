from __future__ import annotations

from domain.models import MarkupDocument
from domain.services.extract_procedure_graph_view import extract_procedure_graph_view


def test_extract_procedure_graph_view_marks_merge_nodes_and_cycles() -> None:
    payload = {
        "markup_type": "procedure_graph",
        "procedures": [
            {
                "proc_id": "p1",
                "proc_name": "Collect",
                "start_block_ids": ["start_1", "start_2"],
                "end_block_ids": ["end_1", "end_2::exit", "end_3::postpone"],
                "branches": {
                    "start_1": ["next_1", "next_2"],
                    "start_2": ["next_3"],
                },
            },
            {
                "proc_id": "p2",
                "proc_name": "Route",
                "start_block_ids": [],
                "end_block_ids": [],
                "branches": {},
            },
        ],
        "procedure_graph": {
            "p1": ["p2"],
            "p2": ["p1"],
        },
        "procedure_meta": {
            "p1": {
                "team_name": "Alpha",
                "service_name": "Billing",
                "is_intersection": True,
                "services": [
                    {"team_name": "Alpha", "service_name": "Billing"},
                    {"team_name": "Alpha", "service_name": "Fraud"},
                ],
            },
            "p2": {
                "team_name": "Alpha",
                "service_name": "Billing",
                "is_intersection": False,
            },
        },
    }
    document = MarkupDocument.model_validate(payload)

    graph_payload = extract_procedure_graph_view(document)

    assert graph_payload["meta"] == {
        "node_count": 2,
        "edge_count": 2,
        "merge_node_count": 1,
    }
    nodes = {node["id"]: node for node in graph_payload["nodes"]}
    assert nodes["p1"]["label"] == "Collect"
    assert nodes["p1"]["is_merge_node"] is True
    assert nodes["p1"]["merge_entity_count"] == 2
    assert nodes["p1"]["team_name"] == "Alpha"
    assert nodes["p1"]["service_name"] == "Billing"
    assert nodes["p1"]["start_count"] == 2
    assert nodes["p1"]["branch_count"] == 3
    assert nodes["p1"]["end_type_counts"] == {"end": 1, "exit": 1, "postpone": 1}
    assert nodes["p2"]["is_merge_node"] is False
    assert nodes["p2"]["start_count"] == 0
    assert nodes["p2"]["branch_count"] == 0
    assert nodes["p2"]["end_type_counts"] == {}

    edges = {edge["id"]: edge for edge in graph_payload["edges"]}
    assert edges["p1->p2"]["is_cycle"] is True
    assert edges["p2->p1"]["is_cycle"] is True
    assert edges["p1->p2"]["edge_type"] == "procedure_graph"
    assert edges["p2->p1"]["edge_type"] == "procedure_graph_cycle"


def test_extract_procedure_graph_view_adds_nodes_from_adjacency() -> None:
    payload = {
        "markup_type": "procedure_graph",
        "procedures": [
            {
                "proc_id": "p1",
                "start_block_ids": [],
                "end_block_ids": [],
                "branches": {},
            }
        ],
        "procedure_graph": {
            "p1": ["p2"],
        },
    }
    document = MarkupDocument.model_validate(payload)

    graph_payload = extract_procedure_graph_view(document)

    nodes = {node["id"]: node for node in graph_payload["nodes"]}
    assert set(nodes) == {"p1", "p2"}
    assert nodes["p2"]["label"] == "p2"
    assert nodes["p2"]["start_count"] == 0
    assert nodes["p2"]["branch_count"] == 0
    assert nodes["p2"]["end_type_counts"] == {}
    edges = graph_payload["edges"]
    assert len(edges) == 1
    assert edges[0]["source"] == "p1"
    assert edges[0]["target"] == "p2"
    assert edges[0]["is_cycle"] is False
    assert edges[0]["edge_type"] == "procedure_graph"


def test_extract_procedure_graph_view_uses_service_graph_stats_from_meta() -> None:
    payload = {
        "markup_type": "service_graph",
        "procedures": [
            {
                "proc_id": "svc::payments::1",
                "proc_name": "[Услуга] Payments",
                "start_block_ids": [],
                "end_block_ids": [],
                "branches": {},
            }
        ],
        "procedure_graph": {"svc::payments::1": []},
        "procedure_meta": {
            "svc::payments::1": {
                "team_name": "Alpha",
                "service_name": "Payments",
                "procedure_count": 4,
                "graph_stats": {"start": 3, "branch": 5, "end": 2, "postpone": 1},
            }
        },
    }
    document = MarkupDocument.model_validate(payload)

    graph_payload = extract_procedure_graph_view(document)
    node = graph_payload["nodes"][0]

    assert node["procedure_count"] == 4
    assert node["start_count"] == 3
    assert node["branch_count"] == 5
    assert node["end_count"] == 2
    assert node["postpone_count"] == 1
