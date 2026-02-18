from __future__ import annotations

import re
from typing import Any, cast

from domain.models import MarkupDocument, Point, ServiceZonePlacement, UnidrawDocument
from domain.services.convert_markup_base import ElementRegistry, Metadata
from domain.services.convert_markup_to_unidraw import MarkupToUnidrawConverter
from domain.services.convert_procedure_graph_base import ProcedureGraphConverterMixin

_MERGE_INFO_TEXT_COLOR = "#fc6f57"
_MERGE_INFO_PANEL_SIDE_PADDING = 18.0


class ProcedureGraphToUnidrawConverter(ProcedureGraphConverterMixin, MarkupToUnidrawConverter):
    def _post_process_elements(self, elements: list[dict[str, Any]]) -> None:
        super()._post_process_elements(elements)

        marker_centers: dict[tuple[str, int], Point] = {}
        merge_panel_layout: dict[str, tuple[float, float]] = {}
        dashed_code = self._stroke_style_code("dashed")
        for element in elements:
            cjm = element.get("cjm", {})
            if not isinstance(cjm, dict):
                continue
            role = cjm.get("role")
            if role == "frame" and cjm.get("is_intersection") is True:
                style = element.get("style")
                if isinstance(style, dict):
                    style["fc"] = "transparent"
                continue
            if role in {"service_zone", "intersection_highlight"}:
                style = element.get("style")
                if isinstance(style, dict):
                    style["ss"] = dashed_code
            if role == "intersection_index_marker":
                key = self._merge_key(cjm)
                center = self._element_center(element)
                if key is not None and center is not None:
                    marker_centers[key] = center
            if role == "scenario_merge_panel":
                group_id = self._first_group_id(element)
                position = element.get("position")
                size = element.get("size")
                if group_id is not None and isinstance(position, dict) and isinstance(size, dict):
                    panel_left = float(position.get("x", 0.0))
                    panel_width = float(size.get("width", 0.0))
                    merge_panel_layout[group_id] = (panel_left, panel_width)

        for element in elements:
            cjm = element.get("cjm", {})
            if isinstance(cjm, dict) and cjm.get("role") == "scenario_merge":
                style = element.get("style")
                if isinstance(style, dict):
                    style["tc"] = _MERGE_INFO_TEXT_COLOR
                    style["tw"] = True
                group_id = self._first_group_id(element)
                panel = merge_panel_layout.get(group_id) if group_id is not None else None
                size = element.get("size")
                position = element.get("position")
                if panel and isinstance(size, dict):
                    panel_left, panel_width = panel
                    target_width = max(1.0, panel_width - _MERGE_INFO_PANEL_SIDE_PADDING * 2)
                    size["width"] = max(float(size.get("width", 0.0)), target_width)
                    if isinstance(position, dict):
                        min_text_x = panel_left + _MERGE_INFO_PANEL_SIDE_PADDING
                        position["x"] = max(float(position.get("x", min_text_x)), min_text_x)

            if not isinstance(cjm, dict) or cjm.get("role") != "intersection_index_label":
                continue
            style = element.get("style")
            if not isinstance(style, dict):
                continue
            font_size = max(float(style.get("tfs", 0.0) or 0.0), 24.0)
            style["tfs"] = font_size
            style["ta"] = "m"
            style["tva"] = "m"

            key = self._merge_key(cjm)
            center = marker_centers.get(key) if key is not None else None
            if center is None:
                center = self._element_center(element)
            if center is None:
                continue

            text = self._plain_text(element.get("text"))
            width = self._text_width(
                text,
                font_size,
                max_width=None,
                width_factor=self._text_width_factor(cjm),
            )
            height = max(font_size * 1.11, 1.0)
            element["size"] = {"width": width, "height": height}
            element["position"] = {
                "x": center.x - width / 2,
                "y": center.y - height / 2,
            }

        self._prioritize_zone_background_layers(elements)

    def _build_service_zone_rectangles(
        self,
        zones: list[ServiceZonePlacement],
        registry: ElementRegistry,
        base_metadata: Metadata,
    ) -> None:
        zone_layers = sorted(
            zones,
            key=lambda candidate: candidate.size.width * candidate.size.height,
            reverse=True,
        )
        for zone in zone_layers:
            zone_scope = self._service_zone_scope(zone)
            group_id = self._stable_id("service-zone-group", *zone_scope)
            zone_id = self._stable_id("service-zone", *zone_scope)
            zone_meta: dict[str, object] = {
                "role": "service_zone",
                "service_name": zone.service_name,
                "service_color": zone.color,
            }
            if zone.team_name:
                zone_meta["team_name"] = zone.team_name
            if zone.team_id is not None:
                zone_meta["team_id"] = zone.team_id
            if zone.procedure_ids:
                zone_meta["procedure_ids"] = list(zone.procedure_ids)
            registry.add(
                self._rectangle_element(
                    element_id=zone_id,
                    position=zone.origin,
                    size=zone.size,
                    frame_id=None,
                    group_ids=[group_id],
                    metadata=self._with_base_metadata(zone_meta, base_metadata),
                    background_color="transparent",
                    stroke_color="#000000",
                    stroke_style="dashed",
                    fill_style="solid",
                    roundness={"type": 3},
                )
            )

    def _build_service_zone_labels(
        self,
        zones: list[ServiceZonePlacement],
        registry: ElementRegistry,
        base_metadata: Metadata,
    ) -> None:
        for zone in zones:
            zone_scope = self._service_zone_scope(zone)
            group_id = self._stable_id("service-zone-group", *zone_scope)
            label_meta: dict[str, object] = {
                "service_name": zone.service_name,
                "service_color": zone.color,
            }
            if zone.team_name:
                label_meta["team_name"] = zone.team_name
            if zone.team_id is not None:
                label_meta["team_id"] = zone.team_id
            panel_meta = self._with_base_metadata(
                {
                    **label_meta,
                    "role": "service_zone_label_panel",
                },
                base_metadata,
            )
            panel_id = self._stable_id("service-zone-label-panel", *zone_scope)
            registry.add(
                self._rectangle_element(
                    element_id=panel_id,
                    position=zone.label_origin,
                    size=zone.label_size,
                    frame_id=None,
                    group_ids=[group_id],
                    metadata=panel_meta,
                    background_color=zone.color,
                    stroke_color="#000000",
                    fill_style="solid",
                    roundness={"type": 3},
                )
            )

            text_padding_x = max(8.0, zone.label_font_size * 0.3)
            text_padding_y = max(4.0, zone.label_font_size * 0.22)
            label_id = self._stable_id("service-zone-label", *zone_scope)
            label_element = self._text_block_element(
                element_id=label_id,
                text=self._format_service_name_with_markup_type(
                    zone.service_name,
                    zone.markup_type,
                ),
                origin=Point(
                    zone.label_origin.x + text_padding_x,
                    zone.label_origin.y + text_padding_y,
                ),
                width=max(1.0, zone.label_size.width - text_padding_x * 2),
                height=max(1.0, zone.label_size.height - text_padding_y * 2),
                metadata=self._with_base_metadata(
                    {
                        **label_meta,
                        "role": "service_zone_label",
                    },
                    base_metadata,
                ),
                group_ids=[group_id],
                font_size=zone.label_font_size,
                text_color="#000000",
            )
            if isinstance(label_element, dict):
                self._apply_service_zone_label_style(label_element)
            registry.add(label_element)

    def convert(self, document: MarkupDocument) -> UnidrawDocument:
        return cast(UnidrawDocument, self._convert_procedure_graph(document))

    def _merge_key(self, metadata: dict[str, Any]) -> tuple[str, int] | None:
        procedure_id = metadata.get("procedure_id")
        merge_index = metadata.get("merge_index")
        if isinstance(procedure_id, str) and isinstance(merge_index, int):
            return procedure_id, merge_index
        return None

    def _element_center(self, element: dict[str, Any]) -> Point | None:
        position = element.get("position")
        size = element.get("size")
        if not isinstance(position, dict) or not isinstance(size, dict):
            return None
        x = float(position.get("x", 0.0))
        y = float(position.get("y", 0.0))
        width = float(size.get("width", 0.0))
        height = float(size.get("height", 0.0))
        return Point(x + width / 2, y + height / 2)

    def _plain_text(self, value: Any) -> str:
        if not isinstance(value, str):
            return ""
        text = re.sub(r"<[^>]+>", "", value)
        return text.replace("\n", "").strip()

    def _first_group_id(self, element: dict[str, Any]) -> str | None:
        group_ids = element.get("groupIds")
        if not isinstance(group_ids, list):
            return None
        for value in group_ids:
            if isinstance(value, str) and value:
                return value
        return None

    def _prioritize_zone_background_layers(self, elements: list[dict[str, Any]]) -> None:
        edge_elements: list[dict[str, Any]] = []
        rest: list[dict[str, Any]] = []
        for element in elements:
            cjm = element.get("cjm", {})
            if isinstance(cjm, dict) and cjm.get("role") == "edge":
                edge_elements.append(element)
            else:
                rest.append(element)

        zones: list[dict[str, Any]] = []
        zone_panels: list[dict[str, Any]] = []
        zone_labels: list[dict[str, Any]] = []
        other: list[dict[str, Any]] = []
        for element in rest:
            cjm = element.get("cjm", {})
            role = cjm.get("role") if isinstance(cjm, dict) else None
            if role == "service_zone":
                zones.append(element)
            elif role == "service_zone_label_panel":
                zone_panels.append(element)
            elif role == "service_zone_label":
                zone_labels.append(element)
            else:
                other.append(element)

        zones.sort(
            key=lambda zone: float(zone.get("size", {}).get("width", 0.0))
            * float(zone.get("size", {}).get("height", 0.0)),
            reverse=True,
        )
        ordered_rest = zones + zone_panels + zone_labels + other
        elements[:] = edge_elements + ordered_rest
        for idx, edge in enumerate(edge_elements, start=1):
            edge["zIndex"] = -idx
        for idx, element in enumerate(ordered_rest, start=1):
            element["zIndex"] = idx
