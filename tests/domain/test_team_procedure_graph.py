from __future__ import annotations

import pytest

from adapters.layout.grid import LayoutConfig
from adapters.layout.procedure_graph import ProcedureGraphLayoutEngine
from domain.models import MarkupDocument, Size
from domain.services.build_team_procedure_graph import (
    _SERVICE_COLORS,
    BuildTeamProcedureGraph,
)
from domain.services.convert_markup_to_excalidraw import (
    SERVICE_ZONE_LABEL_FONT_FAMILY as EXCALIDRAW_SERVICE_ZONE_LABEL_FONT_FAMILY,
)
from domain.services.convert_markup_to_unidraw import (
    SERVICE_ZONE_LABEL_FONT_FAMILY as UNIDRAW_SERVICE_ZONE_LABEL_FONT_FAMILY,
)
from domain.services.convert_procedure_graph_to_excalidraw import (
    ProcedureGraphToExcalidrawConverter,
)
from domain.services.convert_procedure_graph_to_unidraw import ProcedureGraphToUnidrawConverter
from tests.helpers.markup_fixtures import load_markup_fixture


def test_build_team_procedure_graph_merges_documents() -> None:
    doc_alpha = MarkupDocument.model_validate(
        {
            "markup_type": "service",
            "service_name": "Payments",
            "team_name": "Alpha",
            "procedures": [
                {
                    "proc_id": "p1",
                    "proc_name": "Authorize",
                    "start_block_ids": ["a"],
                    "end_block_ids": ["b::end"],
                    "branches": {"a": ["b"]},
                }
            ],
            "procedure_graph": {"p1": []},
        }
    )
    doc_beta = MarkupDocument.model_validate(
        {
            "markup_type": "service",
            "service_name": "Refunds",
            "team_name": "Beta",
            "procedures": [
                {
                    "proc_id": "p2",
                    "proc_name": "Refund",
                    "start_block_ids": ["c"],
                    "end_block_ids": ["d::end"],
                    "branches": {"c": ["d"]},
                }
            ],
            "procedure_graph": {"p2": []},
        }
    )

    merged = BuildTeamProcedureGraph().build([doc_beta, doc_alpha])

    assert merged.service_name == "Alpha + Beta"
    assert {proc.procedure_id for proc in merged.procedures} == {"p1", "p2"}
    assert merged.procedure_meta["p1"]["service_name"] == "Payments"
    assert merged.procedure_meta["p1"]["team_name"] == "Alpha"
    assert merged.procedure_graph["p2"] == []


def test_build_team_procedure_graph_sets_team_id_for_single_team() -> None:
    document = MarkupDocument.model_validate(
        {
            "markup_type": "service",
            "service_name": "Payments",
            "team_id": "team-alpha",
            "team_name": "Alpha",
            "procedures": [
                {
                    "proc_id": "p1",
                    "proc_name": "Authorize",
                    "start_block_ids": ["a"],
                    "end_block_ids": ["b::end"],
                    "branches": {"a": ["b"]},
                }
            ],
            "procedure_graph": {"p1": []},
        }
    )

    merged = BuildTeamProcedureGraph().build([document])

    assert merged.team_id == "team-alpha"
    assert merged.team_name == "Alpha"


def test_build_team_service_graph_aggregates_by_service() -> None:
    doc_alpha = MarkupDocument.model_validate(
        {
            "markup_type": "service",
            "service_name": "Payments",
            "finedog_unit_id": "svc-pay",
            "team_id": "team-alpha",
            "team_name": "Alpha",
            "procedures": [
                {
                    "proc_id": "entry",
                    "proc_name": "Entry",
                    "start_block_ids": ["a"],
                    "end_block_ids": ["b::end"],
                    "branches": {"a": ["b"]},
                }
            ],
            "procedure_graph": {"entry": ["shared"], "shared": []},
        }
    )
    doc_beta = MarkupDocument.model_validate(
        {
            "markup_type": "service",
            "service_name": "Refunds",
            "finedog_unit_id": "svc-ref",
            "team_id": "team-beta",
            "team_name": "Beta",
            "procedures": [
                {
                    "proc_id": "shared",
                    "proc_name": "Shared",
                    "start_block_ids": ["c"],
                    "end_block_ids": ["d::end"],
                    "branches": {"c": ["d"]},
                }
            ],
            "procedure_graph": {"shared": []},
        }
    )

    merged = BuildTeamProcedureGraph().build([doc_alpha, doc_beta], graph_level="service")

    assert merged.markup_type == "service_graph"
    assert merged.service_name is not None
    assert merged.service_name.startswith("Services")
    assert len(merged.procedures) == 2
    by_service_name = {
        str(meta.get("service_name")): proc_id for proc_id, meta in merged.procedure_meta.items()
    }
    alpha_id = by_service_name["Payments"]
    beta_id = by_service_name["Refunds"]
    assert merged.procedure_graph[alpha_id] == [beta_id]
    assert merged.procedure_graph[beta_id] == []
    assert merged.procedure_meta[alpha_id]["is_intersection"] is False
    assert merged.procedure_meta[beta_id]["is_intersection"] is False
    name_lookup = {proc.procedure_id: proc.procedure_name for proc in merged.procedures}
    assert name_lookup[alpha_id] == "[Alpha] Payments"
    assert name_lookup[beta_id] == "[Beta] Refunds"


def test_service_graph_layout_skips_left_dashboard_panels() -> None:
    payload = {
        "markup_type": "service_graph",
        "service_name": "Services · Alpha + Beta",
        "procedures": [
            {
                "proc_id": "service::alpha::payments::entry",
                "proc_name": "[Alpha] Payments",
                "start_block_ids": [],
                "end_block_ids": [],
                "branches": {},
            },
            {
                "proc_id": "service::beta::refunds::shared",
                "proc_name": "[Beta] Refunds",
                "start_block_ids": [],
                "end_block_ids": [],
                "branches": {},
            },
        ],
        "procedure_graph": {
            "service::alpha::payments::entry": ["service::beta::refunds::shared"],
            "service::beta::refunds::shared": [],
        },
    }
    document = MarkupDocument.model_validate(payload).model_copy(
        update={
            "procedure_meta": {
                "service::alpha::payments::entry": {
                    "team_name": "Alpha",
                    "service_name": "Payments",
                    "procedure_color": "#d9f5ff",
                },
                "service::beta::refunds::shared": {
                    "team_name": "Beta",
                    "service_name": "Refunds",
                    "procedure_color": "#e3f7d9",
                },
            }
        }
    )

    plan = ProcedureGraphLayoutEngine().build_plan(document)
    assert not plan.scenarios
    assert not plan.service_zones

    scene = ProcedureGraphToExcalidrawConverter(ProcedureGraphLayoutEngine()).convert(document)
    roles = {
        str(element.get("customData", {}).get("cjm", {}).get("role"))
        for element in scene.elements
        if isinstance(element.get("customData", {}).get("cjm", {}), dict)
    }
    assert "service_zone" not in roles
    assert not any(role.startswith("scenario_") for role in roles)


def test_service_graph_splits_multiple_procedures_by_service() -> None:
    document = MarkupDocument.model_validate(
        {
            "markup_type": "service",
            "service_name": "Payments",
            "team_name": "Alpha",
            "procedures": [
                {
                    "proc_id": "p1",
                    "proc_name": "Flow 1",
                    "start_block_ids": ["a"],
                    "end_block_ids": ["b::end"],
                    "branches": {"a": ["b"]},
                },
                {
                    "proc_id": "p2",
                    "proc_name": "Flow 2",
                    "start_block_ids": ["c"],
                    "end_block_ids": ["d::end"],
                    "branches": {"c": ["d"]},
                },
            ],
            "procedure_graph": {"p1": [], "p2": []},
        }
    )

    merged = BuildTeamProcedureGraph().build([document], graph_level="service")

    assert merged.markup_type == "service_graph"
    name_lookup = {proc.procedure_id: proc.procedure_name for proc in merged.procedures}
    names = sorted(name for name in name_lookup.values() if name is not None)
    assert names == [
        "[Alpha] Payments (Graph #1)",
        "[Alpha] Payments (Graph #2)",
    ]
    by_name = {name: proc_id for proc_id, name in name_lookup.items()}
    assert merged.procedure_graph[by_name["[Alpha] Payments (Graph #1)"]] == []
    assert merged.procedure_graph[by_name["[Alpha] Payments (Graph #2)"]] == []


def test_service_graph_node_sizes_scale_with_procedure_count() -> None:
    document = MarkupDocument.model_validate(
        {
            "markup_type": "service_graph",
            "service_name": "Services · Alpha",
            "procedures": [
                {
                    "proc_id": "svc-one",
                    "proc_name": "[Alpha] Payments",
                    "start_block_ids": [],
                    "end_block_ids": [],
                    "branches": {},
                },
                {
                    "proc_id": "svc-ten",
                    "proc_name": "[Alpha] Payments (Graph #2)",
                    "start_block_ids": [],
                    "end_block_ids": [],
                    "branches": {},
                },
                {
                    "proc_id": "svc-twenty",
                    "proc_name": "[Alpha] Payments (Graph #3)",
                    "start_block_ids": [],
                    "end_block_ids": [],
                    "branches": {},
                },
            ],
            "procedure_graph": {"svc-one": [], "svc-ten": [], "svc-twenty": []},
            "procedure_meta": {
                "svc-one": {"procedure_count": 1},
                "svc-ten": {"procedure_count": 10},
                "svc-twenty": {"procedure_count": 20},
            },
        }
    )

    base = LayoutConfig().block_size
    base_service = Size(base.width * 3, base.height * 1.2)

    plan = ProcedureGraphLayoutEngine().build_plan(document)
    sizes = {frame.procedure_id: frame.size for frame in plan.frames}

    assert sizes["svc-one"] == base_service
    assert sizes["svc-ten"].width == pytest.approx(base_service.width * 1.45)
    assert sizes["svc-ten"].height == pytest.approx(base_service.height * 1.45)
    assert sizes["svc-twenty"].width == pytest.approx(base_service.width * 1.95)
    assert sizes["svc-twenty"].height == pytest.approx(base_service.height * 1.95)


