from __future__ import annotations

from adapters.layout.grid import LayoutConfig
from adapters.layout.procedure_graph import ProcedureGraphLayoutEngine
from domain.models import MarkupDocument, Size
from domain.services.build_team_procedure_graph import BuildTeamProcedureGraph
from domain.services.convert_procedure_graph_to_excalidraw import (
    ProcedureGraphToExcalidrawConverter,
)
from domain.services.convert_procedure_graph_to_unidraw import ProcedureGraphToUnidrawConverter


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
    alpha_colors = {
        service.get("service_color") for service in services if service.get("team_name") == "Alpha"
    }
    beta_colors = {
        service.get("service_color") for service in services if service.get("team_name") == "Beta"
    }
    assert len(alpha_colors) == 1
    assert len(beta_colors) == 1
    assert alpha_colors != beta_colors


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
        "procedure_graph": {},
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
        "procedure_graph": {},
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
    merge_text = plan.scenarios[0].merge_text or ""
    assert "Узлы слияния" in merge_text
    assert "shared" in merge_text
    assert "Shared Flow" not in merge_text


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
