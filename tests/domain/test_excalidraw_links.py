from __future__ import annotations

from adapters.layout.grid import GridLayoutEngine
from domain.models import MarkupDocument
from domain.services.convert_markup_to_excalidraw import MarkupToExcalidrawConverter
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