def test_service_graph_collects_component_stats() -> None:
    document = MarkupDocument.model_validate(
        {
            "markup_type": "service",
            "service_name": "Payments",
            "team_name": "Alpha",
            "procedures": [
                {
                    "proc_id": "p1",
                    "proc_name": "Authorize",
                    "start_block_ids": ["s1", "s2"],
                    "end_block_ids": ["e1"],
                    "branches": {"s1": ["b1", "b2"]},
                    "end_block_types": {"e1": "end"},
                },
                {
                    "proc_id": "p2",
                    "proc_name": "Capture",
                    "start_block_ids": ["s3"],
                    "end_block_ids": ["e2", "e3"],
                    "branches": {"s3": ["b3"]},
                    "end_block_types": {"e2": "postpone", "e3": "end"},
                },
            ],
            "procedure_graph": {"p1": ["p2"], "p2": []},
        }
    )

    merged = BuildTeamProcedureGraph().build([document], graph_level="service")

    assert merged.markup_type == "service_graph"
    assert len(merged.procedures) == 1
    service_id = merged.procedures[0].procedure_id
    stats = merged.procedure_meta[service_id]["graph_stats"]
    assert stats == {"start": 3, "branch": 3, "end": 2, "postpone": 1}


def test_build_team_procedure_graph_title_limits_team_names() -> None:
    documents = []
    for idx, team_name in enumerate(["Alpha", "Beta", "Gamma", "Zeta"], start=1):
        documents.append(
            MarkupDocument.model_validate(
                {
                    "markup_type": "service",
                    "service_name": f"Service {idx}",
                    "team_name": team_name,
                    "procedures": [
                        {
                            "proc_id": f"p{idx}",
                            "start_block_ids": [f"a{idx}"],
                            "end_block_ids": [f"b{idx}::end"],
                            "branches": {f"a{idx}": [f"b{idx}"]},
                        }
                    ],
                    "procedure_graph": {f"p{idx}": []},
                }
            )
        )

    merged = BuildTeamProcedureGraph().build(documents)

    assert merged.service_name == "Alpha + Beta + Gamma + еще 1 команд"


def test_build_team_procedure_graph_allows_duplicate_procedure_ids() -> None:
    doc_alpha = MarkupDocument.model_validate(
        {
            "markup_type": "service",
            "service_name": "Payments",
            "team_name": "Alpha",
            "procedures": [
                {
                    "proc_id": "shared",
                    "proc_name": "Common Flow",
                    "start_block_ids": ["a"],
                    "end_block_ids": ["b::end"],
                    "branches": {"a": ["b"]},
                }
            ],
            "procedure_graph": {"shared": []},
        }
    )
    doc_beta = MarkupDocument.model_validate(
        {
            "markup_type": "service",
            "service_name": "Loans",
            "team_name": "Beta",
            "procedures": [
                {
                    "proc_id": "shared",
                    "proc_name": "Common Flow",
                    "start_block_ids": ["c"],
                    "end_block_ids": ["d::end"],
                    "branches": {"c": ["d"]},
                }
            ],
            "procedure_graph": {"shared": []},
        }
    )

    merged = BuildTeamProcedureGraph().build([doc_alpha, doc_beta])

    assert [proc.procedure_id for proc in merged.procedures] == ["shared"]
    proc = merged.procedures[0]
    assert set(proc.start_block_ids) == {"a", "c"}
    assert set(proc.end_block_ids) == {"b", "d"}
    assert merged.procedure_meta["shared"]["is_intersection"] is True
    assert merged.procedure_meta["shared"]["procedure_color"] == "#ffd6d6"
    services = merged.procedure_meta["shared"]["services"]
    assert isinstance(services, list)
    assert any(
        service.get("team_name") == "Alpha"
        and service.get("service_name") == "Payments"
        and isinstance(service.get("service_color"), str)
        for service in services
    )
    assert any(
        service.get("team_name") == "Beta"
        and service.get("service_name") == "Loans"
        and isinstance(service.get("service_color"), str)
        for service in services
    )


def test_build_team_procedure_graph_merge_threshold_zero_disables_shared_merges() -> None:
    doc_alpha = MarkupDocument.model_validate(
        {
            "markup_type": "service",
            "service_name": "Payments",
            "team_name": "Alpha",
            "procedures": [
                {
                    "proc_id": "shared",
                    "proc_name": "Shared Flow",
                    "start_block_ids": ["a1"],
                    "end_block_ids": ["a2::end"],
                    "branches": {"a1": ["a2"]},
                }
            ],
            "procedure_graph": {"shared": []},
        }
    )
    doc_beta = MarkupDocument.model_validate(
        {
            "markup_type": "service",
            "service_name": "Loans",
            "team_name": "Beta",
            "procedures": [
                {
                    "proc_id": "shared",
                    "proc_name": "Shared Flow",
                    "start_block_ids": ["b1"],
                    "end_block_ids": ["b2::end"],
                    "branches": {"b1": ["b2"]},
                }
            ],
            "procedure_graph": {"shared": []},
        }
    )

    merged = BuildTeamProcedureGraph().build(
        [doc_alpha, doc_beta],
        merge_selected_markups=True,
        merge_node_min_chain_size=0,
    )

    proc_ids = [proc.procedure_id for proc in merged.procedures]
    shared_proc_ids = [proc_id for proc_id in proc_ids if proc_id.startswith("shared::doc")]
    assert len(shared_proc_ids) == 2
    assert "shared" not in proc_ids
    assert all(merged.procedure_meta[proc_id]["is_intersection"] is False for proc_id in proc_ids)


def test_build_team_procedure_graph_merge_threshold_groups_shared_chains() -> None:
    doc_alpha = MarkupDocument.model_validate(
        {
            "markup_type": "service",
            "service_name": "Payments",
            "team_name": "Alpha",
            "procedures": [
                {
                    "proc_id": "shared_a",
                    "proc_name": "Shared A",
                    "start_block_ids": ["a1"],
                    "end_block_ids": ["a2::end"],
                    "branches": {"a1": ["a2"]},
                },
                {
                    "proc_id": "shared_b",
                    "proc_name": "Shared B",
                    "start_block_ids": ["a3"],
                    "end_block_ids": ["a4::end"],
                    "branches": {"a3": ["a4"]},
                },
            ],
            "procedure_graph": {"shared_a": ["shared_b"], "shared_b": []},
        }
    )
    doc_beta = MarkupDocument.model_validate(
        {
            "markup_type": "service",
            "service_name": "Loans",
            "team_name": "Beta",
            "procedures": [
                {
                    "proc_id": "shared_a",
                    "proc_name": "Shared A",
                    "start_block_ids": ["b1"],
                    "end_block_ids": ["b2::end"],
                    "branches": {"b1": ["b2"]},
                },
                {
                    "proc_id": "shared_b",
                    "proc_name": "Shared B",
                    "start_block_ids": ["b3"],
                    "end_block_ids": ["b4::end"],
                    "branches": {"b3": ["b4"]},
                },
            ],
            "procedure_graph": {"shared_a": ["shared_b"], "shared_b": []},
        }
    )

    merged = BuildTeamProcedureGraph().build(
        [doc_alpha, doc_beta],
        merge_selected_markups=True,
        merge_node_min_chain_size=2,
    )

    proc_ids = [proc.procedure_id for proc in merged.procedures]
    assert "shared_a" in proc_ids
    assert "shared_b" in proc_ids
    assert merged.procedure_meta["shared_a"]["is_intersection"] is True
    assert merged.procedure_meta["shared_b"]["is_intersection"] is True


def test_build_team_procedure_graph_chain_threshold_keeps_adjacent_non_merge_nodes() -> None:
    basic = load_markup_fixture("basic.json")
    graphs_set = load_markup_fixture("graphs_set.json")

    merged = BuildTeamProcedureGraph().build(
        [basic],
        merge_documents=[basic, graphs_set],
        merge_selected_markups=True,
        merge_node_min_chain_size=2,
    )

    proc_ids = {proc.procedure_id for proc in merged.procedures}
    assert "proc_shared_intake" in proc_ids
    assert "proc_shared_handoff" in proc_ids
    assert "proc_shared_routing" in proc_ids

    assert merged.procedure_meta["proc_shared_intake"]["is_intersection"] is True
    assert merged.procedure_meta["proc_shared_handoff"]["is_intersection"] is True
    assert merged.procedure_meta["proc_shared_routing"]["is_intersection"] is False


def test_build_team_procedure_graph_scoped_chain_groups_do_not_cross_documents() -> None:
    basic = load_markup_fixture("basic.json")
    graphs_set = load_markup_fixture("graphs_set.json")

    merged = BuildTeamProcedureGraph().build(
        [basic, graphs_set],
        merge_selected_markups=False,
        merge_node_min_chain_size=2,
    )

    intake_doc1 = merged.procedure_meta["proc_shared_intake::doc1"]
    intake_doc2 = merged.procedure_meta["proc_shared_intake::doc2"]
    group_id_doc1 = intake_doc1.get("merge_chain_group_id")
    group_id_doc2 = intake_doc2.get("merge_chain_group_id")

    assert isinstance(group_id_doc1, str)
    assert isinstance(group_id_doc2, str)
    assert group_id_doc1 != group_id_doc2
    assert "proc_shared_intake::doc1" in group_id_doc1
    assert "proc_shared_handoff::doc1" in group_id_doc1
    assert "proc_shared_intake::doc2" in group_id_doc2
    assert "proc_shared_handoff::doc2" in group_id_doc2


def test_build_team_procedure_graph_marks_singleton_shared_nodes_when_flag_is_off() -> None:
    doc_alpha = MarkupDocument.model_validate(
        {
            "markup_type": "service",
            "service_name": "Payments",
            "team_name": "Alpha",
            "procedures": [
                {
                    "proc_id": "shared",
                    "proc_name": "Common Flow",
                    "start_block_ids": ["a"],
                    "end_block_ids": ["b::end"],
                    "branches": {"a": ["b"]},
                }
            ],
            "procedure_graph": {"shared": []},
        }
    )
    doc_beta = MarkupDocument.model_validate(
        {
            "markup_type": "service",
            "service_name": "Loans",
            "team_name": "Beta",
            "procedures": [
                {
                    "proc_id": "shared",
                    "proc_name": "Common Flow",
                    "start_block_ids": ["c"],
                    "end_block_ids": ["d::end"],
                    "branches": {"c": ["d"]},
                }
            ],
            "procedure_graph": {"shared": []},
        }
    )

    merged = BuildTeamProcedureGraph().build(
        [doc_alpha, doc_beta],
        merge_selected_markups=False,
    )

    proc_ids = [proc.procedure_id for proc in merged.procedures]
    assert len(proc_ids) == 2
    shared_proc_ids = [proc_id for proc_id in proc_ids if proc_id.startswith("shared::doc")]
    assert len(shared_proc_ids) == 2
    for proc_id in shared_proc_ids:
        meta = merged.procedure_meta[proc_id]
        assert meta["is_intersection"] is True
        services = meta["services"]
        assert isinstance(services, list)
        assert len(services) == 1
        merge_services = meta.get("merge_services")
        assert isinstance(merge_services, list)
        assert len(merge_services) == 2


