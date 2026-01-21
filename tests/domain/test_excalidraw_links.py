from __future__ import annotations

from adapters.layout.grid import GridLayoutEngine
from adapters.layout.procedure_graph import ProcedureGraphLayoutEngine
from domain.models import MarkupDocument
from domain.services.convert_markup_to_excalidraw import MarkupToExcalidrawConverter
from domain.services.convert_procedure_graph_to_excalidraw import (
    ProcedureGraphToExcalidrawConverter,
)
from domain.services.excalidraw_links import ExcalidrawLinkTemplates


def test_links_applied_to_procedure_and_block_elements() -> None:
    payload = {
        "markup_type": "service",
        "procedures": [
            {
                "proc_id": "proc-1",
                "start_block_ids": ["block-a"],
                "end_block_ids": ["block-b"],
                "branches": {"block-a": ["block-b"]},
            }
        ],
    }
    markup = MarkupDocument.model_validate(payload)
    templates = ExcalidrawLinkTemplates(
        procedure="https://example.com/procedures/{procedure_id}",
        block="https://example.com/procedures/{procedure_id}/blocks/{block_id}",
    )
    excal = MarkupToExcalidrawConverter(GridLayoutEngine(), link_templates=templates).convert(
        markup
    )

    frame = next(
        element
        for element in excal.elements
        if element.get("customData", {}).get("cjm", {}).get("role") == "frame"
    )
    assert frame.get("link") == "https://example.com/procedures/proc-1"

    block_rect = next(
        element
        for element in excal.elements
        if element.get("customData", {}).get("cjm", {}).get("role") == "block"
        and element.get("customData", {}).get("cjm", {}).get("block_id") == "block-a"
    )
    block_label = next(
        element
        for element in excal.elements
        if element.get("customData", {}).get("cjm", {}).get("role") == "block_label"
        and element.get("customData", {}).get("cjm", {}).get("block_id") == "block-a"
    )
    assert block_rect.get("link") == "https://example.com/procedures/proc-1/blocks/block-a"
    assert block_label.get("link") == "https://example.com/procedures/proc-1/blocks/block-a"


def test_links_applied_to_service_title() -> None:
    payload = {
        "markup_type": "service",
        "finedog_unit_id": "unit-42",
        "finedog_unit_meta": {"service_name": "Billing Flow"},
        "procedures": [
            {
                "proc_id": "proc-1",
                "start_block_ids": ["block-a"],
                "end_block_ids": ["block-b"],
                "branches": {"block-a": ["block-b"]},
            }
        ],
    }
    markup = MarkupDocument.model_validate(payload)
    templates = ExcalidrawLinkTemplates(service="https://example.com/units")
    excal = MarkupToExcalidrawConverter(GridLayoutEngine(), link_templates=templates).convert(
        markup
    )

    title_panel = next(
        element
        for element in excal.elements
        if element.get("customData", {}).get("cjm", {}).get("role") == "diagram_title_panel"
    )
    assert title_panel.get("link") == "https://example.com/units?unit_id=unit-42"


def test_links_applied_to_procedure_graph_service_and_team_panels() -> None:
    payload = {
        "markup_type": "procedure_graph",
        "service_name": "Team Alpha",
        "team_id": "team-alpha",
        "team_name": "Team Alpha",
        "procedures": [
            {
                "proc_id": "p1",
                "start_block_ids": ["a"],
                "end_block_ids": ["b::end"],
                "branches": {"a": ["b"]},
            }
        ],
        "procedure_graph": {"p1": []},
        "procedure_meta": {
            "p1": {
                "team_name": "Team Alpha",
                "team_id": "team-alpha",
                "service_name": "Checkout",
                "procedure_color": "#d9f5ff",
                "services": [
                    {
                        "team_name": "Team Alpha",
                        "team_id": "team-alpha",
                        "service_name": "Checkout",
                        "finedog_unit_id": "unit-99",
                        "service_color": "#d9f5ff",
                    }
                ],
            }
        },
    }
    markup = MarkupDocument.model_validate(payload)
    templates = ExcalidrawLinkTemplates(
        service="https://example.com/units",
        team="https://example.com/teams",
    )
    excal = ProcedureGraphToExcalidrawConverter(
        ProcedureGraphLayoutEngine(), link_templates=templates
    ).convert(markup)

    service_panel = next(
        element
        for element in excal.elements
        if element.get("customData", {}).get("cjm", {}).get("role")
        == "scenario_procedures_service_panel"
    )
    team_text = next(
        element
        for element in excal.elements
        if element.get("customData", {}).get("cjm", {}).get("role") == "scenario_procedures_team"
    )
    assert service_panel.get("link") == "https://example.com/units?unit_id=unit-99"
    assert team_text.get("link") == "https://example.com/teams?team_id=team-alpha"
