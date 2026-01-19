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
    SeparatorPlacement,
    Size,
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
        procedures_lines = self._component_service_lines(
            component, procedure_map, frame_lookup, procedure_meta
        )
        procedures_body = (
            ["Услуги:", *procedures_lines]
            if procedures_lines
            else [
                "Услуги:",
                "- (нет данных)",
            ]
        )
        procedures_max_width = scenario_width - (self.config.scenario_procedures_padding * 2)
        procedures_lines_wrapped = self._wrap_lines(
            procedures_body, procedures_max_width, self.config.scenario_procedures_font_size
        )
        procedures_text = "\n".join(procedures_lines_wrapped)
        procedures_height = max(
            self.config.scenario_procedures_min_height,
            len(procedures_lines_wrapped) * self.config.scenario_procedures_font_size * 1.35
            + self.config.scenario_procedures_padding * 2,
        )
        procedures_origin = Point(
            x=x_left,
            y=origin.y + scenario_height + self.config.scenario_procedures_gap,
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
        )

    def _component_service_lines(
        self,
        component: set[str],
        procedure_map: Mapping[str, Procedure],
        frame_lookup: Mapping[str, FramePlacement],
        procedure_meta: Mapping[str, Mapping[str, object]],
    ) -> list[str]:
        service_entries: dict[tuple[str, str], list[tuple[float, str]]] = {}
        for proc_id in sorted(component):
            proc = procedure_map.get(proc_id)
            if proc is None:
                continue
            frame = frame_lookup.get(proc_id)
            x_pos = frame.origin.x if frame else 0.0
            meta = procedure_meta.get(proc_id, {})
            label = proc.procedure_name or proc.procedure_id
            services = meta.get("services")
            if isinstance(services, list) and services:
                seen: set[tuple[str, str]] = set()
                for service in services:
                    if not isinstance(service, Mapping):
                        continue
                    team_name = str(service.get("team_name") or "Unknown team")
                    service_name = str(service.get("service_name") or "Unknown service")
                    key = (team_name, service_name)
                    if key in seen:
                        continue
                    seen.add(key)
                    service_entries.setdefault(key, []).append((x_pos, label))
            else:
                team_name = str(meta.get("team_name") or meta.get("team_id") or "Unknown team")
                service_name = str(meta.get("service_name") or "Unknown service")
                service_entries.setdefault((team_name, service_name), []).append((x_pos, label))

        if not service_entries:
            return []

        lines: list[str] = []
        limit = 8
        sorted_services = sorted(
            service_entries.items(),
            key=lambda entry: (entry[0][0].lower(), entry[0][1].lower()),
        )
        for (team_name, service_name), entries in sorted_services:
            lines.append(f"{team_name} - {service_name}")
            entries.sort(key=lambda item: (item[0], item[1]))
            labels = [label for _, label in entries]
            if len(labels) > limit:
                trimmed = labels[:limit]
                lines.extend([f"- {label}" for label in trimmed])
                lines.append(f"- и еще {len(labels) - limit}")
            else:
                lines.extend([f"- {label}" for label in labels])
        return lines