def test_build_team_procedure_graph_marks_terminal_to_start_nodes_when_flag_is_off() -> None:
    doc_alpha = MarkupDocument.model_validate(
        {
            "markup_type": "service",
            "service_name": "Payments",
            "team_name": "Alpha",
            "procedures": [
                {
                    "proc_id": "entry_alpha",
                    "proc_name": "Entry Alpha",
                    "start_block_ids": ["a1"],
                    "end_block_ids": ["a2::end"],
                    "branches": {"a1": ["a2"]},
                },
                {
                    "proc_id": "shared",
                    "proc_name": "Shared",
                    "start_block_ids": ["a3"],
                    "end_block_ids": ["a4::end"],
                    "branches": {"a3": ["a4"]},
                },
            ],
            "procedure_graph": {"entry_alpha": ["shared"], "shared": []},
        }
    )
    doc_beta = MarkupDocument.model_validate(
        {
            "markup_type": "service",
            "service_name": "Loans",
            "team_name": "Beta",
            "procedures": [
                {
                    "proc_id": "shared",
                    "proc_name": "Shared",
                    "start_block_ids": ["b1"],
                    "end_block_ids": ["b2::end"],
                    "branches": {"b1": ["b2"]},
                },
                {
                    "proc_id": "tail_beta",
                    "proc_name": "Tail Beta",
                    "start_block_ids": ["b3"],
                    "end_block_ids": ["b4::end"],
                    "branches": {"b3": ["b4"]},
                },
            ],
            "procedure_graph": {"shared": ["tail_beta"], "tail_beta": []},
        }
    )

    merged = BuildTeamProcedureGraph().build(
        [doc_alpha, doc_beta],
        merge_selected_markups=False,
    )

    proc_ids = [proc.procedure_id for proc in merged.procedures]
    assert len(proc_ids) == 4
    shared_proc_ids = [proc_id for proc_id in proc_ids if proc_id.startswith("shared::doc")]
    assert len(shared_proc_ids) == 2
    for proc_id in shared_proc_ids:
        assert merged.procedure_meta[proc_id]["is_intersection"] is True


def test_build_team_procedure_graph_uses_merge_documents_for_intersections() -> None:
    doc_alpha = MarkupDocument.model_validate(
        {
            "markup_type": "service",
            "service_name": "Payments",
            "team_name": "Alpha",
            "procedures": [
                {
                    "proc_id": "shared",
                    "proc_name": "Shared Flow",
                    "start_block_ids": ["a"],
                    "end_block_ids": ["b::end"],
                    "branches": {"a": ["b"]},
                }
            ],
            "procedure_graph": {"shared": []},
        }
    )
    doc_beta = MarkupDocument.model_validate(
        {
            "markup_type": "service",
            "service_name": "Loans",
            "team_name": "Beta",
            "procedures": [
                {
                    "proc_id": "shared",
                    "proc_name": "Shared Flow",
                    "start_block_ids": ["c"],
                    "end_block_ids": ["d::end"],
                    "branches": {"c": ["d"]},
                }
            ],
            "procedure_graph": {"shared": []},
        }
    )

    merged = BuildTeamProcedureGraph().build([doc_alpha], merge_documents=[doc_alpha, doc_beta])

    meta = merged.procedure_meta["shared"]
    assert meta["is_intersection"] is True
    assert meta["procedure_color"] == "#ffd6d6"
    services = meta["services"]
    assert isinstance(services, list)
    assert len(services) == 1
    merge_services = meta["merge_services"]
    assert isinstance(merge_services, list)
    assert any(
        service.get("team_name") == "Alpha" and service.get("service_name") == "Payments"
        for service in merge_services
    )
    assert any(
        service.get("team_name") == "Beta" and service.get("service_name") == "Loans"
        for service in merge_services
    )


def test_build_team_procedure_graph_uses_merge_documents_procedure_graph() -> None:
    doc_alpha = MarkupDocument.model_validate(
        {
            "markup_type": "service",
            "service_name": "Payments",
            "team_name": "Alpha",
            "procedures": [
                {
                    "proc_id": "shared",
                    "proc_name": "Shared Flow",
                    "start_block_ids": ["a"],
                    "end_block_ids": ["b::end"],
                    "branches": {"a": ["b"]},
                }
            ],
            "procedure_graph": {"shared": []},
        }
    )
    doc_beta = MarkupDocument.model_validate(
        {
            "markup_type": "service",
            "service_name": "Loans",
            "team_name": "Beta",
            "procedures": [],
            "procedure_graph": {"shared": []},
        }
    )

    merged = BuildTeamProcedureGraph().build([doc_alpha], merge_documents=[doc_alpha, doc_beta])

    meta = merged.procedure_meta["shared"]
    assert meta["is_intersection"] is True
    merge_services = meta["merge_services"]
    assert isinstance(merge_services, list)
    assert any(
        service.get("team_name") == "Alpha" and service.get("service_name") == "Payments"
        for service in merge_services
    )
    assert any(
        service.get("team_name") == "Beta" and service.get("service_name") == "Loans"
        for service in merge_services
    )


def test_build_team_procedure_graph_does_not_backfill_unselected_nodes_from_merge_documents() -> (
    None
):
    doc_alpha = MarkupDocument.model_validate(
        {
            "markup_type": "service",
            "service_name": "Payments",
            "team_name": "Alpha",
            "procedures": [
                {
                    "proc_id": "entry",
                    "proc_name": "Entry Flow",
                    "start_block_ids": ["a"],
                    "end_block_ids": [],
                    "branches": {"a": ["b"]},
                }
            ],
            "procedure_graph": {"entry": ["shared"], "shared": []},
        }
    )
    doc_beta = MarkupDocument.model_validate(
        {
            "markup_type": "service",
            "service_name": "Loans",
            "team_name": "Beta",
            "procedures": [
                {
                    "proc_id": "shared",
                    "proc_name": "Shared Flow",
                    "start_block_ids": ["c"],
                    "end_block_ids": ["d::end"],
                    "branches": {"c": ["d"]},
                }
            ],
            "procedure_graph": {"shared": []},
        }
    )

    merged = BuildTeamProcedureGraph().build([doc_alpha], merge_documents=[doc_alpha, doc_beta])

    assert {proc.procedure_id for proc in merged.procedures} == {"entry"}
    assert "shared" not in merged.procedure_meta
    assert merged.procedure_graph.get("entry") == []


def test_build_team_procedure_graph_groups_service_colors_when_palette_exhausted() -> None:
    documents = []
    for idx in range(5):
        documents.append(
            MarkupDocument.model_validate(
                {
                    "markup_type": "service",
                    "service_name": f"Alpha Service {idx}",
                    "team_name": "Alpha",
                    "procedures": [
                        {
                            "proc_id": "shared",
                            "proc_name": "Shared Flow",
                            "start_block_ids": ["a"],
                            "end_block_ids": ["b::end"],
                            "branches": {"a": ["b"]},
                        }
                    ],
                    "procedure_graph": {"shared": []},
                }
            )
        )
    for idx in range(4):
        documents.append(
            MarkupDocument.model_validate(
                {
                    "markup_type": "service",
                    "service_name": f"Beta Service {idx}",
                    "team_name": "Beta",
                    "procedures": [
                        {
                            "proc_id": "shared",
                            "proc_name": "Shared Flow",
                            "start_block_ids": ["c"],
                            "end_block_ids": ["d::end"],
                            "branches": {"c": ["d"]},
                        }
                    ],
                    "procedure_graph": {"shared": []},
                }
            )
        )

    merged = BuildTeamProcedureGraph().build(documents)

    services = merged.procedure_meta["shared"]["services"]
    assert isinstance(services, list)
    colors = {service.get("service_color") for service in services}
    assert colors == set(_SERVICE_COLORS)


def test_build_team_procedure_graph_drops_non_merge_intermediate_without_markers() -> None:
    document = MarkupDocument.model_validate(
        {
            "markup_type": "service",
            "service_name": "Payments",
            "team_name": "Alpha",
            "procedures": [
                {
                    "proc_id": "entry",
                    "proc_name": "Entry",
                    "start_block_ids": ["s1"],
                    "end_block_ids": ["e1::end"],
                    "branches": {"s1": ["e1"]},
                },
                {
                    "proc_id": "bridge",
                    "proc_name": "Bridge",
                    "start_block_ids": [],
                    "end_block_ids": [],
                    "branches": {"m1": ["m2"]},
                },
                {
                    "proc_id": "tail",
                    "proc_name": "Tail",
                    "start_block_ids": ["s2"],
                    "end_block_ids": ["e2::end"],
                    "branches": {"s2": ["e2"]},
                },
            ],
            "procedure_graph": {"entry": ["bridge"], "bridge": ["tail"], "tail": []},
        }
    )

    merged = BuildTeamProcedureGraph().build([document])

    assert {proc.procedure_id for proc in merged.procedures} == {"entry", "tail"}
    assert merged.procedure_graph == {"entry": ["tail"], "tail": []}


def test_build_team_procedure_graph_keeps_merge_intermediate_without_markers() -> None:
    doc_alpha = MarkupDocument.model_validate(
        {
            "markup_type": "service",
            "service_name": "Payments",
            "team_name": "Alpha",
            "procedures": [
                {
                    "proc_id": "entry",
                    "start_block_ids": ["a1"],
                    "end_block_ids": ["a2::end"],
                    "branches": {"a1": ["a2"]},
                },
                {
                    "proc_id": "shared",
                    "start_block_ids": [],
                    "end_block_ids": [],
                    "branches": {"a3": ["a4"]},
                },
                {
                    "proc_id": "tail",
                    "start_block_ids": ["a5"],
                    "end_block_ids": ["a6::end"],
                    "branches": {"a5": ["a6"]},
                },
            ],
            "procedure_graph": {"entry": ["shared"], "shared": ["tail"], "tail": []},
        }
    )
    doc_beta = MarkupDocument.model_validate(
        {
            "markup_type": "service",
            "service_name": "Loans",
            "team_name": "Beta",
            "procedures": [
                {
                    "proc_id": "entry",
                    "start_block_ids": ["b1"],
                    "end_block_ids": ["b2::end"],
                    "branches": {"b1": ["b2"]},
                },
                {
                    "proc_id": "shared",
                    "start_block_ids": [],
                    "end_block_ids": [],
                    "branches": {"b3": ["b4"]},
                },
                {
                    "proc_id": "tail",
                    "start_block_ids": ["b5"],
                    "end_block_ids": ["b6::end"],
                    "branches": {"b5": ["b6"]},
                },
            ],
            "procedure_graph": {"entry": ["shared"], "shared": ["tail"], "tail": []},
        }
    )

    merged = BuildTeamProcedureGraph().build([doc_alpha, doc_beta])

    assert {proc.procedure_id for proc in merged.procedures} == {"entry", "shared", "tail"}
    assert merged.procedure_graph == {"entry": ["shared"], "shared": ["tail"], "tail": []}


