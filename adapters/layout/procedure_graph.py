from __future__ import annotations

from collections.abc import Mapping

from adapters.layout.grid import GridLayoutEngine, LayoutConfig
from domain.models import (
    FramePlacement,
    LayoutPlan,
    MarkupDocument,
    Point,
    Procedure,
    ScenarioPlacement,
    ScenarioProceduresBlock,
    SeparatorPlacement,
    Size,
    normalize_finedog_unit_id,
)


class ProcedureGraphLayoutEngine(GridLayoutEngine):
    def __init__(self, config: LayoutConfig | None = None) -> None:
        super().__init__(config or LayoutConfig())

    def build_plan(self, document: MarkupDocument) -> LayoutPlan:
        frames: list[FramePlacement] = []
        separators: list[SeparatorPlacement] = []
        scenarios: list[ScenarioPlacement] = []

        procedures = list(document.procedures)
        if not procedures:
            return LayoutPlan(
                frames=frames, blocks=[], markers=[], separators=separators, scenarios=scenarios
            )

        proc_ids = [proc.procedure_id for proc in procedures]
        order_hint = self._procedure_order_hint(procedures, document.procedure_graph)
        order_index = {proc_id: idx for idx, proc_id in enumerate(order_hint)}
        adjacency = self._normalize_procedure_graph(proc_ids, document.procedure_graph)
        components = self._procedure_components(proc_ids, adjacency)
        components.sort(
            key=lambda component: min(order_index.get(proc_id, 0) for proc_id in component)
        )

        node_size = self._procedure_node_size()
        lane_span = node_size.width + self.config.lane_gap
        proc_gap_y = self.config.gap_y
        component_gap = max(proc_gap_y, self.config.separator_padding * 2)

        origin_x = 0.0
        origin_y = 0.0
        separator_ys: list[float] = []
        frame_lookup: dict[str, FramePlacement] = {}
        procedure_map = {proc.procedure_id: proc for proc in procedures}

        for idx, component in enumerate(components):
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

            level_heights: dict[int, float] = {}
            for lvl, nodes in level_nodes.items():
                if not nodes:
                    level_heights[lvl] = 0.0
                    continue
                total = len(nodes) * node_size.height + proc_gap_y * (len(nodes) - 1)
                level_heights[lvl] = total

            component_height = max(level_heights.values() or [0.0])
            component_frames: list[FramePlacement] = []
            for lvl, nodes in level_nodes.items():
                y = origin_y
                for proc_id in nodes:
                    frame = FramePlacement(
                        procedure_id=proc_id,
                        origin=Point(origin_x + lvl * lane_span, y),
                        size=node_size,
                    )
                    frames.append(frame)
                    frame_lookup[proc_id] = frame
                    component_frames.append(frame)
                    y += node_size.height + proc_gap_y

            scenario_total_height = 0.0
            if component_frames:
                scenario = self._scenario_with_services(
                    component=component,
                    component_index=idx + 1,
                    component_count=len(components),
                    frame_lookup=frame_lookup,
                    procedure_map=procedure_map,
                    procedure_graph=document.procedure_graph,
                    order_index=order_index,
                    procedure_meta=document.procedure_meta,
                )
                if scenario:
                    scenarios.append(scenario)
                    scenario_total_height = (
                        scenario.procedures_origin.y
                        + scenario.procedures_size.height
                        - scenario.origin.y
                    )

            component_visual_height = max(component_height, scenario_total_height)
            if idx < len(components) - 1:
                separator_ys.append(origin_y + component_visual_height + component_gap / 2)
                origin_y += component_visual_height + component_gap
            else:
                origin_y += component_visual_height + proc_gap_y

        if frames and separator_ys:
            min_x = min(frame.origin.x for frame in frames)
            max_x = max(frame.origin.x + frame.size.width for frame in frames)
            x_start = min_x - self.config.separator_margin_x
            x_end = max_x + self.config.separator_margin_x
            separators = [
                SeparatorPlacement(start=Point(x_start, y), end=Point(x_end, y))
                for y in separator_ys
            ]

        return LayoutPlan(
            frames=frames,
            blocks=[],
            markers=[],
            separators=separators,
            scenarios=scenarios,
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
        order_index: dict[str, int],
        procedure_meta: Mapping[str, Mapping[str, object]] | None,
    ) -> ScenarioPlacement | None:
        procedure_meta = procedure_meta or {}
        component_frames = [
            frame_lookup[proc_id] for proc_id in component if proc_id in frame_lookup
        ]
        if not component_frames:
            return None
        min_x = min(frame.origin.x for frame in component_frames)
        min_y = min(frame.origin.y for frame in component_frames)
        title = "Граф" if component_count == 1 else f"Граф {component_index}"
        starts, ends, variants = self._component_stats(component, procedure_map, procedure_graph)
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
            component, procedure_meta
        )
        merge_blocks, merge_text, merge_block_padding = self._component_merge_blocks(
            component, procedure_map, procedure_meta, order_index
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
                y=origin.y + scenario_height + self.config.scenario_merge_gap,
            )
            merge_size = Size(scenario_width, merge_height)
            procedures_origin = Point(
                x=x_left,
                y=merge_origin.y + merge_height + self.config.scenario_procedures_gap,
            )
        else:
            procedures_origin = Point(
                x=x_left,
                y=origin.y + scenario_height + self.config.scenario_procedures_gap,
            )
        procedures_content_height = sum(block.height for block in procedures_blocks)
        procedures_height = max(
            self.config.scenario_procedures_min_height,
            procedures_content_height + self.config.scenario_procedures_padding * 2,
        )
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
        )

    def _component_service_blocks(
        self,
        component: set[str],
        procedure_meta: Mapping[str, Mapping[str, object]],
    ) -> tuple[list[ScenarioProceduresBlock], str, float]:
        groups, summary = self._component_service_groups(component, procedure_meta)
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
            for service_idx, (service_name, service_color, finedog_unit_id) in enumerate(services):
                wrapped = self._wrap_lines(
                    [service_name],
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
                lines.append(f"- {service_name}")
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

    def _component_merge_blocks(
        self,
        component: set[str],
        procedure_map: Mapping[str, Procedure],
        procedure_meta: Mapping[str, Mapping[str, object]],
        order_index: Mapping[str, int],
    ) -> tuple[list[ScenarioProceduresBlock], str | None, float | None]:
        merge_ids = [
            proc_id
            for proc_id in component
            if procedure_meta.get(proc_id, {}).get("is_intersection") is True
        ]
        if not merge_ids:
            return [], None, None

        merge_ids.sort(key=lambda proc_id: order_index.get(proc_id, 0))
        header = "Узлы слияния:"
        font_size = self.config.scenario_merge_font_size
        line_height = font_size * 1.35
        header_gap = 0.0
        item_gap = 0.0
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
                underline=True,
            )
        )
        if header_gap:
            blocks.append(ScenarioProceduresBlock(kind="spacer", text="", height=header_gap))

        lines = [header]
        for idx, proc_id in enumerate(merge_ids):
            line = proc_id
            wrapped = self._wrap_lines([line], content_width - item_padding * 2, font_size)
            blocks.append(
                ScenarioProceduresBlock(
                    kind="merge_item",
                    text="\n".join(wrapped),
                    height=len(wrapped) * line_height + item_padding * 2,
                    font_size=font_size,
                )
            )
            lines.append(line)
            if idx < len(merge_ids) - 1 and item_gap:
                blocks.append(ScenarioProceduresBlock(kind="spacer", text="", height=item_gap))

        if lines and not lines[-1]:
            lines.pop()
        return blocks, "\n".join(lines), item_padding

    def _component_service_groups(
        self,
        component: set[str],
        procedure_meta: Mapping[str, Mapping[str, object]],
    ) -> tuple[list[tuple[str, str | int | None, list[tuple[str, str, str | None]]]], str | None]:
        team_services: dict[tuple[str, str | int | None], dict[str, dict[str, object]]] = {}
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
                    color = service.get("service_color")
                    finedog_unit_id = service.get("finedog_unit_id")
                    normalized_unit_id = normalize_finedog_unit_id(finedog_unit_id)
                    if not isinstance(color, str):
                        color = meta.get("procedure_color")
                    team_key = (team_name, team_id if isinstance(team_id, str | int) else None)
                    service_entry = team_services.setdefault(team_key, {})
                    if service_name not in service_entry:
                        service_entry[service_name] = {
                            "color": color if isinstance(color, str) else "#e9f0fb",
                            "finedog_unit_id": normalized_unit_id,
                        }
                    else:
                        existing = service_entry[service_name]
                        if (
                            existing.get("finedog_unit_id") is None
                            and normalized_unit_id is not None
                        ):
                            existing["finedog_unit_id"] = normalized_unit_id
            else:
                team_id = meta.get("team_id")
                team_name = str(meta.get("team_name") or team_id or "Unknown team")
                service_name = str(meta.get("service_name") or "Unknown service")
                color = meta.get("procedure_color")
                team_key = (team_name, team_id if isinstance(team_id, str | int) else None)
                service_entry = team_services.setdefault(team_key, {})
                if service_name not in service_entry:
                    normalized_unit_id = normalize_finedog_unit_id(meta.get("finedog_unit_id"))
                    service_entry[service_name] = {
                        "color": color if isinstance(color, str) else "#e9f0fb",
                        "finedog_unit_id": normalized_unit_id,
                    }

        if not team_services:
            return [], None

        teams_sorted = sorted(team_services.keys(), key=lambda item: item[0].lower())
        groups: list[tuple[str, str | int | None, list[tuple[str, str, str | None]]]] = []
        for team_name, team_id in teams_sorted:
            services = team_services[(team_name, team_id)]
            sorted_services: list[tuple[str, str, str | None]] = []
            for service_name, payload in sorted(services.items(), key=lambda item: item[0].lower()):
                color = payload.get("color")
                unit_id = payload.get("finedog_unit_id")
                sorted_services.append(
                    (
                        service_name,
                        color if isinstance(color, str) else "#e9f0fb",
                        normalize_finedog_unit_id(unit_id),
                    )
                )
            groups.append((team_name, team_id, sorted_services))
        return groups, None
