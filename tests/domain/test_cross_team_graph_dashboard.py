from __future__ import annotations

import json
from pathlib import Path

from domain.models import MarkupDocument, Procedure
from domain.services.build_cross_team_graph_dashboard import BuildCrossTeamGraphDashboard
from domain.services.build_team_procedure_graph import BuildTeamProcedureGraph


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
    assert dashboard.unique_graph_count == 6
    assert dashboard.bot_graph_count == 2
    assert dashboard.multi_graph_count == 1
    assert dashboard.total_procedure_count == 8
    assert dashboard.unique_procedure_count == 7
    assert dashboard.bot_procedure_count == 2
    assert dashboard.multi_procedure_count == 1
    assert dashboard.employee_procedure_count == 5

    assert dashboard.internal_intersection_markup_count == 3
    assert dashboard.external_intersection_markup_count == 1
    assert [(item.team_name, item.count) for item in dashboard.external_team_intersections] == [
        ("Gamma", 1)
    ]
    overlap = dashboard.external_team_intersections[0]
    assert overlap.external_depends_on_selected_count == 1
    assert overlap.selected_depends_on_external_count == 0
    assert (
        overlap.external_depends_on_selected_count + overlap.selected_depends_on_external_count
        == overlap.count
    )
    assert [
        (item.service_name, item.count)
        for item in dashboard.external_team_intersections[0].services
    ] == [("Wallet", 1)]
    service_overlap = dashboard.external_team_intersections[0].services[0]
    assert service_overlap.external_depends_on_selected_count == 1
    assert service_overlap.selected_depends_on_external_count == 0
    assert (
        service_overlap.external_depends_on_selected_count
        + service_overlap.selected_depends_on_external_count
        == service_overlap.count
    )
    assert dashboard.split_service_count == 1
    assert dashboard.target_service_count == 0
    assert dashboard.total_service_count == 3

    top_proc = dashboard.linking_procedures[0]
    assert top_proc.procedure_id == "shared_core"
    assert top_proc.graph_count == 3
    assert top_proc.usage_in_other_graphs == 2
    assert top_proc.incoming_edges == 3
    assert top_proc.outgoing_edges == 1
    assert top_proc.graph_labels == (
        "Alpha / Loans",
        "Alpha / Payments",
        "Beta / Cards",
    )
    assert [
        (
            item.graph_label,
            item.is_cross_entity,
            item.incoming_edges,
            item.outgoing_edges,
        )
        for item in top_proc.graph_usage_stats
    ] == [
        ("Alpha / Loans", True, 1, 0),
        ("Alpha / Payments", True, 1, 0),
        ("Beta / Cards", True, 1, 1),
    ]

    top_service = dashboard.overloaded_services[0]
    assert top_service.team_name == "Alpha"
    assert top_service.service_name == "Loans"
    assert top_service.in_team_merge_nodes == 1
    assert top_service.cycle_count == 0
    assert top_service.procedure_count == 4
    assert top_service.block_count == 6
    assert [
        (
            item.procedure_id,
            item.in_team_merge_hits,
            item.cycle_hits,
            item.linked_procedure_count,
            item.block_count,
        )
        for item in top_service.procedure_usage_stats
    ] == [
        ("multi_route", 0, 0, 1, 2),
        ("split_a", 0, 0, 0, 2),
        ("split_b", 0, 0, 0, 2),
        ("shared_core", 1, 0, 1, 0),
    ]


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


def test_dashboard_graph_stats_follow_same_merge_graph_as_diagram() -> None:
    selected_documents = [
        _doc(
            markup_type="service",
            team_id="team-alpha",
            team_name="Alpha",
            service_name="Payments",
            unit_id="svc-pay",
            procedures=[
                Procedure(procedure_id="entry", branches={"a": ["b"]}),
                Procedure(procedure_id="shared", branches={"c": ["d"]}),
            ],
            procedure_graph={"entry": [], "shared": []},
        )
    ]
    all_documents = [
        *selected_documents,
        _doc(
            markup_type="service",
            team_id="team-beta",
            team_name="Beta",
            service_name="Loans",
            unit_id="svc-loans",
            procedures=[
                Procedure(procedure_id="entry", branches={"x": ["y"]}),
                Procedure(procedure_id="shared", branches={"z": ["w"]}),
            ],
            procedure_graph={"entry": ["shared"], "shared": []},
        ),
    ]

    merged_from_selected_only = BuildTeamProcedureGraph().build(
        selected_documents,
        merge_selected_markups=True,
    )
    merged_with_all_markups = BuildTeamProcedureGraph().build(
        selected_documents,
        merge_documents=all_documents,
        merge_selected_markups=True,
    )
    assert len(merged_from_selected_only.procedure_graph.get("entry", [])) == 0
    assert merged_with_all_markups.procedure_graph.get("entry") == ["shared"]

    dashboard_without_all = BuildCrossTeamGraphDashboard().build(
        selected_documents=selected_documents,
        all_documents=all_documents,
        selected_team_ids=["team-alpha"],
        merge_selected_markups=True,
    )
    dashboard_with_all = BuildCrossTeamGraphDashboard().build(
        selected_documents=selected_documents,
        all_documents=all_documents,
        selected_team_ids=["team-alpha"],
        merge_selected_markups=True,
        merge_documents=all_documents,
    )

    assert dashboard_without_all.unique_graph_count == 2
    assert dashboard_with_all.unique_graph_count == 1