def test_build_team_procedure_graph_preserves_connectivity_after_multi_drop() -> None:
    document = MarkupDocument.model_validate(
        {
            "markup_type": "service",
            "service_name": "Payments",
            "team_name": "Alpha",
            "procedures": [
                {
                    "proc_id": "entry",
                    "start_block_ids": ["s1"],
                    "end_block_ids": ["e1::end"],
                    "branches": {"s1": ["e1"]},
                },
                {
                    "proc_id": "middle_1",
                    "start_block_ids": [],
                    "end_block_ids": [],
                    "branches": {"m1": ["m2"]},
                },
                {
                    "proc_id": "middle_2",
                    "start_block_ids": [],
                    "end_block_ids": [],
                    "branches": {"m3": ["m4"]},
                },
                {
                    "proc_id": "alt",
                    "start_block_ids": ["a1"],
                    "end_block_ids": ["a2::end"],
                    "branches": {"a1": ["a2"]},
                },
                {
                    "proc_id": "tail",
                    "start_block_ids": ["t1"],
                    "end_block_ids": ["t2::end"],
                    "branches": {"t1": ["t2"]},
                },
            ],
            "procedure_graph": {
                "entry": ["middle_1", "alt"],
                "middle_1": ["middle_2"],
                "middle_2": ["tail"],
                "alt": ["tail"],
                "tail": [],
            },
        }
    )

    merged = BuildTeamProcedureGraph().build([document])

    assert {proc.procedure_id for proc in merged.procedures} == {"entry", "alt", "tail"}
    assert merged.procedure_graph == {"entry": ["alt", "tail"], "alt": ["tail"], "tail": []}


def test_procedure_graph_panel_colors_match_graph() -> None:
    payload_alpha = {
        "markup_type": "service",
        "service_name": "Payments",
        "team_name": "Alpha",
        "procedures": [
            {
                "proc_id": "p1",
                "proc_name": "Authorize",
                "start_block_ids": ["a"],
                "end_block_ids": ["b::end"],
                "branches": {"a": ["b"]},
            }
        ],
        "procedure_graph": {"p1": []},
    }
    payload_beta = {
        "markup_type": "service",
        "service_name": "Refunds",
        "team_name": "Beta",
        "procedures": [
            {
                "proc_id": "p2",
                "proc_name": "Refund",
                "start_block_ids": ["c"],
                "end_block_ids": ["d::end"],
                "branches": {"c": ["d"]},
            }
        ],
        "procedure_graph": {"p2": []},
    }
    document = BuildTeamProcedureGraph().build(
        [
            MarkupDocument.model_validate(payload_alpha),
            MarkupDocument.model_validate(payload_beta),
        ]
    )

    service_colors: dict[str, str] = {}
    for meta in document.procedure_meta.values():
        services = meta.get("services")
        if not isinstance(services, list):
            continue
        if len(services) == 1 and isinstance(services[0], dict):
            color = services[0].get("service_color")
            if isinstance(color, str):
                assert meta.get("procedure_color") == color
        for service in services:
            if not isinstance(service, dict):
                continue
            service_name = service.get("service_name")
            color = service.get("service_color")
            if isinstance(service_name, str) and isinstance(color, str):
                service_colors[service_name] = color

    layout = ProcedureGraphLayoutEngine()
    plan = layout.build_plan(document)
    service_blocks = []
    for scenario in plan.scenarios:
        service_blocks.extend(
            [block for block in (scenario.procedures_blocks or ()) if block.kind == "service"]
        )
    block_colors = {block.text: block.color for block in service_blocks}
    for service_name, color in service_colors.items():
        assert block_colors.get(service_name) == color

    excal = ProcedureGraphToExcalidrawConverter(layout).convert(document)
    for element in excal.elements:
        meta = element.get("customData", {}).get("cjm", {})
        if element.get("type") != "frame":
            continue
        proc_id = meta.get("procedure_id")
        if not isinstance(proc_id, str):
            continue
        proc_meta = document.procedure_meta.get(proc_id, {})
        services = proc_meta.get("services")
        if not isinstance(services, list) or len(services) != 1:
            continue
        service_color = services[0].get("service_color")
        if isinstance(service_color, str):
            assert element.get("backgroundColor") == service_color


def test_procedure_graph_layout_lists_services_per_component() -> None:
    payload = {
        "markup_type": "service",
        "procedures": [
            {
                "proc_id": "p1",
                "proc_name": "Start Flow",
                "start_block_ids": ["a"],
                "end_block_ids": ["b::end"],
                "branches": {"a": ["b"]},
            },
            {
                "proc_id": "p2",
                "proc_name": "Branch Flow",
                "start_block_ids": ["c"],
                "end_block_ids": ["d::end"],
                "branches": {"c": ["d"]},
            },
            {
                "proc_id": "p3",
                "proc_name": "Shared Flow",
                "start_block_ids": ["e"],
                "end_block_ids": ["f::end"],
                "branches": {"e": ["f"]},
            },
        ],
        "procedure_graph": {"p1": ["p2"], "p2": ["p3"]},
    }
    document = MarkupDocument.model_validate(payload).model_copy(
        update={
            "procedure_meta": {
                "p1": {"team_name": "Alpha", "service_name": "Payments"},
                "p2": {"team_name": "Alpha", "service_name": "Payments"},
                "p3": {"team_name": "Beta", "service_name": "Refunds"},
            }
        }
    )

    layout = ProcedureGraphLayoutEngine()
    plan = layout.build_plan(document)

    assert plan.scenarios
    procedures_text = plan.scenarios[0].procedures_text
    assert "Разметки:" in procedures_text
    assert "Alpha" in procedures_text
    assert "- Payments" in procedures_text
    assert "Beta" in procedures_text
    assert "- Refunds" in procedures_text


def test_procedure_graph_layout_repeats_procedures_for_shared_services() -> None:
    payload = {
        "markup_type": "service",
        "procedures": [
            {
                "proc_id": "p1",
                "proc_name": "Shared Flow",
                "start_block_ids": ["a"],
                "end_block_ids": ["b::end"],
                "branches": {"a": ["b"]},
            }
        ],
        "procedure_graph": {"shared_one": ["shared_two"], "shared_two": []},
    }
    document = MarkupDocument.model_validate(payload).model_copy(
        update={
            "procedure_meta": {
                "p1": {
                    "services": [
                        {"team_name": "Alpha", "service_name": "Payments"},
                        {"team_name": "Beta", "service_name": "Loans"},
                    ]
                }
            }
        }
    )

    layout = ProcedureGraphLayoutEngine()
    plan = layout.build_plan(document)

    assert plan.scenarios
    procedures_text = plan.scenarios[0].procedures_text
    assert "Разметки:" in procedures_text
    assert "Alpha" in procedures_text
    assert "Beta" in procedures_text
    assert procedures_text.count("- Payments") == 1
    assert procedures_text.count("- Loans") == 1


def test_procedure_graph_layout_includes_merge_panel() -> None:
    payload = {
        "markup_type": "service",
        "procedures": [
            {
                "proc_id": "shared",
                "proc_name": "Shared Flow",
                "start_block_ids": ["a"],
                "end_block_ids": ["b::end"],
                "branches": {"a": ["b"]},
            }
        ],
        "procedure_graph": {"shared_one": ["shared_two"], "shared_two": []},
    }
    document = MarkupDocument.model_validate(payload).model_copy(
        update={
            "procedure_meta": {
                "shared": {
                    "is_intersection": True,
                    "team_name": "Alpha",
                    "service_name": "Payments",
                    "services": [
                        {"team_name": "Alpha", "service_name": "Payments"},
                        {"team_name": "Beta", "service_name": "Loans"},
                    ],
                }
            }
        }
    )

    layout = ProcedureGraphLayoutEngine()
    plan = layout.build_plan(document)

    assert plan.scenarios
    scenario = plan.scenarios[0]
    merge_text = scenario.merge_text or ""
    assert "Узлы слияния" in merge_text
    assert "> [Alpha] Payments x [Beta] Loans:" in merge_text
    assert "(1) Shared Flow" in merge_text
    assert scenario.merge_origin is not None
    assert scenario.merge_size is not None
    assert scenario.procedures_origin.y + scenario.procedures_size.height <= scenario.merge_origin.y


def test_procedure_graph_layout_uses_merge_services_for_groups() -> None:
    payload = {
        "markup_type": "service",
        "procedures": [
            {
                "proc_id": "shared",
                "proc_name": "Shared Flow",
                "start_block_ids": ["a"],
                "end_block_ids": ["b::end"],
                "branches": {"a": ["b"]},
            }
        ],
        "procedure_graph": {"shared": []},
    }
    document = MarkupDocument.model_validate(payload).model_copy(
        update={
            "procedure_meta": {
                "shared": {
                    "is_intersection": True,
                    "services": [
                        {"team_name": "Alpha", "service_name": "Payments"},
                    ],
                    "merge_services": [
                        {"team_name": "Alpha", "service_name": "Payments"},
                        {"team_name": "Beta", "service_name": "Loans"},
                    ],
                }
            }
        }
    )

    layout = ProcedureGraphLayoutEngine()
    plan = layout.build_plan(document)

    assert plan.scenarios
    merge_text = plan.scenarios[0].merge_text or ""
    assert "> [Alpha] Payments x [Beta] Loans:" in merge_text


def test_procedure_graph_layout_groups_merge_nodes_by_services() -> None:
    payload = {
        "markup_type": "service",
        "procedures": [
            {
                "proc_id": "shared_one",
                "proc_name": "Shared One",
                "start_block_ids": ["a"],
                "end_block_ids": ["b::end"],
                "branches": {"a": ["b"]},
            },
            {
                "proc_id": "shared_two",
                "proc_name": "Shared Two",
                "start_block_ids": ["c"],
                "end_block_ids": ["d::end"],
                "branches": {"c": ["d"]},
            },
        ],
        "procedure_graph": {"shared_one": ["shared_two"], "shared_two": []},
    }
    document = MarkupDocument.model_validate(payload).model_copy(
        update={
            "procedure_meta": {
                "shared_one": {
                    "is_intersection": True,
                    "services": [
                        {"team_name": "Alpha", "service_name": "Payments"},
                        {"team_name": "Beta", "service_name": "Loans"},
                    ],
                },
                "shared_two": {
                    "is_intersection": True,
                    "services": [
                        {"team_name": "Alpha", "service_name": "Payments"},
                        {"team_name": "Beta", "service_name": "Loans"},
                    ],
                },
            }
        }
    )

    layout = ProcedureGraphLayoutEngine()
    plan = layout.build_plan(document)

    assert plan.scenarios
    merge_text = plan.scenarios[0].merge_text or ""
    assert merge_text.count("> [Alpha] Payments x [Beta] Loans:") == 1
    assert "(1) Shared One" in merge_text
    assert "(2) Shared Two" in merge_text


