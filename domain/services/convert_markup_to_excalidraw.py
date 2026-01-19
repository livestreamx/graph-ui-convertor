from __future__ import annotations

from typing import Any

from domain.models import CUSTOM_DATA_KEY, ExcalidrawDocument, FramePlacement, Point, Size
from domain.ports.layout import LayoutEngine
from domain.services.convert_markup_base import (
    Element,
    ElementRegistry,
    MarkupToDiagramConverter,
    Metadata,
)
from domain.services.excalidraw_links import ExcalidrawLinkTemplates, ensure_excalidraw_links
from domain.services.excalidraw_title import apply_title_focus


class MarkupToExcalidrawConverter(MarkupToDiagramConverter):
    def __init__(
        self,
        layout_engine: LayoutEngine,
        link_templates: ExcalidrawLinkTemplates | None = None,
    ) -> None:
        super().__init__(layout_engine)
        self.link_templates = link_templates

    def _build_document(
        self, elements: list[Element], app_state: dict[str, Any]
    ) -> ExcalidrawDocument:
        return ExcalidrawDocument(elements=elements, app_state=app_state, files={})

    def _build_app_state(self, elements: list[Element]) -> dict[str, Any]:
        app_state = {
            "viewBackgroundColor": "#ffffff",
            "gridSize": None,
            "currentItemFontFamily": 1,
            "currentItemFontSize": 20,
            "currentItemStrokeColor": "#1e1e1e",
        }
        apply_title_focus(app_state, elements)
        return app_state

    def _post_process_elements(self, elements: list[Element]) -> None:
        ensure_excalidraw_links(elements, self.link_templates)
        edges: list[Element] = []
        rest: list[Element] = []
        for element in elements:
            meta = element.get("customData", {}).get(CUSTOM_DATA_KEY, {}).get("role")
            if element.get("type") == "arrow" or meta == "edge":
                edges.append(element)
            else:
                rest.append(element)
        if edges:
            elements[:] = edges + rest

    def _register_edge_bindings(self, arrow: Element, registry: ElementRegistry) -> None:
        arrow_id = arrow.get("id")
        if not arrow_id:
            return
        for key in ("startBinding", "endBinding"):
            binding = arrow.get(key)
            if not binding:
                continue
            target_id = binding.get("elementId")
            target = registry.index.get(target_id)
            if target is not None:
                target.setdefault("boundElements", []).append({"id": arrow_id, "type": "arrow"})

    def _offset_element(self, element: Element, dx: float, dy: float) -> None:
        if "x" not in element or "y" not in element:
            return
        element["x"] = float(element.get("x", 0.0)) + dx
        element["y"] = float(element.get("y", 0.0)) + dy

    def _frame_element(
        self,
        element_id: str,
        frame: FramePlacement,
        metadata: Metadata,
        name: str | None = None,
    ) -> Element:
        background = metadata.get("procedure_color")
        background_color = background if isinstance(background, str) else "transparent"
        return self._base_shape(
            element_id=element_id,
            type_name="frame",
            position=frame.origin,
            width=frame.size.width,
            height=frame.size.height,
            extra={
                "name": name or frame.procedure_id,
                "strokeColor": "#1e1e1e",
                "backgroundColor": background_color,
                "fillStyle": "solid",
                "seed": self._rand_seed(),
                "version": 1,
                "versionNonce": self._rand_seed(),
                "nameFontSize": 28,
            },
            metadata=metadata,
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
        return self._base_shape(
            element_id=element_id,
            type_name="rectangle",
            position=position,
            width=size.width,
            height=size.height,
            frame_id=frame_id,
            group_ids=group_ids,
            extra={
                "strokeColor": "#1e1e1e",
                "backgroundColor": background_color or "#cce5ff",
                "fillStyle": "hachure",
                "seed": self._rand_seed(),
                "version": 1,
                "versionNonce": self._rand_seed(),
                "boundElements": [],
            },
            metadata=metadata,
        )

    def _scenario_panel_element(
        self,
        element_id: str,
        origin: Point,
        size: Size,
        metadata: Metadata,
        group_ids: list[str],
    ) -> Element:
        return self._base_shape(
            element_id=element_id,
            type_name="rectangle",
            position=origin,
            width=size.width,
            height=size.height,
            group_ids=group_ids,
            extra={
                "strokeColor": "#c7bba3",
                "backgroundColor": "#f7f3ea",
                "fillStyle": "solid",
                "roughness": 0,
                "seed": self._rand_seed(),
                "version": 1,
                "versionNonce": self._rand_seed(),
                "roundness": {"type": 3},
            },
            metadata=metadata,
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
        return self._base_shape(
            element_id=element_id,
            type_name="rectangle",
            position=origin,
            width=size.width,
            height=size.height,
            group_ids=group_ids,
            extra={
                "strokeColor": stroke_color or "#7a8aa8",
                "backgroundColor": background_color or "#e9f0fb",
                "fillStyle": "solid",
                "roughness": 0,
                "seed": self._rand_seed(),
                "version": 1,
                "versionNonce": self._rand_seed(),
                "roundness": {"type": 3},
            },
            metadata=metadata,
        )

    def _title_panel_element(
        self,
        element_id: str,
        origin: Point,
        size: Size,
        metadata: Metadata,
        group_ids: list[str],
    ) -> Element:
        return self._base_shape(
            element_id=element_id,
            type_name="rectangle",
            position=origin,
            width=size.width,
            height=size.height,
            group_ids=group_ids,
            extra={
                "strokeColor": "#34445b",
                "backgroundColor": "#eef3ff",
                "fillStyle": "solid",
                "roughness": 0,
                "seed": self._rand_seed(),
                "version": 1,
                "versionNonce": self._rand_seed(),
                "roundness": {"type": 3},
                "strokeWidth": 2,
            },
            metadata=metadata,
        )

    def _ellipse_element(
        self,
        element_id: str,
        position: Point,
        size: Size,
        frame_id: str | None,
        metadata: Metadata,
        background_color: str | None = None,
        stroke_color: str | None = None,
        stroke_style: str | None = None,
        stroke_width: float | None = None,
    ) -> Element:
        return self._base_shape(
            element_id=element_id,
            type_name="ellipse",
            position=position,
            width=size.width,
            height=size.height,
            frame_id=frame_id,
            extra={
                "strokeColor": stroke_color or "#1e1e1e",
                "backgroundColor": background_color or "#d1ffd6",
                "fillStyle": "solid",
                "strokeStyle": stroke_style or "solid",
                "strokeWidth": stroke_width if stroke_width is not None else 1,
                "seed": self._rand_seed(),
                "version": 1,
                "versionNonce": self._rand_seed(),
            },
            metadata=metadata,
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
        return {
            "id": element_id,
            "type": "text",
            "x": origin.x,
            "y": origin.y,
            "width": width,
            "height": height,
            "angle": 0,
            "strokeColor": text_color or "#2b2b2b",
            "backgroundColor": "transparent",
            "fillStyle": "solid",
            "strokeWidth": 1,
            "strokeStyle": "solid",
            "roughness": 0,
            "opacity": 100,
            "groupIds": group_ids or [],
            "frameId": None,
            "roundness": None,
            "seed": self._rand_seed(),
            "version": 1,
            "versionNonce": self._rand_seed(),
            "isDeleted": False,
            "boundElements": [],
            "locked": False,
            "text": text,
            "fontSize": font_size,
            "fontFamily": 1,
            "textAlign": "left",
            "verticalAlign": "top",
            "baseline": font_size,
            "customData": {CUSTOM_DATA_KEY: metadata},
        }

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
        return {
            "id": element_id,
            "type": "text",
            "x": x,
            "y": y,
            "width": width,
            "height": height,
            "angle": 0,
            "strokeColor": "#1e1e1e",
            "backgroundColor": "transparent",
            "fillStyle": "solid",
            "strokeWidth": 1,
            "strokeStyle": "solid",
            "roughness": 0,
            "opacity": 100,
            "groupIds": group_ids or [],
            "frameId": frame_id,
            "roundness": None,
            "seed": self._rand_seed(),
            "version": 1,
            "versionNonce": self._rand_seed(),
            "isDeleted": False,
            "boundElements": [],
            "locked": False,
            "text": content,
            "fontSize": size,
            "fontFamily": 1,
            "textAlign": "center",
            "verticalAlign": "middle",
            "baseline": height / 2,
            "containerId": container_id,
            "customData": {CUSTOM_DATA_KEY: metadata},
        }

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
        return {
            "id": element_id,
            "type": "line",
            "x": position.x,
            "y": position.y,
            "width": size.width,
            "height": size.height,
            "angle": 0,
            "strokeColor": stroke_color or "#1e1e1e",
            "backgroundColor": "transparent",
            "fillStyle": "solid",
            "strokeWidth": stroke_width,
            "strokeStyle": stroke_style or "solid",
            "roughness": 0,
            "opacity": 100,
            "groupIds": group_ids or [],
            "roundness": None,
            "seed": self._rand_seed(),
            "version": 1,
            "versionNonce": self._rand_seed(),
            "isDeleted": False,
            "boundElements": [],
            "locked": False,
            "points": adjusted_points,
            "customData": {CUSTOM_DATA_KEY: metadata},
        }

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
                direction = (
                    curve_direction if curve_direction is not None else (1.0 if dy >= 0 else -1.0)
                )
                mid_y = dy / 2 + (curve_offset * direction)
                points = [[0.0, 0.0], [mid_x, mid_y], [dx, dy]]
                roundness = {"type": 3}
        if roundness is None:
            roundness = {"type": 2}

        position, size, adjusted_points = self._normalize_points(start, points)
        arrow = {
            "id": arrow_id,
            "type": "arrow",
            "x": position.x,
            "y": position.y,
            "width": size.width,
            "height": size.height,
            "angle": 0,
            "strokeColor": stroke_color or "#1e1e1e",
            "backgroundColor": "transparent",
            "fillStyle": "solid",
            "strokeWidth": stroke_width if stroke_width is not None else 1,
            "strokeStyle": stroke_style or "solid",
            "roughness": 0,
            "opacity": 100,
            "groupIds": [],
            "roundness": roundness,
            "seed": self._rand_seed(),
            "version": 1,
            "versionNonce": self._rand_seed(),
            "isDeleted": False,
            "boundElements": [],
            "locked": False,
            "points": adjusted_points,
            "startBinding": {"elementId": start_binding, "focus": 0.0, "gap": 8}
            if start_binding
            else None,
            "endBinding": {"elementId": end_binding, "focus": 0.0, "gap": 8}
            if end_binding
            else None,
            "label": label,
            "text": label if show_text else "",
            "customData": {CUSTOM_DATA_KEY: metadata},
        }
        if start_arrowhead is not None:
            arrow["startArrowhead"] = start_arrowhead
        if end_arrowhead is not None:
            arrow["endArrowhead"] = end_arrowhead
        return arrow

    def _base_shape(
        self,
        element_id: str,
        type_name: str,
        position: Point,
        width: float,
        height: float,
        metadata: Metadata,
        frame_id: str | None = None,
        group_ids: list[str] | None = None,
        extra: dict[str, Any] | None = None,
    ) -> Element:
        return {
            "id": element_id,
            "type": type_name,
            "x": position.x,
            "y": position.y,
            "width": width,
            "height": height,
            "angle": 0,
            "strokeWidth": 1,
            "strokeStyle": "solid",
            "roughness": 0,
            "opacity": 100,
            "groupIds": group_ids or [],
            "roundness": None,
            "seed": self._rand_seed(),
            "version": 1,
            "versionNonce": self._rand_seed(),
            "isDeleted": False,
            "boundElements": [],
            "locked": False,
            "frameId": frame_id,
            "customData": {CUSTOM_DATA_KEY: metadata},
            **(extra or {}),
        }
