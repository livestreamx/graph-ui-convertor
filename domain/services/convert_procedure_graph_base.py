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
        frame_ids = self._build_frames(plan.frames, registry, base_metadata, proc_name_lookup)
        self._build_procedure_stats(document, plan.frames, frame_ids, registry, base_metadata)
        self._build_separators(plan.separators, registry, base_metadata)
        self._build_scenarios(plan.scenarios, registry, base_metadata)
        self._build_procedure_flow_edges(document, plan.frames, frame_ids, registry, base_metadata)
        self._build_service_title(plan, registry, base_metadata, document.service_name)
        self._center_on_first_frame(plan, registry.elements)
        self._post_process_elements(registry.elements)
        app_state = self._build_app_state(registry.elements)
        return self._build_document(registry.elements, app_state)

    def _format_procedure_label(self, procedure_name: str | None, procedure_id: str) -> str:
        return procedure_name or procedure_id

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
