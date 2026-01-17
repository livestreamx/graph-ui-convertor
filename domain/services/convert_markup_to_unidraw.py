from __future__ import annotations

import html
import math
import time
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

_DEFAULT_FONT_FAMILY = "Virgil"


class MarkupToUnidrawConverter(MarkupToDiagramConverter):
    def __init__(
        self,
        layout_engine: LayoutEngine,
        link_templates: ExcalidrawLinkTemplates | None = None,
    ) -> None:
        super().__init__(layout_engine)
        self._timestamp_ms = 0
        self._z_index = 0
        self.link_templates = link_templates

    def convert(self, document: MarkupDocument) -> UnidrawDocument:
        self._timestamp_ms = int(time.time() * 1000)
        self._z_index = 0
        return cast(UnidrawDocument, super().convert(document))

    def _build_document(
        self, elements: list[Element], app_state: dict[str, Any]
    ) -> UnidrawDocument:
        return UnidrawDocument(elements=elements, app_state=app_state)

    def _build_app_state(self, elements: list[Element]) -> dict[str, Any]:
        return {
            "viewBackgroundColor": "#ffffff",
            "gridSize": None,
        }

    def _post_process_elements(self, elements: list[Element]) -> None:
        ensure_unidraw_links(elements, self.link_templates)

    def _offset_element(self, element: Element, dx: float, dy: float) -> None:
        position = element.get("position")
        if isinstance(position, dict):
            position["x"] = float(position.get("x", 0.0)) + dx
            position["y"] = float(position.get("y", 0.0)) + dy
        tip_points = element.get("tipPoints")
        if isinstance(tip_points, list):
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
        return self._base_element(
            element_id=element_id,
            type_name="frame",
            position=frame.origin,
            size=frame.size,
            metadata=metadata,
            extra={"name": name or frame.procedure_id},
            style=self._style(
                stroke_color="#1e1e1e",
                background_color="transparent",
                stroke_width=1.0,
            ),
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
    ) -> Element:
        return self._base_element(
            element_id=element_id,
            type_name="shape",
            position=position,
            size=size,
            metadata=metadata,
            frame_id=frame_id,
            group_ids=group_ids,
            extra={"shape": "rectangle"},
            style=self._style(
                stroke_color="#1e1e1e",
                background_color=background_color or "#cce5ff",
                stroke_width=1.0,
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
            extra={"shape": "rectangle"},
            style=self._style(
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
    ) -> Element:
        return self._base_element(
            element_id=element_id,
            type_name="shape",
            position=origin,
            size=size,
            metadata=metadata,
            group_ids=group_ids,
            extra={"shape": "rectangle"},
            style=self._style(
                stroke_color="#7a8aa8",
                background_color="#e9f0fb",
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
            extra={"shape": "rectangle"},
            style=self._style(
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
        background_color: str | None = None,
    ) -> Element:
        return self._base_element(
            element_id=element_id,
            type_name="shape",
            position=position,
            size=size,
            metadata=metadata,
            frame_id=frame_id,
            extra={"shape": "ellipse"},
            style=self._style(
                stroke_color="#1e1e1e",
                background_color=background_color or "#d1ffd6",
                stroke_width=1.0,
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
            style=self._style(
                text_color=text_color or "#2b2b2b",
                font_family=_DEFAULT_FONT_FAMILY,
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
        width = max(80.0, len(text) * 9.0)
        if max_width is not None:
            width = max_width
        max_size = font_size or 20.0
        size = max_size
        content = text
        if max_width is not None and max_height is not None and len(text) > 0:
            content, size, height = self._fit_text(
                text=text,
                max_width=max_width,
                max_height=max_height,
                min_size=11.0,
                max_size=max_size,
            )
        else:
            if max_width is not None and len(text) > 0:
                ratio = max_width / (len(text) * 7.5)
                size = max(11.0, min(max_size, max_size * ratio))
            height = (size * 1.35) if max_height is None else max_height
        x = center.x - width / 2
        y = center.y - height / 2
        return self._base_element(
            element_id=element_id,
            type_name="text",
            position=Point(x, y),
            size=Size(width, height),
            metadata=metadata,
            group_ids=group_ids,
            frame_id=frame_id,
            extra={"text": self._html_text(content), "containerId": container_id},
            style=self._style(
                text_color="#1e1e1e",
                font_family=_DEFAULT_FONT_FAMILY,
                font_size=size,
                text_align="center",
            ),
        )

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
        dx = end.x - start.x
        dy = end.y - start.y
        points = [[0.0, 0.0], [dx, dy]]
        position, size, adjusted_points = self._normalize_points(start, points)
        return self._base_element(
            element_id=element_id,
            type_name="line",
            position=position,
            size=size,
            metadata=metadata,
            group_ids=group_ids,
            extra={"points": adjusted_points},
            style=self._style(
                stroke_color=stroke_color or "#1e1e1e",
                stroke_width=stroke_width,
                stroke_style=stroke_style or "solid",
            ),
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
        dx = end.x - start.x
        dy = end.y - start.y
        arrow_id = self._stable_id(
            "arrow", metadata.get("procedure_id", ""), label, str(start), str(end)
        )
        edge_type = metadata.get("edge_type")
        show_text = edge_type in {"branch", "branch_cycle", "procedure_cycle"}
        if points is None:
            points = [[0.0, 0.0], [dx, dy]]
            if curve_offset is not None:
                mid_x = dx / 2
                curve_dir = (
                    curve_direction if curve_direction is not None else (1.0 if dy >= 0 else -1.0)
                )
                mid_y = dy / 2 + (curve_offset * curve_dir)
                points = [[0.0, 0.0], [mid_x, mid_y], [dx, dy]]
        position, size, adjusted_points = self._normalize_points(start, points)
        direction = self._unit_vector(dx, dy)
        tip_points = [
            self._tip_point(start, -direction[0], -direction[1], start_binding),
            self._tip_point(end, direction[0], direction[1], end_binding),
        ]
        extra = {
            "points": adjusted_points,
            "tipPoints": tip_points,
            "text": self._html_text(label) if show_text else self._html_text(""),
            "label": label,
            "lineType": "arrow",
        }
        if start_arrowhead is not None:
            extra["startArrowhead"] = start_arrowhead
        if end_arrowhead is not None:
            extra["endArrowhead"] = end_arrowhead
        return self._base_element(
            element_id=arrow_id,
            type_name="line",
            position=position,
            size=size,
            metadata=metadata,
            extra=extra,
            style=self._style(
                stroke_color=stroke_color or "#1e1e1e",
                stroke_width=stroke_width if stroke_width is not None else 1.0,
                stroke_style=stroke_style or "solid",
            ),
        )

    def _block_label_placeholders(
        self,
        block: BlockPlacement,
        frame_id: str | None,
        group_ids: list[str],
        metadata: Metadata,
    ) -> list[Element]:
        placeholder_id = self._stable_id(
            "block-label-placeholder", block.procedure_id, block.block_id
        )
        center = self._center(block.position, block.size.width, block.size.height)
        meta = dict(metadata)
        meta["role"] = "block_label_placeholder"
        size = Size(1.0, 1.0)
        position = Point(center.x - 0.5, center.y - 0.5)
        return [
            self._base_element(
                element_id=placeholder_id,
                type_name="text",
                position=position,
                size=size,
                metadata=meta,
                group_ids=group_ids,
                frame_id=frame_id,
                extra={"text": "<p></p>", "containerId": None, "isPlaceholder": True},
                style=self._style(
                    text_color="#1e1e1e",
                    font_family=_DEFAULT_FONT_FAMILY,
                    font_size=12.0,
                    text_align="center",
                ),
            )
        ]

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
    ) -> Element:
        return {
            "id": element_id,
            "type": type_name,
            "position": {"x": position.x, "y": position.y},
            "size": {"width": size.width, "height": size.height},
            "rotation": 0,
            "alpha": 1.0,
            "schema": 2,
            "createdAt": self._timestamp_ms,
            "updatedAt": self._timestamp_ms,
            "zIndex": self._next_z_index(),
            "isDTO": False,
            "isExposed": True,
            "isDeleted": False,
            "locked": False,
            "groupIds": group_ids or [],
            "frameId": frame_id,
            "style": style or {},
            "cjm": metadata,
            **(extra or {}),
        }

    def _style(
        self,
        stroke_color: str | None = None,
        background_color: str | None = None,
        stroke_width: float | None = None,
        stroke_style: str | None = None,
        font_family: str | None = None,
        font_size: float | None = None,
        text_align: str | None = None,
        text_color: str | None = None,
    ) -> dict[str, Any]:
        style: dict[str, Any] = {}
        if background_color is not None:
            style["fc"] = background_color
        if stroke_color is not None:
            style["sc"] = stroke_color
        if stroke_width is not None:
            style["sw"] = stroke_width
        if stroke_style is not None:
            style["ss"] = stroke_style
        if font_family is not None:
            style["tff"] = font_family
        if font_size is not None:
            style["tfs"] = font_size
        if text_align is not None:
            style["ta"] = text_align
        if text_color is not None:
            style["tc"] = text_color
        return style

    def _html_text(self, text: str) -> str:
        lines = text.splitlines() if text is not None else []
        if not lines:
            return "<p></p>"
        return "".join(f"<p>{html.escape(line)}</p>" for line in lines)

    def _next_z_index(self) -> int:
        self._z_index += 1
        return self._z_index

    def _unit_vector(self, dx: float, dy: float) -> tuple[float, float]:
        length = math.hypot(dx, dy)
        if length == 0:
            return 0.0, 0.0
        return dx / length, dy / length

    def _tip_point(
        self,
        point: Point,
        nx: float,
        ny: float,
        binding: str | None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "position": {"x": point.x, "y": point.y},
            "normal": {"x": nx, "y": ny},
        }
        if binding:
            payload["binding"] = {"elementId": binding}
        return payload
