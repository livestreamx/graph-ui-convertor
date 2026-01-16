from __future__ import annotations

from typing import Any

from adapters.layout.grid import GridLayoutEngine
from domain.models import MarkupDocument
from domain.services.convert_markup_to_excalidraw import MarkupToExcalidrawConverter
from domain.services.excalidraw_title import (
    TITLE_ROLES,
    apply_title_focus,
    ensure_service_title,
)


def _strip_title_elements(elements: list[dict[str, Any]]) -> list[dict[str, Any]]:
    filtered: list[dict[str, Any]] = []
    for element in elements:
        role = element.get("customData", {}).get("cjm", {}).get("role")
        if role in TITLE_ROLES:
            continue
        filtered.append(element)
    return filtered


def test_injects_title_when_missing() -> None:
    payload = {
        "markup_type": "service",
        "finedog_unit_meta": {"service_name": "Billing Flow"},
        "procedures": [
            {
                "proc_id": "p1",
                "start_block_ids": ["a"],
                "end_block_ids": ["b"],
                "branches": {"a": ["b"]},
            }
        ],
    }
    markup = MarkupDocument.model_validate(payload)
    excal = MarkupToExcalidrawConverter(GridLayoutEngine()).convert(markup)
    elements = _strip_title_elements(list(excal.elements))

    ensure_service_title(elements)

    roles = [element.get("customData", {}).get("cjm", {}).get("role") for element in elements]
    assert "diagram_title" in roles
    assert "diagram_title_panel" in roles
    app_state: dict[str, Any] = {}
    apply_title_focus(app_state, elements)
    assert "scrollX" in app_state
    assert "scrollY" in app_state


def test_skips_title_without_service_name() -> None:
    payload = {
        "markup_type": "service",
        "procedures": [
            {
                "proc_id": "p1",
                "start_block_ids": ["a"],
                "end_block_ids": ["b"],
                "branches": {"a": ["b"]},
            }
        ],
    }
    markup = MarkupDocument.model_validate(payload)
    excal = MarkupToExcalidrawConverter(GridLayoutEngine()).convert(markup)
    elements = _strip_title_elements(list(excal.elements))

    ensure_service_title(elements)

    roles = [element.get("customData", {}).get("cjm", {}).get("role") for element in elements]
    assert "diagram_title" not in roles
