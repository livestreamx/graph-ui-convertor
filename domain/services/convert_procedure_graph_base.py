from __future__ import annotations

from typing import Any

from domain.models import (
    END_TYPE_COLORS,
    END_TYPE_DEFAULT,
    FramePlacement,
    MarkupDocument,
    Point,
    Size,
)
from domain.services.convert_markup_base import (
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
        frame_ids = self._build_procedure_frames(
            document, plan.frames, registry, base_metadata, proc_name_lookup
        )
        self._build_procedure_stats(document, plan.frames, frame_ids, registry, base_metadata)
        self._build_separators(plan.separators, registry, base_metadata)
        self._build_scenarios(plan.scenarios, registry, base_metadata)
        self._build_procedure_flow_edges(document, plan.frames, frame_ids, registry, base_metadata)
        self._build_service_title(plan, registry, base_metadata, document.service_name)
        self._center_on_first_frame(plan, registry.elements)
        self._post_process_elements(registry.elements)
        app_state = self._build_app_state(registry.elements)
        return self._build_document(registry.elements, app_state)

    def _procedure_edge_stroke_width(self, is_cycle: bool) -> float | None:
        return 1.0

    def _format_procedure_label(self, procedure_name: str | None, procedure_id: str) -> str:
        return procedure_name or procedure_id

    def _build_procedure_frames(
        self,
        document: MarkupDocument,
        frames: list[FramePlacement],
        registry: ElementRegistry,
        base_metadata: Metadata,
        proc_name_lookup: dict[str, str],
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
            highlight_color = "#f5c542"
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
        }
        plurals = {
            "start": "starts",
            "branch": "branches",
            "end": "ends",
        }
        for frame in frames:
            proc = procedure_map.get(frame.procedure_id)
            if proc is None:
                continue
            start_count = len(proc.start_block_ids)
            end_count = len(proc.end_block_ids)
            branch_count = sum(len(targets) for targets in proc.branches.values())
            stats = [
                ("start", start_count),
                ("branch", branch_count),
                ("end", end_count),
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
                        metadata=stat_meta,
                        max_width=stat_size.width - 10.0,
                        max_height=stat_size.height - 8.0,
                        font_size=14.0,
                    )
                )
