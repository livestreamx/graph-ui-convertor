from __future__ import annotations

from adapters.layout.grid import LayoutConfig
from adapters.layout.procedure_graph import ProcedureGraphLayoutEngine
from domain.models import MarkupDocument, Size
from domain.services.build_team_procedure_graph import BuildTeamProcedureGraph
from domain.services.convert_procedure_graph_to_excalidraw import (
    ProcedureGraphToExcalidrawConverter,
)


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

    assert merged.service_name == "Alpha, Beta"
    assert {proc.procedure_id for proc in merged.procedures} == {"p1", "p2"}
    assert merged.procedure_meta["p1"]["service_name"] == "Payments"
    assert merged.procedure_meta["p1"]["team_name"] == "Alpha"
    assert merged.procedure_graph["p2"] == []


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
    assert "Alpha - Payments" in procedures_text
    assert "- Start Flow" in procedures_text
    assert "Beta - Refunds" in procedures_text


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
