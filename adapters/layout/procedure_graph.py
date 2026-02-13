from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass
from itertools import pairwise

from adapters.layout.grid import GridLayoutEngine, LayoutConfig
from domain.markup_type_labels import humanize_markup_type_for_brackets
from domain.models import (
    FramePlacement,
    LayoutPlan,
    MarkupDocument,
    MarkupTypeColumnPlacement,
    Point,
    Procedure,
    ScenarioPlacement,
    ScenarioProceduresBlock,
    SeparatorPlacement,
    ServiceZonePlacement,
    Size,
    normalize_finedog_unit_id,
)

_MARKUP_TYPE_COLUMN_ORDER = (
    "system_service_search",
    "service",
    "system_task_processor",
    "system_default",
)
_MARKUP_TYPE_COLUMN_ORDER_INDEX = {
    markup_type: idx for idx, markup_type in enumerate(_MARKUP_TYPE_COLUMN_ORDER)
}


@dataclass(frozen=True)
class _ServiceInfo:
    service_key: str
    service_name: str
    markup_type: str
    team_name: str
    team_id: str | int | None
    color: str


@dataclass(frozen=True)
class _ServiceBand:
    service: _ServiceInfo
    start_y: float
    height: float


@dataclass(frozen=True)
class _ZoneDraft:
    info: _ServiceInfo
    procedure_ids: tuple[str, ...]
    origin: Point
    size: Size
    label_origin: Point
    label_size: Size


@dataclass
class _MergeGroup:
    label: str
    proc_ids: list[str]


@dataclass(frozen=True)
class _ComponentPlacementInfo:
    component_index: int
    procedure_ids: tuple[str, ...]
    markup_type: str
    is_merged_markup_types: bool
    primary_service_name: str
    sort_key: tuple[object, ...]
    min_x: float
    min_y: float
    max_x: float
    max_y: float

    @property
    def width(self) -> float:
        return self.max_x - self.min_x

    @property
    def height(self) -> float:
        return self.max_y - self.min_y


