from __future__ import annotations

import json
from pathlib import Path

from domain.models import MarkupDocument, Procedure
from domain.services.build_cross_team_graph_dashboard import BuildCrossTeamGraphDashboard


def _doc(
    *,
    markup_type: str,
    team_id: str,
    team_name: str,
    service_name: str,
    unit_id: str,
    procedures: list[Procedure],
    procedure_graph: dict[str, list[str]],
) -> MarkupDocument:
    return MarkupDocument(
        markup_type=markup_type,
        team_id=team_id,
        team_name=team_name,
        service_name=service_name,
        finedog_unit_id=unit_id,
        procedures=procedures,
        procedure_graph=procedure_graph,
    )


def test_build_cross_team_graph_dashboard() -> None:
    selected_documents = [
        _doc(
            markup_type="service",
            team_id="team-alpha",
            team_name="Alpha",
            service_name="Payments",
            unit_id="svc-pay",
            procedures=[
                Procedure(procedure_id="bot_auth", branches={"a": ["b"]}),
                Procedure(procedure_id="shared_core", branches={"c": ["d"]}),
            ],
            procedure_graph={"bot_auth": ["shared_core"], "shared_core": []},
        ),
        _doc(
            markup_type="service",
            team_id="team-alpha",
            team_name="Alpha",
            service_name="Loans",
            unit_id="svc-loans",
            procedures=[
                Procedure(procedure_id="multi_route", branches={"l1": ["l2"]}),
                Procedure(procedure_id="split_a", branches={"s1": ["s2"]}),
                Procedure(procedure_id="split_b", branches={"s3": ["s4"]}),
            ],
            procedure_graph={
                "multi_route": ["shared_core"],
                "split_a": [],
                "split_b": [],
            },
        ),
        _doc(
            markup_type="service",
            team_id="team-beta",
            team_name="Beta",
            service_name="Cards",
            unit_id="svc-cards",
            procedures=[
                Procedure(procedure_id="shared_core", branches={"x": ["y"]}),
                Procedure(procedure_id="loop_proc", branches={"z": ["z2"]}),
            ],
            procedure_graph={"shared_core": ["loop_proc"], "loop_proc": ["shared_core"]},
        ),
        _doc(
            markup_type="operations",
            team_id="team-alpha",
            team_name="Alpha",
            service_name="Payments",
            unit_id="svc-pay",
            procedures=[Procedure(procedure_id="bot_helper", branches={"k": ["m"]})],
            procedure_graph={"bot_helper": ["bot_auth"]},
        ),
    ]
    all_documents = [
        *selected_documents,
        _doc(
            markup_type="service",
            team_id="team-gamma",
            team_name="Gamma",
            service_name="Wallet",
            unit_id="svc-wallet",
            procedures=[Procedure(procedure_id="shared_core", branches={"w1": ["w2"]})],
            procedure_graph={"shared_core": []},
        ),
    ]

    dashboard = BuildCrossTeamGraphDashboard().build(
        selected_documents=selected_documents,
        all_documents=all_documents,
        selected_team_ids=["team-alpha", "team-beta"],
        top_limit=5,
    )

    assert [(item.markup_type, item.count) for item in dashboard.markup_type_counts] == [
        ("service", 3),
        ("operations", 1),
    ]
    assert dashboard.unique_graph_count == 4
    assert dashboard.bot_graph_count == 2
    assert dashboard.multi_graph_count == 1
    assert dashboard.total_procedure_count == 8
    assert dashboard.unique_procedure_count == 7
    assert dashboard.bot_procedure_count == 2
    assert dashboard.multi_procedure_count == 1
    assert dashboard.employee_procedure_count == 5

    assert dashboard.internal_intersection_markup_count == 3
    assert dashboard.external_intersection_markup_count == 3
    assert [(item.team_name, item.count) for item in dashboard.external_team_intersections] == [
        ("Gamma", 3)
    ]
    assert [
        (item.service_name, item.count)
        for item in dashboard.external_team_intersections[0].services
    ] == [("Wallet", 3)]
    assert dashboard.split_service_count == 1
    assert dashboard.target_service_count == 0
    assert dashboard.total_service_count == 3

    top_proc = dashboard.linking_procedures[0]
    assert top_proc.procedure_id == "shared_core"
    assert top_proc.graph_count == 3
    assert top_proc.usage_in_other_graphs == 2
    assert top_proc.incoming_edges == 3
    assert top_proc.outgoing_edges == 1

    top_service = dashboard.overloaded_services[0]
    assert top_service.team_name == "Beta"
    assert top_service.service_name == "Cards"
    assert top_service.cycle_count == 1
    assert top_service.block_count == 4


def test_unique_graph_count_reuses_team_graph_builder_logic() -> None:
    selected_documents = [
        _doc(
            markup_type="service",
            team_id="team-alpha",
            team_name="Alpha",
            service_name="Payments",
            unit_id="svc-pay-v1",
            procedures=[Procedure(procedure_id="entry", branches={"a": ["b"]})],
            procedure_graph={"entry": []},
        ),
        _doc(
            markup_type="operations",
            team_id="team-alpha",
            team_name="Alpha",
            service_name="Payments",
            unit_id="svc-pay-v2",
            procedures=[Procedure(procedure_id="entry_ops", branches={"c": ["d"]})],
            procedure_graph={"entry_ops": []},
        ),
    ]

    dashboard = BuildCrossTeamGraphDashboard().build(
        selected_documents=selected_documents,
        all_documents=selected_documents,
        selected_team_ids=["team-alpha"],
    )

    assert dashboard.unique_graph_count == 2
    assert dashboard.unique_graphs == ("Alpha / Payments #1", "Alpha / Payments #2")
    assert [(item.label, item.graph_count) for item in dashboard.graph_groups] == [
        ("Alpha / Payments", 2)
    ]


def test_graph_counts_use_procedure_graph_components_for_single_markup() -> None:
    fixture_path = Path("examples/markup/graphs_set.json")
    document = MarkupDocument.model_validate(json.loads(fixture_path.read_text(encoding="utf-8")))

    dashboard = BuildCrossTeamGraphDashboard().build(
        selected_documents=[document],
        all_documents=[document],
        selected_team_ids=[str(document.team_id)],
    )

    assert dashboard.unique_graph_count == len(document.procedures)
    assert dashboard.multi_graph_count == 1
    assert sum(item.graph_count for item in dashboard.graph_groups) == dashboard.unique_graph_count
