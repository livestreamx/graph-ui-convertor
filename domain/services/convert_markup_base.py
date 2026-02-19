from __future__ import annotations

import random
import uuid
from abc import ABC, abstractmethod
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

from domain.markup_type_labels import humanize_markup_type, humanize_markup_type_for_brackets
from domain.models import (
    END_TYPE_COLORS,
    END_TYPE_DEFAULT,
    END_TYPE_TURN_OUT,
    INITIAL_BLOCK_COLOR,
    INTERMEDIATE_BLOCK_COLOR,
    METADATA_SCHEMA_VERSION,
    BlockPlacement,
    FramePlacement,
    LayoutPlan,
    MarkerPlacement,
    MarkupDocument,
    Point,
    ScenarioPlacement,
    SeparatorPlacement,
    Size,
)
from domain.ports.layout import LayoutEngine
from domain.services.block_graph_resolution import (
    resolve_block_graph_edges,
)

Metadata = dict[str, Any]
Element = dict[str, Any]
MERGE_ALERT_COLOR = "#ff2d2d"
MERGE_ALERT_PANEL_COLOR = "#ff9d9d99"


@dataclass
class ElementRegistry:
    elements: list[Element] = field(default_factory=list)
    index: dict[str, Element] = field(default_factory=dict)

    def add(self, element: Element) -> None:
        self.elements.append(element)
        element_id = element.get("id")
        if isinstance(element_id, str):
            self.index[element_id] = element


