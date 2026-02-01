from __future__ import annotations

import html
import math
import time
import uuid
from typing import Any, cast

from domain.models import (
    BlockPlacement,
    FramePlacement,
    MarkupDocument,
    Point,
    Size,
    UnidrawDocument,
)
from domain.ports.layout import LayoutEngine
from domain.services.convert_markup_base import (
    Element,
    MarkupToDiagramConverter,
    Metadata,
)
from domain.services.excalidraw_links import ExcalidrawLinkTemplates, ensure_unidraw_links

_DEFAULT_TEXT_FONT_FAMILY = "Caveat, Segoe UI Emoji"
_DEFAULT_SHAPE_FONT_FAMILY = "Neue Haas Unica, Segoe UI Emoji"
_FRAME_TEXT_COLOR = "#CCCCCC"
_SHAPE_TEXT_COLOR = "#3A3A3A"
_DEFAULT_TEXT_COLOR = "#2b2b2b"
_UNIDRAW_ALPHA = 100
_UNIDRAW_FILL_STYLE = "s"
_UNIDRAW_FILL_STYLE_HATCH = "h"
_UNIDRAW_STROKE_SOLID = "s"
_UNIDRAW_STROKE_DASHED = "d"
_UNIDRAW_LINE_TYPE_CONNECTOR = "c"
_UNIDRAW_LINE_TYPE_ABSOLUTE = "a"
_UNIDRAW_LINE_END = 0
_UNIDRAW_LINE_END_BLOCK_ARROW = 2
_UNIDRAW_LINE_END_PROCEDURE_ARROW = 14
_UNIDRAW_LINE_CAP = 1
_UNIDRAW_PROCEDURE_EDGE_STROKE_WIDTH = 2.0
_SHAPE_RECTANGLE = "1"
_SHAPE_ELLIPSE = "5"
_FRAME_FONT_SIZE = 20
_SHAPE_FONT_SIZE = 20
_UNIDRAW_TEXT_WIDTH_FACTOR = 0.38
_UNIDRAW_MARKER_TEXT_WIDTH_FACTOR = 0.46
_UNIDRAW_TEXT_LINE_HEIGHT = 1.11
_UNIDRAW_TEXT_MIN_SIZE = 11.0
_EMPTY_PARAGRAPH = "<p></p>"