def test_procedure_graph_layout_groups_chain_merge_nodes_into_single_item() -> None:
    payload = {
        "markup_type": "procedure_graph",
        "procedures": [
            {
                "proc_id": "proc_shared_intake",
                "proc_name": "Intake",
                "start_block_ids": ["a"],
                "end_block_ids": [],
                "branches": {"a": ["b"]},
            },
            {
                "proc_id": "proc_shared_handoff",
                "proc_name": "Intake to routing handoff",
                "start_block_ids": [],
                "end_block_ids": ["c::end"],
                "branches": {"b": ["c"]},
            },
        ],
        "procedure_graph": {
            "proc_shared_intake": ["proc_shared_handoff"],
            "proc_shared_handoff": [],
        },
    }
    chain_group_id = "merge_chain::proc_shared_intake|proc_shared_handoff"
    document = MarkupDocument.model_validate(payload).model_copy(
        update={
            "procedure_meta": {
                "proc_shared_intake": {
                    "is_intersection": True,
                    "merge_chain_group_id": chain_group_id,
                    "merge_chain_members": ["proc_shared_intake", "proc_shared_handoff"],
                    "services": [
                        {"team_name": "Alpha", "service_name": "Payments"},
                        {"team_name": "Beta", "service_name": "Routing"},
                    ],
                },
                "proc_shared_handoff": {
                    "is_intersection": True,
                    "merge_chain_group_id": chain_group_id,
                    "merge_chain_members": ["proc_shared_intake", "proc_shared_handoff"],
                    "services": [
                        {"team_name": "Alpha", "service_name": "Payments"},
                        {"team_name": "Beta", "service_name": "Routing"},
                    ],
                },
            }
        }
    )

    plan = ProcedureGraphLayoutEngine().build_plan(document)
    assert plan.scenarios
    merge_text = plan.scenarios[0].merge_text or ""
    assert "(1) Intake + Intake to routing handoff" in merge_text
    assert "(2)" not in merge_text


def test_procedure_graph_merge_panel_no_group_divider_for_single_group() -> None:
    payload = {
        "markup_type": "procedure_graph",
        "procedures": [
            {
                "proc_id": "shared",
                "proc_name": "Shared Flow",
                "start_block_ids": ["a"],
                "end_block_ids": ["b::end"],
                "branches": {"a": ["b"]},
            }
        ],
        "procedure_graph": {},
    }
    document = MarkupDocument.model_validate(payload).model_copy(
        update={
            "procedure_meta": {
                "shared": {
                    "is_intersection": True,
                    "services": [
                        {"team_name": "Alpha", "service_name": "Payments"},
                        {"team_name": "Beta", "service_name": "Loans"},
                    ],
                }
            }
        }
    )

    layout = ProcedureGraphLayoutEngine()
    excal = ProcedureGraphToExcalidrawConverter(layout).convert(document)

    underlines = [
        element
        for element in excal.elements
        if element.get("customData", {}).get("cjm", {}).get("role") == "scenario_merge_underline"
    ]
    assert not underlines


def test_procedure_graph_merge_panel_adds_group_divider_for_multiple_groups() -> None:
    payload = {
        "markup_type": "procedure_graph",
        "procedures": [
            {
                "proc_id": "shared_one",
                "proc_name": "Shared One",
                "start_block_ids": ["a"],
                "end_block_ids": ["b::end"],
                "branches": {"a": ["b"]},
            },
            {
                "proc_id": "shared_two",
                "proc_name": "Shared Two",
                "start_block_ids": ["c"],
                "end_block_ids": ["d::end"],
                "branches": {"c": ["d"]},
            },
        ],
        "procedure_graph": {"shared_one": ["shared_two"], "shared_two": []},
    }
    document = MarkupDocument.model_validate(payload).model_copy(
        update={
            "procedure_meta": {
                "shared_one": {
                    "is_intersection": True,
                    "services": [
                        {"team_name": "Alpha", "service_name": "Payments"},
                        {"team_name": "Beta", "service_name": "Loans"},
                    ],
                },
                "shared_two": {
                    "is_intersection": True,
                    "services": [
                        {"team_name": "Gamma", "service_name": "Investments"},
                        {"team_name": "Delta", "service_name": "Support"},
                    ],
                },
            }
        }
    )

    layout = ProcedureGraphLayoutEngine()
    excal = ProcedureGraphToExcalidrawConverter(layout).convert(document)

    underlines = [
        element
        for element in excal.elements
        if element.get("customData", {}).get("cjm", {}).get("role") == "scenario_merge_underline"
    ]
    assert len(underlines) == 1


def test_procedure_graph_separator_below_services_block() -> None:
    payload = {
        "markup_type": "service",
        "procedures": [
            {
                "proc_id": "p1",
                "proc_name": "Alpha Flow",
                "start_block_ids": ["a"],
                "end_block_ids": ["b::end"],
                "branches": {"a": ["b"]},
            },
            {
                "proc_id": "p2",
                "proc_name": "Beta Flow",
                "start_block_ids": ["c"],
                "end_block_ids": ["d::end"],
                "branches": {"c": ["d"]},
            },
        ],
        "procedure_graph": {},
    }
    document = MarkupDocument.model_validate(payload).model_copy(
        update={
            "procedure_meta": {
                "p1": {"team_name": "Alpha", "service_name": "Payments"},
                "p2": {"team_name": "Beta", "service_name": "Refunds"},
            }
        }
    )

    layout = ProcedureGraphLayoutEngine()
    plan = layout.build_plan(document)

    assert plan.separators
    assert plan.scenarios
    top_scenario = min(plan.scenarios, key=lambda scenario: scenario.origin.y)
    separator_y = plan.separators[0].start.y
    scenario_bottom = top_scenario.procedures_origin.y + top_scenario.procedures_size.height
    assert separator_y > scenario_bottom


def test_procedure_graph_converter_adds_stats_and_label() -> None:
    payload = {
        "markup_type": "service",
        "procedures": [
            {
                "proc_id": "proc_internal",
                "proc_name": "Payments Graph",
                "start_block_ids": ["s1", "s2"],
                "end_block_ids": ["e1::end"],
                "branches": {"s1": ["e1", "e2"], "s2": ["e1"]},
            }
        ],
        "procedure_graph": {},
    }
    document = MarkupDocument.model_validate(payload)
    layout = ProcedureGraphLayoutEngine(LayoutConfig(block_size=Size(280.0, 180.0), gap_y=120.0))
    excal = ProcedureGraphToExcalidrawConverter(layout).convert(document)

    frame = next(
        element
        for element in excal.elements
        if element.get("type") == "frame"
        and element.get("customData", {}).get("cjm", {}).get("procedure_id") == "proc_internal"
    )
    assert frame.get("name") == "Payments Graph"

    stats = [
        element
        for element in excal.elements
        if element.get("type") == "ellipse"
        and element.get("customData", {}).get("cjm", {}).get("role") == "procedure_stat"
    ]
    assert len(stats) == 3
    counts = {
        stat["customData"]["cjm"]["stat_type"]: stat["customData"]["cjm"]["stat_value"]
        for stat in stats
    }
    assert counts["start"] == 2
    assert counts["branch"] == 3
    assert counts["end"] == 1

    stat_texts = {
        element.get("text")
        for element in excal.elements
        if element.get("type") == "text"
        and element.get("customData", {}).get("cjm", {}).get("role") == "procedure_stat"
    }
    assert "2 starts" in stat_texts
    assert "3 branches" in stat_texts
    assert "1 end" in stat_texts


def test_procedure_graph_converter_renders_postpone_stats_separately() -> None:
    payload = {
        "markup_type": "service",
        "procedures": [
            {
                "proc_id": "proc_internal",
                "proc_name": "Payments Graph",
                "start_block_ids": ["s1"],
                "end_block_ids": ["e1::end", "e2::postpone"],
                "branches": {"s1": ["e1", "e2"]},
            }
        ],
        "procedure_graph": {},
    }
    document = MarkupDocument.model_validate(payload)
    layout = ProcedureGraphLayoutEngine(LayoutConfig(block_size=Size(280.0, 180.0), gap_y=120.0))
    excal = ProcedureGraphToExcalidrawConverter(layout).convert(document)

    stats = [
        element
        for element in excal.elements
        if element.get("type") == "ellipse"
        and element.get("customData", {}).get("cjm", {}).get("role") == "procedure_stat"
    ]
    assert len(stats) == 4
    counts = {
        stat["customData"]["cjm"]["stat_type"]: stat["customData"]["cjm"]["stat_value"]
        for stat in stats
    }
    assert counts["start"] == 1
    assert counts["branch"] == 2
    assert counts["end"] == 1
    assert counts["postpone"] == 1

    stat_texts = {
        element.get("text")
        for element in excal.elements
        if element.get("type") == "text"
        and element.get("customData", {}).get("cjm", {}).get("role") == "procedure_stat"
    }
    assert "1 start" in stat_texts
    assert "2 branches" in stat_texts
    assert "1 end" in stat_texts
    assert "1 postpone" in stat_texts


def test_procedure_graph_converter_skips_zero_stats() -> None:
    payload = {
        "markup_type": "service",
        "procedures": [
            {
                "proc_id": "proc_zero",
                "proc_name": "Zero Stats",
                "start_block_ids": [],
                "end_block_ids": [],
                "branches": {},
            }
        ],
        "procedure_graph": {},
    }
    document = MarkupDocument.model_validate(payload)
    layout = ProcedureGraphLayoutEngine(LayoutConfig(block_size=Size(260.0, 140.0)))
    excal = ProcedureGraphToExcalidrawConverter(layout).convert(document)

    stats = [
        element
        for element in excal.elements
        if element.get("customData", {}).get("cjm", {}).get("role") == "procedure_stat"
    ]
    assert not stats