class MarkupToDiagramConverter(ABC):
    def __init__(self, layout_engine: LayoutEngine) -> None:
        self.layout_engine = layout_engine
        self.namespace = uuid.uuid5(uuid.NAMESPACE_DNS, "cjm-ui-convertor")

    def convert(self, document: MarkupDocument) -> Any:
        plan = self.layout_engine.build_plan(document)
        registry = ElementRegistry()
        base_metadata = self._base_metadata(document)
        display_markup_type = str(
            base_metadata.get("display_markup_type", document.markup_type) or ""
        )

        proc_name_lookup = {
            proc.procedure_id: proc.procedure_name
            for proc in document.procedures
            if proc.procedure_name
        }
        frame_ids = self._build_frames(plan.frames, registry, base_metadata, proc_name_lookup)
        self._build_separators(plan.separators, registry, base_metadata)
        self._build_scenarios(plan.scenarios, registry, base_metadata)
        included_procs = {frame.procedure_id for frame in plan.frames}
        end_block_type_lookup = {
            (proc.procedure_id, block_id): proc.end_block_types.get(block_id, END_TYPE_DEFAULT)
            for proc in document.procedures
            if proc.procedure_id in included_procs
            for block_id in proc.end_block_ids
        }
        block_ids_in_plan = {(block.procedure_id, block.block_id) for block in plan.blocks}
        block_name_lookup = {
            (proc.procedure_id, block_id): name
            for proc in document.procedures
            for block_id, name in proc.block_id_to_block_name.items()
            if name and (proc.procedure_id, block_id) in block_ids_in_plan
        }
        source_procedure_ids: dict[str, str] = {}
        for proc_id, proc_meta in (document.procedure_meta or {}).items():
            source_proc_id = proc_meta.get("source_procedure_id")
            if isinstance(source_proc_id, str) and source_proc_id:
                source_procedure_ids[proc_id] = source_proc_id

        blocks = self._build_blocks(
            plan.blocks,
            frame_ids,
            registry,
            base_metadata,
            end_block_type_lookup,
            block_name_lookup,
            document.block_graph_initials,
            source_procedure_ids=source_procedure_ids,
        )

        start_label_index: dict[tuple[str, str], int] = {}
        start_blocks_global = [
            (proc.procedure_id, blk_id)
            for proc in document.procedures
            if proc.procedure_id in included_procs
            for blk_id in proc.start_block_ids
        ]
        for idx, (proc_id, blk_id) in enumerate(start_blocks_global, start=1):
            start_label_index[(proc_id, blk_id)] = idx
        markers = self._build_markers(
            plan.markers,
            frame_ids,
            registry,
            base_metadata,
            start_label_index,
            end_block_type_lookup,
        )

        self._build_start_edges(document, blocks, markers, registry, base_metadata)
        self._build_end_edges(
            document,
            blocks,
            markers,
            registry,
            base_metadata,
            end_block_type_lookup,
        )
        self._build_branch_edges(document, blocks, registry, base_metadata)
        self._build_procedure_flow_edges(
            document, plan.frames, frame_ids, registry, base_metadata, blocks
        )
        self._build_service_title(
            plan,
            registry,
            base_metadata,
            document.service_name,
            display_markup_type,
        )
        self._center_on_first_frame(plan, registry.elements)
        self._post_process_elements(registry.elements)
        app_state = self._build_app_state(registry.elements)
        return self._build_document(registry.elements, app_state)

    def _base_metadata(self, document: MarkupDocument) -> Metadata:
        display_markup_type = self._resolve_display_markup_type(document)
        base_metadata: Metadata = {
            "schema_version": METADATA_SCHEMA_VERSION,
            "markup_type": document.markup_type,
            "display_markup_type": display_markup_type,
        }
        if document.finedog_unit_id:
            base_metadata["finedog_unit_id"] = document.finedog_unit_id
        if document.service_name:
            base_metadata["service_name"] = document.service_name
        if document.criticality_level:
            base_metadata["criticality_level"] = document.criticality_level
        if document.team_id is not None:
            base_metadata["team_id"] = document.team_id
        if document.team_name:
            base_metadata["team_name"] = document.team_name
        return base_metadata

    def _resolve_display_markup_type(self, document: MarkupDocument) -> str:
        technical_markup_type = str(document.markup_type or "").strip() or "unknown"
        if technical_markup_type not in {"procedure_graph", "service_graph"}:
            return humanize_markup_type(technical_markup_type)

        procedure_meta = document.procedure_meta or {}
        source_types: set[str] = set()
        for meta in procedure_meta.values():
            direct_markup_type = str(meta.get("markup_type") or "").strip()
            if direct_markup_type:
                source_types.add(direct_markup_type)
            services = meta.get("services")
            if not isinstance(services, list):
                continue
            for item in services:
                if not isinstance(item, dict):
                    continue
                service_markup_type = str(item.get("markup_type") or "").strip()
                if service_markup_type:
                    source_types.add(service_markup_type)

        if len(source_types) == 1:
            return humanize_markup_type(next(iter(source_types)))
        if len(source_types) > 1:
            return "mixed"
        return humanize_markup_type(technical_markup_type)

    @abstractmethod
    def _build_document(self, elements: list[Element], app_state: dict[str, Any]) -> Any:
        raise NotImplementedError

    @abstractmethod
    def _build_app_state(self, elements: list[Element]) -> dict[str, Any]:
        raise NotImplementedError

    def _post_process_elements(self, elements: list[Element]) -> None:
        return

    def _register_edge_bindings(self, arrow: Element, registry: ElementRegistry) -> None:
        return

    def _procedure_edge_stroke_width(self, is_cycle: bool) -> float | None:
        return 2 if is_cycle else None

    def _apply_service_zone_label_style(self, element: Element) -> None:
        return

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
        markup_label = humanize_markup_type_for_brackets(markup_label)
        return f"[{markup_label}] {title}"

    @abstractmethod
    def _offset_element(self, element: Element, dx: float, dy: float) -> None:
        raise NotImplementedError

    def _center_on_first_frame(self, plan: LayoutPlan, elements: list[Element]) -> None:
        if not plan.frames:
            return
        first_frame = min(plan.frames, key=lambda frame: (frame.origin.x, frame.origin.y))
        offset_x = -(first_frame.origin.x + first_frame.size.width / 2)
        offset_y = -(first_frame.origin.y + first_frame.size.height / 2)
        if offset_x == 0 and offset_y == 0:
            return
        for element in elements:
            self._offset_element(element, offset_x, offset_y)

    def _build_frames(
        self,
        frames: Iterable[FramePlacement],
        registry: ElementRegistry,
        base_metadata: Metadata,
        proc_name_lookup: dict[str, str],
    ) -> dict[str, str]:
        frame_ids: dict[str, str] = {}
        for frame in frames:
            frame_id = self._stable_id("frame", frame.procedure_id)
            frame_ids[frame.procedure_id] = frame_id
            procedure_name = proc_name_lookup.get(frame.procedure_id)
            label = self._format_procedure_label(procedure_name, frame.procedure_id)
            frame_meta = {
                "procedure_id": frame.procedure_id,
                "role": "frame",
            }
            if procedure_name:
                frame_meta["procedure_name"] = procedure_name
            registry.add(
                self._frame_element(
                    element_id=frame_id,
                    frame=frame,
                    metadata=self._with_base_metadata(
                        frame_meta,
                        base_metadata,
                    ),
                    name=label,
                )
            )
        return frame_ids

    def _build_separators(
        self,
        separators: Iterable[SeparatorPlacement],
        registry: ElementRegistry,
        base_metadata: Metadata,
    ) -> None:
        for idx, separator in enumerate(separators):
            element_id = self._stable_id(
                "separator", str(idx), str(separator.start), str(separator.end)
            )
            registry.add(
                self._line_element(
                    element_id=element_id,
                    start=separator.start,
                    end=separator.end,
                    metadata=self._with_base_metadata(
                        {"role": "separator", "separator_index": idx},
                        base_metadata,
                    ),
                    stroke_color="#9e9e9e",
                    stroke_style="dashed",
                    stroke_width=2,
                )
            )

    def _build_service_title(
        self,
        plan: LayoutPlan,
        registry: ElementRegistry,
        base_metadata: Metadata,
        service_name: str | None,
        markup_type: str | None = None,
        title_gap_y: float = 160.0,
    ) -> None:
        if not service_name:
            return
        title = self._format_service_name_with_markup_type(service_name, markup_type)
        if not title:
            return
        bounds = self._plan_bounds(plan)
        if not bounds:
            return
        min_x, min_y, max_x, _ = bounds
        content_width = max_x - min_x
        title_width = max(content_width + 160.0, 420.0)
        title_height = 96.0
        gap_y = title_gap_y
        origin_x = (min_x + max_x) / 2 - title_width / 2
        origin_y = min_y - gap_y - title_height
        group_id = self._stable_id("diagram-title-group", title)
        panel_id = self._stable_id("diagram-title-panel", title)
        rule_id = self._stable_id("diagram-title-rule", title)
        text_id = self._stable_id("diagram-title-text", title)
        panel_meta = self._with_base_metadata({"role": "diagram_title_panel"}, base_metadata)
        rule_meta = self._with_base_metadata({"role": "diagram_title_rule"}, base_metadata)
        text_meta = self._with_base_metadata({"role": "diagram_title"}, base_metadata)
        title_origin = Point(x=origin_x, y=origin_y)
        registry.add(
            self._title_panel_element(
                element_id=panel_id,
                origin=title_origin,
                size=Size(title_width, title_height),
                metadata=panel_meta,
                group_ids=[group_id],
            )
        )
        line_y = origin_y + title_height - 14.0
        registry.add(
            self._line_element(
                element_id=rule_id,
                start=Point(origin_x + 26.0, line_y),
                end=Point(origin_x + title_width - 26.0, line_y),
                metadata=rule_meta,
                stroke_color="#7b8fb0",
                stroke_width=3,
                group_ids=[group_id],
            )
        )
        title_center = Point(
            x=origin_x + title_width / 2,
            y=origin_y + title_height / 2,
        )
        registry.add(
            self._text_element(
                element_id=text_id,
                text=title,
                center=title_center,
                container_id=None,
                frame_id=None,
                metadata=text_meta,
                group_ids=[group_id],
                max_width=title_width - 96.0,
                max_height=title_height - 40.0,
                font_size=36.0,
            )
        )

    def _build_scenarios(
        self,
        scenarios: Iterable[ScenarioPlacement],
        registry: ElementRegistry,
        base_metadata: Metadata,
    ) -> None:
        for idx, scenario in enumerate(scenarios, start=1):
            group_id = self._stable_id("scenario-group", str(idx))
            panel_id = self._stable_id("scenario-panel", str(idx))
            title_id = self._stable_id("scenario-title", str(idx))
            body_id = self._stable_id("scenario-body", str(idx))
            cycle_id = self._stable_id("scenario-cycle", str(idx))
            panel_meta = self._with_base_metadata(
                {"role": "scenario_panel", "scenario_index": idx},
                base_metadata,
            )
            registry.add(
                self._scenario_panel_element(
                    element_id=panel_id,
                    origin=scenario.origin,
                    size=scenario.size,
                    metadata=panel_meta,
                    group_ids=[group_id],
                )
            )
            content_width = scenario.size.width - (scenario.padding * 2)
            title_lines = scenario.title_text.splitlines() or [scenario.title_text]
            body_lines = scenario.body_text.splitlines() or [scenario.body_text]
            title_height = len(title_lines) * scenario.title_font_size * 1.35
            body_height = len(body_lines) * scenario.body_font_size * 1.35
            cycle_height = 0.0
            cycle_lines = []
            if scenario.cycle_text:
                cycle_lines = scenario.cycle_text.splitlines()
                cycle_height = len(cycle_lines) * scenario.cycle_font_size * 1.35
            title_origin = Point(
                x=scenario.origin.x + scenario.padding,
                y=scenario.origin.y + scenario.padding,
            )
            cycle_origin = Point(
                x=scenario.origin.x + scenario.padding,
                y=scenario.origin.y + scenario.padding + title_height,
            )
            body_origin = Point(
                x=scenario.origin.x + scenario.padding,
                y=scenario.origin.y
                + scenario.padding
                + title_height
                + (cycle_height + (scenario.section_gap if scenario.cycle_text else 0.0)),
            )
            registry.add(
                self._text_block_element(
                    element_id=title_id,
                    text=scenario.title_text,
                    origin=title_origin,
                    width=content_width,
                    height=title_height,
                    metadata=self._with_base_metadata(
                        {"role": "scenario_title", "scenario_index": idx},
                        base_metadata,
                    ),
                    group_ids=[group_id],
                    font_size=scenario.title_font_size,
                )
            )
            if scenario.cycle_text:
                registry.add(
                    self._text_block_element(
                        element_id=cycle_id,
                        text=scenario.cycle_text,
                        origin=cycle_origin,
                        width=content_width,
                        height=cycle_height,
                        metadata=self._with_base_metadata(
                            {"role": "scenario_cycle", "scenario_index": idx},
                            base_metadata,
                        ),
                        group_ids=[group_id],
                        font_size=scenario.cycle_font_size,
                        text_color="#d32f2f",
                    )
                )
            registry.add(
                self._text_block_element(
                    element_id=body_id,
                    text=scenario.body_text,
                    origin=body_origin,
                    width=content_width,
                    height=body_height,
                    metadata=self._with_base_metadata(
                        {"role": "scenario_body", "scenario_index": idx},
                        base_metadata,
                    ),
                    group_ids=[group_id],
                    font_size=scenario.body_font_size,
                )
            )
            merge_origin = getattr(scenario, "merge_origin", None)
            merge_size = getattr(scenario, "merge_size", None)
            merge_text = getattr(scenario, "merge_text", None)
            merge_blocks = getattr(scenario, "merge_blocks", None)
            merge_padding = getattr(scenario, "merge_padding", None) or 0.0
            merge_font_size = (
                getattr(scenario, "merge_font_size", None) or scenario.procedures_font_size
            )
            if merge_origin and merge_size:
                merge_group = self._stable_id("scenario-merge-group", str(idx))
                merge_panel_id = self._stable_id("scenario-merge-panel", str(idx))
                registry.add(
                    self._scenario_procedures_panel_element(
                        element_id=merge_panel_id,
                        origin=merge_origin,
                        size=merge_size,
                        metadata=self._with_base_metadata(
                            {"role": "scenario_merge_panel", "scenario_index": idx},
                            base_metadata,
                        ),
                        group_ids=[merge_group],
                        background_color=MERGE_ALERT_PANEL_COLOR,
                        stroke_color=MERGE_ALERT_PANEL_COLOR,
                    )
                )
                if merge_blocks:
                    block_padding = getattr(scenario, "merge_block_padding", None) or 0.0
                    content_x = merge_origin.x + merge_padding
                    content_y = merge_origin.y + merge_padding
                    content_width = merge_size.width - (merge_padding * 2)
                    current_y = content_y
                    for block_idx, block in enumerate(merge_blocks):
                        if block.kind == "spacer":
                            current_y += block.height
                            continue
                        block_font_size = (
                            block.font_size if block.font_size is not None else merge_font_size
                        )
                        text_origin = Point(content_x, current_y)
                        registry.add(
                            self._text_block_element(
                                element_id=self._stable_id(
                                    "scenario-merge-block",
                                    str(idx),
                                    str(block_idx),
                                ),
                                text=block.text,
                                origin=text_origin,
                                width=content_width,
                                height=block.height,
                                metadata=self._with_base_metadata(
                                    {"role": "scenario_merge", "scenario_index": idx},
                                    base_metadata,
                                ),
                                group_ids=[merge_group],
                                font_size=block_font_size,
                                text_color="#ffffff",
                            )
                        )
                        if block.underline:
                            line_y = current_y + block.height - max(2.0, block_font_size * 0.15)
                            registry.add(
                                self._line_element(
                                    element_id=self._stable_id(
                                        "scenario-merge-underline",
                                        str(idx),
                                        str(block_idx),
                                    ),
                                    start=Point(content_x, line_y),
                                    end=Point(content_x + content_width, line_y),
                                    metadata=self._with_base_metadata(
                                        {"role": "scenario_merge_underline", "scenario_index": idx},
                                        base_metadata,
                                    ),
                                    stroke_color="#ffffff",
                                    stroke_width=2.0,
                                    group_ids=[merge_group],
                                )
                            )
                        current_y += block.height
                elif merge_text:
                    registry.add(
                        self._text_block_element(
                            element_id=self._stable_id("scenario-merge-text", str(idx)),
                            text=merge_text,
                            origin=Point(
                                merge_origin.x + merge_padding, merge_origin.y + merge_padding
                            ),
                            width=merge_size.width - (merge_padding * 2),
                            height=merge_size.height - (merge_padding * 2),
                            metadata=self._with_base_metadata(
                                {"role": "scenario_merge", "scenario_index": idx},
                                base_metadata,
                            ),
                            group_ids=[merge_group],
                            font_size=merge_font_size,
                            text_color="#ffffff",
                        )
                    )
            procedures_group = self._stable_id("scenario-procedures-group", str(idx))
            procedures_panel_id = self._stable_id("scenario-procedures-panel", str(idx))
            procedures_text_id = self._stable_id("scenario-procedures-text", str(idx))
            registry.add(
                self._scenario_procedures_panel_element(
                    element_id=procedures_panel_id,
                    origin=scenario.procedures_origin,
                    size=scenario.procedures_size,
                    metadata=self._with_base_metadata(
                        {"role": "scenario_procedures_panel", "scenario_index": idx},
                        base_metadata,
                    ),
                    group_ids=[procedures_group],
                )
            )
            procedures_blocks = getattr(scenario, "procedures_blocks", None)
            if procedures_blocks:
                block_padding = (
                    scenario.procedures_block_padding
                    if scenario.procedures_block_padding is not None
                    else 0.0
                )
                content_x = scenario.procedures_origin.x + scenario.procedures_padding
                content_y = scenario.procedures_origin.y + scenario.procedures_padding
                content_width = scenario.procedures_size.width - (scenario.procedures_padding * 2)
                current_y = content_y
                for block_idx, block in enumerate(procedures_blocks):
                    kind = block.kind
                    if kind == "spacer":
                        current_y += block.height
                        continue
                    block_font_size = (
                        block.font_size
                        if block.font_size is not None
                        else scenario.procedures_font_size
                    )
                    if kind == "team":
                        text_origin = Point(content_x, current_y)
                        team_meta = {"role": "scenario_procedures_team", "scenario_index": idx}
                        if block.team_id is not None:
                            team_meta["team_id"] = block.team_id
                        registry.add(
                            self._text_block_element(
                                element_id=self._stable_id(
                                    "scenario-procedures-team",
                                    str(idx),
                                    str(block_idx),
                                ),
                                text=block.text,
                                origin=text_origin,
                                width=content_width,
                                height=block.height,
                                metadata=self._with_base_metadata(team_meta, base_metadata),
                                group_ids=[procedures_group],
                                font_size=block_font_size,
                            )
                        )
                        if block.underline:
                            line_y = current_y + block.height - max(2.0, block_font_size * 0.15)
                            registry.add(
                                self._line_element(
                                    element_id=self._stable_id(
                                        "scenario-procedures-team-underline",
                                        str(idx),
                                        str(block_idx),
                                    ),
                                    start=Point(content_x, line_y),
                                    end=Point(content_x + content_width, line_y),
                                    metadata=self._with_base_metadata(
                                        {
                                            "role": "scenario_procedures_underline",
                                            "scenario_index": idx,
                                        },
                                        base_metadata,
                                    ),
                                    stroke_color="#1e1e1e",
                                    stroke_width=2.0,
                                    group_ids=[procedures_group],
                                )
                            )
                        current_y += block.height
                        continue
                    if kind == "service":
                        service_meta = {
                            "role": "scenario_procedures_service_panel",
                            "scenario_index": idx,
                        }
                        if block.finedog_unit_id:
                            service_meta["finedog_unit_id"] = block.finedog_unit_id
                        panel_id = self._stable_id(
                            "scenario-procedures-service-panel",
                            str(idx),
                            str(block_idx),
                            block.text,
                        )
                        registry.add(
                            self._scenario_procedures_panel_element(
                                element_id=panel_id,
                                origin=Point(content_x, current_y),
                                size=Size(content_width, block.height),
                                metadata=self._with_base_metadata(
                                    service_meta,
                                    base_metadata,
                                ),
                                group_ids=[procedures_group],
                                background_color=block.color,
                            )
                        )
                        text_origin = Point(
                            x=content_x + block_padding,
                            y=current_y + block_padding,
                        )
                        text_height = max(0.0, block.height - block_padding * 2)
                        service_text_meta = {
                            "role": "scenario_procedures_service",
                            "scenario_index": idx,
                        }
                        if block.finedog_unit_id:
                            service_text_meta["finedog_unit_id"] = block.finedog_unit_id
                        registry.add(
                            self._text_block_element(
                                element_id=self._stable_id(
                                    "scenario-procedures-service-text",
                                    str(idx),
                                    str(block_idx),
                                ),
                                text=block.text,
                                origin=text_origin,
                                width=max(0.0, content_width - block_padding * 2),
                                height=text_height,
                                metadata=self._with_base_metadata(
                                    service_text_meta,
                                    base_metadata,
                                ),
                                group_ids=[procedures_group],
                                font_size=block_font_size,
                            )
                        )
                        current_y += block.height
                        continue
                    text_origin = Point(content_x, current_y)
                    registry.add(
                        self._text_block_element(
                            element_id=self._stable_id(
                                "scenario-procedures-block",
                                str(idx),
                                str(block_idx),
                            ),
                            text=block.text,
                            origin=text_origin,
                            width=content_width,
                            height=block.height,
                            metadata=self._with_base_metadata(
                                {"role": "scenario_procedures", "scenario_index": idx},
                                base_metadata,
                            ),
                            group_ids=[procedures_group],
                            font_size=block_font_size,
                        )
                    )
                    if block.underline:
                        line_y = current_y + block.height - max(2.0, block_font_size * 0.15)
                        registry.add(
                            self._line_element(
                                element_id=self._stable_id(
                                    "scenario-procedures-underline",
                                    str(idx),
                                    str(block_idx),
                                ),
                                start=Point(content_x, line_y),
                                end=Point(content_x + content_width, line_y),
                                metadata=self._with_base_metadata(
                                    {
                                        "role": "scenario_procedures_underline",
                                        "scenario_index": idx,
                                    },
                                    base_metadata,
                                ),
                                stroke_color="#1e1e1e",
                                stroke_width=2.0,
                                group_ids=[procedures_group],
                            )
                        )
                    current_y += block.height
            else:
                procedures_width = scenario.procedures_size.width - (
                    scenario.procedures_padding * 2
                )
                procedures_lines = scenario.procedures_text.splitlines() or [
                    scenario.procedures_text
                ]
                procedures_height = len(procedures_lines) * scenario.procedures_font_size * 1.35
                procedures_origin = Point(
                    x=scenario.procedures_origin.x + scenario.procedures_padding,
                    y=scenario.procedures_origin.y + scenario.procedures_padding,
                )
                registry.add(
                    self._text_block_element(
                        element_id=procedures_text_id,
                        text=scenario.procedures_text,
                        origin=procedures_origin,
                        width=procedures_width,
                        height=procedures_height,
                        metadata=self._with_base_metadata(
                            {"role": "scenario_procedures", "scenario_index": idx},
                            base_metadata,
                        ),
                        group_ids=[procedures_group],
                        font_size=scenario.procedures_font_size,
                    )
                )

    def _build_blocks(
        self,
        blocks: Iterable[BlockPlacement],
        frame_ids: dict[str, str],
        registry: ElementRegistry,
        base_metadata: Metadata,
        end_block_type_lookup: dict[tuple[str, str], str],
        block_name_lookup: dict[tuple[str, str], str],
        block_graph_initials: set[str],
        source_procedure_ids: dict[str, str] | None = None,
    ) -> dict[tuple[str, str], BlockPlacement]:
        placement_index: dict[tuple[str, str], BlockPlacement] = {}
        source_lookup = source_procedure_ids or {}
        for block in blocks:
            placement_index[(block.procedure_id, block.block_id)] = block
            group_id = self._stable_id("group", block.procedure_id, block.block_id)
            rect_id = self._stable_id("block", block.procedure_id, block.block_id)
            text_id = self._stable_id("block-text", block.procedure_id, block.block_id)
            end_block_type = end_block_type_lookup.get((block.procedure_id, block.block_id))
            is_initial = block.block_id in block_graph_initials
            block_meta: dict[str, object] = {
                "procedure_id": block.procedure_id,
                "block_id": block.block_id,
                "role": "block",
            }
            source_procedure_id = source_lookup.get(block.procedure_id)
            if isinstance(source_procedure_id, str) and source_procedure_id:
                block_meta["source_procedure_id"] = source_procedure_id
            if is_initial:
                block_meta["block_graph_initial"] = True
            if end_block_type:
                block_meta["end_block_type"] = end_block_type
            label_text = block_name_lookup.get((block.procedure_id, block.block_id), block.block_id)
            registry.add(
                self._rectangle_element(
                    element_id=rect_id,
                    position=block.position,
                    size=block.size,
                    frame_id=frame_ids.get(block.procedure_id),
                    group_ids=[group_id],
                    metadata=self._with_base_metadata(block_meta, base_metadata),
                    background_color=(
                        INITIAL_BLOCK_COLOR
                        if is_initial
                        else (
                            INTERMEDIATE_BLOCK_COLOR if end_block_type == "intermediate" else None
                        )
                    ),
                    stroke_style="dashed" if is_initial else None,
                    fill_style="hachure" if is_initial else None,
                )
            )
            label_meta: dict[str, object] = {
                "procedure_id": block.procedure_id,
                "block_id": block.block_id,
                "role": "block_label",
                "end_block_type": end_block_type,
            }
            if isinstance(source_procedure_id, str) and source_procedure_id:
                label_meta["source_procedure_id"] = source_procedure_id
            if is_initial:
                label_meta["block_graph_initial"] = True
            if label_text != block.block_id:
                label_meta["block_name"] = label_text
            registry.add(
                self._text_element(
                    element_id=text_id,
                    text=label_text,
                    center=self._center(block.position, block.size.width, block.size.height),
                    container_id=rect_id,
                    group_ids=[group_id],
                    frame_id=frame_ids.get(block.procedure_id),
                    metadata=self._with_base_metadata(label_meta, base_metadata),
                    max_width=max(100.0, block.size.width - 24),
                    max_height=max(24.0, block.size.height - 24),
                    font_size=18.0,
                )
            )
            placeholders = self._block_label_placeholders(
                block=block,
                frame_id=frame_ids.get(block.procedure_id),
                group_ids=[group_id],
                metadata=self._with_base_metadata(label_meta, base_metadata),
            )
            for placeholder in placeholders:
                registry.add(placeholder)
        return placement_index

    def _block_label_placeholders(
        self,
        block: BlockPlacement,
        frame_id: str | None,
        group_ids: list[str],
        metadata: Metadata,
    ) -> Iterable[Element]:
        return []

    def _build_markers(
        self,
        markers: Iterable[MarkerPlacement],
        frame_ids: dict[str, str],
        registry: ElementRegistry,
        base_metadata: Metadata,
        start_label_index: dict[tuple[str, str], int],
        end_block_type_lookup: dict[tuple[str, str], str],
    ) -> dict[tuple[str, str, str, str | None], MarkerPlacement]:
        marker_index: dict[tuple[str, str, str, str | None], MarkerPlacement] = {}
        for marker in markers:
            marker_index[(marker.procedure_id, marker.block_id, marker.role, marker.end_type)] = (
                marker
            )
            group_id = self._stable_id(
                "marker-group",
                marker.procedure_id,
                marker.role,
                marker.block_id,
                marker.end_type or "",
            )
            element_id = self._marker_element_id(
                marker.procedure_id, marker.role, marker.block_id, marker.end_type
            )
            marker_meta = {
                "procedure_id": marker.procedure_id,
                "block_id": marker.block_id,
                "role": marker.role,
            }
            end_type = None
            block_end_type = None
            background_color = None
            stroke_style = None
            if marker.role == "end_marker":
                end_type = marker.end_type or END_TYPE_DEFAULT
                block_end_type = end_block_type_lookup.get((marker.procedure_id, marker.block_id))
                if block_end_type is None:
                    block_end_type = end_type
                marker_meta["end_block_type"] = block_end_type
                marker_meta["end_type"] = end_type
                background_color = END_TYPE_COLORS.get(end_type, END_TYPE_COLORS[END_TYPE_DEFAULT])
                if end_type == "intermediate":
                    stroke_style = "dashed"
            registry.add(
                self._ellipse_element(
                    element_id=element_id,
                    position=marker.position,
                    size=marker.size,
                    frame_id=frame_ids.get(marker.procedure_id),
                    metadata=self._with_base_metadata(marker_meta, base_metadata),
                    group_ids=[group_id],
                    background_color=background_color,
                    stroke_style=stroke_style,
                )
            )
            label_id = self._stable_id(
                "marker-text",
                marker.procedure_id,
                marker.role,
                marker.block_id,
                marker.end_type or "",
            )
            label_text = "START"
            if marker.role == "start_marker":
                idx = start_label_index.get((marker.procedure_id, marker.block_id), 1)
                label_text = "START" if len(start_label_index) == 1 else f"START #{idx}"
            elif marker.role == "end_marker":
                if end_type == "postpone":
                    label_text = "POSTPONE"
                elif end_type == END_TYPE_TURN_OUT:
                    label_text = "TURN OUT"
                elif end_type in {"all", "intermediate"}:
                    label_text = "END & EXIT"
                else:
                    label_text = "END" if end_type != "exit" else "EXIT"
            registry.add(
                self._text_element(
                    element_id=label_id,
                    text=label_text,
                    center=self._center(marker.position, marker.size.width, marker.size.height),
                    container_id=element_id,
                    frame_id=frame_ids.get(marker.procedure_id),
                    group_ids=[group_id],
                    metadata=self._with_base_metadata(marker_meta, base_metadata),
                    max_width=marker.size.width - 24,
                    max_height=min(52.0, marker.size.height - 14),
                    font_size=None,
                )
            )
        return marker_index

    def _build_start_edges(
        self,
        document: MarkupDocument,
        blocks: dict[tuple[str, str], BlockPlacement],
        markers: dict[tuple[str, str, str, str | None], MarkerPlacement],
        registry: ElementRegistry,
        base_metadata: Metadata,
    ) -> None:
        for procedure in document.procedures:
            for start_block_id in procedure.start_block_ids:
                marker = markers.get((procedure.procedure_id, start_block_id, "start_marker", None))
                block = blocks.get((procedure.procedure_id, start_block_id))
                if not marker or not block:
                    continue
                start_center = self._marker_anchor(marker, side="right")
                end_center = self._block_anchor(block, side="left")
                arrow = self._arrow_element(
                    start=start_center,
                    end=end_center,
                    label="start",
                    metadata=self._with_base_metadata(
                        {
                            "procedure_id": procedure.procedure_id,
                            "role": "edge",
                            "edge_type": "start",
                            "target_block_id": start_block_id,
                        },
                        base_metadata,
                    ),
                    start_binding=self._marker_element_id(
                        procedure.procedure_id, "start_marker", start_block_id, None
                    ),
                    end_binding=self._stable_id("block", procedure.procedure_id, start_block_id),
                )
                registry.add(arrow)
                self._register_edge_bindings(arrow, registry)

    def _build_end_edges(
        self,
        document: MarkupDocument,
        blocks: dict[tuple[str, str], BlockPlacement],
        markers: dict[tuple[str, str, str, str | None], MarkerPlacement],
        registry: ElementRegistry,
        base_metadata: Metadata,
        end_block_type_lookup: dict[tuple[str, str], str],
    ) -> None:
        for (proc_id, block_id, role, marker_end_type), marker in markers.items():
            if role != "end_marker":
                continue
            block = blocks.get((proc_id, block_id))
            if not block:
                continue
            end_type = marker_end_type or END_TYPE_DEFAULT
            block_end_type = end_block_type_lookup.get((proc_id, block_id), end_type)
            start_center = self._block_anchor(block, side="right")
            end_center = self._marker_anchor(marker, side="left")
            arrow = self._arrow_element(
                start=start_center,
                end=end_center,
                label="end",
                metadata=self._with_base_metadata(
                    {
                        "procedure_id": proc_id,
                        "role": "edge",
                        "edge_type": "end",
                        "end_type": end_type,
                        "end_block_type": block_end_type,
                        "source_block_id": block_id,
                    },
                    base_metadata,
                ),
                start_binding=self._stable_id("block", proc_id, block_id),
                end_binding=self._marker_element_id(
                    proc_id, "end_marker", block_id, marker_end_type
                ),
            )
            registry.add(arrow)
            self._register_edge_bindings(arrow, registry)

    def _build_branch_edges(
        self,
        document: MarkupDocument,
        blocks: dict[tuple[str, str], BlockPlacement],
        registry: ElementRegistry,
        base_metadata: Metadata,
    ) -> None:
        if document.block_graph:
            return
        cycle_edges_by_proc: dict[str, set[tuple[str, str]]] = {
            procedure.procedure_id: self._edges_in_cycles(procedure.branches)
            for procedure in document.procedures
        }
        branch_offsets: dict[tuple[str, str], list[float]] = {}
        for procedure in document.procedures:
            for source_block, targets in procedure.branches.items():
                count = max(1, len(targets))
                offsets = [(idx - (count - 1) / 2) * 15.0 for idx in range(count)]
                branch_offsets[(procedure.procedure_id, source_block)] = offsets
        branch_index: dict[tuple[str, str], int] = {}

        # Index blocks by block_id for potential cross-procedure branches (best-effort).
        block_by_id: dict[str, list[tuple[str, BlockPlacement]]] = {}
        for (proc_id, blk_id), placement in blocks.items():
            block_by_id.setdefault(blk_id, []).append((proc_id, placement))

        for procedure in document.procedures:
            for source_block, targets in procedure.branches.items():
                source = blocks.get((procedure.procedure_id, source_block))
                if not source:
                    continue
                for target_block in targets:
                    target = blocks.get((procedure.procedure_id, target_block))
                    target_proc_id = procedure.procedure_id
                    if not target:
                        candidates = block_by_id.get(target_block, [])
                        if len(candidates) == 1:
                            target_proc_id, target = candidates[0]
                    if not target:
                        continue
                    offset_key = (procedure.procedure_id, source_block)
                    offset_idx = branch_index.get(offset_key, 0)
                    branch_index[offset_key] = offset_idx + 1
                    is_cycle = (source_block, target_block) in cycle_edges_by_proc.get(
                        procedure.procedure_id, set()
                    )
                    dy = branch_offsets.get(offset_key, [0])[
                        min(offset_idx, len(branch_offsets.get(offset_key, [0])) - 1)
                    ]
                    if is_cycle:
                        start_center = self._block_anchor(source, side="top")
                        end_center = self._block_anchor(target, side="top")
                        cycle_points = self._elbow_points(start_center, end_center, 80.0)
                    else:
                        start_center = self._block_anchor(source, side="right", y_offset=dy)
                        end_center = self._block_anchor(target, side="left", y_offset=dy)
                        cycle_points = None
                    edge_type = "branch_cycle" if is_cycle else "branch"
                    label = "ЦИКЛ" if is_cycle else "branch"
                    arrow = self._arrow_element(
                        start=start_center,
                        end=end_center,
                        label=label,
                        metadata=self._with_base_metadata(
                            {
                                "procedure_id": procedure.procedure_id,
                                "target_procedure_id": target_proc_id,
                                "role": "edge",
                                "edge_type": edge_type,
                                "is_cycle": is_cycle,
                                "source_block_id": source_block,
                                "target_block_id": target_block,
                            },
                            base_metadata,
                        ),
                        start_binding=self._stable_id(
                            "block", procedure.procedure_id, source_block
                        ),
                        end_binding=self._stable_id("block", target_proc_id, target_block),
                        smoothing=0.15,
                        stroke_style="dashed" if is_cycle else None,
                        stroke_color="#d32f2f" if is_cycle else None,
                        stroke_width=1 if is_cycle else None,
                        points=cycle_points,
                        end_arrowhead="arrow" if is_cycle else None,
                    )
                    registry.add(arrow)
                    self._register_edge_bindings(arrow, registry)

    def _build_procedure_flow_edges(
        self,
        document: MarkupDocument,
        frames: Iterable[FramePlacement],
        frame_ids: dict[str, str],
        registry: ElementRegistry,
        base_metadata: Metadata,
        blocks: dict[tuple[str, str], BlockPlacement] | None = None,
    ) -> None:
        if document.block_graph and blocks:
            self._build_block_graph_edges(document, blocks, registry, base_metadata)
            return
        frames_list = list(frames)
        if len(frames_list) <= 1:
            return
        frame_lookup: dict[str, FramePlacement] = {f.procedure_id: f for f in frames_list}
        graph_edges: list[tuple[str, str]] = []
        cycle_edges: set[tuple[str, str]] = set()
        for parent, children in document.procedure_graph.items():
            if parent not in frame_lookup:
                continue
            for child in children:
                if child in frame_lookup:
                    graph_edges.append((parent, child))

        if graph_edges:
            seen: set[tuple[str, str]] = set()
            edges_to_draw = []
            for edge in graph_edges:
                if edge in seen:
                    continue
                seen.add(edge)
                edges_to_draw.append(edge)
        else:
            # Connect procedures when no explicit block-to-block cross edges.
            proc_for_block: dict[str, str] = {}
            for proc in document.procedures:
                for blk in proc.block_ids():
                    proc_for_block[blk] = proc.procedure_id

            cross_edges = []
            for proc in document.procedures:
                for _src, targets in proc.branches.items():
                    for tgt in targets:
                        tgt_proc = proc_for_block.get(tgt)
                        if tgt_proc and tgt_proc != proc.procedure_id:
                            cross_edges.append((proc.procedure_id, tgt_proc))
            seen_edges: set[tuple[str, str]] = set()
            edges_to_draw = []
            for edge in cross_edges:
                if edge in seen_edges:
                    continue
                seen_edges.add(edge)
                edges_to_draw.append(edge)
        if edges_to_draw:
            adjacency: dict[str, list[str]] = {}
            for src, tgt in edges_to_draw:
                adjacency.setdefault(src, []).append(tgt)
            cycle_edges = self._edges_in_cycles(adjacency)

        for source_id, target_id in edges_to_draw:
            source_frame = frame_lookup.get(source_id)
            target_frame = frame_lookup.get(target_id)
            if not source_frame or not target_frame:
                continue
            is_cycle = (source_id, target_id) in cycle_edges
            if source_frame.origin.x == target_frame.origin.x:
                is_reverse = source_frame.origin.y > target_frame.origin.y
            else:
                is_reverse = source_frame.origin.x > target_frame.origin.x
            cycle_marker = is_cycle and is_reverse
            edge_type = "procedure_cycle" if cycle_marker else "procedure_flow"
            label = "ЦИКЛ" if cycle_marker else "procedure"
            curve_direction = None
            if cycle_marker:
                start = Point(
                    x=source_frame.origin.x + source_frame.size.width / 2,
                    y=source_frame.origin.y + source_frame.size.height,
                )
                end = Point(
                    x=target_frame.origin.x,
                    y=target_frame.origin.y + target_frame.size.height / 2,
                )
                dx = end.x - start.x
                dy = end.y - start.y
                if dx == 0:
                    curve_direction = -1.0 if dy >= 0 else 1.0
                else:
                    curve_direction = -1.0 if dx > 0 else 1.0
            else:
                start = Point(
                    x=source_frame.origin.x + source_frame.size.width,
                    y=source_frame.origin.y + source_frame.size.height / 2,
                )
                end = Point(
                    x=target_frame.origin.x,
                    y=target_frame.origin.y + target_frame.size.height / 2,
                )
            arrow = self._arrow_element(
                start=start,
                end=end,
                label=label,
                metadata=self._with_base_metadata(
                    {
                        "procedure_id": source_id,
                        "target_procedure_id": target_id,
                        "role": "edge",
                        "edge_type": edge_type,
                        "is_cycle": cycle_marker,
                    },
                    base_metadata,
                ),
                start_binding=self._stable_id("frame", source_id),
                end_binding=self._stable_id("frame", target_id),
                smoothing=0.1,
                stroke_style="dashed" if cycle_marker else None,
                stroke_color="#d32f2f" if cycle_marker else None,
                stroke_width=self._procedure_edge_stroke_width(cycle_marker),
                curve_offset=100.0 if cycle_marker else None,
                curve_direction=curve_direction if cycle_marker else None,
                end_arrowhead="arrow" if cycle_marker else None,
            )
            registry.add(arrow)
            self._register_edge_bindings(arrow, registry)

    def _build_block_graph_edges(
        self,
        document: MarkupDocument,
        blocks: dict[tuple[str, str], BlockPlacement],
        registry: ElementRegistry,
        base_metadata: Metadata,
    ) -> None:
        owners_by_block: dict[str, set[str]] = {}
        for proc_id, block_id in blocks:
            owners_by_block.setdefault(block_id, set()).add(proc_id)
        resolved_edges = resolve_block_graph_edges(
            document.block_graph,
            owners_by_block,
            document.procedure_graph,
        )
        edges_by_source: dict[
            tuple[str, str],
            list[tuple[str, str, BlockPlacement, BlockPlacement]],
        ] = {}
        for edge in resolved_edges:
            source_key = (edge.source_procedure_id, edge.source_block_id)
            target_key = (edge.target_procedure_id, edge.target_block_id)
            source_block = blocks.get(source_key)
            target_block = blocks.get(target_key)
            if not source_block or not target_block:
                continue
            edges_by_source.setdefault(source_key, []).append(
                (
                    edge.target_block_id,
                    edge.target_procedure_id,
                    source_block,
                    target_block,
                )
            )

        if not edges_by_source:
            return

        adjacency = {
            f"{source_proc}\x1f{source_block_id}": [
                f"{target_proc}\x1f{target_block_id}"
                for target_block_id, target_proc, _source_block, _target_block in edges
            ]
            for (source_proc, source_block_id), edges in edges_by_source.items()
        }
        cycle_edges = self._edges_in_cycles(adjacency)
        edge_offsets: dict[tuple[str, str], list[float]] = {}
        for source_key, edges in edges_by_source.items():
            count = max(1, len(edges))
            edge_offsets[source_key] = [(idx - (count - 1) / 2) * 15.0 for idx in range(count)]

        for (source_proc, source_block_id), edges in edges_by_source.items():
            offsets = edge_offsets.get((source_proc, source_block_id), [0.0])
            for offset_idx, (
                target_block_id,
                target_proc,
                source_block,
                target_block,
            ) in enumerate(edges):
                dy = offsets[min(offset_idx, len(offsets) - 1)]
                source_node_key = f"{source_proc}\x1f{source_block_id}"
                target_node_key = f"{target_proc}\x1f{target_block_id}"
                is_cycle = (source_node_key, target_node_key) in cycle_edges
                cycle_marker = is_cycle and self._is_reverse_block_edge(source_block, target_block)
                if cycle_marker:
                    start_center = self._block_anchor(source_block, side="bottom")
                    end_center = self._block_anchor(target_block, side="left")
                    points = self._elbow_points(start_center, end_center, 80.0)
                else:
                    start_center = self._block_anchor(source_block, side="right", y_offset=dy)
                    end_center = self._block_anchor(target_block, side="left", y_offset=dy)
                    points = None
                edge_type = "block_graph_cycle" if cycle_marker else "block_graph"
                label = "ЦИКЛ" if cycle_marker else "graph"
                arrow = self._arrow_element(
                    start=start_center,
                    end=end_center,
                    label=label,
                    metadata=self._with_base_metadata(
                        {
                            "procedure_id": source_proc,
                            "target_procedure_id": target_proc,
                            "role": "edge",
                            "edge_type": edge_type,
                            "is_cycle": is_cycle,
                            "source_block_id": source_block_id,
                            "target_block_id": target_block_id,
                        },
                        base_metadata,
                    ),
                    start_binding=self._stable_id("block", source_proc, source_block_id),
                    end_binding=self._stable_id("block", target_proc, target_block_id),
                    smoothing=0.15,
                    stroke_style="dashed" if cycle_marker else None,
                    stroke_color="#d32f2f" if cycle_marker else None,
                    stroke_width=1 if cycle_marker else None,
                    points=points,
                    end_arrowhead="arrow" if cycle_marker else None,
                )
                registry.add(arrow)
                self._register_edge_bindings(arrow, registry)

    def _format_procedure_label(self, procedure_name: str | None, procedure_id: str) -> str:
        if procedure_name:
            return f"{procedure_name} ({procedure_id})"
        return procedure_id

    def _marker_element_id(
        self,
        procedure_id: str,
        role: str,
        block_id: str,
        end_type: str | None,
    ) -> str:
        if role == "end_marker" and end_type:
            return self._stable_id("marker", procedure_id, role, block_id, end_type)
        return self._stable_id("marker", procedure_id, role, block_id)

    def _elbow_points(
        self,
        start: Point,
        end: Point,
        offset: float,
    ) -> list[list[float]]:
        dx = end.x - start.x
        dy = end.y - start.y
        if dx == 0:
            direction = -1.0 if dy >= 0 else 1.0
        else:
            direction = -1.0 if dx > 0 else 1.0
        elbow_offset = offset * direction
        return [[0.0, 0.0], [0.0, elbow_offset], [dx, elbow_offset], [dx, dy]]

    def _edges_in_cycles(self, adjacency: dict[str, list[str]]) -> set[tuple[str, str]]:
        normalized: dict[str, list[str]] = {
            node: list(children) for node, children in adjacency.items()
        }

        nodes = set(normalized.keys())
        for children in normalized.values():
            nodes.update(children)
        if not nodes:
            return set()

        index = 0
        indices: dict[str, int] = {}
        lowlinks: dict[str, int] = {}
        stack: list[str] = []
        on_stack: set[str] = set()
        components: list[list[str]] = []

        def strongconnect(node: str) -> None:
            nonlocal index
            indices[node] = index
            lowlinks[node] = index
            index += 1
            stack.append(node)
            on_stack.add(node)

            for child in normalized.get(node, []):
                if child not in indices:
                    strongconnect(child)
                    lowlinks[node] = min(lowlinks[node], lowlinks[child])
                elif child in on_stack:
                    lowlinks[node] = min(lowlinks[node], indices[child])

            if lowlinks[node] == indices[node]:
                component: list[str] = []
                while True:
                    current = stack.pop()
                    on_stack.remove(current)
                    component.append(current)
                    if current == node:
                        break
                components.append(component)

        for node in nodes:
            if node not in indices:
                strongconnect(node)

        component_id: dict[str, int] = {}
        component_sizes: dict[int, int] = {}
        for idx, component in enumerate(components):
            component_sizes[idx] = len(component)
            for node in component:
                component_id[node] = idx

        cycle_edges: set[tuple[str, str]] = set()
        for source, targets in normalized.items():
            for target in targets:
                src_id = component_id.get(source)
                tgt_id = component_id.get(target)
                if src_id is None or tgt_id is None or src_id != tgt_id:
                    continue
                if component_sizes.get(src_id, 0) > 1 or source == target:
                    cycle_edges.add((source, target))
        return cycle_edges

    def _plan_bounds(self, plan: LayoutPlan) -> tuple[float, float, float, float] | None:
        min_x = float("inf")
        min_y = float("inf")
        max_x = float("-inf")
        max_y = float("-inf")
        for frame in plan.frames:
            min_x = min(min_x, frame.origin.x)
            min_y = min(min_y, frame.origin.y)
            max_x = max(max_x, frame.origin.x + frame.size.width)
            max_y = max(max_y, frame.origin.y + frame.size.height)
        for scenario in plan.scenarios:
            min_x = min(min_x, scenario.origin.x)
            min_y = min(min_y, scenario.origin.y)
            max_x = max(max_x, scenario.origin.x + scenario.size.width)
            max_y = max(max_y, scenario.origin.y + scenario.size.height)
        for separator in plan.separators:
            min_x = min(min_x, separator.start.x, separator.end.x)
            max_x = max(max_x, separator.start.x, separator.end.x)
            min_y = min(min_y, separator.start.y, separator.end.y)
            max_y = max(max_y, separator.start.y, separator.end.y)
        for column in plan.markup_type_columns:
            min_x = min(min_x, column.origin.x)
            min_y = min(min_y, column.origin.y)
            max_x = max(max_x, column.origin.x + column.size.width)
            max_y = max(max_y, column.origin.y + column.size.height)
        if min_x == float("inf"):
            return None
        return min_x, min_y, max_x, max_y

    def _center(self, position: Point, width: float, height: float) -> Point:
        return Point(x=position.x + width / 2, y=position.y + height / 2)

    def _block_anchor(
        self,
        block: BlockPlacement,
        side: str,
        x_offset: float = 0.0,
        y_offset: float = 0.0,
    ) -> Point:
        if side == "left":
            return Point(
                x=block.position.x + x_offset,
                y=block.position.y + block.size.height / 2 + y_offset,
            )
        if side == "top":
            return Point(
                x=block.position.x + block.size.width / 2 + x_offset,
                y=block.position.y + y_offset,
            )
        if side == "bottom":
            return Point(
                x=block.position.x + block.size.width / 2 + x_offset,
                y=block.position.y + block.size.height + y_offset,
            )
        return Point(
            x=block.position.x + block.size.width + x_offset,
            y=block.position.y + block.size.height / 2 + y_offset,
        )

    def _is_reverse_block_edge(self, source: BlockPlacement, target: BlockPlacement) -> bool:
        source_center = self._center(source.position, source.size.width, source.size.height)
        target_center = self._center(target.position, target.size.width, target.size.height)
        if abs(source_center.x - target_center.x) < 1e-6:
            return source_center.y > target_center.y
        return source_center.x > target_center.x

    def _marker_anchor(self, marker: MarkerPlacement, side: str) -> Point:
        if side == "left":
            return Point(
                x=marker.position.x,
                y=marker.position.y + marker.size.height / 2,
            )
        return Point(
            x=marker.position.x + marker.size.width,
            y=marker.position.y + marker.size.height / 2,
        )

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

    def _stable_id(self, *parts: str) -> str:
        return str(uuid.uuid5(self.namespace, "|".join(parts)))

    def _rand_seed(self) -> int:
        return random.randint(1, 2**31 - 1)

    def _with_base_metadata(self, metadata: Metadata, base: Metadata) -> Metadata:
        merged = dict(base)
        merged.update(metadata)
        return merged

    def _normalize_points(
        self,
        start: Point,
        points: list[list[float]],
    ) -> tuple[Point, Size, list[list[float]]]:
        min_x = min(point[0] for point in points)
        max_x = max(point[0] for point in points)
        min_y = min(point[1] for point in points)
        max_y = max(point[1] for point in points)
        width = max_x - min_x
        height = max_y - min_y
        adjusted_points = [[point[0] - min_x, point[1] - min_y] for point in points]
        return Point(x=start.x + min_x, y=start.y + min_y), Size(width, height), adjusted_points

    @abstractmethod
    def _frame_element(
        self,
        element_id: str,
        frame: FramePlacement,
        metadata: Metadata,
        name: str | None = None,
    ) -> Element:
        raise NotImplementedError

    @abstractmethod
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
        raise NotImplementedError

    @abstractmethod
    def _scenario_panel_element(
        self,
        element_id: str,
        origin: Point,
        size: Size,
        metadata: Metadata,
        group_ids: list[str],
    ) -> Element:
        raise NotImplementedError

    @abstractmethod
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
        raise NotImplementedError

    @abstractmethod
    def _title_panel_element(
        self,
        element_id: str,
        origin: Point,
        size: Size,
        metadata: Metadata,
        group_ids: list[str],
    ) -> Element:
        raise NotImplementedError

    @abstractmethod
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
        raise NotImplementedError

    @abstractmethod
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
        raise NotImplementedError

    @abstractmethod
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
        raise NotImplementedError

    @abstractmethod
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
        raise NotImplementedError

    @abstractmethod
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
        raise NotImplementedError