class MarkupToUnidrawConverter(MarkupToDiagramConverter):
    def __init__(
        self,
        layout_engine: LayoutEngine,
        link_templates: ExcalidrawLinkTemplates | None = None,
    ) -> None:
        super().__init__(layout_engine)
        self._timestamp_ms = 0
        self._z_index = 0
        self._created_by = str(uuid.uuid5(self.namespace, "unidraw-user"))
        self._element_bounds: dict[str, tuple[Point, Size]] = {}
        self.link_templates = link_templates

    def convert(self, document: MarkupDocument) -> UnidrawDocument:
        self._timestamp_ms = int(time.time() * 1000)
        self._z_index = 0
        self._element_bounds = {}
        return cast(UnidrawDocument, super().convert(document))

    def _build_document(
        self, elements: list[Element], app_state: dict[str, Any]
    ) -> UnidrawDocument:
        return UnidrawDocument(elements=elements, app_state=app_state)

    def _build_app_state(self, elements: list[Element]) -> dict[str, Any]:
        return {
            "viewBackgroundColor": "#FFFFFF",
            "gridSize": None,
        }

    def _post_process_elements(self, elements: list[Element]) -> None:
        ensure_unidraw_links(elements, self.link_templates)
        procedure_edges: list[Element] = []
        other_edges: list[Element] = []
        rest: list[Element] = []
        for element in elements:
            meta = element.get("cjm", {})
            if meta.get("role") == "edge":
                if meta.get("edge_type") in {"procedure_flow", "procedure_cycle"}:
                    procedure_edges.append(element)
                else:
                    other_edges.append(element)
            else:
                rest.append(element)
        if procedure_edges or other_edges:
            edges = procedure_edges + other_edges
            elements[:] = edges + rest
            for idx, element in enumerate(edges, start=1):
                element["zIndex"] = -idx
            for idx, element in enumerate(rest, start=1):
                element["zIndex"] = idx

    def _offset_element(self, element: Element, dx: float, dy: float) -> None:
        position = element.get("position")
        if isinstance(position, dict):
            position["x"] = float(position.get("x", 0.0)) + dx
            position["y"] = float(position.get("y", 0.0)) + dy
        element_id = element.get("id")
        size = element.get("size")
        if isinstance(element_id, str) and isinstance(position, dict) and isinstance(size, dict):
            self._element_bounds[element_id] = (
                Point(float(position.get("x", 0.0)), float(position.get("y", 0.0))),
                Size(float(size.get("width", 0.0)), float(size.get("height", 0.0))),
            )
        tip_points = element.get("tipPoints")
        if isinstance(tip_points, dict):
            for key in ("start", "end"):
                tip = tip_points.get(key)
                if not isinstance(tip, dict):
                    continue
                abs_pos = tip.get("absolutePosition")
                if isinstance(abs_pos, dict):
                    abs_pos["x"] = float(abs_pos.get("x", 0.0)) + dx
                    abs_pos["y"] = float(abs_pos.get("y", 0.0)) + dy
                pos = tip.get("position")
                if isinstance(pos, dict) and not tip.get("boundToId"):
                    pos["x"] = float(pos.get("x", 0.0)) + dx
                    pos["y"] = float(pos.get("y", 0.0)) + dy
        elif isinstance(tip_points, list):
            for tip in tip_points:
                tip_pos = tip.get("position")
                if isinstance(tip_pos, dict):
                    tip_pos["x"] = float(tip_pos.get("x", 0.0)) + dx
                    tip_pos["y"] = float(tip_pos.get("y", 0.0)) + dy

    def _frame_element(
        self,
        element_id: str,
        frame: FramePlacement,
        metadata: Metadata,
        name: str | None = None,
    ) -> Element:
        style = self._frame_style()
        background = metadata.get("procedure_color")
        if isinstance(background, str) and background:
            style["fc"] = background
        return self._base_element(
            element_id=element_id,
            type_name="frame",
            position=frame.origin,
            size=frame.size,
            metadata=metadata,
            extra={
                "text": self._html_text(name or frame.procedure_id),
                "isExposed": True,
                "children": [],
            },
            style=style,
            z_index=-1,
        )

    def _rectangle_element(
        self,
        element_id: str,
        position: Point,
        size: Size,
        frame_id: str | None,
        group_ids: list[str],
        metadata: Metadata,
        background_color: str | None = None,
        stroke_color: str | None = None,
        stroke_style: str | None = None,
        fill_style: str | None = None,
        roundness: dict[str, Any] | None = None,
    ) -> Element:
        resolved_fill = _UNIDRAW_FILL_STYLE_HATCH if fill_style == "hachure" else fill_style
        return self._base_element(
            element_id=element_id,
            type_name="shape",
            position=position,
            size=size,
            metadata=metadata,
            group_ids=group_ids,
            extra={"shape": _SHAPE_RECTANGLE, "text": _EMPTY_PARAGRAPH},
            style=self._shape_style(
                stroke_color=stroke_color or "#1e1e1e",
                background_color=background_color or "#cce5ff",
                stroke_width=1.0,
                stroke_style=stroke_style,
                fill_style=resolved_fill,
            ),
        )

    def _scenario_panel_element(
        self,
        element_id: str,
        origin: Point,
        size: Size,
        metadata: Metadata,
        group_ids: list[str],
    ) -> Element:
        return self._base_element(
            element_id=element_id,
            type_name="shape",
            position=origin,
            size=size,
            metadata=metadata,
            group_ids=group_ids,
            extra={"shape": _SHAPE_RECTANGLE, "text": _EMPTY_PARAGRAPH},
            style=self._shape_style(
                stroke_color="#c7bba3",
                background_color="#f7f3ea",
                stroke_width=1.0,
            ),
        )

    def _scenario_procedures_panel_element(
        self,
        element_id: str,
        origin: Point,
        size: Size,
        metadata: Metadata,
        group_ids: list[str],
        background_color: str | None = None,
        stroke_color: str | None = None,
    ) -> Element:
        return self._base_element(
            element_id=element_id,
            type_name="shape",
            position=origin,
            size=size,
            metadata=metadata,
            group_ids=group_ids,
            extra={"shape": _SHAPE_RECTANGLE, "text": _EMPTY_PARAGRAPH},
            style=self._shape_style(
                stroke_color=stroke_color or "#7a8aa8",
                background_color=background_color or "#e9f0fb",
                stroke_width=1.0,
            ),
        )

    def _title_panel_element(
        self,
        element_id: str,
        origin: Point,
        size: Size,
        metadata: Metadata,
        group_ids: list[str],
    ) -> Element:
        return self._base_element(
            element_id=element_id,
            type_name="shape",
            position=origin,
            size=size,
            metadata=metadata,
            group_ids=group_ids,
            extra={"shape": _SHAPE_RECTANGLE, "text": _EMPTY_PARAGRAPH},
            style=self._shape_style(
                stroke_color="#34445b",
                background_color="#eef3ff",
                stroke_width=2.0,
            ),
        )

    def _ellipse_element(
        self,
        element_id: str,
        position: Point,
        size: Size,
        frame_id: str | None,
        metadata: Metadata,
        group_ids: list[str] | None = None,
        background_color: str | None = None,
        stroke_color: str | None = None,
        stroke_style: str | None = None,
        stroke_width: float | None = None,
    ) -> Element:
        return self._base_element(
            element_id=element_id,
            type_name="shape",
            position=position,
            size=size,
            metadata=metadata,
            group_ids=group_ids,
            extra={"shape": _SHAPE_ELLIPSE, "text": _EMPTY_PARAGRAPH},
            style=self._shape_style(
                stroke_color=stroke_color or "#1e1e1e",
                background_color=background_color or "#d1ffd6",
                stroke_width=stroke_width if stroke_width is not None else 1.0,
                stroke_style=stroke_style,
            ),
        )

    def _text_block_element(
        self,
        element_id: str,
        text: str,
        origin: Point,
        width: float,
        height: float,
        metadata: Metadata,
        group_ids: list[str] | None = None,
        font_size: float = 16.0,
        text_color: str | None = None,
    ) -> Element:
        return self._base_element(
            element_id=element_id,
            type_name="text",
            position=origin,
            size=Size(width, height),
            metadata=metadata,
            group_ids=group_ids,
            extra={"text": self._html_text(text)},
            style=self._text_style(
                text_color=text_color or _DEFAULT_TEXT_COLOR,
                font_family=_DEFAULT_TEXT_FONT_FAMILY,
                font_size=font_size,
                text_align="left",
            ),
        )

    def _text_element(
        self,
        element_id: str,
        text: str,
        center: Point,
        container_id: str | None,
        frame_id: str | None,
        metadata: Metadata,
        group_ids: list[str] | None = None,
        max_width: float | None = None,
        max_height: float | None = None,
        font_size: float | None = None,
    ) -> Element:
        max_size = font_size or 20.0
        width_factor = self._text_width_factor(metadata)
        size = max_size
        content = text
        if max_width is not None and max_height is not None and text.strip():
            content, size, height = self._fit_text_with_metrics(
                text=text,
                max_width=max_width,
                max_height=max_height,
                min_size=_UNIDRAW_TEXT_MIN_SIZE,
                max_size=max_size,
                width_factor=width_factor,
                line_height=_UNIDRAW_TEXT_LINE_HEIGHT,
            )
        else:
            if max_width is not None and text.strip():
                line_lengths = [len(line) for line in text.splitlines()] or [len(text)]
                max_len = max(line_lengths)
                if max_len > 0:
                    size = min(
                        max_size,
                        max_width / (max_len * width_factor),
                    )
                size = max(_UNIDRAW_TEXT_MIN_SIZE, size)
            line_count = max(1, len(content.splitlines())) if content else 1
            height = line_count * size * _UNIDRAW_TEXT_LINE_HEIGHT
            if max_height is not None:
                height = min(max_height, height)
        width = self._text_width(content, size, max_width, width_factor)
        x = center.x - width / 2
        y = center.y - height / 2
        return self._base_element(
            element_id=element_id,
            type_name="text",
            position=Point(x, y),
            size=Size(width, height),
            metadata=metadata,
            group_ids=group_ids,
            extra={"text": self._html_text(content)},
            style=self._text_style(
                text_color="#1e1e1e",
                font_family=_DEFAULT_TEXT_FONT_FAMILY,
                font_size=size,
                text_align="center",
            ),
        )

    def _fit_text(
        self,
        text: str,
        max_width: float,
        max_height: float,
        min_size: float,
        max_size: float,
    ) -> tuple[str, float, float]:
        return self._fit_text_with_metrics(
            text=text,
            max_width=max_width,
            max_height=max_height,
            min_size=min_size,
            max_size=max_size,
            width_factor=_UNIDRAW_TEXT_WIDTH_FACTOR,
            line_height=_UNIDRAW_TEXT_LINE_HEIGHT,
        )

    def _fit_text_with_metrics(
        self,
        text: str,
        max_width: float,
        max_height: float,
        min_size: float,
        max_size: float,
        width_factor: float,
        line_height: float,
    ) -> tuple[str, float, float]:
        if not text.strip():
            size = max_size
            height = min(max_height, size * line_height)
            return text, size, height

        words = text.split()

        def wrap_words(max_chars: int) -> list[str]:
            lines: list[str] = []
            current: list[str] = []
            count = 0
            for word in words:
                if not current:
                    if len(word) <= max_chars:
                        current = [word]
                        count = len(word)
                    else:
                        for idx in range(0, len(word), max_chars):
                            chunk = word[idx : idx + max_chars]
                            if current:
                                lines.append(" ".join(current))
                            current = [chunk]
                            count = len(chunk)
                    continue
                if count + 1 + len(word) <= max_chars:
                    current.append(word)
                    count += 1 + len(word)
                else:
                    lines.append(" ".join(current))
                    current = [word]
                    count = len(word)
            if current:
                lines.append(" ".join(current))
            return lines

        start = int(max_size)
        end = int(min_size)
        for size in range(start, end - 1, -1):
            max_chars = max(1, int(max_width / (size * width_factor)))
            lines = wrap_words(max_chars)
            height_needed = len(lines) * size * line_height
            if height_needed <= max_height:
                return "\n".join(lines), float(size), min(max_height, height_needed)

        size = max(min_size, 1.0)
        max_chars = max(1, int(max_width / (size * width_factor)))
        lines = wrap_words(max_chars)
        height_needed = len(lines) * size * line_height
        return "\n".join(lines), size, min(max_height, height_needed)

    def _text_width(
        self,
        content: str,
        font_size: float,
        max_width: float | None,
        width_factor: float,
    ) -> float:
        lines = content.splitlines() if content else []
        if not lines:
            width = max_width if max_width is not None else 1.0
            return max(1.0, width)
        max_len = max(len(line) for line in lines)
        width = max_len * font_size * width_factor
        if max_width is not None:
            width = min(width, max_width)
        return max(1.0, width)

    def _line_element(
        self,
        element_id: str,
        start: Point,
        end: Point,
        metadata: Metadata,
        stroke_color: str | None = None,
        stroke_style: str | None = None,
        stroke_width: float = 1.0,
        group_ids: list[str] | None = None,
    ) -> Element:
        position, size = self._line_bounds(start, end)
        return self._base_element(
            element_id=element_id,
            type_name="line",
            position=position,
            size=size,
            metadata=metadata,
            group_ids=group_ids,
            extra={
                "points": [],
                "tipPoints": self._absolute_tip_points(start, end),
            },
            style=self._line_style(
                stroke_color=stroke_color or "#1e1e1e",
                stroke_width=stroke_width,
                stroke_style=stroke_style or "solid",
                line_type=_UNIDRAW_LINE_TYPE_ABSOLUTE,
            ),
            version_nonce=0,
        )

    def _arrow_element(
        self,
        start: Point,
        end: Point,
        label: str,
        metadata: Metadata,
        start_binding: str | None = None,
        end_binding: str | None = None,
        smoothing: float = 0.0,
        stroke_style: str | None = None,
        stroke_color: str | None = None,
        stroke_width: float | None = None,
        curve_offset: float | None = None,
        curve_direction: float | None = None,
        points: list[list[float]] | None = None,
        roundness: dict[str, Any] | None = None,
        start_arrowhead: str | None = None,
        end_arrowhead: str | None = None,
    ) -> Element:
        arrow_id = self._stable_id(
            "arrow", metadata.get("procedure_id", ""), label, str(start), str(end)
        )
        start_point, end_point = self._procedure_cycle_points(
            start, end, metadata, start_binding, end_binding
        )
        dx = end_point.x - start_point.x
        dy = end_point.y - start_point.y
        position, size = self._line_bounds(start_point, end_point)
        direction = self._unit_vector(dx, dy)
        start_normal, end_normal = self._connector_normals(
            dx,
            dy,
            direction,
            start_binding=start_binding,
            end_binding=end_binding,
        )
        if metadata.get("edge_type") == "procedure_cycle":
            start_normal = self._binding_normal(start_binding, start_point, start_normal)
            end_normal = self._binding_normal(end_binding, end_point, end_normal)
        tip_points = {
            "start": self._bound_tip_point(start_point, start_binding, start_normal),
            "end": self._bound_tip_point(end_point, end_binding, end_normal),
        }
        return self._base_element(
            element_id=arrow_id,
            type_name="line",
            position=position,
            size=size,
            metadata=metadata,
            extra={
                "points": [],
                "tipPoints": tip_points,
            },
            style=self._line_style(
                stroke_color=stroke_color or "#1e1e1e",
                stroke_width=self._arrow_stroke_width(stroke_width, metadata),
                stroke_style=stroke_style or "solid",
                line_type=_UNIDRAW_LINE_TYPE_CONNECTOR,
                line_end=self._arrow_line_end(metadata),
            ),
            version_nonce=0,
        )

    def _block_label_placeholders(
        self,
        block: BlockPlacement,
        frame_id: str | None,
        group_ids: list[str],
        metadata: Metadata,
    ) -> list[Element]:
        return []

    def _base_element(
        self,
        element_id: str,
        type_name: str,
        position: Point,
        size: Size,
        metadata: Metadata,
        group_ids: list[str] | None = None,
        frame_id: str | None = None,
        extra: dict[str, Any] | None = None,
        style: dict[str, Any] | None = None,
        z_index: int | None = None,
        version_nonce: int | None = None,
    ) -> Element:
        computed_z = self._next_z_index()
        element = {
            "id": element_id,
            "position": {"x": position.x, "y": position.y},
            "size": {"width": size.width, "height": size.height},
            "version": 1,
            "versionNonce": (version_nonce if version_nonce is not None else self._rand_seed()),
            "createdAt": self._timestamp_ms,
            "updatedAt": self._timestamp_ms,
            "createdBy": self._created_by,
            "alpha": _UNIDRAW_ALPHA,
            "zIndex": z_index if z_index is not None else computed_z,
            "rotation": 0,
            "groupIds": group_ids or [],
            "isLocked": False,
            "isDeleted": False,
            "isDTO": True,
            "type": type_name,
            "schema": 2,
            "style": style or {},
            "cjm": metadata,
            **(extra or {}),
        }
        self._element_bounds[element_id] = (position, size)
        return element

    def _text_style(
        self,
        text_color: str,
        font_family: str,
        font_size: float,
        text_align: str,
    ) -> dict[str, Any]:
        align = self._text_align_code(text_align)
        return {
            "tc": text_color,
            "tff": font_family,
            "tfs": font_size,
            "ta": align,
            "tva": "m" if align == "m" else "s",
        }

    def _shape_style(
        self,
        stroke_color: str,
        background_color: str,
        stroke_width: float,
        stroke_style: str | None = None,
        fill_style: str | None = None,
    ) -> dict[str, Any]:
        style = self._text_style(
            text_color=_SHAPE_TEXT_COLOR,
            font_family=_DEFAULT_SHAPE_FONT_FAMILY,
            font_size=_SHAPE_FONT_SIZE,
            text_align="center",
        )
        style.update(
            {
                "fc": background_color,
                "fs": fill_style or _UNIDRAW_FILL_STYLE,
                "sc": stroke_color,
                "sw": stroke_width,
                "ss": _UNIDRAW_STROKE_DASHED if stroke_style == "dashed" else _UNIDRAW_STROKE_SOLID,
            }
        )
        return style

    def _frame_style(self) -> dict[str, Any]:
        style = self._text_style(
            text_color=_FRAME_TEXT_COLOR,
            font_family=_DEFAULT_SHAPE_FONT_FAMILY,
            font_size=_FRAME_FONT_SIZE,
            text_align="left",
        )
        style.update(
            {
                "ss": _UNIDRAW_STROKE_SOLID,
                "fc": "transparent",
                "fs": _UNIDRAW_FILL_STYLE,
                "sc": "#1e1e1e",
                "sw": 1,
            }
        )
        return style

    def _line_style(
        self,
        stroke_color: str,
        stroke_width: float,
        stroke_style: str,
        line_type: str,
        line_start: int | None = None,
        line_end: int | None = None,
    ) -> dict[str, Any]:
        return {
            "ss": self._stroke_style_code(stroke_style),
            "sc": stroke_color,
            "sw": stroke_width,
            "fc": "transparent",
            "fs": _UNIDRAW_FILL_STYLE,
            "lst": _UNIDRAW_LINE_END if line_start is None else line_start,
            "let": _UNIDRAW_LINE_END if line_end is None else line_end,
            "lt": line_type,
            "lsc": _UNIDRAW_LINE_CAP,
        }

    def _text_align_code(self, text_align: str | None) -> str:
        return {"left": "s", "center": "m", "right": "e"}.get(text_align or "", "s")

    def _stroke_style_code(self, stroke_style: str | None) -> str:
        if stroke_style == "dashed":
            return _UNIDRAW_STROKE_DASHED
        return _UNIDRAW_STROKE_SOLID

    def _line_bounds(self, start: Point, end: Point) -> tuple[Point, Size]:
        min_x = min(start.x, end.x)
        min_y = min(start.y, end.y)
        return Point(min_x, min_y), Size(abs(end.x - start.x), abs(end.y - start.y))

    def _absolute_tip_points(self, start: Point, end: Point) -> dict[str, Any]:
        return {
            "start": {
                "position": {"x": start.x, "y": start.y},
                "absolutePosition": {"x": start.x, "y": start.y},
            },
            "end": {
                "position": {"x": end.x, "y": end.y},
                "absolutePosition": {"x": end.x, "y": end.y},
            },
        }

    def _bound_tip_point(
        self,
        point: Point,
        binding: str | None,
        normal: tuple[float, float],
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "position": {"x": point.x, "y": point.y},
            "absolutePosition": {"x": point.x, "y": point.y},
        }
        if binding:
            relative = self._relative_position(binding, point)
            payload["boundToId"] = binding
            payload["snappedToEdge"] = True
            if relative is not None:
                payload["position"] = relative
            payload["normal"] = {"x": normal[0], "y": normal[1]}
        return payload

    def _relative_position(self, binding: str, point: Point) -> dict[str, float] | None:
        bounds = self._element_bounds.get(binding)
        if not bounds:
            return None
        origin, size = bounds
        width = size.width or 0.0
        height = size.height or 0.0
        rel_x = 0.0 if width == 0 else (point.x - origin.x) / width
        rel_y = 0.0 if height == 0 else (point.y - origin.y) / height
        return {
            "x": min(1.0, max(0.0, rel_x)),
            "y": min(1.0, max(0.0, rel_y)),
        }

    def _html_text(self, text: str) -> str:
        lines = text.splitlines() if text is not None else []
        if not lines:
            return _EMPTY_PARAGRAPH
        return "".join(f"<p>{html.escape(line)}</p>" for line in lines)

    def _text_width_factor(self, metadata: Metadata) -> float:
        role = metadata.get("role") if metadata else None
        if role in {"start_marker", "end_marker"}:
            return _UNIDRAW_MARKER_TEXT_WIDTH_FACTOR
        return _UNIDRAW_TEXT_WIDTH_FACTOR

    def _arrow_line_end(self, metadata: Metadata) -> int:
        edge_type = metadata.get("edge_type") if metadata else None
        if edge_type in {"procedure_flow", "procedure_cycle"}:
            return _UNIDRAW_LINE_END_PROCEDURE_ARROW
        return _UNIDRAW_LINE_END_BLOCK_ARROW

    def _arrow_stroke_width(self, stroke_width: float | None, metadata: Metadata) -> float:
        if stroke_width is not None:
            return stroke_width
        edge_type = metadata.get("edge_type") if metadata else None
        if edge_type in {"procedure_flow", "procedure_cycle"}:
            return _UNIDRAW_PROCEDURE_EDGE_STROKE_WIDTH
        return 1.0

    def _connector_normals(
        self,
        dx: float,
        dy: float,
        direction: tuple[float, float],
        start_binding: str | None,
        end_binding: str | None,
    ) -> tuple[tuple[float, float], tuple[float, float]]:
        if not start_binding or not end_binding:
            return direction, (-direction[0], -direction[1])
        if abs(dy) <= 1.0:
            return direction, (-direction[0], -direction[1])
        curve_dir = 1.0 if dx >= 0 else -1.0
        return (curve_dir, 0.0), (-curve_dir, 0.0)

    def _binding_normal(
        self,
        binding: str | None,
        point: Point,
        fallback: tuple[float, float],
    ) -> tuple[float, float]:
        if not binding:
            return fallback
        relative = self._relative_position(binding, point)
        if not relative:
            return fallback
        rel_x = relative.get("x", 0.5)
        rel_y = relative.get("y", 0.5)
        if rel_y >= 0.95:
            return (0.0, 1.0)
        if rel_y <= 0.05:
            return (0.0, -1.0)
        if rel_x >= 0.95:
            return (1.0, 0.0)
        if rel_x <= 0.05:
            return (-1.0, 0.0)
        return fallback

    def _procedure_cycle_points(
        self,
        start: Point,
        end: Point,
        metadata: Metadata,
        start_binding: str | None,
        end_binding: str | None,
    ) -> tuple[Point, Point]:
        if metadata.get("edge_type") != "procedure_cycle":
            return start, end
        if not start_binding or not end_binding:
            return start, end
        start_bounds = self._element_bounds.get(start_binding)
        end_bounds = self._element_bounds.get(end_binding)
        if not start_bounds or not end_bounds:
            return start, end
        start_origin, start_size = start_bounds
        end_origin, end_size = end_bounds
        if start_origin.x <= end_origin.x:
            return start, end
        return (
            Point(
                x=start_origin.x + start_size.width / 2,
                y=start_origin.y + start_size.height,
            ),
            Point(
                x=end_origin.x,
                y=end_origin.y + end_size.height / 2,
            ),
        )

    def _next_z_index(self) -> int:
        self._z_index += 1
        return self._z_index

    def _unit_vector(self, dx: float, dy: float) -> tuple[float, float]:
        length = math.hypot(dx, dy)
        if length == 0:
            return 0.0, 0.0
        return dx / length, dy / length