def test_procedure_graph_converter_uses_procedure_color() -> None:
    payload = {
        "markup_type": "procedure_graph",
        "procedures": [
            {
                "proc_id": "p1",
                "proc_name": "Payments Graph",
                "start_block_ids": ["s1"],
                "end_block_ids": ["e1::end"],
                "branches": {"s1": ["e1"]},
            }
        ],
        "procedure_graph": {},
    }
    document = MarkupDocument.model_validate(payload).model_copy(
        update={"procedure_meta": {"p1": {"procedure_color": "#d9f5ff"}}}
    )
    layout = ProcedureGraphLayoutEngine(LayoutConfig(block_size=Size(280.0, 140.0)))

    excal = ProcedureGraphToExcalidrawConverter(layout).convert(document)
    excal_frame = next(
        element
        for element in excal.elements
        if element.get("type") == "frame"
        and element.get("customData", {}).get("cjm", {}).get("procedure_id") == "p1"
    )
    assert excal_frame.get("backgroundColor") == "#d9f5ff"

    unidraw_scene = ProcedureGraphToUnidrawConverter(layout).convert(document)
    unidraw_frame = next(
        element
        for element in unidraw_scene.elements
        if element.get("type") == "frame" and element.get("cjm", {}).get("procedure_id") == "p1"
    )
    assert unidraw_frame.get("style", {}).get("fc") == "#d9f5ff"


def test_procedure_graph_converter_renders_service_zones_for_multiple_services() -> None:
    payload = {
        "markup_type": "procedure_graph",
        "procedures": [
            {
                "proc_id": "p1",
                "proc_name": "Payments",
                "start_block_ids": ["a"],
                "end_block_ids": ["b::end"],
                "branches": {"a": ["b"]},
            },
            {
                "proc_id": "p2",
                "proc_name": "Refunds",
                "start_block_ids": ["c"],
                "end_block_ids": ["d::end"],
                "branches": {"c": ["d"]},
            },
        ],
        "procedure_graph": {"p1": ["p2"], "p2": []},
    }
    document = MarkupDocument.model_validate(payload).model_copy(
        update={
            "procedure_meta": {
                "p1": {
                    "team_name": "Alpha",
                    "service_name": "Payments",
                    "procedure_color": "#d9f5ff",
                    "services": [
                        {
                            "team_name": "Alpha",
                            "service_name": "Payments",
                            "service_color": "#d9f5ff",
                        }
                    ],
                },
                "p2": {
                    "team_name": "Beta",
                    "service_name": "Refunds",
                    "procedure_color": "#e3f7d9",
                    "services": [
                        {
                            "team_name": "Beta",
                            "service_name": "Refunds",
                            "service_color": "#e3f7d9",
                        }
                    ],
                },
            }
        }
    )
    layout = ProcedureGraphLayoutEngine()
    excal = ProcedureGraphToExcalidrawConverter(layout).convert(document)

    zones = [
        element
        for element in excal.elements
        if element.get("customData", {}).get("cjm", {}).get("role") == "service_zone"
    ]
    assert len(zones) == 2
    assert all(zone.get("strokeStyle") == "dashed" for zone in zones)
    assert all(zone.get("backgroundColor") == "transparent" for zone in zones)
    assert all(zone.get("roundness") == {"type": 3} for zone in zones)
    colors = {
        zone.get("customData", {}).get("cjm", {}).get("service_name"): zone.get("strokeColor")
        for zone in zones
    }
    assert colors.get("Payments") == "#d9f5ff"
    assert colors.get("Refunds") == "#e3f7d9"

    labels = [
        element
        for element in excal.elements
        if element.get("customData", {}).get("cjm", {}).get("role") == "service_zone_label"
    ]
    label_texts = {label.get("text", "").replace("\n", " ").strip() for label in labels}
    assert "Payments" in label_texts
    assert "Refunds" in label_texts
    label_colors = {label.get("text", "").strip(): label.get("strokeColor") for label in labels}
    assert label_colors.get("Payments") == "#d9f5ff"
    assert label_colors.get("Refunds") == "#e3f7d9"
    assert all(label.get("fontStyle") == "bold" for label in labels)
    assert all(
        label.get("fontFamily") == EXCALIDRAW_SERVICE_ZONE_LABEL_FONT_FAMILY for label in labels
    )

    unidraw_scene = ProcedureGraphToUnidrawConverter(layout).convert(document)
    unidraw_zones = [
        element
        for element in unidraw_scene.elements
        if element.get("cjm", {}).get("role") == "service_zone"
    ]
    assert unidraw_zones
    assert all(zone.get("style", {}).get("sc") == "#000000" for zone in unidraw_zones)
    assert all(zone.get("style", {}).get("ss") == "da" for zone in unidraw_zones)

    largest_zone = max(
        unidraw_zones,
        key=lambda zone: zone["size"]["width"] * zone["size"]["height"],
    )
    zone_layers = [
        int(zone["zIndex"]) for zone in unidraw_zones if isinstance(zone.get("zIndex"), int)
    ]
    assert zone_layers
    assert largest_zone.get("zIndex") == min(zone_layers)

    unidraw_label_panels = [
        element
        for element in unidraw_scene.elements
        if element.get("cjm", {}).get("role") == "service_zone_label_panel"
    ]
    assert len(unidraw_label_panels) == 2
    panel_colors = {
        panel.get("cjm", {}).get("service_name"): panel.get("style", {}).get("fc")
        for panel in unidraw_label_panels
    }
    assert panel_colors.get("Payments") == "#d9f5ff"
    assert panel_colors.get("Refunds") == "#e3f7d9"
    assert all(panel.get("style", {}).get("sc") == "#000000" for panel in unidraw_label_panels)

    unidraw_labels = [
        element
        for element in unidraw_scene.elements
        if element.get("cjm", {}).get("role") == "service_zone_label"
    ]
    assert unidraw_labels
    assert all(label.get("style", {}).get("tc") == "#000000" for label in unidraw_labels)
    assert all(
        label.get("style", {}).get("tff") == UNIDRAW_SERVICE_ZONE_LABEL_FONT_FAMILY
        for label in unidraw_labels
    )

    frame_layers = [
        int(element["zIndex"])
        for element in unidraw_scene.elements
        if element.get("cjm", {}).get("role") == "frame" and isinstance(element.get("zIndex"), int)
    ]
    assert frame_layers
    frame_front = min(frame_layers)
    panel_layers = [
        int(panel["zIndex"])
        for panel in unidraw_label_panels
        if isinstance(panel.get("zIndex"), int)
    ]
    label_layers = [
        int(label["zIndex"]) for label in unidraw_labels if isinstance(label.get("zIndex"), int)
    ]
    assert len(panel_layers) == len(unidraw_label_panels)
    assert len(label_layers) == len(unidraw_labels)
    assert all(layer < frame_front for layer in panel_layers)
    assert all(layer < frame_front for layer in label_layers)


def test_procedure_graph_unidraw_service_zone_ids_are_unique_across_components() -> None:
    payload = {
        "markup_type": "procedure_graph",
        "procedures": [
            {
                "proc_id": "p1",
                "proc_name": "Component 1 A",
                "start_block_ids": ["a1"],
                "end_block_ids": ["a2::end"],
                "branches": {"a1": ["a2"]},
            },
            {
                "proc_id": "p2",
                "proc_name": "Component 1 B",
                "start_block_ids": ["b1"],
                "end_block_ids": ["b2::end"],
                "branches": {"b1": ["b2"]},
            },
            {
                "proc_id": "p3",
                "proc_name": "Component 2 A",
                "start_block_ids": ["c1"],
                "end_block_ids": ["c2::end"],
                "branches": {"c1": ["c2"]},
            },
            {
                "proc_id": "p4",
                "proc_name": "Component 2 C",
                "start_block_ids": ["d1"],
                "end_block_ids": ["d2::end"],
                "branches": {"d1": ["d2"]},
            },
        ],
        "procedure_graph": {"p1": ["p2"], "p2": [], "p3": ["p4"], "p4": []},
    }
    document = MarkupDocument.model_validate(payload).model_copy(
        update={
            "procedure_meta": {
                "p1": {
                    "team_name": "Alpha",
                    "service_name": "Payments",
                    "procedure_color": "#d9f5ff",
                    "services": [
                        {
                            "team_name": "Alpha",
                            "service_name": "Payments",
                            "service_color": "#d9f5ff",
                        }
                    ],
                },
                "p2": {
                    "team_name": "Beta",
                    "service_name": "Refunds",
                    "procedure_color": "#e3f7d9",
                    "services": [
                        {
                            "team_name": "Beta",
                            "service_name": "Refunds",
                            "service_color": "#e3f7d9",
                        }
                    ],
                },
                "p3": {
                    "team_name": "Alpha",
                    "service_name": "Payments",
                    "procedure_color": "#d9f5ff",
                    "services": [
                        {
                            "team_name": "Alpha",
                            "service_name": "Payments",
                            "service_color": "#d9f5ff",
                        }
                    ],
                },
                "p4": {
                    "team_name": "Gamma",
                    "service_name": "Disputes",
                    "procedure_color": "#f7e9d9",
                    "services": [
                        {
                            "team_name": "Gamma",
                            "service_name": "Disputes",
                            "service_color": "#f7e9d9",
                        }
                    ],
                },
            }
        }
    )
    layout = ProcedureGraphLayoutEngine()
    scene = ProcedureGraphToUnidrawConverter(layout).convert(document)

    element_ids = [str(element.get("id")) for element in scene.elements if element.get("id")]
    assert len(element_ids) == len(set(element_ids))

    payments_zone_ids = {
        str(element.get("id"))
        for element in scene.elements
        if element.get("cjm", {}).get("service_name") == "Payments"
        and element.get("cjm", {}).get("role")
        in {"service_zone", "service_zone_label_panel", "service_zone_label"}
    }
    assert len(payments_zone_ids) == 6


def test_procedure_graph_converter_uses_single_highlight_for_chain_group() -> None:
    payload = {
        "markup_type": "procedure_graph",
        "procedures": [
            {
                "proc_id": "proc_shared_intake",
                "proc_name": "Intake",
                "start_block_ids": ["a"],
                "end_block_ids": [],
                "branches": {"a": ["b"]},
            },
            {
                "proc_id": "proc_shared_handoff",
                "proc_name": "Intake to routing handoff",
                "start_block_ids": [],
                "end_block_ids": ["c::end"],
                "branches": {"b": ["c"]},
            },
        ],
        "procedure_graph": {
            "proc_shared_intake": ["proc_shared_handoff"],
            "proc_shared_handoff": [],
        },
    }
    chain_group_id = "merge_chain::proc_shared_intake|proc_shared_handoff"
    document = MarkupDocument.model_validate(payload).model_copy(
        update={
            "procedure_meta": {
                "proc_shared_intake": {
                    "is_intersection": True,
                    "merge_chain_group_id": chain_group_id,
                    "merge_chain_members": ["proc_shared_intake", "proc_shared_handoff"],
                    "services": [
                        {"team_name": "Alpha", "service_name": "Payments"},
                        {"team_name": "Beta", "service_name": "Routing"},
                    ],
                },
                "proc_shared_handoff": {
                    "is_intersection": True,
                    "merge_chain_group_id": chain_group_id,
                    "merge_chain_members": ["proc_shared_intake", "proc_shared_handoff"],
                    "services": [
                        {"team_name": "Alpha", "service_name": "Payments"},
                        {"team_name": "Beta", "service_name": "Routing"},
                    ],
                },
            }
        }
    )

    scene = ProcedureGraphToExcalidrawConverter(ProcedureGraphLayoutEngine()).convert(document)
    highlights = [
        element
        for element in scene.elements
        if element.get("customData", {}).get("cjm", {}).get("role") == "intersection_highlight"
    ]
    assert len(highlights) == 1
    marker_labels = [
        element.get("text")
        for element in scene.elements
        if element.get("customData", {}).get("cjm", {}).get("role") == "intersection_index_label"
    ]
    assert marker_labels == ["1"]