class ProcedureGraphLayoutEngine(GridLayoutEngine):
    def __init__(self, config: LayoutConfig | None = None) -> None:
        super().__init__(config or LayoutConfig())

    def build_plan(self, document: MarkupDocument) -> LayoutPlan:
        frames: list[FramePlacement] = []
        separators: list[SeparatorPlacement] = []
        scenarios: list[ScenarioPlacement] = []
        service_zones: list[ServiceZonePlacement] = []
        markup_type_columns: list[MarkupTypeColumnPlacement] = []
        is_service_graph = str(document.markup_type or "").strip().lower() == "service_graph"

        procedures = list(document.procedures)
        if not procedures:
            return LayoutPlan(
                frames=frames,
                blocks=[],
                markers=[],
                separators=separators,
                scenarios=scenarios,
                service_zones=service_zones,
                markup_type_columns=markup_type_columns,
            )

        proc_ids = [proc.procedure_id for proc in procedures]
        order_hint = self._procedure_order_hint(procedures, document.procedure_graph)
        order_index = {proc_id: idx for idx, proc_id in enumerate(order_hint)}
        adjacency = self._normalize_procedure_graph(proc_ids, document.procedure_graph)
        components = self._procedure_components(proc_ids, adjacency)
        components.sort(
            key=lambda component: min(order_index.get(proc_id, 0) for proc_id in component)
        )
        component_index_by_proc: dict[str, int] = {}
        for component_idx, component in enumerate(components):
            for proc_id in component:
                component_index_by_proc[proc_id] = component_idx
        scenario_index_by_component: dict[int, int] = {}
        zone_range_by_component: dict[int, tuple[int, int]] = {}

        procedure_meta = document.procedure_meta or {}
        default_markup_type = str(document.markup_type or "").strip() or "unknown"
        node_size = self._procedure_node_size()
        base_service_node_size = Size(node_size.width * 3, node_size.height * 1.2)
        service_node_sizes: dict[str, Size] = {}
        if is_service_graph:
            for proc in procedures:
                meta = procedure_meta.get(proc.procedure_id, {})
                count_raw = meta.get("procedure_count")
                count = count_raw if isinstance(count_raw, int) and count_raw > 0 else 1
                scale = 1.0 + 0.05 * (count - 1)
                service_node_sizes[proc.procedure_id] = Size(
                    base_service_node_size.width * scale,
                    base_service_node_size.height * scale,
                )
        lane_span = node_size.width + self.config.lane_gap
        proc_gap_y = self.config.gap_y
        component_gap = max(proc_gap_y, self.config.separator_padding * 2)

        origin_x = 0.0
        origin_y = 0.0
        scenario_cursor_y = 0.0
        separator_ys: list[float] = []
        frame_lookup: dict[str, FramePlacement] = {}
        procedure_map = {proc.procedure_id: proc for proc in procedures}
        block_graph_nodes = self._block_graph_nodes(document) if document.block_graph else set()
        owned_blocks_by_proc = self._resolve_owned_blocks(document, block_graph_nodes)
        layout_edges_by_proc = self._layout_edges_by_proc(
            document, procedures, owned_blocks_by_proc
        )

        for idx, component in enumerate(components):
            component_top = origin_y
            component_adjacency = {
                proc_id: [child for child in adjacency.get(proc_id, []) if child in component]
                for proc_id in component
            }
            cycle_edges = self._find_cycle_edges(component_adjacency, order_index)
            for source, target in cycle_edges:
                component_adjacency[source] = [
                    child for child in component_adjacency.get(source, []) if child != target
                ]

            levels = self._procedure_levels(component, component_adjacency, order_index)
            max_level = max(levels.values() or [0])
            level_nodes: dict[int, list[str]] = {lvl: [] for lvl in range(max_level + 1)}
            for proc_id, lvl in levels.items():
                level_nodes.setdefault(lvl, []).append(proc_id)
            for nodes in level_nodes.values():
                nodes.sort(key=lambda proc_id: order_index.get(proc_id, 0))

            service_info_by_key, proc_service_keys = self._component_service_info(
                component,
                procedure_meta,
                default_markup_type,
            )
            zone_enabled = not is_service_graph and len(service_info_by_key) > 1
            component_frames: list[FramePlacement] = []
            component_frame_lookup: dict[str, FramePlacement] = {}
            component_height = 0.0
            zones_for_component: list[ServiceZonePlacement] = []
            service_order: list[_ServiceInfo] = []
            assigned: dict[str, str] = {}

            if zone_enabled:
                service_order = self._sorted_service_infos(service_info_by_key)
                assigned, service_counts = self._assign_component_services(
                    proc_service_keys, service_order
                )
                service_order = [
                    info for info in service_order if service_counts.get(info.service_key, 0) > 0
                ]
                if service_order:
                    linear_frames = self._linear_component_frames(
                        level_nodes=level_nodes,
                        origin_x=origin_x,
                        origin_y=origin_y,
                        lane_span=lane_span,
                        node_size=node_size,
                        proc_gap_y=proc_gap_y,
                    )
                    has_edges = any(component_adjacency.values())
                    use_linear_layout = has_edges and not self._edges_cross(
                        frame_lookup={frame.procedure_id: frame for frame in linear_frames},
                        adjacency=component_adjacency,
                    )
                else:
                    use_linear_layout = True
                    linear_frames = []
                if service_order and not use_linear_layout:
                    (
                        component_frames,
                        component_frame_lookup,
                        component_height,
                    ) = self._service_band_component_frames(
                        level_nodes=level_nodes,
                        assigned=assigned,
                        service_order=service_order,
                        order_index=order_index,
                        origin_x=origin_x,
                        origin_y=origin_y,
                        lane_span=lane_span,
                        node_size=node_size,
                        proc_gap_y=proc_gap_y,
                    )
                else:
                    if not service_order:
                        linear_frames = self._linear_component_frames(
                            level_nodes=level_nodes,
                            origin_x=origin_x,
                            origin_y=origin_y,
                            lane_span=lane_span,
                            node_size=node_size,
                            proc_gap_y=proc_gap_y,
                        )
                    for frame in linear_frames:
                        component_frames.append(frame)
                        component_frame_lookup[frame.procedure_id] = frame
                    if service_order and component_frames:
                        linear_zones = self._build_component_service_zones(
                            service_info_by_key=service_info_by_key,
                            proc_service_keys=proc_service_keys,
                            frame_lookup=component_frame_lookup,
                        )
                        if self._zones_have_non_nested_overlap(linear_zones):
                            (
                                component_frames,
                                component_frame_lookup,
                                component_height,
                            ) = self._service_band_component_frames(
                                level_nodes=level_nodes,
                                assigned=assigned,
                                service_order=service_order,
                                order_index=order_index,
                                origin_x=origin_x,
                                origin_y=origin_y,
                                lane_span=lane_span,
                                node_size=node_size,
                                proc_gap_y=proc_gap_y,
                            )
                    if component_frames:
                        max_bottom = max(
                            frame.origin.y + frame.size.height for frame in component_frames
                        )
                        component_height = max_bottom - origin_y

            if not zone_enabled:
                if is_service_graph:
                    level_heights: dict[int, float] = {}
                    level_widths: dict[int, float] = {}
                    for lvl, nodes in level_nodes.items():
                        if not nodes:
                            level_heights[lvl] = 0.0
                            level_widths[lvl] = base_service_node_size.width
                            continue
                        widths = [
                            service_node_sizes.get(proc_id, base_service_node_size).width
                            for proc_id in nodes
                        ]
                        heights = [
                            service_node_sizes.get(proc_id, base_service_node_size).height
                            for proc_id in nodes
                        ]
                        level_widths[lvl] = max(widths) if widths else base_service_node_size.width
                        total_height = sum(heights) + proc_gap_y * (len(heights) - 1)
                        level_heights[lvl] = total_height

                    component_height = max(level_heights.values() or [0.0])
                    level_offsets: dict[int, float] = {}
                    current_x = origin_x
                    for lvl in sorted(level_nodes):
                        level_offsets[lvl] = current_x
                        current_x += level_widths.get(lvl, base_service_node_size.width)
                        current_x += self.config.lane_gap

                    for lvl, nodes in level_nodes.items():
                        y = origin_y
                        level_width = level_widths.get(lvl, base_service_node_size.width)
                        x_base = level_offsets.get(lvl, origin_x)
                        for proc_id in nodes:
                            size = service_node_sizes.get(proc_id, base_service_node_size)
                            x = x_base + max(0.0, (level_width - size.width) / 2)
                            frame = FramePlacement(
                                procedure_id=proc_id,
                                origin=Point(x, y),
                                size=size,
                            )
                            component_frames.append(frame)
                            component_frame_lookup[proc_id] = frame
                            y += size.height + proc_gap_y
                    if component_frames:
                        max_bottom = max(
                            frame.origin.y + frame.size.height for frame in component_frames
                        )
                        component_height = max(component_height, max_bottom - origin_y)
                else:
                    level_heights_simple: dict[int, float] = {}
                    for lvl, nodes in level_nodes.items():
                        if not nodes:
                            level_heights_simple[lvl] = 0.0
                            continue
                        total = len(nodes) * node_size.height + proc_gap_y * (len(nodes) - 1)
                        level_heights_simple[lvl] = total

                    component_height = max(level_heights_simple.values() or [0.0])
                    for lvl, nodes in level_nodes.items():
                        y = origin_y
                        for proc_id in nodes:
                            frame = FramePlacement(
                                procedure_id=proc_id,
                                origin=Point(origin_x + lvl * lane_span, y),
                                size=node_size,
                            )
                            component_frames.append(frame)
                            component_frame_lookup[proc_id] = frame
                            y += node_size.height + proc_gap_y
                    if component_frames:
                        max_bottom = max(
                            frame.origin.y + frame.size.height for frame in component_frames
                        )
                        component_height = max(component_height, max_bottom - origin_y)

            component_frames = self._align_merge_chain_frames(
                component_frames=component_frames,
                procedure_meta=procedure_meta,
            )
            if component_frames:
                component_frame_lookup = {frame.procedure_id: frame for frame in component_frames}
                if zone_enabled:
                    zones_for_component = self._build_component_service_zones(
                        service_info_by_key=service_info_by_key,
                        proc_service_keys=proc_service_keys,
                        frame_lookup=component_frame_lookup,
                    )

            if zone_enabled and component_frames:
                zones_for_component = self._build_component_service_zones(
                    service_info_by_key=service_info_by_key,
                    proc_service_keys=proc_service_keys,
                    frame_lookup=component_frame_lookup,
                )
                if zones_for_component:
                    min_zone_top = min(zone.origin.y for zone in zones_for_component)
                    if min_zone_top < component_top:
                        shift = component_top - min_zone_top
                        component_frames = [
                            FramePlacement(
                                procedure_id=frame.procedure_id,
                                origin=Point(frame.origin.x, frame.origin.y + shift),
                                size=frame.size,
                            )
                            for frame in component_frames
                        ]
                        component_frame_lookup = {
                            frame.procedure_id: frame for frame in component_frames
                        }
                        zones_for_component = [
                            ServiceZonePlacement(
                                service_key=zone.service_key,
                                service_name=zone.service_name,
                                markup_type=zone.markup_type,
                                team_name=zone.team_name,
                                team_id=zone.team_id,
                                color=zone.color,
                                origin=Point(zone.origin.x, zone.origin.y + shift),
                                size=zone.size,
                                label_origin=Point(
                                    zone.label_origin.x, zone.label_origin.y + shift
                                ),
                                label_size=zone.label_size,
                                label_font_size=zone.label_font_size,
                                procedure_ids=zone.procedure_ids,
                            )
                            for zone in zones_for_component
                        ]

            scenario_total_height = 0.0
            scenario_extent_from_component_top = 0.0
            if component_frames and not is_service_graph:
                scenario_top = max(component_top, scenario_cursor_y)
                scenario = self._scenario_with_services(
                    component=component,
                    component_index=idx + 1,
                    component_count=len(components),
                    frame_lookup=component_frame_lookup,
                    procedure_map=procedure_map,
                    procedure_graph=document.procedure_graph,
                    layout_edges_by_proc=layout_edges_by_proc,
                    order_index=order_index,
                    procedure_meta=procedure_meta,
                    default_markup_type=default_markup_type,
                    component_top_y=scenario_top,
                )
                if scenario:
                    scenarios.append(scenario)
                    scenario_index_by_component[idx] = len(scenarios) - 1
                    procedures_bottom = (
                        scenario.procedures_origin.y + scenario.procedures_size.height
                    )
                    merge_bottom = procedures_bottom
                    if scenario.merge_origin and scenario.merge_size:
                        merge_bottom = scenario.merge_origin.y + scenario.merge_size.height
                    scenario_bottom = max(procedures_bottom, merge_bottom)
                    scenario_total_height = scenario_bottom - scenario.origin.y
                    scenario_extent_from_component_top = max(0.0, scenario_bottom - component_top)
                    scenario_cursor_y = scenario.origin.y + scenario_total_height + component_gap

            if component_frames:
                frames.extend(component_frames)
                frame_lookup.update(component_frame_lookup)
            zone_start = len(service_zones)
            if zones_for_component:
                service_zones.extend(zones_for_component)
            zone_range_by_component[idx] = (zone_start, len(service_zones))

            component_height = 0.0
            if component_frames:
                max_frame_bottom = max(
                    frame.origin.y + frame.size.height for frame in component_frames
                )
                component_height = max(component_height, max_frame_bottom - component_top)
            if zones_for_component:
                max_zone_bottom = max(
                    zone.origin.y + zone.size.height for zone in zones_for_component
                )
                component_height = max(component_height, max_zone_bottom - component_top)

            component_visual_height = component_height
            component_stack_height = max(component_height, scenario_extent_from_component_top)
            if idx < len(components) - 1:
                separator_ys.append(component_top + component_stack_height + component_gap / 2)
                origin_y = component_top + component_stack_height + component_gap
            else:
                origin_y = component_top + component_visual_height + proc_gap_y

        if frames and separator_ys:
            min_x = min(frame.origin.x for frame in frames)
            max_x = max(frame.origin.x + frame.size.width for frame in frames)
            x_start = min_x - self.config.separator_margin_x
            x_end = max_x + self.config.separator_margin_x
            separators = [
                SeparatorPlacement(start=Point(x_start, y), end=Point(x_end, y))
                for y in separator_ys
            ]

        if frames:
            (
                frames,
                separators,
                scenarios,
                service_zones,
                markup_type_columns,
            ) = self._arrange_components_by_markup_type_columns(
                components=components,
                adjacency=adjacency,
                order_index=order_index,
                procedure_map=procedure_map,
                procedure_meta=procedure_meta,
                default_markup_type=default_markup_type,
                frames=frames,
                scenarios=scenarios,
                service_zones=service_zones,
                component_index_by_proc=component_index_by_proc,
                scenario_index_by_component=scenario_index_by_component,
                zone_range_by_component=zone_range_by_component,
            )

        return LayoutPlan(
            frames=frames,
            blocks=[],
            markers=[],
            separators=separators,
            scenarios=scenarios,
            service_zones=service_zones,
            markup_type_columns=markup_type_columns,
        )

    def _procedure_node_size(self) -> Size:
        return self.config.block_size

    def _scenario_with_services(
        self,
        component: set[str],
        component_index: int,
        component_count: int,
        frame_lookup: Mapping[str, FramePlacement],
        procedure_map: Mapping[str, Procedure],
        procedure_graph: dict[str, list[str]],
        layout_edges_by_proc: Mapping[str, Mapping[str, list[str]]],
        order_index: dict[str, int],
        procedure_meta: Mapping[str, Mapping[str, object]] | None,
        default_markup_type: str,
        component_top_y: float,
    ) -> ScenarioPlacement | None:
        procedure_meta = procedure_meta or {}
        component_frames = [
            frame_lookup[proc_id] for proc_id in component if proc_id in frame_lookup
        ]
        if not component_frames:
            return None
        min_x = min(frame.origin.x for frame in component_frames)
        min_y = component_top_y
        title = "Граф" if component_count == 1 else f"Граф {component_index}"
        starts, ends, variants = self._component_stats(
            component, procedure_map, procedure_graph, layout_edges_by_proc
        )
        properties, cycle_text = self._component_graph_properties(
            component, procedure_graph, order_index
        )
        body_lines = [
            *properties,
            "",
            "",
            "Комплексность:",
            f"- Входы: {starts}",
            f"- Выходы: {ends}",
            f"- Ветвления: {variants}",
        ]
        max_width = self.config.scenario_width - (self.config.scenario_padding * 2)
        title_lines = self._wrap_lines([title], max_width, self.config.scenario_title_font_size)
        cycle_lines: list[str] = []
        cycle_height = 0.0
        if cycle_text:
            cycle_lines = self._wrap_lines(
                [cycle_text], max_width, self.config.scenario_cycle_font_size
            )
            cycle_height = len(cycle_lines) * self.config.scenario_cycle_font_size * 1.35
        body_lines_wrapped = self._wrap_lines(
            body_lines, max_width, self.config.scenario_body_font_size
        )
        title_text = "\n".join(title_lines)
        body_text = "\n".join(body_lines_wrapped)
        title_height = len(title_lines) * self.config.scenario_title_font_size * 1.35
        body_height = len(body_lines_wrapped) * self.config.scenario_body_font_size * 1.35
        gap_after_cycle = self.config.scenario_section_gap if cycle_text else 0.0
        scenario_height = max(
            self.config.scenario_min_height,
            title_height
            + cycle_height
            + gap_after_cycle
            + body_height
            + self.config.scenario_padding * 2,
        )
        scenario_width = self.config.scenario_width
        x_left = min_x - self.config.scenario_gap - scenario_width
        origin = Point(x=x_left, y=min_y)
        procedures_blocks, procedures_text, block_padding = self._component_service_blocks(
            component,
            procedure_meta,
            default_markup_type,
        )
        merge_blocks, merge_text, merge_block_padding, merge_node_numbers = (
            self._component_merge_blocks(
                component,
                procedure_map,
                procedure_meta,
                order_index,
                default_markup_type,
            )
        )
        procedures_content_height = sum(block.height for block in procedures_blocks)
        procedures_height = max(
            self.config.scenario_procedures_min_height,
            procedures_content_height + self.config.scenario_procedures_padding * 2,
        )
        procedures_origin = Point(
            x=x_left,
            y=origin.y + scenario_height + self.config.scenario_procedures_gap,
        )
        merge_height = 0.0
        merge_origin = None
        merge_size = None
        if merge_blocks:
            merge_content_height = sum(block.height for block in merge_blocks)
            merge_height = max(
                self.config.scenario_merge_min_height,
                merge_content_height + self.config.scenario_merge_padding * 2,
            )
            merge_origin = Point(
                x=x_left,
                y=procedures_origin.y + procedures_height + self.config.scenario_merge_gap,
            )
            merge_size = Size(scenario_width, merge_height)
        return ScenarioPlacement(
            origin=origin,
            size=Size(scenario_width, scenario_height),
            title_text=title_text,
            body_text=body_text,
            cycle_text=cycle_text,
            title_font_size=self.config.scenario_title_font_size,
            body_font_size=self.config.scenario_body_font_size,
            cycle_font_size=self.config.scenario_cycle_font_size,
            padding=self.config.scenario_padding,
            section_gap=self.config.scenario_section_gap,
            procedures_origin=procedures_origin,
            procedures_size=Size(scenario_width, procedures_height),
            procedures_text=procedures_text,
            procedures_font_size=self.config.scenario_procedures_font_size,
            procedures_padding=self.config.scenario_procedures_padding,
            procedures_blocks=tuple(procedures_blocks) if procedures_blocks else None,
            procedures_block_padding=block_padding,
            merge_origin=merge_origin,
            merge_size=merge_size,
            merge_text=merge_text,
            merge_font_size=self.config.scenario_merge_font_size if merge_blocks else None,
            merge_padding=self.config.scenario_merge_padding if merge_blocks else None,
            merge_blocks=tuple(merge_blocks) if merge_blocks else None,
            merge_block_padding=merge_block_padding if merge_blocks else None,
            merge_node_numbers=merge_node_numbers,
        )

    def _component_service_blocks(
        self,
        component: set[str],
        procedure_meta: Mapping[str, Mapping[str, object]],
        default_markup_type: str,
    ) -> tuple[list[ScenarioProceduresBlock], str, float]:
        groups, summary = self._component_service_groups(
            component,
            procedure_meta,
            default_markup_type,
        )
        header = "Разметки:"
        font_size = self.config.scenario_procedures_font_size
        line_height = font_size * 1.35
        team_font_size = font_size + 2.0
        team_line_height = team_font_size * 1.35
        header_gap = max(6.0, font_size * 0.6)
        team_gap = max(8.0, font_size * 0.8)
        service_gap = max(4.0, font_size * 0.4)
        service_padding = max(6.0, font_size * 0.4)
        content_width = self.config.scenario_width - (self.config.scenario_procedures_padding * 2)
        blocks: list[ScenarioProceduresBlock] = []

        header_lines = self._wrap_lines([header], content_width, font_size)
        header_text = "\n".join(header_lines)
        blocks.append(
            ScenarioProceduresBlock(
                kind="header",
                text=header_text,
                height=len(header_lines) * line_height,
                font_size=font_size,
            )
        )
        blocks.append(ScenarioProceduresBlock(kind="spacer", text="", height=header_gap))

        lines = [header, ""]
        if not groups:
            empty_text = "- (нет данных)"
            empty_lines = self._wrap_lines([empty_text], content_width, font_size)
            blocks.append(
                ScenarioProceduresBlock(
                    kind="summary",
                    text="\n".join(empty_lines),
                    height=len(empty_lines) * line_height,
                    font_size=font_size,
                )
            )
            lines.append(empty_text)
            return blocks, "\n".join(lines), service_padding

        for team_idx, (team_name, team_id, services) in enumerate(groups):
            team_lines = self._wrap_lines([team_name], content_width, team_font_size)
            blocks.append(
                ScenarioProceduresBlock(
                    kind="team",
                    text="\n".join(team_lines),
                    height=len(team_lines) * team_line_height,
                    font_size=team_font_size,
                    underline=True,
                    team_id=team_id,
                )
            )
            blocks.append(ScenarioProceduresBlock(kind="spacer", text="", height=service_gap))
            lines.append(team_name)
            for service_idx, (
                service_name,
                markup_type,
                service_color,
                finedog_unit_id,
            ) in enumerate(services):
                service_label = f"[{humanize_markup_type_for_brackets(markup_type)}] {service_name}"
                wrapped = self._wrap_lines(
                    [service_label],
                    content_width - service_padding * 2,
                    font_size,
                )
                blocks.append(
                    ScenarioProceduresBlock(
                        kind="service",
                        text="\n".join(wrapped),
                        height=len(wrapped) * line_height + service_padding * 2,
                        color=service_color,
                        font_size=font_size,
                        finedog_unit_id=finedog_unit_id,
                    )
                )
                lines.append(f"- {service_label}")
                if service_idx < len(services) - 1:
                    blocks.append(
                        ScenarioProceduresBlock(kind="spacer", text="", height=service_gap)
                    )
            if team_idx < len(groups) - 1:
                blocks.append(ScenarioProceduresBlock(kind="spacer", text="", height=team_gap))
                lines.append("")

        if summary:
            blocks.append(ScenarioProceduresBlock(kind="spacer", text="", height=team_gap))
            summary_lines = self._wrap_lines([summary], content_width, font_size)
            blocks.append(
                ScenarioProceduresBlock(
                    kind="summary",
                    text="\n".join(summary_lines),
                    height=len(summary_lines) * line_height,
                    font_size=font_size,
                )
            )
            lines.append("")
            lines.append(summary)

        if lines and not lines[-1]:
            lines.pop()
        return blocks, "\n".join(lines), service_padding

    def _align_merge_chain_frames(
        self,
        *,
        component_frames: list[FramePlacement],
        procedure_meta: Mapping[str, Mapping[str, object]],
    ) -> list[FramePlacement]:
        if len(component_frames) < 2:
            return component_frames

        frame_by_proc = {frame.procedure_id: frame for frame in component_frames}
        chain_groups: dict[str, list[str]] = {}
        for frame in component_frames:
            meta = procedure_meta.get(frame.procedure_id, {})
            if meta.get("is_intersection") is not True:
                continue
            group_id = meta.get("merge_chain_group_id")
            members_raw = meta.get("merge_chain_members")
            if not isinstance(group_id, str) or not isinstance(members_raw, list):
                continue
            members = [
                member
                for member in members_raw
                if isinstance(member, str) and member in frame_by_proc
            ]
            unique_members = list(dict.fromkeys(members))
            if len(unique_members) < 2:
                continue
            chain_groups[group_id] = unique_members
        if not chain_groups:
            return component_frames

        group_member_ids = {proc_id for members in chain_groups.values() for proc_id in members}
        occupied_rects: list[tuple[float, float, float, float]] = []
        for frame in component_frames:
            if frame.procedure_id in group_member_ids:
                continue
            occupied_rects.append(self._frame_rect(frame))

        updated = dict(frame_by_proc)
        horizontal_gap = max(20.0, self.config.gap_y * 0.5)
        vertical_step = max(30.0, self.config.gap_y * 0.8)
        vertical_padding = max(6.0, self.config.gap_y * 0.2)
        ordered_groups = sorted(
            chain_groups.values(),
            key=lambda members: min(
                frame_by_proc[proc_id].origin.y for proc_id in members if proc_id in frame_by_proc
            ),
        )
        for members in ordered_groups:
            member_frames = [updated[proc_id] for proc_id in members if proc_id in updated]
            if len(member_frames) < 2:
                continue

            member_frames.sort(
                key=lambda frame: (
                    frame.origin.x,
                    frame.origin.y,
                    frame.procedure_id,
                )
            )
            base_x = min(frame.origin.x for frame in member_frames)
            base_y = min(frame.origin.y for frame in member_frames)
            max_height = max(frame.size.height for frame in member_frames)

            planned: list[FramePlacement] = []
            next_x = base_x
            for frame in member_frames:
                aligned_y = base_y + (max_height - frame.size.height) / 2
                planned.append(
                    FramePlacement(
                        procedure_id=frame.procedure_id,
                        origin=Point(next_x, aligned_y),
                        size=frame.size,
                    )
                )
                next_x += frame.size.width + horizontal_gap

            attempts = 0
            while attempts < 20:
                rects = [self._frame_rect(item) for item in planned]
                if not self._chain_rects_overlap_any(
                    rects,
                    occupied_rects,
                    padding=vertical_padding,
                ):
                    break
                planned = [
                    FramePlacement(
                        procedure_id=item.procedure_id,
                        origin=Point(item.origin.x, item.origin.y + vertical_step),
                        size=item.size,
                    )
                    for item in planned
                ]
                attempts += 1

            for item in planned:
                updated[item.procedure_id] = item
                occupied_rects.append(self._frame_rect(item))

        aligned_frames = [updated.get(frame.procedure_id, frame) for frame in component_frames]
        return self._normalize_component_row_spacing(aligned_frames)

    def _frame_rect(self, frame: FramePlacement) -> tuple[float, float, float, float]:
        return (
            frame.origin.x,
            frame.origin.y,
            frame.origin.x + frame.size.width,
            frame.origin.y + frame.size.height,
        )

    def _chain_rects_overlap_any(
        self,
        rects: list[tuple[float, float, float, float]],
        occupied: list[tuple[float, float, float, float]],
        *,
        padding: float,
    ) -> bool:
        for left in rects:
            for right in occupied:
                if self._chain_rects_overlap(left, right, padding=padding):
                    return True
        return False

    def _chain_rects_overlap(
        self,
        left: tuple[float, float, float, float],
        right: tuple[float, float, float, float],
        *,
        padding: float,
    ) -> bool:
        left_x1, left_y1, left_x2, left_y2 = left
        right_x1, right_y1, right_x2, right_y2 = right
        return not (
            left_x2 + padding <= right_x1
            or right_x2 + padding <= left_x1
            or left_y2 + padding <= right_y1
            or right_y2 + padding <= left_y1
        )

    def _normalize_component_row_spacing(
        self,
        frames: list[FramePlacement],
    ) -> list[FramePlacement]:
        if len(frames) < 2:
            return frames

        row_tolerance = max(10.0, self.config.gap_y * 0.3)
        sorted_frames = sorted(frames, key=lambda frame: (frame.origin.y, frame.origin.x))
        rows: list[list[FramePlacement]] = []
        row_tops: list[float] = []
        for frame in sorted_frames:
            frame_y = frame.origin.y
            row_index = -1
            for idx, top in enumerate(row_tops):
                if abs(frame_y - top) <= row_tolerance:
                    row_index = idx
                    break
            if row_index < 0:
                rows.append([frame])
                row_tops.append(frame_y)
                continue
            rows[row_index].append(frame)
            top = min(item.origin.y for item in rows[row_index])
            row_tops[row_index] = top

        if len(rows) <= 1:
            return frames

        row_specs = sorted(
            (
                min(item.origin.y for item in row),
                max(item.size.height for item in row),
                row,
            )
            for row in rows
        )
        top_anchor = row_specs[0][0]
        next_top = top_anchor
        remapped: dict[str, FramePlacement] = {}
        for original_top, row_height, row in row_specs:
            delta_y = next_top - original_top
            for frame in row:
                remapped[frame.procedure_id] = FramePlacement(
                    procedure_id=frame.procedure_id,
                    origin=Point(frame.origin.x, frame.origin.y + delta_y),
                    size=frame.size,
                )
            next_top += row_height + self.config.gap_y

        return [remapped.get(frame.procedure_id, frame) for frame in frames]

    def _component_merge_blocks(
        self,
        component: set[str],
        procedure_map: Mapping[str, Procedure],
        procedure_meta: Mapping[str, Mapping[str, object]],
        order_index: Mapping[str, int],
        default_markup_type: str,
    ) -> tuple[
        list[ScenarioProceduresBlock], str | None, float | None, dict[str, list[int]] | None
    ]:
        merge_ids = [
            proc_id
            for proc_id in component
            if procedure_meta.get(proc_id, {}).get("is_intersection") is True
        ]
        if not merge_ids:
            return [], None, None, None

        merge_ids.sort(key=lambda proc_id: order_index.get(proc_id, 0))
        header = "Узлы слияния:"
        font_size = self.config.scenario_merge_font_size
        line_height = font_size * 1.35
        header_gap = max(6.0, font_size * 0.4)
        group_gap = max(8.0, font_size * 0.5)
        item_padding = 0.0
        content_width = self.config.scenario_width - (self.config.scenario_merge_padding * 2)
        blocks: list[ScenarioProceduresBlock] = []

        header_lines = self._wrap_lines([header], content_width, font_size)
        blocks.append(
            ScenarioProceduresBlock(
                kind="header",
                text="\n".join(header_lines),
                height=len(header_lines) * line_height,
                font_size=font_size,
                underline=False,
            )
        )
        if header_gap:
            blocks.append(ScenarioProceduresBlock(kind="spacer", text="", height=header_gap))

        lines = [header]
        groups: dict[tuple[tuple[str, str, str], ...], _MergeGroup] = {}
        for proc_id in merge_ids:
            meta = procedure_meta.get(proc_id, {})
            entries = self._procedure_merge_entries(meta, default_markup_type)
            service_tokens: list[tuple[str, str, str]] = []
            for entry in entries:
                team_name = str(entry.get("team_name") or "Unknown team")
                markup_type = str(entry.get("markup_type") or default_markup_type)
                service_name = str(entry.get("service_name") or "Unknown service")
                service_tokens.append((team_name, markup_type, service_name))
            if not service_tokens:
                service_tokens.append(("Unknown team", "unknown", "Unknown service"))
            unique_tokens = sorted(
                set(service_tokens),
                key=lambda item: (item[0].lower(), item[1].lower(), item[2].lower()),
            )
            label_parts = [
                f"[{team}] [{humanize_markup_type_for_brackets(markup_type)}] {service}"
                for team, markup_type, service in unique_tokens
            ]
            label = " x ".join(label_parts)
            key = tuple(unique_tokens)
            group = groups.setdefault(key, _MergeGroup(label=label, proc_ids=[]))
            chain_group_id = meta.get("merge_chain_group_id")
            chain_members = meta.get("merge_chain_members")
            group_node_ids: list[str]
            if isinstance(chain_group_id, str) and isinstance(chain_members, list):
                group_node_ids = [
                    member_id
                    for member_id in chain_members
                    if isinstance(member_id, str) and member_id in merge_ids
                ]
                group_node_ids = list(dict.fromkeys(group_node_ids))
                if len(group_node_ids) < 2:
                    continue
            else:
                group_node_ids = [proc_id]
            group.proc_ids.append("|".join(group_node_ids))

        ordered_groups: list[tuple[int, str, list[list[str]]]] = []
        for group in groups.values():
            node_proc_ids: list[list[str]] = []
            seen: set[str] = set()
            for token in group.proc_ids:
                members = [proc_id for proc_id in token.split("|") if proc_id]
                if not members:
                    continue
                canonical = "|".join(sorted(members))
                if canonical in seen:
                    continue
                seen.add(canonical)
                members.sort(key=lambda proc_id: (order_index.get(proc_id, 0), proc_id))
                node_proc_ids.append(members)
            node_proc_ids.sort(
                key=lambda members: min(order_index.get(proc_id, 0) for proc_id in members)
            )
            if not node_proc_ids:
                continue
            order = min(
                min(order_index.get(proc_id, 0) for proc_id in members) for members in node_proc_ids
            )
            label = group.label
            ordered_groups.append((order, label, node_proc_ids))
        ordered_groups.sort(key=lambda item: (item[0], item[1].lower()))

        merge_numbers: dict[str, list[int]] = {}
        merge_index = 1
        multiple_groups = len(ordered_groups) > 1
        for idx, (_, label, group_nodes) in enumerate(ordered_groups):
            if idx > 0:
                blocks.append(ScenarioProceduresBlock(kind="spacer", text="", height=group_gap))
                lines.append("")
            header_line = f"> {label}:"
            header_lines = self._wrap_lines(
                [header_line], content_width - item_padding * 2, font_size
            )
            blocks.append(
                ScenarioProceduresBlock(
                    kind="merge_group",
                    text="\n".join(header_lines),
                    height=len(header_lines) * line_height + item_padding * 2,
                    font_size=font_size,
                )
            )
            lines.append(header_line)
            item_lines: list[str] = []
            for node_members in group_nodes:
                proc_names: list[str] = []
                for proc_id in node_members:
                    proc = procedure_map.get(proc_id)
                    proc_name = proc.procedure_name if proc and proc.procedure_name else proc_id
                    proc_names.append(proc_name)
                    merge_numbers.setdefault(proc_id, []).append(merge_index)
                if len(proc_names) <= 1:
                    node_text = proc_names[0] if proc_names else "Unknown procedure"
                else:
                    node_text = " + ".join(proc_names)
                item_lines.append(f"({merge_index}) {node_text}")
                merge_index += 1
            wrapped = self._wrap_lines(item_lines, content_width - item_padding * 2, font_size)
            blocks.append(
                ScenarioProceduresBlock(
                    kind="merge_item",
                    text="\n".join(wrapped),
                    height=len(wrapped) * line_height + item_padding * 2,
                    font_size=font_size,
                    underline=multiple_groups and idx < len(ordered_groups) - 1,
                )
            )
            lines.extend(item_lines)

        if lines and not lines[-1]:
            lines.pop()
        return blocks, "\n".join(lines), item_padding, merge_numbers

    def _component_service_groups(
        self,
        component: set[str],
        procedure_meta: Mapping[str, Mapping[str, object]],
        default_markup_type: str,
    ) -> tuple[
        list[tuple[str, str | int | None, list[tuple[str, str, str, str | None]]]],
        str | None,
    ]:
        team_services: dict[
            tuple[str, str | int | None],
            dict[tuple[str, str], dict[str, object]],
        ] = {}
        for proc_id in sorted(component):
            meta = procedure_meta.get(proc_id, {})
            services = meta.get("services")
            if isinstance(services, list) and services:
                for service in services:
                    if not isinstance(service, Mapping):
                        continue
                    team_name = str(service.get("team_name") or "Unknown team")
                    team_id = service.get("team_id")
                    service_name = str(service.get("service_name") or "Unknown service")
                    markup_type = str(service.get("markup_type") or default_markup_type)
                    color = service.get("service_color")
                    finedog_unit_id = service.get("finedog_unit_id")
                    normalized_unit_id = normalize_finedog_unit_id(finedog_unit_id)
                    if not isinstance(color, str):
                        color = meta.get("procedure_color")
                    team_key = (team_name, team_id if isinstance(team_id, str | int) else None)
                    service_entry = team_services.setdefault(team_key, {})
                    service_key = (service_name, markup_type)
                    if service_key not in service_entry:
                        service_entry[service_key] = {
                            "color": color if isinstance(color, str) else "#e9f0fb",
                            "finedog_unit_id": normalized_unit_id,
                        }
                    else:
                        existing = service_entry[service_key]
                        if (
                            existing.get("finedog_unit_id") is None
                            and normalized_unit_id is not None
                        ):
                            existing["finedog_unit_id"] = normalized_unit_id
            else:
                team_id = meta.get("team_id")
                team_name = str(meta.get("team_name") or team_id or "Unknown team")
                service_name = str(meta.get("service_name") or "Unknown service")
                markup_type = str(meta.get("markup_type") or default_markup_type)
                color = meta.get("procedure_color")
                team_key = (team_name, team_id if isinstance(team_id, str | int) else None)
                service_entry = team_services.setdefault(team_key, {})
                service_key = (service_name, markup_type)
                if service_key not in service_entry:
                    normalized_unit_id = normalize_finedog_unit_id(meta.get("finedog_unit_id"))
                    service_entry[service_key] = {
                        "color": color if isinstance(color, str) else "#e9f0fb",
                        "finedog_unit_id": normalized_unit_id,
                    }

        if not team_services:
            return [], None

        teams_sorted = sorted(team_services.keys(), key=lambda item: item[0].lower())
        groups: list[tuple[str, str | int | None, list[tuple[str, str, str, str | None]]]] = []
        for team_name, team_id in teams_sorted:
            services = team_services[(team_name, team_id)]
            sorted_services: list[tuple[str, str, str, str | None]] = []
            for (service_name, markup_type), payload in sorted(
                services.items(),
                key=lambda item: (item[0][0].lower(), item[0][1].lower()),
            ):
                color = payload.get("color")
                unit_id = payload.get("finedog_unit_id")
                sorted_services.append(
                    (
                        service_name,
                        markup_type,
                        color if isinstance(color, str) else "#e9f0fb",
                        normalize_finedog_unit_id(unit_id),
                    )
                )
            groups.append((team_name, team_id, sorted_services))
        return groups, None

    def _service_zone_key(
        self,
        team_name: str,
        team_id: str | int | None,
        markup_type: str,
        service_name: str,
    ) -> str:
        team_token = str(team_id) if team_id is not None else team_name
        return f"{team_token}::{markup_type}::{service_name}"

    def _procedure_service_entries(
        self,
        meta: Mapping[str, object],
        default_markup_type: str,
    ) -> list[Mapping[str, object]]:
        services = meta.get("services")
        if isinstance(services, list) and services:
            entries = [service for service in services if isinstance(service, Mapping)]
            if entries:
                return entries
        return [
            {
                "team_name": meta.get("team_name") or meta.get("team_id") or "Unknown team",
                "team_id": meta.get("team_id"),
                "service_name": meta.get("service_name") or "Unknown service",
                "markup_type": meta.get("markup_type") or default_markup_type,
                "service_color": meta.get("procedure_color"),
            }
        ]

    def _procedure_merge_entries(
        self,
        meta: Mapping[str, object],
        default_markup_type: str,
    ) -> list[Mapping[str, object]]:
        merge_services = meta.get("merge_services")
        if isinstance(merge_services, list) and merge_services:
            entries = [service for service in merge_services if isinstance(service, Mapping)]
            if entries:
                return entries
        return self._procedure_service_entries(meta, default_markup_type)

    def _normalize_service_entry(
        self,
        meta: Mapping[str, object],
        entry: Mapping[str, object],
        default_markup_type: str,
    ) -> _ServiceInfo:
        team_name = str(entry.get("team_name") or "Unknown team")
        team_id = entry.get("team_id")
        if not isinstance(team_id, str | int):
            team_id = None
        service_name = str(entry.get("service_name") or "Unknown service")
        markup_type = str(
            entry.get("markup_type") or meta.get("markup_type") or default_markup_type
        )
        color = entry.get("service_color")
        if not isinstance(color, str) or not color:
            color = meta.get("procedure_color")
        if not isinstance(color, str) or not color:
            color = "#e9f0fb"
        service_key = self._service_zone_key(team_name, team_id, markup_type, service_name)
        return _ServiceInfo(
            service_key=service_key,
            service_name=service_name,
            markup_type=markup_type,
            team_name=team_name,
            team_id=team_id,
            color=color,
        )

    def _component_service_info(
        self,
        component: set[str],
        procedure_meta: Mapping[str, Mapping[str, object]],
        default_markup_type: str,
    ) -> tuple[dict[str, _ServiceInfo], dict[str, list[str]]]:
        service_info_by_key: dict[str, _ServiceInfo] = {}
        proc_service_keys: dict[str, list[str]] = {}
        for proc_id in component:
            meta = procedure_meta.get(proc_id, {})
            entries = self._procedure_service_entries(meta, default_markup_type)
            keys: list[str] = []
            for entry in entries:
                info = self._normalize_service_entry(meta, entry, default_markup_type)
                if info.service_key not in keys:
                    keys.append(info.service_key)
                if info.service_key not in service_info_by_key:
                    service_info_by_key[info.service_key] = info
            if keys:
                proc_service_keys[proc_id] = keys
        return service_info_by_key, proc_service_keys

    def _sorted_service_infos(
        self,
        service_info_by_key: Mapping[str, _ServiceInfo],
    ) -> list[_ServiceInfo]:
        return sorted(
            service_info_by_key.values(),
            key=lambda info: (
                info.team_name.lower(),
                info.service_name.lower(),
                str(info.team_id or ""),
            ),
        )

    def _assign_component_services(
        self,
        proc_service_keys: Mapping[str, list[str]],
        service_order: list[_ServiceInfo],
    ) -> tuple[dict[str, str], dict[str, int]]:
        counts: dict[str, int] = {info.service_key: 0 for info in service_order}
        assigned: dict[str, str] = {}
        deferred: list[str] = []
        for proc_id, keys in proc_service_keys.items():
            if len(keys) == 1:
                assigned[proc_id] = keys[0]
                counts[keys[0]] = counts.get(keys[0], 0) + 1
            elif keys:
                deferred.append(proc_id)

        order_index = {info.service_key: idx for idx, info in enumerate(service_order)}
        for proc_id in deferred:
            keys = proc_service_keys.get(proc_id, [])
            if not keys:
                continue
            chosen = min(
                keys,
                key=lambda key: (counts.get(key, 0), order_index.get(key, 0)),
            )
            assigned[proc_id] = chosen
            counts[chosen] = counts.get(chosen, 0) + 1
        return assigned, counts

    def _linear_component_frames(
        self,
        level_nodes: Mapping[int, list[str]],
        origin_x: float,
        origin_y: float,
        lane_span: float,
        node_size: Size,
        proc_gap_y: float,
    ) -> list[FramePlacement]:
        frames: list[FramePlacement] = []
        for lvl, nodes in level_nodes.items():
            y = origin_y
            for proc_id in nodes:
                frames.append(
                    FramePlacement(
                        procedure_id=proc_id,
                        origin=Point(origin_x + lvl * lane_span, y),
                        size=node_size,
                    )
                )
                y += node_size.height + proc_gap_y
        return frames

    def _build_component_service_zones(
        self,
        service_info_by_key: Mapping[str, _ServiceInfo],
        proc_service_keys: Mapping[str, list[str]],
        frame_lookup: Mapping[str, FramePlacement],
    ) -> list[ServiceZonePlacement]:
        if not service_info_by_key:
            return []
        service_order = self._sorted_service_infos(service_info_by_key)
        padding_x = self.config.service_zone_padding_x
        padding_y = self.config.service_zone_padding_y
        label_font_size = self.config.service_zone_label_font_size
        label_gap = self.config.service_zone_label_gap + max(10.0, label_font_size * 0.5)
        label_padding_y = max(6.0, label_font_size * 0.25)
        drafts: dict[str, _ZoneDraft] = {}
        procedures_by_service: dict[str, list[str]] = {}
        for proc_id, keys in proc_service_keys.items():
            for key in keys:
                procedures_by_service.setdefault(key, []).append(proc_id)

        for info in service_order:
            proc_ids = sorted(set(procedures_by_service.get(info.service_key, [])))
            if not proc_ids:
                continue
            service_frames = [
                frame_lookup[proc_id] for proc_id in proc_ids if proc_id in frame_lookup
            ]
            if not service_frames:
                continue
            min_x = min(frame.origin.x for frame in service_frames)
            max_x = max(frame.origin.x + frame.size.width for frame in service_frames)
            min_y = min(frame.origin.y for frame in service_frames)
            max_y = max(frame.origin.y + frame.size.height for frame in service_frames)
            label_width = max_x - min_x
            label_lines = self._wrap_lines(
                [info.service_name], label_width if label_width > 0 else 1.0, label_font_size
            )
            label_height = len(label_lines) * label_font_size * 1.35 + label_padding_y * 2
            top_padding = padding_y + label_height + label_gap
            origin = Point(min_x - padding_x, min_y - top_padding)
            size = Size(
                max_x - min_x + padding_x * 2,
                max_y - min_y + top_padding + padding_y,
            )
            label_origin = Point(
                origin.x + padding_x,
                origin.y + padding_y,
            )
            label_size = Size(size.width - padding_x * 2, label_height)
            drafts[info.service_key] = _ZoneDraft(
                info=info,
                procedure_ids=tuple(proc_ids),
                origin=origin,
                size=size,
                label_origin=label_origin,
                label_size=label_size,
            )

        if not drafts:
            return []

        contains: dict[str, list[str]] = {key: [] for key in drafts}
        draft_items = list(drafts.items())
        for idx, (outer_key, outer) in enumerate(draft_items):
            for inner_key, inner in draft_items[idx + 1 :]:
                if self._rect_contains(outer.origin, outer.size, inner.origin, inner.size):
                    contains[outer_key].append(inner_key)
                elif self._rect_contains(inner.origin, inner.size, outer.origin, outer.size):
                    contains[inner_key].append(outer_key)

        depth_cache: dict[str, int] = {}
        visiting: set[str] = set()

        def zone_depth(key: str) -> int:
            if key in depth_cache:
                return depth_cache[key]
            if key in visiting:
                return 0
            visiting.add(key)
            depth = 0
            for child_key in contains.get(key, []):
                depth = max(depth, zone_depth(child_key) + 1)
            visiting.remove(key)
            depth_cache[key] = depth
            return depth

        border_gap_x = max(12.0, padding_x * 0.35)
        border_gap_y = max(12.0, padding_y * 0.35)
        zones: list[ServiceZonePlacement] = []

        for info in service_order:
            draft = drafts.get(info.service_key)
            if not draft:
                continue
            depth = zone_depth(info.service_key)
            if depth > 0:
                label_step = draft.label_size.height + label_gap
                extra_left = border_gap_x * depth
                extra_right = border_gap_x * depth
                extra_bottom = border_gap_y * depth
                extra_top = (border_gap_y + label_step) * depth
            else:
                extra_left = 0.0
                extra_right = 0.0
                extra_bottom = 0.0
                extra_top = 0.0

            origin = Point(draft.origin.x - extra_left, draft.origin.y - extra_top)
            size = Size(
                draft.size.width + extra_left + extra_right,
                draft.size.height + extra_top + extra_bottom,
            )
            label_origin = Point(
                draft.label_origin.x - extra_left,
                draft.label_origin.y - extra_top,
            )
            label_size = Size(max(1.0, size.width - padding_x * 2), draft.label_size.height)

            zones.append(
                ServiceZonePlacement(
                    service_key=info.service_key,
                    service_name=info.service_name,
                    markup_type=info.markup_type,
                    team_name=info.team_name,
                    team_id=info.team_id,
                    color=info.color,
                    origin=origin,
                    size=size,
                    label_origin=label_origin,
                    label_size=label_size,
                    label_font_size=label_font_size,
                    procedure_ids=draft.procedure_ids,
                )
            )
        return zones

    def _service_band_component_frames(
        self,
        level_nodes: Mapping[int, list[str]],
        assigned: Mapping[str, str],
        service_order: list[_ServiceInfo],
        order_index: Mapping[str, int],
        origin_x: float,
        origin_y: float,
        lane_span: float,
        node_size: Size,
        proc_gap_y: float,
    ) -> tuple[list[FramePlacement], dict[str, FramePlacement], float]:
        label_height = self.config.service_zone_label_font_size * 1.35
        top_padding = (
            self.config.service_zone_padding_y + label_height + self.config.service_zone_label_gap
        )
        bottom_padding = self.config.service_zone_padding_y

        max_counts: dict[str, int] = {info.service_key: 0 for info in service_order}
        for nodes in level_nodes.values():
            counts: dict[str, int] = {}
            for proc_id in nodes:
                key = assigned.get(proc_id)
                if not key:
                    continue
                counts[key] = counts.get(key, 0) + 1
            for key, count in counts.items():
                if count > max_counts.get(key, 0):
                    max_counts[key] = count

        bands: list[_ServiceBand] = []
        current_y = origin_y
        for info in service_order:
            key = info.service_key
            count = max_counts.get(key, 0)
            if count <= 0:
                continue
            nodes_height = count * node_size.height + proc_gap_y * (count - 1)
            band_height = nodes_height + top_padding + bottom_padding
            bands.append(_ServiceBand(service=info, start_y=current_y, height=band_height))
            current_y += band_height + proc_gap_y

        component_height = 0.0
        if bands:
            component_height = current_y - origin_y - proc_gap_y
        band_lookup = {band.service.service_key: band for band in bands}

        frames: list[FramePlacement] = []
        frame_lookup: dict[str, FramePlacement] = {}
        for lvl, nodes in level_nodes.items():
            by_service: dict[str, list[str]] = {}
            for proc_id in nodes:
                key = assigned.get(proc_id)
                if not key:
                    continue
                by_service.setdefault(key, []).append(proc_id)
            for key, proc_ids in by_service.items():
                proc_ids.sort(key=lambda proc_id: order_index.get(proc_id, 0))
                band = band_lookup.get(key)
                if not band:
                    continue
                start_y = band.start_y + top_padding
                for offset, proc_id in enumerate(proc_ids):
                    frame = FramePlacement(
                        procedure_id=proc_id,
                        origin=Point(
                            origin_x + lvl * lane_span,
                            start_y + offset * (node_size.height + proc_gap_y),
                        ),
                        size=node_size,
                    )
                    frames.append(frame)
                    frame_lookup[proc_id] = frame
        return frames, frame_lookup, component_height

    def _arrange_components_by_markup_type_columns(
        self,
        *,
        components: list[set[str]],
        adjacency: Mapping[str, list[str]],
        order_index: Mapping[str, int],
        procedure_map: Mapping[str, Procedure],
        procedure_meta: Mapping[str, Mapping[str, object]],
        default_markup_type: str,
        frames: list[FramePlacement],
        scenarios: list[ScenarioPlacement],
        service_zones: list[ServiceZonePlacement],
        component_index_by_proc: Mapping[str, int],
        scenario_index_by_component: Mapping[int, int],
        zone_range_by_component: Mapping[int, tuple[int, int]],
    ) -> tuple[
        list[FramePlacement],
        list[SeparatorPlacement],
        list[ScenarioPlacement],
        list[ServiceZonePlacement],
        list[MarkupTypeColumnPlacement],
    ]:
        frame_by_proc = {frame.procedure_id: frame for frame in frames}
        zones_by_component: dict[int, list[ServiceZonePlacement]] = defaultdict(list)
        for component_idx, (start, end) in zone_range_by_component.items():
            zones_by_component[component_idx].extend(service_zones[start:end])

        component_infos: list[_ComponentPlacementInfo] = []
        for component_idx, component in enumerate(components):
            if not component:
                continue
            proc_ids = tuple(
                sorted(component, key=lambda proc_id: (order_index.get(proc_id, 0), proc_id))
            )
            scenario: ScenarioPlacement | None = None
            scenario_idx = scenario_index_by_component.get(component_idx)
            if isinstance(scenario_idx, int) and 0 <= scenario_idx < len(scenarios):
                scenario = scenarios[scenario_idx]
            bounds = self._component_bounds(
                procedure_ids=proc_ids,
                frame_by_proc=frame_by_proc,
                zones=zones_by_component.get(component_idx, []),
                scenario=scenario,
            )
            if bounds is None:
                continue
            (
                column_markup_type,
                is_merged_markup_types,
            ) = self._component_column_markup_type(
                procedure_ids=proc_ids,
                procedure_meta=procedure_meta,
                default_markup_type=default_markup_type,
            )
            sort_key = self._component_sort_key(
                procedure_ids=proc_ids,
                procedure_map=procedure_map,
                procedure_meta=procedure_meta,
                default_markup_type=default_markup_type,
            )
            component_infos.append(
                _ComponentPlacementInfo(
                    component_index=component_idx,
                    procedure_ids=proc_ids,
                    markup_type=column_markup_type,
                    is_merged_markup_types=is_merged_markup_types,
                    primary_service_name=str(sort_key[0]),
                    sort_key=sort_key,
                    min_x=bounds[0],
                    min_y=bounds[1],
                    max_x=bounds[2],
                    max_y=bounds[3],
                )
            )

        if not component_infos:
            return frames, [], scenarios, service_zones, []

        info_by_component = {info.component_index: info for info in component_infos}
        column_components: dict[str, list[_ComponentPlacementInfo]] = defaultdict(list)
        for info in component_infos:
            column_components[info.markup_type].append(info)
        for infos in column_components.values():
            infos.sort(key=lambda info: info.sort_key)

        ordered_columns = sorted(column_components, key=self._markup_type_column_sort_key)
        column_position = {markup_type: idx for idx, markup_type in enumerate(ordered_columns)}
        component_column_index: dict[int, int] = {}
        for column_idx, markup_type in enumerate(ordered_columns):
            for info in column_components[markup_type]:
                component_column_index[info.component_index] = column_idx

        cross_component_links: dict[int, set[int]] = defaultdict(set)
        for source_proc, targets in adjacency.items():
            source_idx = component_index_by_proc.get(source_proc)
            if source_idx is None:
                continue
            for target_proc in targets:
                target_idx = component_index_by_proc.get(target_proc)
                if target_idx is None or target_idx == source_idx:
                    continue
                cross_component_links[target_idx].add(source_idx)
                cross_component_links[source_idx].add(target_idx)

        component_gap = max(self.config.gap_y, self.config.separator_padding * 2)
        column_gap = max(self.config.lane_gap, self.config.separator_padding)
        column_widths: dict[str, float] = {
            markup_type: max((info.width for info in infos), default=0.0)
            for markup_type, infos in column_components.items()
        }

        column_start_x: dict[str, float] = {}
        x_cursor = 0.0
        for markup_type in ordered_columns:
            column_start_x[markup_type] = x_cursor
            x_cursor += column_widths.get(markup_type, 0.0) + column_gap

        desired_center_by_component: dict[int, float] = {}
        placed_center_y: dict[int, float] = {}
        new_bounds_by_component: dict[int, tuple[float, float, float, float]] = {}
        ordered_component_ids_by_column: dict[str, list[int]] = {}
        for markup_type in ordered_columns:
            infos = column_components.get(markup_type, [])
            if not infos:
                continue
            column_idx = column_position.get(markup_type, -1)
            for info in infos:
                neighbor_centers = [
                    placed_center_y[neighbor_idx]
                    for neighbor_idx in cross_component_links.get(info.component_index, set())
                    if neighbor_idx in placed_center_y
                    and component_column_index.get(neighbor_idx, -1) < column_idx
                ]
                if neighbor_centers:
                    desired_center_by_component[info.component_index] = sum(neighbor_centers) / len(
                        neighbor_centers
                    )

            base_centers: dict[int, float] = {}
            cursor = 0.0
            for info in infos:
                base_centers[info.component_index] = cursor + info.height / 2
                cursor += info.height + component_gap

            desired_offsets = [
                desired_center_by_component[info.component_index]
                - base_centers.get(info.component_index, info.height / 2)
                for info in infos
                if info.component_index in desired_center_by_component
            ]
            start_offset = max(0.0, self._median(desired_offsets)) if desired_offsets else 0.0
            current_y = start_offset
            column_component_ids: list[int] = []
            for info in infos:
                desired_center = desired_center_by_component.get(info.component_index)
                if desired_center is not None:
                    desired_top = desired_center - info.height / 2
                    if desired_top > current_y:
                        current_y = desired_top
                new_min_x = column_start_x.get(markup_type, 0.0)
                new_min_y = current_y
                new_max_x = new_min_x + info.width
                new_max_y = new_min_y + info.height
                new_bounds_by_component[info.component_index] = (
                    new_min_x,
                    new_min_y,
                    new_max_x,
                    new_max_y,
                )
                center_y = new_min_y + info.height / 2
                placed_center_y[info.component_index] = center_y
                column_component_ids.append(info.component_index)
                current_y = new_max_y + component_gap
            ordered_component_ids_by_column[markup_type] = column_component_ids

        component_shift: dict[int, tuple[float, float]] = {}
        for component_idx, (new_min_x, new_min_y, _, _) in new_bounds_by_component.items():
            info = info_by_component[component_idx]
            component_shift[component_idx] = (
                new_min_x - info.min_x,
                new_min_y - info.min_y,
            )

        shifted_frames: list[FramePlacement] = []
        for frame in frames:
            frame_component_idx = component_index_by_proc.get(frame.procedure_id)
            shift = (
                component_shift.get(frame_component_idx)
                if frame_component_idx is not None
                else None
            )
            if shift is None:
                shifted_frames.append(frame)
                continue
            dx, dy = shift
            shifted_frames.append(
                FramePlacement(
                    procedure_id=frame.procedure_id,
                    origin=Point(frame.origin.x + dx, frame.origin.y + dy),
                    size=frame.size,
                )
            )

        shifted_scenarios = list(scenarios)
        for component_idx, scenario_idx in scenario_index_by_component.items():
            shift = component_shift.get(component_idx)
            if shift is None:
                continue
            if not (0 <= scenario_idx < len(shifted_scenarios)):
                continue
            shifted_scenarios[scenario_idx] = self._shift_scenario(
                shifted_scenarios[scenario_idx],
                shift[0],
                shift[1],
            )

        shifted_service_zones = list(service_zones)
        for component_idx, (start, end) in zone_range_by_component.items():
            shift = component_shift.get(component_idx)
            if shift is None:
                continue
            dx, dy = shift
            for zone_idx in range(start, min(end, len(shifted_service_zones))):
                shifted_service_zones[zone_idx] = self._shift_service_zone(
                    shifted_service_zones[zone_idx], dx, dy
                )

        shifted_frame_by_proc = {frame.procedure_id: frame for frame in shifted_frames}
        separators: list[SeparatorPlacement] = []
        for markup_type in ordered_columns:
            ordered_component_ids = ordered_component_ids_by_column.get(markup_type, [])
            if len(ordered_component_ids) < 2:
                continue
            column_frames = [
                shifted_frame_by_proc[proc_id]
                for component_idx in ordered_component_ids
                for proc_id in info_by_component[component_idx].procedure_ids
                if proc_id in shifted_frame_by_proc
            ]
            if not column_frames:
                continue
            x_start = (
                min(frame.origin.x for frame in column_frames) - self.config.separator_margin_x
            )
            x_end = (
                max(frame.origin.x + frame.size.width for frame in column_frames)
                + self.config.separator_margin_x
            )
            for left_idx, right_idx in pairwise(ordered_component_ids):
                left_bounds = new_bounds_by_component.get(left_idx)
                right_bounds = new_bounds_by_component.get(right_idx)
                if left_bounds is None or right_bounds is None:
                    continue
                left_bottom = left_bounds[3]
                right_top = right_bounds[1]
                if right_top <= left_bottom:
                    continue
                y = (left_bottom + right_top) / 2
                separators.append(
                    SeparatorPlacement(
                        start=Point(x_start, y),
                        end=Point(x_end, y),
                    )
                )
        separators.sort(key=lambda separator: (separator.start.y, separator.start.x))

        markup_type_columns: list[MarkupTypeColumnPlacement] = []
        header_gap = max(104.0, self.config.scenario_procedures_gap * 4.0)
        header_height = 96.0
        header_padding_x = 40.0
        min_header_width = 420.0
        global_components_top = min(
            (bounds[1] for bounds in new_bounds_by_component.values()),
            default=0.0,
        )
        header_origin_y = global_components_top - header_gap - header_height
        for markup_type in ordered_columns:
            ordered_component_ids = ordered_component_ids_by_column.get(markup_type, [])
            if not ordered_component_ids:
                continue
            column_bounds = [
                new_bounds_by_component[component_idx]
                for component_idx in ordered_component_ids
                if component_idx in new_bounds_by_component
            ]
            if not column_bounds:
                continue
            min_x = min(item[0] for item in column_bounds)
            max_x = max(item[2] for item in column_bounds)
            base_width = (max_x - min_x) + header_padding_x * 2
            header_width = max(min_header_width, base_width)
            extra_width = header_width - base_width
            origin_x = min_x - header_padding_x - extra_width / 2
            markup_type_columns.append(
                MarkupTypeColumnPlacement(
                    markup_type=markup_type,
                    origin=Point(origin_x, header_origin_y),
                    size=Size(header_width, header_height),
                    is_merged_markup_types=any(
                        info_by_component[component_idx].is_merged_markup_types
                        for component_idx in ordered_component_ids
                        if component_idx in info_by_component
                    ),
                )
            )

        return (
            shifted_frames,
            separators,
            shifted_scenarios,
            shifted_service_zones,
            markup_type_columns,
        )

    def _component_bounds(
        self,
        *,
        procedure_ids: tuple[str, ...],
        frame_by_proc: Mapping[str, FramePlacement],
        zones: list[ServiceZonePlacement],
        scenario: ScenarioPlacement | None,
    ) -> tuple[float, float, float, float] | None:
        min_x = float("inf")
        min_y = float("inf")
        max_x = float("-inf")
        max_y = float("-inf")
        has_data = False

        for proc_id in procedure_ids:
            frame = frame_by_proc.get(proc_id)
            if frame is None:
                continue
            has_data = True
            min_x = min(min_x, frame.origin.x)
            min_y = min(min_y, frame.origin.y)
            max_x = max(max_x, frame.origin.x + frame.size.width)
            max_y = max(max_y, frame.origin.y + frame.size.height)

        for zone in zones:
            has_data = True
            min_x = min(min_x, zone.origin.x)
            min_y = min(min_y, zone.origin.y)
            max_x = max(max_x, zone.origin.x + zone.size.width)
            max_y = max(max_y, zone.origin.y + zone.size.height)

        if scenario is not None:
            has_data = True
            min_x = min(min_x, scenario.origin.x, scenario.procedures_origin.x)
            min_y = min(min_y, scenario.origin.y, scenario.procedures_origin.y)
            max_x = max(
                max_x,
                scenario.origin.x + scenario.size.width,
                scenario.procedures_origin.x + scenario.procedures_size.width,
            )
            max_y = max(max_y, scenario.procedures_origin.y + scenario.procedures_size.height)
            if scenario.merge_origin and scenario.merge_size:
                min_x = min(min_x, scenario.merge_origin.x)
                min_y = min(min_y, scenario.merge_origin.y)
                max_x = max(max_x, scenario.merge_origin.x + scenario.merge_size.width)
                max_y = max(max_y, scenario.merge_origin.y + scenario.merge_size.height)

        if not has_data:
            return None
        return min_x, min_y, max_x, max_y

    def _component_column_markup_type(
        self,
        *,
        procedure_ids: tuple[str, ...],
        procedure_meta: Mapping[str, Mapping[str, object]],
        default_markup_type: str,
    ) -> tuple[str, bool]:
        intersection_markup_types: set[str] = set()
        for proc_id in procedure_ids:
            meta = procedure_meta.get(proc_id, {})
            if not self._is_real_intersection_merge(proc_id, meta):
                continue
            for entry in self._procedure_merge_entries(meta, default_markup_type):
                markup_type = str(entry.get("markup_type") or default_markup_type).strip()
                intersection_markup_types.add(markup_type or "unknown")
        if len(intersection_markup_types) > 1:
            ordered_types = sorted(
                intersection_markup_types,
                key=self._markup_type_column_sort_key,
            )
            return " + ".join(ordered_types), True

        markup_types: set[str] = set()
        for proc_id in procedure_ids:
            meta = procedure_meta.get(proc_id, {})
            for entry in self._procedure_service_entries(meta, default_markup_type):
                markup_type = str(entry.get("markup_type") or default_markup_type).strip()
                markup_types.add(markup_type or "unknown")
        if not markup_types:
            return default_markup_type or "unknown", False
        return min(markup_types, key=self._markup_type_column_sort_key), False

    def _is_real_intersection_merge(
        self,
        proc_id: str,
        meta: Mapping[str, object],
    ) -> bool:
        if meta.get("is_intersection") is not True:
            return False
        source_proc_id = meta.get("source_procedure_id")
        if isinstance(source_proc_id, str) and source_proc_id and source_proc_id != proc_id:
            return False
        return True

    def _component_sort_key(
        self,
        *,
        procedure_ids: tuple[str, ...],
        procedure_map: Mapping[str, Procedure],
        procedure_meta: Mapping[str, Mapping[str, object]],
        default_markup_type: str,
    ) -> tuple[object, ...]:
        service_names: set[str] = set()
        for proc_id in procedure_ids:
            meta = procedure_meta.get(proc_id, {})
            for entry in self._procedure_service_entries(meta, default_markup_type):
                raw_name = str(entry.get("service_name") or "").strip()
                if raw_name:
                    service_names.add(raw_name)
            if not service_names:
                fallback_name = str(meta.get("service_name") or "").strip()
                if fallback_name:
                    service_names.add(fallback_name)
        if not service_names:
            service_names.add("Unknown service")
        normalized_services = tuple(
            sorted({service.lower() for service in service_names if service.strip()})
        )
        if not normalized_services:
            normalized_services = ("unknown service",)
        primary_service = normalized_services[0]

        procedure_tokens: list[str] = []
        block_tokens: list[str] = []
        for proc_id in procedure_ids:
            proc = procedure_map.get(proc_id)
            if proc is not None:
                proc_name = str(proc.procedure_name or "").strip().lower()
                procedure_tokens.append(proc_name or proc_id.lower())
                if proc.block_id_to_block_name:
                    block_tokens.extend(
                        value.strip().lower()
                        for value in proc.block_id_to_block_name.values()
                        if isinstance(value, str) and value.strip()
                    )
                else:
                    block_tokens.extend(block_id.lower() for block_id in sorted(proc.block_ids()))
            else:
                procedure_tokens.append(proc_id.lower())
        procedure_tokens.sort()
        block_tokens.sort()
        if not block_tokens:
            block_tokens = [proc_id.lower() for proc_id in procedure_ids]
        return (
            primary_service,
            normalized_services,
            tuple(procedure_tokens),
            tuple(block_tokens),
            tuple(proc_id.lower() for proc_id in procedure_ids),
        )

    def _markup_type_column_sort_key(self, markup_type: str) -> tuple[int, str]:
        normalized = str(markup_type or "").strip() or "unknown"
        return (
            _MARKUP_TYPE_COLUMN_ORDER_INDEX.get(normalized, len(_MARKUP_TYPE_COLUMN_ORDER)),
            normalized.lower(),
        )

    def _median(self, values: list[float]) -> float:
        if not values:
            return 0.0
        ordered = sorted(values)
        mid = len(ordered) // 2
        if len(ordered) % 2 == 1:
            return ordered[mid]
        return (ordered[mid - 1] + ordered[mid]) / 2

    def _shift_service_zone(
        self,
        zone: ServiceZonePlacement,
        dx: float,
        dy: float,
    ) -> ServiceZonePlacement:
        return ServiceZonePlacement(
            service_key=zone.service_key,
            service_name=zone.service_name,
            markup_type=zone.markup_type,
            team_name=zone.team_name,
            team_id=zone.team_id,
            color=zone.color,
            origin=Point(zone.origin.x + dx, zone.origin.y + dy),
            size=zone.size,
            label_origin=Point(zone.label_origin.x + dx, zone.label_origin.y + dy),
            label_size=zone.label_size,
            label_font_size=zone.label_font_size,
            procedure_ids=zone.procedure_ids,
        )

    def _shift_scenario(
        self,
        scenario: ScenarioPlacement,
        dx: float,
        dy: float,
    ) -> ScenarioPlacement:
        merge_origin = None
        if scenario.merge_origin is not None:
            merge_origin = Point(
                scenario.merge_origin.x + dx,
                scenario.merge_origin.y + dy,
            )
        return ScenarioPlacement(
            origin=Point(scenario.origin.x + dx, scenario.origin.y + dy),
            size=scenario.size,
            title_text=scenario.title_text,
            body_text=scenario.body_text,
            cycle_text=scenario.cycle_text,
            title_font_size=scenario.title_font_size,
            body_font_size=scenario.body_font_size,
            cycle_font_size=scenario.cycle_font_size,
            padding=scenario.padding,
            section_gap=scenario.section_gap,
            procedures_origin=Point(
                scenario.procedures_origin.x + dx,
                scenario.procedures_origin.y + dy,
            ),
            procedures_size=scenario.procedures_size,
            procedures_text=scenario.procedures_text,
            procedures_font_size=scenario.procedures_font_size,
            procedures_padding=scenario.procedures_padding,
            procedures_blocks=scenario.procedures_blocks,
            procedures_block_padding=scenario.procedures_block_padding,
            merge_origin=merge_origin,
            merge_size=scenario.merge_size,
            merge_text=scenario.merge_text,
            merge_font_size=scenario.merge_font_size,
            merge_padding=scenario.merge_padding,
            merge_blocks=scenario.merge_blocks,
            merge_block_padding=scenario.merge_block_padding,
            merge_node_numbers=scenario.merge_node_numbers,
        )

    def _zones_have_non_nested_overlap(self, zones: list[ServiceZonePlacement]) -> bool:
        for idx, first in enumerate(zones):
            for second in zones[idx + 1 :]:
                if not self._rects_overlap(first.origin, first.size, second.origin, second.size):
                    continue
                first_contains_second = self._rect_contains(
                    first.origin, first.size, second.origin, second.size
                )
                second_contains_first = self._rect_contains(
                    second.origin, second.size, first.origin, first.size
                )
                if not first_contains_second and not second_contains_first:
                    return True
        return False

    def _edges_cross(
        self,
        frame_lookup: Mapping[str, FramePlacement],
        adjacency: Mapping[str, list[str]],
    ) -> bool:
        edges: list[tuple[str, str, Point, Point]] = []
        for parent, children in adjacency.items():
            source = frame_lookup.get(parent)
            if not source:
                continue
            for child in children:
                target = frame_lookup.get(child)
                if not target:
                    continue
                start = Point(
                    x=source.origin.x + source.size.width,
                    y=source.origin.y + source.size.height / 2,
                )
                end = Point(
                    x=target.origin.x,
                    y=target.origin.y + target.size.height / 2,
                )
                edges.append((parent, child, start, end))

        for idx, edge in enumerate(edges):
            _, _, start_a, end_a = edge
            for other in edges[idx + 1 :]:
                if edge[0] in other[:2] or edge[1] in other[:2]:
                    continue
                _, _, start_b, end_b = other
                if self._segments_intersect(start_a, end_a, start_b, end_b):
                    return True
        return False

    def _segments_intersect(self, a1: Point, a2: Point, b1: Point, b2: Point) -> bool:
        if (
            self._points_equal(a1, b1)
            or self._points_equal(a1, b2)
            or self._points_equal(a2, b1)
            or self._points_equal(a2, b2)
        ):
            return False
        o1 = self._orientation(a1, a2, b1)
        o2 = self._orientation(a1, a2, b2)
        o3 = self._orientation(b1, b2, a1)
        o4 = self._orientation(b1, b2, a2)
        if 0 in {o1, o2, o3, o4}:
            return False
        return o1 != o2 and o3 != o4

    def _orientation(self, p: Point, q: Point, r: Point) -> int:
        value = (q.y - p.y) * (r.x - q.x) - (q.x - p.x) * (r.y - q.y)
        if abs(value) < 1e-6:
            return 0
        return 1 if value > 0 else -1

    def _points_equal(self, p1: Point, p2: Point, eps: float = 1e-6) -> bool:
        return abs(p1.x - p2.x) <= eps and abs(p1.y - p2.y) <= eps

    def _rect_contains(
        self,
        outer_origin: Point,
        outer_size: Size,
        inner_origin: Point,
        inner_size: Size,
        eps: float = 1e-6,
    ) -> bool:
        outer_right = outer_origin.x + outer_size.width
        outer_bottom = outer_origin.y + outer_size.height
        inner_right = inner_origin.x + inner_size.width
        inner_bottom = inner_origin.y + inner_size.height
        if (
            outer_origin.x <= inner_origin.x + eps
            and outer_origin.y <= inner_origin.y + eps
            and outer_right >= inner_right - eps
            and outer_bottom >= inner_bottom - eps
        ):
            return not (
                abs(outer_origin.x - inner_origin.x) <= eps
                and abs(outer_origin.y - inner_origin.y) <= eps
                and abs(outer_right - inner_right) <= eps
                and abs(outer_bottom - inner_bottom) <= eps
            )
        return False

    def _rects_overlap(
        self,
        first_origin: Point,
        first_size: Size,
        second_origin: Point,
        second_size: Size,
        eps: float = 1e-6,
    ) -> bool:
        first_right = first_origin.x + first_size.width
        first_bottom = first_origin.y + first_size.height
        second_right = second_origin.x + second_size.width
        second_bottom = second_origin.y + second_size.height
        overlap_x = min(first_right, second_right) - max(first_origin.x, second_origin.x)
        overlap_y = min(first_bottom, second_bottom) - max(first_origin.y, second_origin.y)
        return overlap_x > eps and overlap_y > eps
