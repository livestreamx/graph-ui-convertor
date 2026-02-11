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
        self._build_service_title(
            plan,
            registry,
            base_metadata,
            document.service_name,
            None,
        )
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
        is_service_graph = str(document.markup_type or "").strip().lower() == "service_graph"
        procedure_meta = document.procedure_meta or {}
        frame_by_proc_id = {frame.procedure_id: frame for frame in frames}
        grouped_proc_ids: set[str] = set()
        group_anchor_by_group: dict[str, str] = {}
        group_members_by_group: dict[str, list[str]] = {}
        for frame in frames:
            meta = procedure_meta.get(frame.procedure_id, {})
            if meta.get("is_intersection") is not True:
                continue
            group_id = meta.get("merge_chain_group_id")
            if not isinstance(group_id, str):
                continue
            group_members_by_group.setdefault(group_id, []).append(frame.procedure_id)
        for group_id, proc_ids in group_members_by_group.items():
            if len(proc_ids) <= 1:
                continue
            ordered = sorted(
                proc_ids,
                key=lambda proc_id: (
                    frame_by_proc_id[proc_id].origin.x,
                    frame_by_proc_id[proc_id].origin.y,
                    proc_id,
                ),
            )
            group_members_by_group[group_id] = ordered
            group_anchor_by_group[group_id] = ordered[0]
            grouped_proc_ids.update(ordered)

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
            source_procedure_id = meta.get("source_procedure_id")
            if isinstance(source_procedure_id, str) and source_procedure_id:
                frame_meta["source_procedure_id"] = source_procedure_id
            color = meta.get("procedure_color")
            if isinstance(color, str) and color:
                frame_meta["procedure_color"] = color
            is_intersection = meta.get("is_intersection") is True
            if is_intersection:
                frame_meta["is_intersection"] = True
            if is_service_graph:
                group_id = self._stable_id("service-frame-group", frame.procedure_id)
                frame_metadata = self._with_base_metadata(frame_meta, base_metadata)
                registry.add(
                    self._rectangle_element(
                        element_id=frame_id,
                        position=frame.origin,
                        size=frame.size,
                        frame_id=None,
                        group_ids=[group_id],
                        metadata=frame_metadata,
                        background_color=color if isinstance(color, str) and color else None,
                        stroke_color="#1e1e1e",
                        fill_style="solid",
                        roundness={"type": 3},
                    )
                )
                text_id = self._stable_id("service-frame-text", frame.procedure_id)
                label_center = Point(
                    x=frame.origin.x + frame.size.width / 2,
                    y=frame.origin.y + frame.size.height * 0.32,
                )
                registry.add(
                    self._text_element(
                        element_id=text_id,
                        text=label,
                        center=label_center,
                        container_id=frame_id,
                        frame_id=None,
                        group_ids=[group_id],
                        metadata=self._with_base_metadata(
                            {**frame_meta, "role": "frame_label"},
                            base_metadata,
                        ),
                        max_width=frame.size.width - 24.0,
                        max_height=frame.size.height * 0.45,
                        font_size=18.0,
                    )
                )
                continue
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
            group_id = meta.get("merge_chain_group_id")
            if isinstance(group_id, str) and frame.procedure_id not in grouped_proc_ids:
                continue
            if (
                isinstance(group_id, str)
                and frame.procedure_id in grouped_proc_ids
                and group_anchor_by_group.get(group_id) != frame.procedure_id
            ):
                continue

            extra_meta: dict[str, object] | None = None
            highlight_frame = frame
            id_token = frame.procedure_id
            merge_indices: list[int] | None = None
            if isinstance(group_id, str) and frame.procedure_id in grouped_proc_ids:
                member_proc_ids = group_members_by_group.get(group_id, [frame.procedure_id])
                member_frames = [
                    frame_by_proc_id[proc_id]
                    for proc_id in member_proc_ids
                    if proc_id in frame_by_proc_id
                ]
                if member_frames:
                    min_x = min(item.origin.x for item in member_frames)
                    min_y = min(item.origin.y for item in member_frames)
                    max_x = max(item.origin.x + item.size.width for item in member_frames)
                    max_y = max(item.origin.y + item.size.height for item in member_frames)
                    highlight_frame = FramePlacement(
                        procedure_id=frame.procedure_id,
                        origin=Point(min_x, min_y),
                        size=Size(max_x - min_x, max_y - min_y),
                    )
                id_token = group_id
                extra_meta = {"merge_chain_members": member_proc_ids}
                if merge_numbers:
                    merged_indices: list[int] = []
                    for proc_id in member_proc_ids:
                        values = merge_numbers.get(proc_id)
                        if not isinstance(values, list | tuple):
                            continue
                        for value in values:
                            if isinstance(value, int) and value not in merged_indices:
                                merged_indices.append(value)
                    merge_indices = merged_indices or None
            else:
                values = merge_numbers.get(frame.procedure_id) if merge_numbers else None
                if isinstance(values, list | tuple):
                    merge_indices = [value for value in values if isinstance(value, int)] or None

            self._render_intersection_highlight(
                registry=registry,
                base_metadata=base_metadata,
                procedure_id=frame.procedure_id,
                highlight_frame=highlight_frame,
                end_binding_frame_id=frame_id,
                merge_indices=merge_indices,
                metadata_extra=extra_meta,
                id_token=id_token,
            )
        return frame_ids

    def _render_intersection_highlight(
        self,
        *,
        registry: ElementRegistry,
        base_metadata: Metadata,
        procedure_id: str,
        highlight_frame: FramePlacement,
        end_binding_frame_id: str,
        merge_indices: list[int] | None,
        metadata_extra: dict[str, object] | None,
        id_token: str,
    ) -> None:
        highlight_padding = 18.0
        highlight_color = MERGE_ALERT_COLOR
        highlight_payload: dict[str, object] = {
            "procedure_id": procedure_id,
            "role": "intersection_highlight",
        }
        if metadata_extra:
            highlight_payload.update(metadata_extra)
        highlight_meta = self._with_base_metadata(highlight_payload, base_metadata)
        registry.add(
            self._ellipse_element(
                element_id=self._stable_id("intersection-oval", id_token),
                position=Point(
                    x=highlight_frame.origin.x - highlight_padding,
                    y=highlight_frame.origin.y - highlight_padding,
                ),
                size=Size(
                    highlight_frame.size.width + highlight_padding * 2,
                    highlight_frame.size.height + highlight_padding * 2,
                ),
                frame_id=None,
                metadata=highlight_meta,
                background_color="transparent",
                stroke_color=highlight_color,
                stroke_style="dashed",
                stroke_width=2.0,
            )
        )

        marker_diameter = highlight_padding * 2.7
        marker_radius = marker_diameter / 2
        marker_layout = None
        if merge_indices:
            marker_layout = self._merge_marker_layout(
                highlight_frame, highlight_padding, marker_diameter, len(merge_indices)
            )
        if marker_layout and merge_indices:
            for slot, merge_index in enumerate(merge_indices):
                pointer_start, marker_center, pointer_end = marker_layout[slot]
                pointer_payload: dict[str, object] = {
                    "procedure_id": procedure_id,
                    "role": "intersection_pointer",
                    "merge_index": merge_index,
                }
                if metadata_extra:
                    pointer_payload.update(metadata_extra)
                pointer_meta = self._with_base_metadata(pointer_payload, base_metadata)
                arrow = self._arrow_element(
                    start=pointer_start,
                    end=pointer_end,
                    label="merge" if slot == 0 else "",
                    metadata=pointer_meta,
                    end_binding=end_binding_frame_id,
                    stroke_color=highlight_color,
                    stroke_width=3.0,
                    end_arrowhead="arrow",
                )
                registry.add(arrow)
                self._register_edge_bindings(arrow, registry)
                marker_id = self._stable_id(
                    "intersection-index-marker",
                    id_token,
                    str(slot),
                    str(merge_index),
                )
                marker_payload: dict[str, object] = {
                    "procedure_id": procedure_id,
                    "role": "intersection_index_marker",
                    "merge_index": merge_index,
                }
                if metadata_extra:
                    marker_payload.update(metadata_extra)
                marker_meta = self._with_base_metadata(marker_payload, base_metadata)
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
                label_payload: dict[str, object] = {
                    "procedure_id": procedure_id,
                    "role": "intersection_index_label",
                    "merge_index": merge_index,
                }
                if metadata_extra:
                    label_payload.update(metadata_extra)
                label_meta = self._with_base_metadata(label_payload, base_metadata)
                label_font_size = getattr(
                    getattr(self.layout_engine, "config", None),
                    "service_zone_label_font_size",
                    20.0,
                )
                index_label = self._text_element(
                    element_id=self._stable_id(
                        "intersection-index-label",
                        id_token,
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
            return

        pointer_payload_single: dict[str, object] = {
            "procedure_id": procedure_id,
            "role": "intersection_pointer",
        }
        if metadata_extra:
            pointer_payload_single.update(metadata_extra)
        pointer_meta = self._with_base_metadata(pointer_payload_single, base_metadata)
        pointer_start = Point(
            x=highlight_frame.origin.x - highlight_padding * 3.5,
            y=highlight_frame.origin.y - highlight_padding * 2.0,
        )
        pointer_end = Point(
            x=highlight_frame.origin.x - highlight_padding * 0.4,
            y=highlight_frame.origin.y + highlight_frame.size.height * 0.2,
        )
        arrow = self._arrow_element(
            start=pointer_start,
            end=pointer_end,
            label="merge",
            metadata=pointer_meta,
            end_binding=end_binding_frame_id,
            stroke_color=highlight_color,
            stroke_width=3.0,
            end_arrowhead="arrow",
        )
        registry.add(arrow)
        self._register_edge_bindings(arrow, registry)

    def _build_procedure_stats(
        self,
        document: MarkupDocument,
        frames: list[FramePlacement],
        frame_ids: dict[str, str],
        registry: ElementRegistry,
        base_metadata: Metadata,
    ) -> None:
        is_service_graph = str(document.markup_type or "").strip().lower() == "service_graph"
        if is_service_graph:
            self._build_service_graph_stats(
                document=document,
                frames=frames,
                frame_ids=frame_ids,
                registry=registry,
                base_metadata=base_metadata,
            )
            return
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

    def _build_service_graph_stats(
        self,
        document: MarkupDocument,
        frames: list[FramePlacement],
        frame_ids: dict[str, str],
        registry: ElementRegistry,
        base_metadata: Metadata,
    ) -> None:
        procedure_meta = document.procedure_meta or {}
        stat_size = Size(92.0, 42.0)
        stat_gap = 12.0
        bottom_padding = 16.0
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
            meta = procedure_meta.get(frame.procedure_id, {})
            stats_meta = meta.get("graph_stats")
            if not isinstance(stats_meta, dict):
                continue
            stats = [
                ("start", stats_meta.get("start", 0)),
                ("branch", stats_meta.get("branch", 0)),
                ("end", stats_meta.get("end", 0)),
                ("postpone", stats_meta.get("postpone", 0)),
            ]
            stats = [
                (stat_key, value)
                for stat_key, value in stats
                if isinstance(value, int) and value > 0
            ]
            procedure_count = meta.get("procedure_count")
            items: list[tuple[str, str, int]] = []
            if isinstance(procedure_count, int) and procedure_count > 0:
                items.append(("rect", "procedure_count", procedure_count))
            for stat_key, value in stats:
                items.append(("oval", stat_key, value))
            if not items:
                continue
            count = len(items)
            total_width = stat_size.width * count + stat_gap * (count - 1)
            start_x = frame.origin.x + (frame.size.width - total_width) / 2
            stat_y = frame.origin.y + frame.size.height - bottom_padding - stat_size.height
            group_id = self._stable_id("service-frame-group", frame.procedure_id)
            for idx, (shape, stat_key, value) in enumerate(items):
                color = "#f2f2f2"
                if shape == "rect":
                    label_text = "procedure" if value == 1 else "procedures"
                else:
                    label, color = labels[stat_key]
                    label_text = label if value == 1 else plurals.get(label, f"{label}s")
                element_id = self._stable_id("service-stat", frame.procedure_id, stat_key)
                stat_group_id = self._stable_id("service-stat-group", frame.procedure_id, stat_key)
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
                if shape == "rect":
                    registry.add(
                        self._rectangle_element(
                            element_id=element_id,
                            position=position,
                            size=stat_size,
                            frame_id=frame_ids.get(frame.procedure_id),
                            metadata=stat_meta,
                            group_ids=[group_id, stat_group_id],
                            background_color=color,
                            stroke_color="#1e1e1e",
                            fill_style="solid",
                            roundness={"type": 2},
                        )
                    )
                else:
                    registry.add(
                        self._ellipse_element(
                            element_id=element_id,
                            position=position,
                            size=stat_size,
                            frame_id=frame_ids.get(frame.procedure_id),
                            metadata=stat_meta,
                            group_ids=[group_id, stat_group_id],
                            background_color=color,
                        )
                    )
                text_id = self._stable_id("service-stat-text", frame.procedure_id, stat_key)
                registry.add(
                    self._text_element(
                        element_id=text_id,
                        text=f"{value} {label_text}",
                        center=self._center(position, stat_size.width, stat_size.height),
                        container_id=element_id,
                        frame_id=frame_ids.get(frame.procedure_id),
                        group_ids=[group_id, stat_group_id],
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
            zone_scope = self._service_zone_scope(zone)
            group_id = self._stable_id("service-zone-group", *zone_scope)
            label_id = self._stable_id("service-zone-label", *zone_scope)
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
                text=self._format_service_name_with_markup_type(
                    zone.service_name,
                    zone.markup_type,
                ),
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

    def _service_zone_scope(self, zone: ServiceZonePlacement) -> tuple[str, ...]:
        if zone.procedure_ids:
            return (zone.service_key, *zone.procedure_ids)
        return (
            zone.service_key,
            f"{zone.origin.x:.3f}",
            f"{zone.origin.y:.3f}",
            f"{zone.size.width:.3f}",
            f"{zone.size.height:.3f}",
        )