def test_procedure_graph_converter_highlights_merge_nodes_in_red() -> None:
    payload = {
        "markup_type": "procedure_graph",
        "procedures": [
            {
                "proc_id": "shared",
                "proc_name": "Shared Flow",
                "start_block_ids": ["a"],
                "end_block_ids": ["b::end"],
                "branches": {"a": ["b"]},
            }
        ],
        "procedure_graph": {},
    }
    document = MarkupDocument.model_validate(payload).model_copy(
        update={
            "procedure_meta": {
                "shared": {
                    "is_intersection": True,
                    "services": [
                        {"team_name": "Alpha", "service_name": "Payments"},
                        {"team_name": "Beta", "service_name": "Loans"},
                    ],
                }
            }
        }
    )
    layout = ProcedureGraphLayoutEngine()

    excal = ProcedureGraphToExcalidrawConverter(layout).convert(document)
    merge_panel = next(
        element
        for element in excal.elements
        if element.get("customData", {}).get("cjm", {}).get("role") == "scenario_merge_panel"
    )
    assert merge_panel.get("backgroundColor") == "#ff2d2d"
    assert merge_panel.get("strokeColor") == "#ff2d2d"

    highlight = next(
        element
        for element in excal.elements
        if element.get("customData", {}).get("cjm", {}).get("role") == "intersection_highlight"
    )
    assert highlight.get("strokeColor") == "#ff2d2d"

    pointer = next(
        element
        for element in excal.elements
        if element.get("customData", {}).get("cjm", {}).get("role") == "intersection_pointer"
    )
    assert pointer.get("strokeColor") == "#ff2d2d"

    marker = next(
        element
        for element in excal.elements
        if element.get("customData", {}).get("cjm", {}).get("role") == "intersection_index_marker"
    )
    assert marker.get("strokeColor") == "#ff2d2d"
    label = next(
        element
        for element in excal.elements
        if element.get("customData", {}).get("cjm", {}).get("role") == "intersection_index_label"
    )
    assert label.get("strokeColor") == "#ff2d2d"
    assert label.get("text") == "1"

    unidraw_scene = ProcedureGraphToUnidrawConverter(layout).convert(document)
    unidraw_frame = next(
        element
        for element in unidraw_scene.elements
        if element.get("type") == "frame" and element.get("cjm", {}).get("procedure_id") == "shared"
    )
    assert unidraw_frame.get("style", {}).get("fc") == "transparent"

    unidraw_marker = next(
        element
        for element in unidraw_scene.elements
        if element.get("cjm", {}).get("role") == "intersection_index_marker"
    )
    assert unidraw_marker.get("style", {}).get("ss") == "s"

    unidraw_highlight = next(
        element
        for element in unidraw_scene.elements
        if element.get("cjm", {}).get("role") == "intersection_highlight"
    )
    assert unidraw_highlight.get("style", {}).get("ss") == "da"

    unidraw_label = next(
        element
        for element in unidraw_scene.elements
        if element.get("cjm", {}).get("role") == "intersection_index_label"
    )
    assert float(unidraw_label.get("style", {}).get("tfs", 0.0)) >= 24.0
    marker_center_x = unidraw_marker["position"]["x"] + unidraw_marker["size"]["width"] / 2
    marker_center_y = unidraw_marker["position"]["y"] + unidraw_marker["size"]["height"] / 2
    label_center_x = unidraw_label["position"]["x"] + unidraw_label["size"]["width"] / 2
    label_center_y = unidraw_label["position"]["y"] + unidraw_label["size"]["height"] / 2
    assert abs(label_center_x - marker_center_x) < 0.5
    assert abs(label_center_y - marker_center_y) < 0.5


def test_procedure_graph_layout_zones_include_shared_procedures() -> None:
    payload = {
        "markup_type": "procedure_graph",
        "procedures": [
            {
                "proc_id": "shared",
                "proc_name": "Shared Flow",
                "start_block_ids": ["a"],
                "end_block_ids": ["b::end"],
                "branches": {"a": ["b"]},
            },
            {
                "proc_id": "p_alpha",
                "proc_name": "Alpha Only",
                "start_block_ids": ["c"],
                "end_block_ids": ["d::end"],
                "branches": {"c": ["d"]},
            },
            {
                "proc_id": "p_beta",
                "proc_name": "Beta Only",
                "start_block_ids": ["e"],
                "end_block_ids": ["f::end"],
                "branches": {"e": ["f"]},
            },
        ],
        "procedure_graph": {"shared": ["p_alpha"], "p_alpha": [], "p_beta": []},
    }
    document = MarkupDocument.model_validate(payload).model_copy(
        update={
            "procedure_meta": {
                "shared": {
                    "services": [
                        {
                            "team_name": "Alpha",
                            "service_name": "Payments",
                            "service_color": "#d9f5ff",
                        },
                        {
                            "team_name": "Beta",
                            "service_name": "Loans",
                            "service_color": "#e3f7d9",
                        },
                    ]
                },
                "p_alpha": {
                    "team_name": "Alpha",
                    "service_name": "Payments",
                    "procedure_color": "#d9f5ff",
                },
                "p_beta": {
                    "team_name": "Beta",
                    "service_name": "Loans",
                    "procedure_color": "#e3f7d9",
                },
            }
        }
    )

    plan = ProcedureGraphLayoutEngine().build_plan(document)
    zones = {zone.service_name: zone for zone in plan.service_zones}
    assert "Payments" in zones
    assert "Loans" in zones
    assert "shared" in zones["Payments"].procedure_ids
    assert "shared" in zones["Loans"].procedure_ids

    frame_lookup = {frame.procedure_id: frame for frame in plan.frames}
    for zone in zones.values():
        for proc_id in zone.procedure_ids:
            frame = frame_lookup[proc_id]
            assert zone.origin.x <= frame.origin.x
            assert zone.origin.y <= frame.origin.y
            assert frame.origin.x + frame.size.width <= zone.origin.x + zone.size.width
            assert frame.origin.y + frame.size.height <= zone.origin.y + zone.size.height


def test_procedure_graph_layout_aligns_zone_top_with_scenario() -> None:
    payload = {
        "markup_type": "procedure_graph",
        "procedures": [
            {
                "proc_id": "p1",
                "proc_name": "Payments",
                "start_block_ids": ["a"],
                "end_block_ids": ["b::end"],
                "branches": {"a": ["b"]},
            },
            {
                "proc_id": "p2",
                "proc_name": "Loans",
                "start_block_ids": ["c"],
                "end_block_ids": ["d::end"],
                "branches": {"c": ["d"]},
            },
        ],
        "procedure_graph": {"p1": ["p2"], "p2": []},
    }
    document = MarkupDocument.model_validate(payload).model_copy(
        update={
            "procedure_meta": {
                "p1": {"team_name": "Alpha", "service_name": "Payments"},
                "p2": {"team_name": "Beta", "service_name": "Loans"},
            }
        }
    )

    plan = ProcedureGraphLayoutEngine().build_plan(document)

    assert plan.scenarios
    assert plan.service_zones
    top_zone = min(plan.service_zones, key=lambda zone: zone.origin.y)
    top_scenario = min(plan.scenarios, key=lambda scenario: scenario.origin.y)
    assert abs(top_zone.origin.y - top_scenario.origin.y) <= 1e-6


def test_procedure_graph_layout_expands_outer_service_zone() -> None:
    payload = {
        "markup_type": "procedure_graph",
        "procedures": [
            {
                "proc_id": "shared",
                "proc_name": "Shared Flow",
                "start_block_ids": ["a"],
                "end_block_ids": ["b::end"],
                "branches": {"a": ["b"]},
            },
            {
                "proc_id": "p_alpha",
                "proc_name": "Alpha Only",
                "start_block_ids": ["c"],
                "end_block_ids": ["d::end"],
                "branches": {"c": ["d"]},
            },
        ],
        "procedure_graph": {"shared": ["p_alpha"], "p_alpha": []},
    }
    document = MarkupDocument.model_validate(payload).model_copy(
        update={
            "procedure_meta": {
                "shared": {
                    "services": [
                        {
                            "team_name": "Alpha",
                            "service_name": "Payments",
                            "service_color": "#d9f5ff",
                        },
                        {
                            "team_name": "Beta",
                            "service_name": "Loans",
                            "service_color": "#e3f7d9",
                        },
                    ]
                },
                "p_alpha": {
                    "team_name": "Alpha",
                    "service_name": "Payments",
                    "procedure_color": "#d9f5ff",
                },
            }
        }
    )

    plan = ProcedureGraphLayoutEngine().build_plan(document)
    zones = {zone.service_name: zone for zone in plan.service_zones}
    payments = zones["Payments"]
    loans = zones["Loans"]

    assert payments.origin.x < loans.origin.x
    assert payments.origin.y < loans.origin.y
    assert payments.origin.x + payments.size.width > loans.origin.x + loans.size.width
    assert payments.origin.y + payments.size.height > loans.origin.y + loans.size.height
    assert payments.label_origin.y < loans.label_origin.y


def test_procedure_graph_layout_prefers_linear_for_simple_graph() -> None:
    payload = {
        "markup_type": "procedure_graph",
        "procedures": [
            {
                "proc_id": "p1",
                "proc_name": "Step 1",
                "start_block_ids": ["a"],
                "end_block_ids": ["b::end"],
                "branches": {"a": ["b"]},
            },
            {
                "proc_id": "p2",
                "proc_name": "Step 2",
                "start_block_ids": ["c"],
                "end_block_ids": ["d::end"],
                "branches": {"c": ["d"]},
            },
            {
                "proc_id": "p3",
                "proc_name": "Step 3",
                "start_block_ids": ["e"],
                "end_block_ids": ["f::end"],
                "branches": {"e": ["f"]},
            },
            {
                "proc_id": "p4",
                "proc_name": "Step 4",
                "start_block_ids": ["g"],
                "end_block_ids": ["h::end"],
                "branches": {"g": ["h"]},
            },
        ],
        "procedure_graph": {"p1": ["p2"], "p2": ["p3"], "p3": ["p4"], "p4": []},
    }
    document = MarkupDocument.model_validate(payload).model_copy(
        update={
            "procedure_meta": {
                "p1": {"team_name": "Alpha", "service_name": "Payments"},
                "p2": {"team_name": "Alpha", "service_name": "Payments"},
                "p3": {"team_name": "Beta", "service_name": "Loans"},
                "p4": {"team_name": "Beta", "service_name": "Loans"},
            }
        }
    )
    plan = ProcedureGraphLayoutEngine().build_plan(document)
    y_positions = {frame.origin.y for frame in plan.frames}
    assert len(y_positions) == 1


