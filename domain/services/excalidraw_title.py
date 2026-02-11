from __future__ import annotations

import uuid
from collections.abc import Mapping
from typing import Any

from domain.models import CUSTOM_DATA_KEY

Element = dict[str, Any]
Metadata = dict[str, Any]

TITLE_ROLES = {
    "diagram_title",
    "diagram_title_panel",
    "diagram_title_rule",
}
TITLE_FONT_SIZE = 36.0
TITLE_HEIGHT = 96.0
TITLE_GAP_Y = 120.0
TITLE_MIN_WIDTH = 420.0
TITLE_WIDTH_PADDING = 160.0
TITLE_TEXT_WIDTH_PADDING = 96.0
TITLE_TEXT_HEIGHT_PADDING = 40.0
TITLE_RULE_OFFSET = 14.0
FOCUS_PADDING = 140.0
_BASE_META_KEYS = {
    "schema_version",
    "markup_type",
    "finedog_unit_id",
    "service_name",
    "criticality_level",
    "team_id",
    "team_name",
}


class ExcalidrawTitleInjector:
    def __init__(self) -> None:
        self._namespace = uuid.uuid5(uuid.NAMESPACE_DNS, "cjm-ui-convertor")

    def ensure_title(self, elements: list[Element]) -> None:
        service_name = self._extract_service_name(elements)
        if not service_name:
            return
        if self._has_title(elements):
            return
        bounds = self._elements_bounds(elements)
        if not bounds:
            return
        markup_type = self._extract_markup_type(elements)
        title = self._format_service_name_with_markup_type(service_name, markup_type)
        if not title:
            return
        base_metadata = self._extract_base_metadata(elements, service_name)
        elements.extend(self._build_title_elements(title, bounds, base_metadata))

    def _extract_service_name(self, elements: list[Element]) -> str | None:
        for element in elements:
            meta = self._metadata(element)
            raw = meta.get("service_name")
            if raw is None:
                continue
            text = str(raw).strip()
            if text:
                return text
        return None

    def _extract_base_metadata(self, elements: list[Element], service_name: str) -> Metadata:
        for element in elements:
            meta = self._metadata(element)
            if meta:
                filtered = {key: meta[key] for key in _BASE_META_KEYS if key in meta}
                filtered["service_name"] = service_name
                return filtered
        return {"service_name": service_name}

    def _extract_markup_type(self, elements: list[Element]) -> str | None:
        for element in elements:
            meta = self._metadata(element)
            raw_display = meta.get("display_markup_type")
            if raw_display is not None:
                display_text = str(raw_display).strip()
                if display_text:
                    return display_text
            raw = meta.get("markup_type")
            if raw is None:
                continue
            text = str(raw).strip()
            if text:
                return text
        return None

    def _format_service_name_with_markup_type(
        self,
        service_name: str,
        markup_type: str | None,
    ) -> str:
        title = service_name.strip()
        if not title:
            return title
        markup_label = str(markup_type or "").strip()
        if not markup_label:
            return title
        return f"[{markup_label}] {title}"

    def _has_title(self, elements: list[Element]) -> bool:
        for element in elements:
            role = self._role(element)
            if role in TITLE_ROLES:
                return True
        return False

    def _elements_bounds(self, elements: list[Element]) -> tuple[float, float, float, float] | None:
        candidates = self._preferred_elements(elements)
        bounds = self._bounds_for(candidates)
        if bounds:
            return bounds
        fallback = [element for element in elements if self._is_eligible(element)]
        return self._bounds_for(fallback)

    def _preferred_elements(self, elements: list[Element]) -> list[Element]:
        frames = [element for element in elements if element.get("type") == "frame"]
        panels = [
            element
            for element in elements
            if self._role(element) in {"scenario_panel", "scenario_procedures_panel"}
        ]
        separators = [element for element in elements if self._role(element) == "separator"]
        combined = [*frames, *panels, *separators]
        return [element for element in combined if self._is_eligible(element)]

    def _bounds_for(self, elements: list[Element]) -> tuple[float, float, float, float] | None:
        min_x = float("inf")
        min_y = float("inf")
        max_x = float("-inf")
        max_y = float("-inf")
        for element in elements:
            bounds = self._element_bounds(element)
            if not bounds:
                continue
            x1, y1, x2, y2 = bounds
            min_x = min(min_x, x1)
            min_y = min(min_y, y1)
            max_x = max(max_x, x2)
            max_y = max(max_y, y2)
        if min_x == float("inf"):
            return None
        return min_x, min_y, max_x, max_y

    def _element_bounds(self, element: Element) -> tuple[float, float, float, float] | None:
        if not self._is_eligible(element):
            return None
        try:
            x = float(element.get("x", 0.0))
            y = float(element.get("y", 0.0))
            width = float(element.get("width", 0.0))
            height = float(element.get("height", 0.0))
        except (TypeError, ValueError):
            return None
        return x, y, x + width, y + height

    def _is_eligible(self, element: Element) -> bool:
        if element.get("isDeleted"):
            return False
        if self._role(element) in TITLE_ROLES:
            return False
        type_name = element.get("type")
        if type_name == "arrow":
            return False
        return all(key in element for key in ("x", "y", "width", "height"))

    def _build_title_elements(
        self,
        service_name: str,
        bounds: tuple[float, float, float, float],
        base_metadata: Metadata,
    ) -> list[Element]:
        min_x, min_y, max_x, _ = bounds
        content_width = max_x - min_x
        title_width = max(content_width + TITLE_WIDTH_PADDING, TITLE_MIN_WIDTH)
        title_height = TITLE_HEIGHT
        gap_y = TITLE_GAP_Y
        origin_x = (min_x + max_x) / 2 - title_width / 2
        origin_y = min_y - gap_y - title_height

        group_id = self._stable_id("diagram-title-group", service_name)
        panel_id = self._stable_id("diagram-title-panel", service_name)
        rule_id = self._stable_id("diagram-title-rule", service_name)
        text_id = self._stable_id("diagram-title-text", service_name)
        panel_meta = self._with_role(base_metadata, "diagram_title_panel")
        rule_meta = self._with_role(base_metadata, "diagram_title_rule")
        text_meta = self._with_role(base_metadata, "diagram_title")

        panel = self._base_shape(
            element_id=panel_id,
            type_name="rectangle",
            x=origin_x,
            y=origin_y,
            width=title_width,
            height=title_height,
            group_ids=[group_id],
            extra={
                "strokeColor": "#34445b",
                "backgroundColor": "#eef3ff",
                "fillStyle": "solid",
                "roughness": 0,
                "roundness": {"type": 3},
                "strokeWidth": 2,
            },
            metadata=panel_meta,
        )
        line_y = origin_y + title_height - TITLE_RULE_OFFSET
        rule = self._line_element(
            element_id=rule_id,
            start=(origin_x + 26.0, line_y),
            end=(origin_x + title_width - 26.0, line_y),
            metadata=rule_meta,
            stroke_color="#7b8fb0",
            stroke_width=3,
            group_ids=[group_id],
        )
        title_center = (origin_x + title_width / 2, origin_y + title_height / 2)
        text = self._text_element(
            element_id=text_id,
            text=service_name,
            center=title_center,
            metadata=text_meta,
            group_ids=[group_id],
            max_width=title_width - TITLE_TEXT_WIDTH_PADDING,
            max_height=title_height - TITLE_TEXT_HEIGHT_PADDING,
            font_size=TITLE_FONT_SIZE,
        )
        return [panel, rule, text]

    def _text_element(
        self,
        element_id: str,
        text: str,
        center: tuple[float, float],
        metadata: Metadata,
        group_ids: list[str],
        max_width: float,
        max_height: float,
        font_size: float,
    ) -> Element:
        content, size, height = self._fit_text(
            text=text,
            max_width=max_width,
            max_height=max_height,
            min_size=12.0,
            max_size=font_size,
        )
        width = max_width
        x = center[0] - width / 2
        y = center[1] - height / 2
        seed = self._stable_seed(element_id)
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
            "groupIds": group_ids,
            "frameId": None,
            "roundness": None,
            "seed": seed,
            "version": 1,
            "versionNonce": self._stable_seed(f"{element_id}:nonce"),
            "isDeleted": False,
            "boundElements": [],
            "locked": False,
            "text": content,
            "fontSize": size,
            "fontFamily": 1,
            "textAlign": "center",
            "verticalAlign": "middle",
            "baseline": height / 2,
            "containerId": None,
            "customData": {CUSTOM_DATA_KEY: metadata},
        }

    def _fit_text(
        self,
        text: str,
        max_width: float,
        max_height: float,
        min_size: float,
        max_size: float,
    ) -> tuple[str, float, float]:
        if not text.strip():
            size = max_size
            height = min(max_height, size * 1.35)
            return text, size, height

        words = text.split()
        width_factor = 0.6
        line_height = 1.35

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

    def _line_element(
        self,
        element_id: str,
        start: tuple[float, float],
        end: tuple[float, float],
        metadata: Metadata,
        stroke_color: str,
        stroke_width: float,
        group_ids: list[str],
    ) -> Element:
        dx = end[0] - start[0]
        dy = end[1] - start[1]
        points = [[0.0, 0.0], [dx, dy]]
        min_x = min(point[0] for point in points)
        max_x = max(point[0] for point in points)
        min_y = min(point[1] for point in points)
        max_y = max(point[1] for point in points)
        width = max_x - min_x
        height = max_y - min_y
        adjusted_points = [[point[0] - min_x, point[1] - min_y] for point in points]
        seed = self._stable_seed(element_id)
        return {
            "id": element_id,
            "type": "line",
            "x": start[0] + min_x,
            "y": start[1] + min_y,
            "width": width,
            "height": height,
            "angle": 0,
            "strokeColor": stroke_color,
            "backgroundColor": "transparent",
            "fillStyle": "solid",
            "strokeWidth": stroke_width,
            "strokeStyle": "solid",
            "roughness": 0,
            "opacity": 100,
            "groupIds": group_ids,
            "roundness": None,
            "seed": seed,
            "version": 1,
            "versionNonce": self._stable_seed(f"{element_id}:nonce"),
            "isDeleted": False,
            "boundElements": [],
            "locked": False,
            "points": adjusted_points,
            "customData": {CUSTOM_DATA_KEY: metadata},
        }

    def _base_shape(
        self,
        element_id: str,
        type_name: str,
        x: float,
        y: float,
        width: float,
        height: float,
        group_ids: list[str],
        extra: dict[str, Any],
        metadata: Metadata,
    ) -> Element:
        seed = self._stable_seed(element_id)
        return {
            "id": element_id,
            "type": type_name,
            "x": x,
            "y": y,
            "width": width,
            "height": height,
            "angle": 0,
            "strokeWidth": 1,
            "strokeStyle": "solid",
            "roughness": 0,
            "opacity": 100,
            "groupIds": group_ids,
            "roundness": None,
            "seed": seed,
            "version": 1,
            "versionNonce": self._stable_seed(f"{element_id}:nonce"),
            "isDeleted": False,
            "boundElements": [],
            "locked": False,
            "frameId": None,
            "customData": {CUSTOM_DATA_KEY: metadata},
            **extra,
        }

    def _with_role(self, base: Metadata, role: str) -> Metadata:
        merged = dict(base)
        merged["role"] = role
        return merged

    def _metadata(self, element: Mapping[str, Any]) -> Metadata:
        custom = element.get("customData")
        if not isinstance(custom, Mapping):
            return {}
        meta = custom.get(CUSTOM_DATA_KEY)
        return dict(meta) if isinstance(meta, Mapping) else {}

    def _role(self, element: Mapping[str, Any]) -> str | None:
        meta = self._metadata(element)
        role = meta.get("role")
        return str(role) if role is not None else None

    def _stable_id(self, *parts: str) -> str:
        return str(uuid.uuid5(self._namespace, "|".join(parts)))

    def _stable_seed(self, label: str) -> int:
        return int(uuid.uuid5(self._namespace, label).int % (2**31 - 1))


