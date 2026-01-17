from __future__ import annotations

from typing import Any, cast

from adapters.layout.grid import GridLayoutEngine
from domain.models import END_TYPE_COLORS, MarkupDocument
from domain.services.convert_markup_to_unidraw import MarkupToUnidrawConverter


def test_unidraw_converter_emits_expected_schema() -> None:
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
    scene = cast(
        dict[str, Any],
        MarkupToUnidrawConverter(GridLayoutEngine()).convert(markup).to_dict(),
    )

    assert scene["type"] == "unidraw"
    assert scene["version"] == 1
    assert set(scene["appState"].keys()) <= {"viewBackgroundColor", "gridSize"}

    elements = cast(list[dict[str, Any]], scene["elements"])
    assert any(element.get("type") == "frame" for element in elements)
    assert any(
        element.get("type") == "shape" and element.get("shape") == "rectangle"
        for element in elements
    )
    assert any(
        element.get("type") == "shape" and element.get("shape") == "ellipse" for element in elements
    )
    text = next(element for element in elements if element.get("type") == "text")
    assert text.get("text", "").startswith("<p>")
    assert "position" in text and "size" in text
    assert "style" in text and "tfs" in text["style"]
    assert "cjm" in text

    arrow = next(
        element
        for element in elements
        if element.get("type") == "line" and element.get("tipPoints")
    )
    assert len(arrow.get("tipPoints", [])) == 2


def test_unidraw_converter_renders_postpone_end_marker() -> None:
    payload = {
        "markup_type": "service",
        "procedures": [
            {
                "proc_id": "p1",
                "start_block_ids": ["a"],
                "end_block_ids": ["b::postpone"],
                "branches": {"a": ["b"]},
            }
        ],
    }
    markup = MarkupDocument.model_validate(payload)
    scene = cast(
        dict[str, Any],
        MarkupToUnidrawConverter(GridLayoutEngine()).convert(markup).to_dict(),
    )
    elements = cast(list[dict[str, Any]], scene["elements"])
    end_markers = [
        element
        for element in elements
        if element.get("type") == "shape"
        and element.get("shape") == "ellipse"
        and element.get("cjm", {}).get("role") == "end_marker"
    ]
    assert end_markers
    colors = {marker.get("style", {}).get("fc") for marker in end_markers}
    assert END_TYPE_COLORS["postpone"] in colors
    assert any(marker.get("cjm", {}).get("end_type") == "postpone" for marker in end_markers)