def test_procedure_graph_layout_uses_bands_when_linear_crosses() -> None:
    payload = {
        "markup_type": "procedure_graph",
        "procedures": [
            {
                "proc_id": "p1",
                "proc_name": "Alpha Start",
                "start_block_ids": ["a"],
                "end_block_ids": ["b::end"],
                "branches": {"a": ["b"]},
            },
            {
                "proc_id": "p2",
                "proc_name": "Beta Start",
                "start_block_ids": ["c"],
                "end_block_ids": ["d::end"],
                "branches": {"c": ["d"]},
            },
            {
                "proc_id": "p3",
                "proc_name": "Beta End",
                "start_block_ids": ["e"],
                "end_block_ids": ["f::end"],
                "branches": {"e": ["f"]},
            },
            {
                "proc_id": "p4",
                "proc_name": "Alpha End",
                "start_block_ids": ["g"],
                "end_block_ids": ["h::end"],
                "branches": {"g": ["h"]},
            },
        ],
        "procedure_graph": {
            "p3": [],
            "p1": ["p4"],
            "p2": ["p3"],
            "p4": [],
        },
    }
    document = MarkupDocument.model_validate(payload).model_copy(
        update={
            "procedure_meta": {
                "p1": {"team_name": "Alpha", "service_name": "Payments"},
                "p4": {"team_name": "Alpha", "service_name": "Payments"},
                "p2": {"team_name": "Beta", "service_name": "Loans"},
                "p3": {"team_name": "Beta", "service_name": "Loans"},
            }
        }
    )

    plan = ProcedureGraphLayoutEngine().build_plan(document)
    frame_lookup = {frame.procedure_id: frame for frame in plan.frames}
    service_ranges: dict[str, tuple[float, float]] = {}
    for proc_id, meta in document.procedure_meta.items():
        service_name = str(meta.get("service_name"))
        frame = frame_lookup[proc_id]
        min_y, max_y = service_ranges.get(service_name, (frame.origin.y, frame.origin.y))
        min_y = min(min_y, frame.origin.y)
        max_y = max(max_y, frame.origin.y + frame.size.height)
        service_ranges[service_name] = (min_y, max_y)

    payments = service_ranges.get("Payments")
    loans = service_ranges.get("Loans")
    assert payments is not None
    assert loans is not None
    assert payments[1] < loans[0] or loans[1] < payments[0]


def test_procedure_graph_zones_avoid_partial_overlap_in_layout_and_renderers() -> None:
    payload = {
        "markup_type": "procedure_graph",
        "procedures": [
            {
                "proc_id": "p1",
                "proc_name": "A1",
                "start_block_ids": ["a1"],
                "end_block_ids": ["a2::end"],
                "branches": {"a1": ["a2"]},
            },
            {
                "proc_id": "p2",
                "proc_name": "B1",
                "start_block_ids": ["b1"],
                "end_block_ids": ["b2::end"],
                "branches": {"b1": ["b2"]},
            },
            {
                "proc_id": "p3",
                "proc_name": "A2",
                "start_block_ids": ["c1"],
                "end_block_ids": ["c2::end"],
                "branches": {"c1": ["c2"]},
            },
            {
                "proc_id": "p4",
                "proc_name": "B2",
                "start_block_ids": ["d1"],
                "end_block_ids": ["d2::end"],
                "branches": {"d1": ["d2"]},
            },
        ],
        "procedure_graph": {"p1": ["p2"], "p2": ["p3"], "p3": ["p4"], "p4": []},
    }
    document = MarkupDocument.model_validate(payload).model_copy(
        update={
            "procedure_meta": {
                "p1": {"team_name": "Alpha", "service_name": "Payments"},
                "p2": {"team_name": "Beta", "service_name": "Loans"},
                "p3": {"team_name": "Alpha", "service_name": "Payments"},
                "p4": {"team_name": "Beta", "service_name": "Loans"},
            }
        }
    )
    layout = ProcedureGraphLayoutEngine()

    def assert_no_partial_overlap(rects: list[tuple[float, float, float, float]]) -> None:
        eps = 1e-6
        for idx, (ax, ay, aw, ah) in enumerate(rects):
            ar = ax + aw
            ab = ay + ah
            for bx, by, bw, bh in rects[idx + 1 :]:
                br = bx + bw
                bb = by + bh
                overlap_x = min(ar, br) - max(ax, bx)
                overlap_y = min(ab, bb) - max(ay, by)
                if overlap_x <= eps or overlap_y <= eps:
                    continue
                a_contains_b = (
                    ax <= bx + eps and ay <= by + eps and ar >= br - eps and ab >= bb - eps
                )
                b_contains_a = (
                    bx <= ax + eps and by <= ay + eps and br >= ar - eps and bb >= ab - eps
                )
                assert a_contains_b or b_contains_a

    plan = layout.build_plan(document)
    layout_rects = [
        (zone.origin.x, zone.origin.y, zone.size.width, zone.size.height)
        for zone in plan.service_zones
    ]
    assert_no_partial_overlap(layout_rects)

    excal_scene = ProcedureGraphToExcalidrawConverter(layout).convert(document)
    excal_rects = [
        (
            float(zone.get("x", 0.0)),
            float(zone.get("y", 0.0)),
            float(zone.get("width", 0.0)),
            float(zone.get("height", 0.0)),
        )
        for zone in excal_scene.elements
        if zone.get("customData", {}).get("cjm", {}).get("role") == "service_zone"
    ]
    assert excal_rects
    assert_no_partial_overlap(excal_rects)

    unidraw_scene = ProcedureGraphToUnidrawConverter(layout).convert(document)
    unidraw_rects = [
        (
            float(zone.get("position", {}).get("x", 0.0)),
            float(zone.get("position", {}).get("y", 0.0)),
            float(zone.get("size", {}).get("width", 0.0)),
            float(zone.get("size", {}).get("height", 0.0)),
        )
        for zone in unidraw_scene.elements
        if zone.get("cjm", {}).get("role") == "service_zone"
    ]
    assert unidraw_rects
    assert_no_partial_overlap(unidraw_rects)


def test_procedure_graph_converter_skips_service_zones_for_single_service() -> None:
    payload = {
        "markup_type": "procedure_graph",
        "procedures": [
            {
                "proc_id": "p1",
                "proc_name": "Payments",
                "start_block_ids": ["a"],
                "end_block_ids": ["b::end"],
                "branches": {"a": ["b"]},
            }
        ],
        "procedure_graph": {},
    }
    document = MarkupDocument.model_validate(payload).model_copy(
        update={
            "procedure_meta": {
                "p1": {
                    "team_name": "Alpha",
                    "service_name": "Payments",
                    "procedure_color": "#d9f5ff",
                    "services": [
                        {
                            "team_name": "Alpha",
                            "service_name": "Payments",
                            "service_color": "#d9f5ff",
                        }
                    ],
                }
            }
        }
    )
    layout = ProcedureGraphLayoutEngine()
    excal = ProcedureGraphToExcalidrawConverter(layout).convert(document)

    zones = [
        element
        for element in excal.elements
        if element.get("customData", {}).get("cjm", {}).get("role") == "service_zone"
    ]
    assert not zones


def test_procedure_graph_unidraw_cycle_edges_follow_offsets() -> None:
    payload = {
        "markup_type": "procedure_graph",
        "procedures": [
            {
                "proc_id": "p1",
                "proc_name": "Start Cycle",
                "start_block_ids": ["a"],
                "end_block_ids": ["b::end"],
                "branches": {"a": ["b"]},
            },
            {
                "proc_id": "p2",
                "proc_name": "Return Cycle",
                "start_block_ids": ["c"],
                "end_block_ids": ["d::end"],
                "branches": {"c": ["d"]},
            },
        ],
        "procedure_graph": {"p1": ["p2"], "p2": ["p1"]},
    }
    document = MarkupDocument.model_validate(payload)
    layout = ProcedureGraphLayoutEngine(LayoutConfig(block_size=Size(320.0, 140.0)))
    scene = ProcedureGraphToUnidrawConverter(layout).convert(document)

    cycle_edges = [
        element
        for element in scene.elements
        if element.get("type") == "line"
        and element.get("cjm", {}).get("edge_type") == "procedure_cycle"
    ]
    flow_edges = [
        element
        for element in scene.elements
        if element.get("type") == "line"
        and element.get("cjm", {}).get("edge_type") == "procedure_flow"
    ]
    assert len(cycle_edges) == 1
    assert len(flow_edges) == 1

    edge_left_to_right = next(
        edge
        for edge in flow_edges
        if edge.get("cjm", {}).get("procedure_id") == "p1"
        and edge.get("cjm", {}).get("target_procedure_id") == "p2"
    )
    edge_right_to_left = next(
        edge
        for edge in cycle_edges
        if edge.get("cjm", {}).get("procedure_id") == "p2"
        and edge.get("cjm", {}).get("target_procedure_id") == "p1"
    )

    tips_forward = edge_left_to_right.get("tipPoints", {})
    start_forward = tips_forward.get("start", {}).get("position", {})
    end_forward = tips_forward.get("end", {}).get("position", {})
    assert round(start_forward.get("x", 0.0), 2) == 1.0
    assert round(start_forward.get("y", 0.0), 2) == 0.5
    assert round(end_forward.get("x", 0.0), 2) == 0.0
    assert round(end_forward.get("y", 0.0), 2) == 0.5

    tips_reverse = edge_right_to_left.get("tipPoints", {})
    start_reverse = tips_reverse.get("start", {}).get("position", {})
    end_reverse = tips_reverse.get("end", {}).get("position", {})
    assert round(start_reverse.get("x", 0.0), 2) == 0.5
    assert round(start_reverse.get("y", 0.0), 2) == 1.0
    assert round(end_reverse.get("x", 0.0), 2) == 0.0
    assert round(end_reverse.get("y", 0.0), 2) == 0.5

    assert edge_left_to_right.get("style", {}).get("sw") == 1.0
    assert edge_right_to_left.get("style", {}).get("sw") == 1.0