def ensure_service_title(elements: list[Element]) -> None:
    ExcalidrawTitleInjector().ensure_title(elements)


def apply_title_focus(app_state: dict[str, Any], elements: list[Element]) -> None:
    title_panel = _find_first_by_role(elements, "diagram_title_panel")
    if not title_panel:
        return
    first_frame = _find_first_frame(elements)
    if not first_frame:
        return
    bounds = _merge_bounds([title_panel, first_frame])
    if not bounds:
        return
    min_x, min_y, _, _ = bounds
    app_state["scrollX"] = -min_x + FOCUS_PADDING
    app_state["scrollY"] = -min_y + FOCUS_PADDING
    zoom = app_state.get("zoom")
    if not isinstance(zoom, Mapping) or "value" not in zoom:
        app_state["zoom"] = {"value": 1}


def _find_first_frame(elements: list[Element]) -> Element | None:
    frames = [element for element in elements if element.get("type") == "frame"]
    if not frames:
        return None
    return min(frames, key=lambda item: (float(item.get("x", 0.0)), float(item.get("y", 0.0))))


def _find_first_by_role(elements: list[Element], role: str) -> Element | None:
    for element in elements:
        meta = element.get("customData", {}).get(CUSTOM_DATA_KEY)
        if isinstance(meta, Mapping) and meta.get("role") == role:
            return element
    return None


def _merge_bounds(elements: list[Element]) -> tuple[float, float, float, float] | None:
    min_x = float("inf")
    min_y = float("inf")
    max_x = float("-inf")
    max_y = float("-inf")
    for element in elements:
        bounds = _element_bounds(element)
        if not bounds:
            continue
        x1, y1, x2, y2 = bounds
        min_x = min(min_x, x1)
        min_y = min(min_y, y1)
        max_x = max(max_x, x2)
        max_y = max(max_y, y2)
    if min_x == float("inf"):
        return None
    return min_x, min_y, max_x, max_y


def _element_bounds(element: Element) -> tuple[float, float, float, float] | None:
    try:
        x = float(element.get("x", 0.0))
        y = float(element.get("y", 0.0))
        width = float(element.get("width", 0.0))
        height = float(element.get("height", 0.0))
    except (TypeError, ValueError):
        return None
    return x, y, x + width, y + height
