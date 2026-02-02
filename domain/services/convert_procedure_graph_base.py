from __future__ import annotations

import math
from typing import Any

from domain.models import (
    END_TYPE_COLORS,
    END_TYPE_DEFAULT,
    FramePlacement,
    MarkupDocument,
    Point,
    ScenarioPlacement,
    ServiceZonePlacement,
    Size,
)
from domain.services.convert_markup_base import (
    MERGE_ALERT_COLOR,
    ElementRegistry,
    MarkupToDiagramConverter,
    Metadata,
)


class ProcedureGraphConverterMixin(MarkupToDiagramConverter):
    def _convert_procedure_graph(self, document: MarkupDocument) -> Any:
        plan = self.layout_engine.build_plan(document)
        registry = ElementRegistry()
        base_metadata = self._base_metadata(document)
        proc_name_lookup = {
            proc.procedure_id: proc.procedure_name
            for proc in document.procedures
            if proc.procedure_name
        }
        self._build_service_zone_rectangles(plan.service_zones, registry, base_metadata)
        merge_numbers = self._merge_number_lookup(plan.scenarios)
        frame_ids = self._build_procedure_frames(
            document,
            plan.frames,
            registry,
            base_metadata,
            proc_name_lookup,
            merge_numbers,
        )
        self._build_procedure_stats(document, plan.frames, frame_ids, registry, base_metadata)
        self._build_separators(plan.separators, registry, base_metadata)
        self._build_scenarios(plan.scenarios, registry, base_metadata)
        self._build_procedure_flow_edges(document, plan.frames, frame_ids, registry, base_metadata)
        self._build_service_zone_labels(plan.service_zones, registry, base_metadata)
        self._build_service_title(plan, registry, base_metadata, document.service_name)
        self._center_on_first_frame(plan, registry.elements)
        self._post_process_elements(registry.elements)
        app_state = self._build_app_state(registry.elements)
        return self._build_document(registry.elements, app_state)

    def _procedure_edge_stroke_width(self, is_cycle: bool) -> float | None:
        return 1.0

    def _merge_number_lookup(
        self, scenarios: list[ScenarioPlacement]
    ) -> dict[str, list[int]] | None:
        merge_numbers: dict[str, list[int]] = {}
        for scenario in scenarios:
            numbers = getattr(scenario, "merge_node_numbers", None)
            if isinstance(numbers, dict):
                for proc_id, index in numbers.items():
                    if not isinstance(proc_id, str):
                        continue
                    if isinstance(index, int):
                        merge_numbers.setdefault(proc_id, []).append(index)
                    elif isinstance(index, list | tuple):
                        for value in index:
                            if isinstance(value, int):
                                merge_numbers.setdefault(proc_id, []).append(value)
        if not merge_numbers:
            return None
        for proc_id, values in merge_numbers.items():
            seen: set[int] = set()
            ordered = []
            for value in values:
                if value in seen:
                    continue
                seen.add(value)
                ordered.append(value)
            merge_numbers[proc_id] = ordered
        return merge_numbers

    def _merge_marker_layout(
        self,
        frame: FramePlacement,
        highlight_padding: float,
        marker_diameter: float,
        count: int,
    ) -> list[tuple[Point, Point, Point]]:
        if count <= 1:
            pointer_start = Point(
                x=frame.origin.x - highlight_padding * 3.5,
                y=frame.origin.y - highlight_padding * 2.0,
            )
            pointer_end = Point(
                x=frame.origin.x - highlight_padding * 0.4,
                y=frame.origin.y + frame.size.height * 0.2,
            )
            marker_center = Point(
                x=pointer_start.x - highlight_padding * 0.95,
                y=pointer_start.y - highlight_padding * 0.95,
            )
            return [(pointer_start, marker_center, pointer_end)]

        center = Point(
            x=frame.origin.x + frame.size.width / 2,
            y=frame.origin.y + frame.size.height / 2,
        )
        radius_x = frame.size.width / 2 + highlight_padding
        radius_y = frame.size.height / 2 + highlight_padding
        base_radius = max(radius_x, radius_y) + highlight_padding * 1.6
        marker_offset = marker_diameter * 0.65 + highlight_padding * 0.6

        angle_step = math.radians(20.0)
        min_range = math.radians(36.0)
        max_range = math.radians(120.0)
        angle_range = min(max_range, max(min_range, angle_step * (count - 1)))
        base_angle = math.radians(225.0)
        start_angle = base_angle - angle_range / 2
        if count > 1:
            angle_step = angle_range / (count - 1)
        angles = [start_angle + idx * angle_step for idx in range(count)]

        layout: list[tuple[Point, Point, Point]] = []
        for idx, angle in enumerate(angles):
            spread = (idx - (count - 1) / 2) * (marker_diameter * 0.2)
            pointer_radius = base_radius + spread
            pointer_start = Point(
                x=center.x + math.cos(angle) * pointer_radius,
                y=center.y + math.sin(angle) * pointer_radius,
            )
            marker_center = Point(
                x=center.x + math.cos(angle) * (pointer_radius + marker_offset),
                y=center.y + math.sin(angle) * (pointer_radius + marker_offset),
            )
            pointer_end = Point(
                x=center.x + math.cos(angle) * radius_x,
                y=center.y + math.sin(angle) * radius_y,
            )
            layout.append((pointer_start, marker_center, pointer_end))
        return layout

    def _apply_text_color(self, element: dict[str, Any], color: str) -> None:
        if "strokeColor" in element:
            element["strokeColor"] = color
        style = element.get("style")
        if isinstance(style, dict):
            if "tc" in style:
                style["tc"] = color

    def _apply_text_bold(self, element: dict[str, Any]) -> None:
        if "strokeColor" in element:
            element["fontStyle"] = "bold"
            element["fontWeight"] = 700
            if "strokeWidth" in element:
                element["strokeWidth"] = max(2.0, float(element.get("strokeWidth", 1.0)))

    def _format_procedure_label(self, procedure_name: str | None, procedure_id: str) -> str:
        return procedure_name or procedure_id

    def _build_procedure_frames(
        self,
        document: MarkupDocument,
        frames: list[FramePlacement],
        registry: ElementRegistry,
        base_metadata: Metadata,
        proc_name_lookup: dict[str, str],
        merge_numbers: dict[str, list[int]] | None = None,
    ) -> dict[str, str]:
        frame_ids: dict[str, str] = {}
        procedure_meta = document.procedure_meta or {}
        for frame in frames:
            frame_id = self._stable_id("frame", frame.procedure_id)
            frame_ids[frame.procedure_id] = frame_id
            procedure_name = proc_name_lookup.get(frame.procedure_id)
            label = self._format_procedure_label(procedure_name, frame.procedure_id)
            frame_meta: dict[str, object] = {
                "procedure_id": frame.procedure_id,
                "role": "frame",
            }
            if procedure_name:
                frame_meta["procedure_name"] = procedure_name
            meta = procedure_meta.get(frame.procedure_id, {})
            color = meta.get("procedure_color")
            if isinstance(color, str) and color:
                frame_meta["procedure_color"] = color
            is_intersection = meta.get("is_intersection") is True
            if is_intersection:
                frame_meta["is_intersection"] = True
            registry.add(
                self._frame_element(
                    element_id=frame_id,
                    frame=frame,
                    metadata=self._with_base_metadata(frame_meta, base_metadata),
                    name=label,
                )
            )
            if not is_intersection:
                continue
            highlight_padding = 18.0
            highlight_color = MERGE_ALERT_COLOR
            highlight_meta = self._with_base_metadata(
                {
                    "procedure_id": frame.procedure_id,
                    "role": "intersection_highlight",
                },
                base_metadata,
            )
            registry.add(
                self._ellipse_element(
                    element_id=self._stable_id("intersection-oval", frame.procedure_id),
                    position=Point(
                        x=frame.origin.x - highlight_padding,
                        y=frame.origin.y - highlight_padding,
                    ),
                    size=Size(
                        frame.size.width + highlight_padding * 2,
                        frame.size.height + highlight_padding * 2,
                    ),
                    frame_id=None,
                    metadata=highlight_meta,
                    background_color="transparent",
                    stroke_color=highlight_color,
                    stroke_style="dashed",
                    stroke_width=2.0,
                )
            )
            merge_indices = merge_numbers.get(frame.procedure_id) if merge_numbers else None
            if isinstance(merge_indices, list | tuple):
                merge_indices = [value for value in merge_indices if isinstance(value, int)]
            else:
                merge_indices = None

            marker_diameter = highlight_padding * 2.7
            marker_radius = marker_diameter / 2
            marker_layout = None
            if merge_indices:
                marker_layout = self._merge_marker_layout(
                    frame, highlight_padding, marker_diameter, len(merge_indices)
                )
            if marker_layout and merge_indices:
                for slot, merge_index in enumerate(merge_indices):
                    pointer_start, marker_center, pointer_end = marker_layout[slot]
                    pointer_meta = self._with_base_metadata(
                        {
                            "procedure_id": frame.procedure_id,
                            "role": "intersection_pointer",
                            "merge_index": merge_index,
                        },
                        base_metadata,
                    )
                    arrow = self._arrow_element(
                        start=pointer_start,
                        end=pointer_end,
                        label="merge" if slot == 0 else "",
                        metadata=pointer_meta,
                        end_binding=frame_id,
                        stroke_color=highlight_color,
                        stroke_width=3.0,
                        end_arrowhead="arrow",
                    )
                    registry.add(arrow)
                    self._register_edge_bindings(arrow, registry)
                    marker_id = self._stable_id(
                        "intersection-index-marker",
                        frame.procedure_id,
                        str(slot),
                        str(merge_index),
                    )
                    marker_meta = self._with_base_metadata(
                        {
                            "procedure_id": frame.procedure_id,
                            "role": "intersection_index_marker",
                            "merge_index": merge_index,
                        },
                        base_metadata,
                    )
                    marker_origin = Point(
                        x=marker_center.x - marker_radius,
                        y=marker_center.y - marker_radius,
                    )
                    marker = self._ellipse_element(
                        element_id=marker_id,
                        position=marker_origin,
                        size=Size(marker_diameter, marker_diameter),
                        frame_id=None,
                        metadata=marker_meta,
                        background_color="transparent",
                        stroke_color=highlight_color,
                        stroke_width=2.0,
                    )
                    if isinstance(marker, dict) and "roughness" in marker:
                        marker["roughness"] = 1
                    registry.add(marker)
                    label_meta = self._with_base_metadata(
                        {
                            "procedure_id": frame.procedure_id,
                            "role": "intersection_index_label",
                            "merge_index": merge_index,
                        },
                        base_metadata,
                    )
                    label_font_size = getattr(
                        getattr(self.layout_engine, "config", None),
                        "service_zone_label_font_size",
                        20.0,
                    )
                    index_label = self._text_element(
                        element_id=self._stable_id(
                            "intersection-index-label",
                            frame.procedure_id,
                            str(slot),
                            str(merge_index),
                        ),
                        text=str(merge_index),
                        center=marker_center,
                        container_id=marker_id,
                        frame_id=None,
                        metadata=label_meta,
                        max_width=marker_diameter,
                        max_height=marker_diameter,
                        font_size=label_font_size,
                    )
                    self._apply_text_color(index_label, highlight_color)
                    if isinstance(index_label, dict):
                        if "strokeWidth" in index_label:
                            index_label["strokeWidth"] = 2.0
                        if "roughness" in index_label:
                            index_label["roughness"] = 1
                    registry.add(index_label)
            else:
                pointer_meta = self._with_base_metadata(
                    {
                        "procedure_id": frame.procedure_id,
                        "role": "intersection_pointer",
                    },
                    base_metadata,
                )
                pointer_start = Point(
                    x=frame.origin.x - highlight_padding * 3.5,
                    y=frame.origin.y - highlight_padding * 2.0,
                )
                pointer_end = Point(
                    x=frame.origin.x - highlight_padding * 0.4,
                    y=frame.origin.y + frame.size.height * 0.2,
                )
                arrow = self._arrow_element(
                    start=pointer_start,
                    end=pointer_end,
                    label="merge",
                    metadata=pointer_meta,
                    end_binding=frame_id,
                    stroke_color=highlight_color,
                    stroke_width=3.0,
                    end_arrowhead="arrow",
                )
                registry.add(arrow)
                self._register_edge_bindings(arrow, registry)
        return frame_ids

    def _build_procedure_stats(
        self,
        document: MarkupDocument,
        frames: list[FramePlacement],
        frame_ids: dict[str, str],
        registry: ElementRegistry,
        base_metadata: Metadata,
    ) -> None:
        procedure_map = {proc.procedure_id: proc for proc in document.procedures}
        stat_size = Size(92.0, 42.0)
        stat_gap = 12.0
        bottom_padding = 24.0
        labels = {
            "start": ("start", "#d1ffd6"),
            "branch": ("branch", "#cce5ff"),
            "end": ("end", END_TYPE_COLORS[END_TYPE_DEFAULT]),
            "postpone": ("postpone", END_TYPE_COLORS["postpone"]),
        }
        plurals = {
            "start": "starts",
            "branch": "branches",
            "end": "ends",
            "postpone": "postpones",
        }
        for frame in frames:
            proc = procedure_map.get(frame.procedure_id)
            if proc is None:
                continue
            start_count = len(proc.start_block_ids)
            postpone_count = sum(
                1
                for block_id in proc.end_block_ids
                if proc.end_block_types.get(block_id) == "postpone"
            )
            end_count = sum(
                1
                for block_id in proc.end_block_ids
                if proc.end_block_types.get(block_id) != "postpone"
            )
            branch_count = sum(len(targets) for targets in proc.branches.values())
            stats = [
                ("start", start_count),
                ("branch", branch_count),
                ("end", end_count),
                ("postpone", postpone_count),
            ]
            stats = [(stat_key, value) for stat_key, value in stats if value > 0]
            if not stats:
                continue
            total_width = stat_size.width * len(stats) + stat_gap * (len(stats) - 1)
            start_x = frame.origin.x + (frame.size.width - total_width) / 2
            stat_y = frame.origin.y + frame.size.height - stat_size.height - bottom_padding
            for idx, (stat_key, value) in enumerate(stats):
                label, color = labels[stat_key]
                label_text = label if value == 1 else plurals.get(label, f"{label}s")
                element_id = self._stable_id("procedure-stat", frame.procedure_id, stat_key)
                group_id = self._stable_id("procedure-stat-group", frame.procedure_id, stat_key)
                stat_meta = self._with_base_metadata(
                    {
                        "procedure_id": frame.procedure_id,
                        "role": "procedure_stat",
                        "stat_type": stat_key,
                        "stat_value": value,
                    },
                    base_metadata,
                )
                position = Point(
                    x=start_x + idx * (stat_size.width + stat_gap),
                    y=stat_y,
                )
                registry.add(
                    self._ellipse_element(
                        element_id=element_id,
                        position=position,
                        size=stat_size,
                        frame_id=frame_ids.get(frame.procedure_id),
                        metadata=stat_meta,
                        group_ids=[group_id],
                        background_color=color,
                    )
                )
                text_id = self._stable_id("procedure-stat-text", frame.procedure_id, stat_key)
                registry.add(
                    self._text_element(
                        element_id=text_id,
                        text=f"{value} {label_text}",
                        center=self._center(position, stat_size.width, stat_size.height),
                        container_id=element_id,
                        frame_id=frame_ids.get(frame.procedure_id),
                        group_ids=[group_id],
                        metadata=stat_meta,
                        max_width=stat_size.width - 10.0,
                        max_height=stat_size.height - 8.0,
                        font_size=14.0,
                    )
                )

    def _build_service_zone_rectangles(
        self,
        zones: list[ServiceZonePlacement],
        registry: ElementRegistry,
        base_metadata: Metadata,
    ) -> None:
        for zone in zones:
            group_id = self._stable_id("service-zone-group", zone.service_key)
            zone_id = self._stable_id("service-zone", zone.service_key)
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
                    stroke_color=zone.color,
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
            group_id = self._stable_id("service-zone-group", zone.service_key)
            label_id = self._stable_id("service-zone-label", zone.service_key)
            label_meta: dict[str, object] = {
                "role": "service_zone_label",
                "service_name": zone.service_name,
                "service_color": zone.color,
            }
            if zone.team_name:
                label_meta["team_name"] = zone.team_name
            if zone.team_id is not None:
                label_meta["team_id"] = zone.team_id
            label_element = self._text_block_element(
                element_id=label_id,
                text=zone.service_name,
                origin=zone.label_origin,
                width=zone.label_size.width,
                height=zone.label_size.height,
                metadata=self._with_base_metadata(label_meta, base_metadata),
                group_ids=[group_id],
                font_size=zone.label_font_size,
                text_color=zone.color,
            )
            if isinstance(label_element, dict):
                self._apply_text_bold(label_element)
                self._apply_service_zone_label_style(label_element)
            registry.add(label_element)
