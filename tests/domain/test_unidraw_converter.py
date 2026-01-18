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


def test_unidraw_converter_centers_marker_text() -> None:
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
    marker = next(
        element
        for element in elements
        if element.get("type") == "shape"
        and element.get("shape") == "5"
        and element.get("cjm", {}).get("role") == "start_marker"
    )
    label = next(
        element
        for element in elements
        if element.get("type") == "text" and element.get("cjm", {}).get("role") == "start_marker"
    )
    marker_center = (
        marker["position"]["x"] + marker["size"]["width"] / 2,
        marker["position"]["y"] + marker["size"]["height"] / 2,
    )
    label_center = (
        label["position"]["x"] + label["size"]["width"] / 2,
        label["position"]["y"] + label["size"]["height"] / 2,
    )
    assert abs(label_center[0] - marker_center[0]) < 0.5
    assert abs(label_center[1] - marker_center[1]) < 0.5


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
    assert block_label.get("link") is None


def test_unidraw_converter_applies_arrowheads() -> None:
    payload = {
        "markup_type": "service",
        "procedures": [
            {
                "proc_id": "p1",
                "start_block_ids": ["a"],
                "end_block_ids": ["b"],
                "branches": {"a": ["b"]},
            },
            {
                "proc_id": "p2",
                "start_block_ids": ["c"],
                "end_block_ids": ["d"],
                "branches": {"c": ["d"]},
            },
        ],
        "procedure_graph": {"p1": ["p2"]},
    }
    markup = MarkupDocument.model_validate(payload)
    scene = cast(
        dict[str, Any],
        MarkupToUnidrawConverter(GridLayoutEngine()).convert(markup).to_dict(),
    )
    elements = cast(list[dict[str, Any]], scene["elements"])
    edges = [
        element
        for element in elements
        if element.get("type") == "line" and element.get("cjm", {}).get("role") == "edge"
    ]
    block_edge = next(
        element
        for element in edges
        if element.get("cjm", {}).get("edge_type") in {"start", "end", "branch"}
    )
    procedure_edge = next(
        element for element in edges if element.get("cjm", {}).get("edge_type") == "procedure_flow"
    )
    assert block_edge.get("style", {}).get("let") == unidraw_module._UNIDRAW_LINE_END_BLOCK_ARROW
    assert (
        procedure_edge.get("style", {}).get("let")
        == unidraw_module._UNIDRAW_LINE_END_PROCEDURE_ARROW
    )
    assert block_edge.get("style", {}).get("sw") == 1.0
    assert procedure_edge.get("style", {}).get("sw") == 2.0


def test_unidraw_converter_curves_non_horizontal_edges() -> None:
    payload = {
        "markup_type": "service",
        "procedures": [
            {
                "proc_id": "p1",
                "start_block_ids": ["a", "b"],
                "end_block_ids": ["e"],
                "branches": {"a": ["c"], "b": ["c"], "c": ["e"]},
            }
        ],
    }
    markup = MarkupDocument.model_validate(payload)
    scene = cast(
        dict[str, Any],
        MarkupToUnidrawConverter(GridLayoutEngine()).convert(markup).to_dict(),
    )
    elements = cast(list[dict[str, Any]], scene["elements"])
    edges = [
        element
        for element in elements
        if element.get("type") == "line" and element.get("cjm", {}).get("role") == "edge"
    ]
    non_horizontal = []
    for edge in edges:
        tips = edge.get("tipPoints", {})
        start = tips.get("start", {})
        end = tips.get("end", {})
        start_pos = start.get("absolutePosition") or start.get("position") or {}
        end_pos = end.get("absolutePosition") or end.get("position") or {}
        dx = end_pos.get("x", 0.0) - start_pos.get("x", 0.0)
        dy = end_pos.get("y", 0.0) - start_pos.get("y", 0.0)
        if abs(dx) > 1.0 and abs(dy) > 1.0:
            non_horizontal.append(edge)

    assert non_horizontal
    for edge in non_horizontal:
        tips = edge.get("tipPoints", {})
        start_normal = tips.get("start", {}).get("normal", {})
        end_normal = tips.get("end", {}).get("normal", {})
        assert abs(start_normal.get("y", 0.0)) < 0.01
        assert abs(end_normal.get("y", 0.0)) < 0.01


def test_unidraw_converter_frame_title_font_size() -> None:
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
    frame = next(element for element in elements if element.get("cjm", {}).get("role") == "frame")
    assert frame.get("style", {}).get("tfs") == unidraw_module._FRAME_FONT_SIZE
