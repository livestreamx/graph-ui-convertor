from __future__ import annotations

import re
from typing import Any, cast

from adapters.layout.grid import GridLayoutEngine
from domain.models import END_TYPE_COLORS, MarkupDocument
from domain.services import convert_markup_to_unidraw as unidraw_module
from domain.services.convert_markup_to_unidraw import MarkupToUnidrawConverter
from domain.services.excalidraw_links import ExcalidrawLinkTemplates


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
        element.get("type") == "shape" and element.get("shape") == "1" for element in elements
    )
    assert any(
        element.get("type") == "shape" and element.get("shape") == "5" for element in elements
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
    tip_points = arrow.get("tipPoints", {})
    assert isinstance(tip_points, dict)
    assert {"start", "end"} <= set(tip_points.keys())


def test_unidraw_converter_sizes_centered_text() -> None:
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
    elements = cast(list[dict[str, Any]], scene["elements"])
    block = next(
        element
        for element in elements
        if element.get("cjm", {}).get("role") == "block"
        and element.get("cjm", {}).get("block_id") == "a"
    )
    label = next(
        element
        for element in elements
        if element.get("cjm", {}).get("role") == "block_label"
        and element.get("cjm", {}).get("block_id") == "a"
    )
    text = label.get("text", "")
    lines = [re.sub(r"<[^>]+>", "", line) for line in text.split("</p>") if line.strip()]
    max_len = max(len(line) for line in lines)
    font_size = label.get("style", {}).get("tfs", 0)
    expected_width = max_len * font_size * unidraw_module._UNIDRAW_TEXT_WIDTH_FACTOR
    expected_height = len(lines) * font_size * unidraw_module._UNIDRAW_TEXT_LINE_HEIGHT
    assert abs(label["size"]["width"] - expected_width) < 2.0
    assert abs(label["size"]["height"] - expected_height) < 1.0
    assert label["size"]["width"] < (block["size"]["width"] - 30)


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
        and element.get("shape") == "5"
        and element.get("cjm", {}).get("role") == "end_marker"
    ]
    assert end_markers
    colors = {marker.get("style", {}).get("fc") for marker in end_markers}
    assert END_TYPE_COLORS["postpone"] in colors
    assert any(marker.get("cjm", {}).get("end_type") == "postpone" for marker in end_markers)


def test_unidraw_converter_applies_links() -> None:
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
    templates = ExcalidrawLinkTemplates(
        procedure="https://example.com/procedures/{procedure_id}",
        block="https://example.com/procedures/{procedure_id}/blocks/{block_id}",
    )
    scene = cast(
        dict[str, Any],
        MarkupToUnidrawConverter(GridLayoutEngine(), link_templates=templates)
        .convert(markup)
        .to_dict(),
    )
    elements = cast(list[dict[str, Any]], scene["elements"])

    frame = next(element for element in elements if element.get("cjm", {}).get("role") == "frame")
    block = next(
        element
        for element in elements
        if element.get("cjm", {}).get("role") == "block"
        and element.get("cjm", {}).get("block_id") == "a"
    )
    block_label = next(
        element
        for element in elements
        if element.get("cjm", {}).get("role") == "block_label"
        and element.get("cjm", {}).get("block_id") == "a"
    )

    assert frame.get("link") == "https://example.com/procedures/p1"
    assert block.get("link") == "https://example.com/procedures/p1/blocks/a"
    assert block_label.get("link") == "https://example.com/procedures/p1/blocks/a"
