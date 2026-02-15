from __future__ import annotations

import heapq
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from domain.models import (
    END_TYPE_DEFAULT,
    END_TYPE_TURN_OUT,
    BlockPlacement,
    FramePlacement,
    LayoutPlan,
    MarkerPlacement,
    MarkupDocument,
    Point,
    Procedure,
    ScenarioPlacement,
    SeparatorPlacement,
    Size,
    normalize_end_type,
)
from domain.ports.layout import LayoutEngine
from domain.services.block_graph_resolution import (
    ResolvedBlockGraphEdge,
    build_block_owner_index,
    resolve_block_graph_edges,
)
from domain.services.graph_metrics import build_directed_graph, compute_graph_metrics


@dataclass(frozen=True)
class LayoutConfig:
    block_size: Size = field(default_factory=lambda: Size(260, 120))
    marker_size: Size = field(default_factory=lambda: Size(180, 90))
    padding: float = 150.0
    gap_x: float = 120.0
    gap_y: float = 80.0
    lane_gap: float = 300.0
    max_cols: int = 4
    separator_padding: float = 220.0
    separator_margin_x: float = 80.0
    scenario_width: float = 360.0
    scenario_gap: float = 120.0
    scenario_padding: float = 24.0
    scenario_title_font_size: float = 22.0
    scenario_body_font_size: float = 16.0
    scenario_cycle_font_size: float = 16.0
    scenario_section_gap: float = 0.0
    scenario_procedures_font_size: float = 16.0
    scenario_procedures_padding: float = 20.0
    scenario_procedures_gap: float = 16.0
    scenario_procedures_min_height: float = 140.0
    scenario_merge_font_size: float = 15.0
    scenario_merge_padding: float = 18.0
    scenario_merge_gap: float = 12.0
    scenario_merge_min_height: float = 90.0
    scenario_min_height: float = 180.0
    service_zone_padding_x: float = 40.0
    service_zone_padding_y: float = 30.0
    service_zone_label_font_size: float = 20.0
    service_zone_label_gap: float = 12.0


@dataclass(frozen=True)
class NodeInfo:
    kind: str  # "block" or "end_marker"
    block_id: str
    end_type: str | None = None


class GridLayoutEngine(LayoutEngine):
    def __init__(self, config: LayoutConfig | None = None) -> None:
        self.config = config or LayoutConfig()

    def build_plan(self, document: MarkupDocument) -> LayoutPlan:
        frames: list[FramePlacement] = []
        blocks: list[BlockPlacement] = []
        markers: list[MarkerPlacement] = []
        separator_ys: list[float] = []
        scenarios: list[ScenarioPlacement] = []

        block_graph_nodes = self._block_graph_nodes(document) if document.block_graph else set()
        owned_blocks_by_proc = self._resolve_owned_blocks(document, block_graph_nodes)
        procedures = [
            proc for proc in document.procedures if owned_blocks_by_proc.get(proc.procedure_id)
        ]
        if not procedures:
            return LayoutPlan(
                frames=frames, blocks=blocks, markers=markers, separators=[], scenarios=[]
            )
        procedure_graph = document.procedure_graph
        block_graph_procedure: dict[str, list[str]] = {}
        if document.block_graph and not any(procedure_graph.values()):
            block_graph_procedure = self._infer_procedure_graph_from_block_graph(
                document.block_graph, procedures, owned_blocks_by_proc
            )
            procedure_graph = block_graph_procedure
        elif document.block_graph:
            block_graph_procedure = self._infer_procedure_graph_from_block_graph(
                document.block_graph, procedures, owned_blocks_by_proc
            )

        proc_ids = [proc.procedure_id for proc in procedures]
        order_hint = self._procedure_order_hint(procedures, procedure_graph)
        order_index = {proc_id: idx for idx, proc_id in enumerate(order_hint)}
        adjacency = self._normalize_procedure_graph(proc_ids, procedure_graph)
        if block_graph_procedure:
            inferred_adjacency = self._normalize_procedure_graph(proc_ids, block_graph_procedure)
            for parent, children in inferred_adjacency.items():
                for child in children:
                    if child not in adjacency[parent]:
                        adjacency[parent].append(child)
        sizing: dict[str, Size] = {}
        layout_edges_by_proc = self._layout_edges_by_proc(
            document, procedures, owned_blocks_by_proc
        )
        end_block_row_offsets = self._end_block_row_offsets(
            document, procedures, owned_blocks_by_proc
        )
        cross_proc_edges = self._cross_procedure_edges(document, procedures, owned_blocks_by_proc)

        # Pre-compute frame sizes using left-to-right levels inside each procedure.
        for procedure in procedures:
            _, max_level, row_counts, _, _, _ = self._compute_block_levels(
                procedure,
                owned_blocks_by_proc.get(procedure.procedure_id),
                layout_edges_by_proc.get(procedure.procedure_id),
                set(procedure.branches.keys()),
                end_block_row_offsets.get(procedure.procedure_id),
            )
            cols = max_level + 1
            rows = max(row_counts.values() or [1])
            start_extra = self.config.marker_size.width + self.config.gap_x * 0.8
            frame_width = (
                self.config.padding * 2
                + start_extra
                + cols * self.config.block_size.width
                + ((cols - 1) * self.config.gap_x)
            )
            frame_height = (
                self.config.padding * 2
                + rows * self.config.block_size.height
                + ((rows - 1) * self.config.gap_y)
            )
            sizing[procedure.procedure_id] = Size(
                frame_width + self.config.marker_size.width + self.config.gap_x * 0.5,
                frame_height + self.config.padding * 0.25,
            )

        components = self._procedure_components(proc_ids, adjacency)
        components.sort(
            key=lambda component: min(order_index.get(proc_id, 0) for proc_id in component)
        )

        origin_x = 0.0
        origin_y = 0.0
        proc_gap_y = self.config.lane_gap
        component_gap = max(proc_gap_y, self.config.separator_padding * 2)

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

            level_widths: dict[int, float] = {}
            for lvl, nodes in level_nodes.items():
                level_widths[lvl] = max((sizing[node].width for node in nodes), default=0.0)

            level_offsets: dict[int, float] = {}
            offset_x = origin_x
            for lvl in range(max_level + 1):
                level_offsets[lvl] = offset_x
                offset_x += level_widths.get(lvl, 0.0) + self.config.lane_gap

            level_heights: dict[int, float] = {}
            for lvl, nodes in level_nodes.items():
                if not nodes:
                    level_heights[lvl] = 0.0
                    continue
                total = sum(sizing[node].height for node in nodes)
                total += proc_gap_y * (len(nodes) - 1)
                level_heights[lvl] = total

            frame_offsets = self._component_frame_offsets(
                component,
                cross_proc_edges,
                order_index,
                sizing,
            )
            component_frames: list[FramePlacement] = []
            for lvl, nodes in level_nodes.items():
                y = origin_y
                for proc_id in nodes:
                    frame_size = sizing[proc_id]
                    y = max(y, origin_y + frame_offsets.get(proc_id, 0.0))
                    frame = FramePlacement(
                        procedure_id=proc_id,
                        origin=Point(level_offsets.get(lvl, origin_x), y),
                        size=frame_size,
                    )
                    frames.append(frame)
                    component_frames.append(frame)
                    y += frame_size.height + proc_gap_y

            if component_frames:
                component_height = (
                    max(frame.origin.y + frame.size.height for frame in component_frames) - origin_y
                )
            else:
                component_height = 0.0
            if idx < len(components) - 1:
                separator_ys.append(origin_y + component_height + component_gap / 2)
                origin_y += component_height + component_gap
            else:
                origin_y += component_height + proc_gap_y

        procedure_map = {proc.procedure_id: proc for proc in procedures}
        for frame in frames:
            frame_proc = procedure_map.get(frame.procedure_id)
            if frame_proc is None:
                continue
            placement_by_block: dict[str, BlockPlacement] = {}
            node_levels, max_level, _, order, row_positions, node_info = self._compute_block_levels(
                frame_proc,
                owned_blocks_by_proc.get(frame_proc.procedure_id),
                layout_edges_by_proc.get(frame_proc.procedure_id),
                set(frame_proc.branches.keys()),
                end_block_row_offsets.get(frame_proc.procedure_id),
            )
            start_extra = self.config.marker_size.width + self.config.gap_x * 0.8
            level_rows: dict[int, float] = {lvl: 0.0 for lvl in range(max_level + 1)}
            for node_id in order:
                level_idx = node_levels.get(node_id, 0)
                row_idx = row_positions.get(node_id, level_rows[level_idx])
                level_rows[level_idx] = max(level_rows[level_idx], row_idx + 1)

                x = (
                    frame.origin.x
                    + self.config.padding
                    + start_extra
                    + level_idx * (self.config.block_size.width + self.config.gap_x)
                )
                y = (
                    frame.origin.y
                    + self.config.padding
                    + row_idx * (self.config.block_size.height + self.config.gap_y)
                )
                info = node_info.get(node_id)
                if not info:
                    continue
                if info.kind == "block":
                    placement = BlockPlacement(
                        procedure_id=frame_proc.procedure_id,
                        block_id=info.block_id,
                        position=Point(x, y),
                        size=self.config.block_size,
                    )
                    blocks.append(placement)
                    placement_by_block[info.block_id] = placement
                elif info.kind == "end_marker":
                    offset_x = (self.config.block_size.width - self.config.marker_size.width) / 2
                    offset_y = (self.config.block_size.height - self.config.marker_size.height) / 2
                    markers.append(
                        MarkerPlacement(
                            procedure_id=frame_proc.procedure_id,
                            block_id=info.block_id,
                            role="end_marker",
                            position=Point(x + offset_x, y + offset_y),
                            size=self.config.marker_size,
                            end_type=info.end_type,
                        )
                    )

            for start_block in frame_proc.start_block_ids:
                block = placement_by_block.get(start_block)
                if not block:
                    continue
                x = block.position.x - (self.config.marker_size.width + self.config.gap_x * 0.8)
                y = block.position.y + (block.size.height - self.config.marker_size.height) / 2
                markers.append(
                    MarkerPlacement(
                        procedure_id=frame_proc.procedure_id,
                        block_id=start_block,
                        role="start_marker",
                        position=Point(x, y),
                        size=self.config.marker_size,
                    )
                )

        if blocks:
            self._adjust_blocks_for_edges(document, blocks, markers)

        if blocks and markers:
            self._adjust_start_markers_for_edges(document, blocks, markers)

        separators: list[SeparatorPlacement] = []
        if frames and separator_ys:
            min_x = min(frame.origin.x for frame in frames)
            max_x = max(frame.origin.x + frame.size.width for frame in frames)
            x_start = min_x - self.config.separator_margin_x
            x_end = max_x + self.config.separator_margin_x
            separators = [
                SeparatorPlacement(
                    start=Point(x_start, y),
                    end=Point(x_end, y),
                )
                for y in separator_ys
            ]

        if frames:
            scenarios = self._build_scenarios(
                components,
                frames,
                procedure_map,
                procedure_graph,
                document.block_graph or None,
                layout_edges_by_proc,
                order_index,
            )

        return LayoutPlan(
            frames=frames,
            blocks=blocks,
            markers=markers,
            separators=separators,
            scenarios=scenarios,
        )

    def _build_scenarios(
        self,
        components: list[set[str]],
        frames: list[FramePlacement],
        procedure_map: Mapping[str, Procedure],
        procedure_graph: dict[str, list[str]],
        block_graph: Mapping[str, list[str]] | None,
        layout_edges_by_proc: Mapping[str, Mapping[str, list[str]]],
        order_index: dict[str, int],
    ) -> list[ScenarioPlacement]:
        scenarios: list[ScenarioPlacement] = []
        component_count = len(components)
        frame_lookup = {frame.procedure_id: frame for frame in frames}
        for idx, component in enumerate(components, start=1):
            component_frames = [
                frame_lookup[proc_id] for proc_id in component if proc_id in frame_lookup
            ]
            if not component_frames:
                continue
            min_x = min(frame.origin.x for frame in component_frames)
            min_y = min(frame.origin.y for frame in component_frames)
            title = "Граф" if component_count == 1 else f"Граф {idx}"
            labels = self._component_procedure_labels(component, procedure_map, frame_lookup)
            starts, ends, variants = self._component_stats(
                component,
                procedure_map,
                procedure_graph,
                layout_edges_by_proc,
                block_graph,
            )
            properties, cycle_text = self._component_graph_properties(
                component, procedure_graph, order_index, block_graph
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
            procedures_lines = [f"- {label}" for label in labels] or ["- (нет данных)"]
            procedures_body = [
                "Процедуры:",
                *procedures_lines,
            ]
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
            scenarios.append(
                ScenarioPlacement(
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
            )
        return scenarios

    def _component_procedure_labels(
        self,
        component: set[str],
        procedure_map: Mapping[str, Procedure],
        frame_lookup: dict[str, FramePlacement],
    ) -> list[str]:
        entries: list[tuple[float, bool, str, str]] = []
        for proc_id in sorted(component):
            proc = procedure_map.get(proc_id)
            if proc is None:
                continue
            frame = frame_lookup.get(proc_id)
            x_pos = frame.origin.x if frame else 0.0
            proc_name = proc.procedure_name
            label = f"{proc_name} ({proc_id})" if proc_name else proc_id
            has_start = bool(proc.start_block_ids)
            entries.append((x_pos, has_start, label, proc_id))

        entries.sort(key=lambda item: (item[0], item[3]))
        labels = [entry[2] for entry in entries]
        limit = 6
        if len(labels) <= limit:
            return labels

        start_entries = [entry for entry in entries if entry[1]]
        other_entries = [entry for entry in entries if not entry[1]]
        combined = start_entries + other_entries
        trimmed = [entry[2] for entry in combined[:limit]]
        trimmed.append(f"и еще {len(entries) - limit}")
        return trimmed

    def _wrap_lines(self, lines: list[str], max_width: float, font_size: float) -> list[str]:
        max_chars = max(1, int(max_width / (font_size * 0.6)))
        wrapped: list[str] = []
        for line in lines:
            if not line:
                wrapped.append("")
                continue
            words = line.split()
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
                                wrapped.append(" ".join(current))
                            current = [chunk]
                            count = len(chunk)
                    continue
                if count + 1 + len(word) <= max_chars:
                    current.append(word)
                    count += 1 + len(word)
                else:
                    wrapped.append(" ".join(current))
                    current = [word]
                    count = len(word)
            if current:
                wrapped.append(" ".join(current))
        return wrapped

    def _component_stats(
        self,
        component: set[str],
        procedure_map: Mapping[str, Procedure],
        procedure_graph: dict[str, list[str]],
        layout_edges_by_proc: Mapping[str, Mapping[str, list[str]]],
        block_graph: Mapping[str, list[str]] | None = None,
    ) -> tuple[int, int, int]:
        start_blocks: set[str] = set()
        end_blocks: set[str] = set()
        branch_adjacency: dict[str, list[str]] = {}
        branch_edges = 0
        for proc_id in component:
            proc = procedure_map.get(proc_id)
            if proc is None:
                continue
            for start_id in proc.start_block_ids:
                start_blocks.add(start_id)
            for end_id in proc.end_block_ids:
                end_blocks.add(end_id)
            edges = layout_edges_by_proc.get(proc_id, {})
            for source, targets in edges.items():
                if targets:
                    branch_edges += len(targets)
                branch_adjacency.setdefault(str(source), []).extend(
                    str(target) for target in targets
                )

        if block_graph:
            metrics = compute_graph_metrics(block_graph)
            branch_count = len(metrics.branch_nodes)
        else:
            if branch_edges > 0:
                combinations = self._count_paths(branch_adjacency, list(start_blocks))
                if combinations <= 0 and component:
                    combinations = 1
            else:
                combinations = self._procedure_graph_combinations(component, procedure_graph)
            branch_count = combinations

        return len(start_blocks), len(end_blocks), branch_count

    def _component_graph_properties(
        self,
        component: set[str],
        procedure_graph: dict[str, list[str]],
        order_index: dict[str, int],
        block_graph: Mapping[str, list[str]] | None = None,
    ) -> tuple[list[str], str | None]:
        if block_graph:
            metrics = compute_graph_metrics(block_graph)
            vertex_label = "вершин (блоков)"
        else:
            adjacency: dict[str, list[str]] = {node: [] for node in component}
            for parent, children in procedure_graph.items():
                if parent not in component:
                    continue
                for child in children:
                    if child in component:
                        adjacency[parent].append(child)
            metrics = compute_graph_metrics(adjacency)
            vertex_label = "вершин"

        cycle_text = None
        properties: list[str] = []
        if metrics.is_acyclic:
            properties.append("- ацикличный")
        else:
            cycle_text = f"- цикличный, кол-во циклов: {metrics.cycle_count}"
        properties.extend(
            [
                "- ориентированный",
                "- слабосвязный" if metrics.weakly_connected else "- несвязный",
                f"- {vertex_label}: {metrics.vertices}",
                f"- ребер: {metrics.edges}",  # noqa: RUF001
                f"- источники: {len(metrics.sources)}",
                f"- стоки: {len(metrics.sinks)}",
                "- разветвляющийся" if metrics.branch_nodes else "- без разветвлений",
                "- слияния есть" if metrics.merge_nodes else "- без слияний",
            ]
        )
        return properties, cycle_text

    def _procedure_graph_combinations(
        self,
        component: set[str],
        procedure_graph: dict[str, list[str]],
    ) -> int:
        adjacency: dict[str, list[str]] = {}
        for parent, children in procedure_graph.items():
            if parent not in component:
                continue
            for child in children:
                if child in component:
                    adjacency.setdefault(parent, []).append(child)

        combinations = self._count_paths(adjacency, [])
        if combinations <= 0 and component:
            return 1
        return combinations

    def _count_paths(
        self,
        adjacency: dict[str, list[str]],
        start_nodes: list[str],
    ) -> int:
        nodes: set[str] = set(start_nodes)
        for source, targets in adjacency.items():
            nodes.add(source)
            nodes.update(targets)
        if not nodes:
            return 0

        if start_nodes:
            starts = [node for node in start_nodes if node in nodes]
            if not starts:
                starts = list(nodes)
        else:
            indegree: dict[str, int] = {node: 0 for node in nodes}
            for _source, targets in adjacency.items():
                for target in targets:
                    indegree[target] = indegree.get(target, 0) + 1
            starts = [node for node, deg in indegree.items() if deg == 0]
            if not starts:
                starts = list(nodes)

        terminals = {node for node in nodes if not adjacency.get(node)}
        memo: dict[str, int] = {}
        visiting: set[str] = set()

        def dfs(node: str) -> int:
            if node in memo:
                return memo[node]
            if node in visiting:
                return 0
            if node in terminals:
                memo[node] = 1
                return 1
            visiting.add(node)
            total = 0
            for child in adjacency.get(node, []):
                total += dfs(child)
            visiting.remove(node)
            memo[node] = total
            return total

        return sum(dfs(node) for node in starts)

    def _procedure_order_hint(
        self, procedures: Sequence[Procedure], procedure_graph: dict[str, list[str]]
    ) -> list[str]:
        proc_ids = [proc.procedure_id for proc in procedures]
        adjacency = self._normalize_procedure_graph(proc_ids, procedure_graph)
        order_index = {proc_id: idx for idx, proc_id in enumerate(proc_ids)}
        has_start = {proc.procedure_id: bool(proc.start_block_ids) for proc in procedures}

        def node_key(proc_id: str) -> tuple[int, int, str]:
            return (
                0 if has_start.get(proc_id, False) else 1,
                order_index.get(proc_id, len(proc_ids)),
                proc_id.lower(),
            )

        indegree: dict[str, int] = {proc_id: 0 for proc_id in proc_ids}
        undirected: dict[str, set[str]] = {proc_id: set() for proc_id in proc_ids}
        for source, targets in adjacency.items():
            for target in targets:
                indegree[target] = indegree.get(target, 0) + 1
                undirected[source].add(target)
                undirected[target].add(source)

        visited_components: set[str] = set()
        components: list[set[str]] = []
        for proc_id in sorted(proc_ids, key=node_key):
            if proc_id in visited_components:
                continue
            stack = [proc_id]
            component: set[str] = set()
            while stack:
                current = stack.pop()
                if current in visited_components:
                    continue
                visited_components.add(current)
                component.add(current)
                stack.extend(undirected.get(current, set()) - visited_components)
            components.append(component)

        payloads: list[tuple[set[str], list[str]]] = []
        for component in components:
            indegree_roots = [proc_id for proc_id in component if indegree.get(proc_id, 0) == 0]
            if indegree_roots:
                roots = sorted(indegree_roots, key=node_key)
            else:
                start_roots = [proc_id for proc_id in component if has_start.get(proc_id, False)]
                roots = (
                    sorted(start_roots, key=node_key)
                    if start_roots
                    else sorted(component, key=node_key)[:1]
                )
            payloads.append((component, roots))
        payloads.sort(key=lambda payload: min(node_key(proc_id) for proc_id in payload[1]))

        order_hint: list[str] = []
        visited: set[str] = set()
        for component, roots in payloads:
            for root in roots or sorted(component, key=node_key):
                stack = [root]
                while stack:
                    node = stack.pop()
                    if node in visited:
                        continue
                    visited.add(node)
                    order_hint.append(node)
                    children = [child for child in adjacency.get(node, []) if child in component]
                    for child in reversed(children):
                        if child not in visited:
                            stack.append(child)
            for proc_id in sorted(component, key=node_key):
                if proc_id in visited:
                    continue
                stack = [proc_id]
                while stack:
                    node = stack.pop()
                    if node in visited:
                        continue
                    visited.add(node)
                    order_hint.append(node)
                    children = [child for child in adjacency.get(node, []) if child in component]
                    for child in reversed(children):
                        if child not in visited:
                            stack.append(child)

        for proc_id in proc_ids:
            if proc_id not in visited:
                order_hint.append(proc_id)
        return order_hint

    def _normalize_procedure_graph(
        self, proc_ids: list[str], procedure_graph: dict[str, list[str]]
    ) -> dict[str, list[str]]:
        adjacency: dict[str, list[str]] = {proc_id: [] for proc_id in proc_ids}
        for parent, children in procedure_graph.items():
            if parent not in adjacency:
                continue
            seen: set[str] = set()
            cleaned: list[str] = []
            for child in children:
                if child in adjacency and child != parent and child not in seen:
                    cleaned.append(child)
                    seen.add(child)
            if cleaned:
                adjacency[parent].extend(cleaned)
        return adjacency

    def _block_graph_nodes(self, document: MarkupDocument) -> set[str]:
        return build_directed_graph(document.block_graph).vertices

    def _resolved_block_graph_edges(
        self,
        document: MarkupDocument,
        procedures: Sequence[Procedure],
        owned_blocks_by_proc: Mapping[str, set[str]],
    ) -> list[ResolvedBlockGraphEdge]:
        if not document.block_graph:
            return []
        owners_by_block = build_block_owner_index(procedures, owned_blocks_by_proc)
        return resolve_block_graph_edges(
            document.block_graph,
            owners_by_block,
            document.procedure_graph,
        )

    def _layout_edges_by_proc(
        self,
        document: MarkupDocument,
        procedures: Sequence[Procedure],
        owned_blocks_by_proc: Mapping[str, set[str]],
    ) -> dict[str, dict[str, list[str]]]:
        if not document.block_graph:
            return {proc.procedure_id: dict(proc.branches) for proc in procedures}

        edges_by_proc: dict[str, dict[str, list[str]]] = {
            proc.procedure_id: {} for proc in procedures
        }
        resolved_edges = self._resolved_block_graph_edges(
            document, procedures, owned_blocks_by_proc
        )
        for edge in resolved_edges:
            if edge.source_procedure_id != edge.target_procedure_id:
                continue
            edges = edges_by_proc.setdefault(edge.source_procedure_id, {}).setdefault(
                edge.source_block_id, []
            )
            if edge.target_block_id not in edges:
                edges.append(edge.target_block_id)

        return edges_by_proc

    def _cross_procedure_edges(
        self,
        document: MarkupDocument,
        procedures: Sequence[Procedure],
        owned_blocks_by_proc: Mapping[str, set[str]],
    ) -> set[tuple[str, str]]:
        if not document.block_graph:
            return set()

        edges: set[tuple[str, str]] = set()
        resolved_edges = self._resolved_block_graph_edges(
            document, procedures, owned_blocks_by_proc
        )
        for edge in resolved_edges:
            if edge.source_procedure_id == edge.target_procedure_id:
                continue
            edges.add((edge.source_procedure_id, edge.target_procedure_id))
        return edges

    def _component_frame_offsets(
        self,
        component: set[str],
        cross_proc_edges: set[tuple[str, str]],
        order_index: Mapping[str, int],
        sizing: Mapping[str, Size],
    ) -> dict[str, float]:
        if not cross_proc_edges:
            return {}
        offsets: dict[str, float] = {}
        for source_proc, target_proc in cross_proc_edges:
            if source_proc not in component or target_proc not in component:
                continue
            src_idx = order_index.get(source_proc)
            tgt_idx = order_index.get(target_proc)
            if src_idx is None or tgt_idx is None:
                continue
            if tgt_idx <= src_idx:
                continue
            if tgt_idx - src_idx < 2:
                continue
            low, high = src_idx, tgt_idx
            for proc_id in component:
                proc_idx = order_index.get(proc_id)
                if proc_idx is None or proc_idx <= low or proc_idx >= high:
                    continue
                frame_size = sizing.get(proc_id)
                if not frame_size:
                    continue
                shift = frame_size.height + self.config.lane_gap
                offsets[proc_id] = max(offsets.get(proc_id, 0.0), shift)
        return offsets

    def _end_block_row_offsets(
        self,
        document: MarkupDocument,
        procedures: Sequence[Procedure],
        owned_blocks_by_proc: Mapping[str, set[str]],
    ) -> dict[str, dict[str, float]]:
        if not document.block_graph:
            return {}

        end_blocks_by_proc = {proc.procedure_id: set(proc.end_block_ids) for proc in procedures}
        offsets: dict[str, dict[str, float]] = {proc.procedure_id: {} for proc in procedures}
        resolved_edges = self._resolved_block_graph_edges(
            document, procedures, owned_blocks_by_proc
        )
        edges_by_source: dict[tuple[str, str], list[ResolvedBlockGraphEdge]] = {}
        for edge in resolved_edges:
            edges_by_source.setdefault((edge.source_procedure_id, edge.source_block_id), []).append(
                edge
            )

        for (source_proc, _source_block), source_edges in edges_by_source.items():
            has_external = any(edge.target_procedure_id != source_proc for edge in source_edges)
            if not has_external:
                continue
            for edge in source_edges:
                if edge.target_procedure_id != source_proc:
                    continue
                if edge.target_block_id not in end_blocks_by_proc.get(source_proc, set()):
                    continue
                offsets[source_proc][edge.target_block_id] = 1.0

        return offsets

    def _adjust_start_markers_for_edges(
        self,
        document: MarkupDocument,
        blocks: Sequence[BlockPlacement],
        markers: list[MarkerPlacement],
    ) -> None:
        edge_segments = self._block_edge_segments(document, blocks)
        if not edge_segments:
            return
        start_markers = [m for m in markers if m.role == "start_marker"]
        if not start_markers:
            return
        row_shift = self.config.block_size.height + self.config.gap_y
        diag_shift = max(8.0, self.config.gap_x * 0.2)

        for idx, marker in enumerate(markers):
            if marker.role != "start_marker":
                continue
            if not self._segment_intersects_rect_any(edge_segments, marker):
                continue
            updated = marker
            for _ in range(3):
                updated = MarkerPlacement(
                    procedure_id=updated.procedure_id,
                    block_id=updated.block_id,
                    role=updated.role,
                    position=Point(
                        updated.position.x - diag_shift,
                        updated.position.y + row_shift,
                    ),
                    size=updated.size,
                    end_type=updated.end_type,
                )
                if not self._segment_intersects_rect_any(edge_segments, updated):
                    break
            markers[idx] = updated

    def _adjust_blocks_for_edges(
        self,
        document: MarkupDocument,
        blocks: list[BlockPlacement],
        markers: list[MarkerPlacement],
    ) -> None:
        edge_segments = self._block_edge_segments_with_blocks(document, blocks)
        if not edge_segments:
            return

        start_blocks: set[tuple[str, str]] = set()
        for proc in document.procedures:
            for block_id in proc.start_block_ids:
                start_blocks.add((proc.procedure_id, block_id))

        block_index = {
            (block.procedure_id, block.block_id): idx for idx, block in enumerate(blocks)
        }
        row_shift = self.config.block_size.height + self.config.gap_y

        def shift_block(proc_id: str, block_id: str, dy: float) -> None:
            idx = block_index.get((proc_id, block_id))
            if idx is None:
                return
            block = blocks[idx]
            blocks[idx] = BlockPlacement(
                procedure_id=block.procedure_id,
                block_id=block.block_id,
                position=Point(block.position.x, block.position.y + dy),
                size=block.size,
            )
            for marker_idx, marker in enumerate(markers):
                if marker.procedure_id == proc_id and marker.block_id == block_id:
                    markers[marker_idx] = MarkerPlacement(
                        procedure_id=marker.procedure_id,
                        block_id=marker.block_id,
                        role=marker.role,
                        position=Point(marker.position.x, marker.position.y + dy),
                        size=marker.size,
                        end_type=marker.end_type,
                    )

        for proc_id, block_id in start_blocks:
            idx = block_index.get((proc_id, block_id))
            if idx is None:
                continue
            for _ in range(3):
                block = blocks[idx]
                rect = self._rect_bounds(block.position, block.size)
                intersects = False
                for source_block, target_block, start, end in edge_segments:
                    if (
                        source_block.block_id == block.block_id
                        and source_block.procedure_id == block.procedure_id
                    ) or (
                        target_block.block_id == block.block_id
                        and target_block.procedure_id == block.procedure_id
                    ):
                        continue
                    if self._segment_intersects_rect(start, end, rect):
                        intersects = True
                        break
                if not intersects:
                    break
                shift_block(proc_id, block_id, row_shift)
                edge_segments = self._block_edge_segments_with_blocks(document, blocks)

    def _segment_intersects_rect_any(
        self,
        edge_segments: Sequence[tuple[Point, Point]],
        marker: MarkerPlacement,
    ) -> bool:
        rect = self._rect_bounds(marker.position, marker.size)
        for start, end in edge_segments:
            if self._segment_intersects_rect(start, end, rect):
                return True
        return False

    def _block_edge_segments(
        self,
        document: MarkupDocument,
        blocks: Sequence[BlockPlacement],
    ) -> list[tuple[Point, Point]]:
        block_by_proc_id: dict[tuple[str, str], BlockPlacement] = {
            (block.procedure_id, block.block_id): block for block in blocks
        }
        block_by_id: dict[str, list[BlockPlacement]] = {}
        for block in blocks:
            block_by_id.setdefault(block.block_id, []).append(block)

        segments: list[tuple[Point, Point]] = []
        if document.block_graph:
            block_graph_nodes = self._block_graph_nodes(document)
            owned_blocks_by_proc = self._resolve_owned_blocks(document, block_graph_nodes)
            resolved_edges = self._resolved_block_graph_edges(
                document,
                document.procedures,
                owned_blocks_by_proc,
            )
            for edge in resolved_edges:
                source_block = block_by_proc_id.get(
                    (edge.source_procedure_id, edge.source_block_id)
                )
                target_block = block_by_proc_id.get(
                    (edge.target_procedure_id, edge.target_block_id)
                )
                if not source_block or not target_block:
                    continue
                segments.append(self._block_edge_segment(source_block, target_block))
            return segments

        for proc in document.procedures:
            for source_id, targets in proc.branches.items():
                source_candidates = block_by_id.get(source_id, [])
                if len(source_candidates) != 1:
                    continue
                source_block = source_candidates[0]
                for target_id in targets:
                    target_candidates = block_by_id.get(target_id, [])
                    if len(target_candidates) != 1:
                        continue
                    target_block = target_candidates[0]
                    segments.append(self._block_edge_segment(source_block, target_block))
        return segments

    def _block_edge_segments_with_blocks(
        self,
        document: MarkupDocument,
        blocks: Sequence[BlockPlacement],
    ) -> list[tuple[BlockPlacement, BlockPlacement, Point, Point]]:
        block_by_proc_id: dict[tuple[str, str], BlockPlacement] = {
            (block.procedure_id, block.block_id): block for block in blocks
        }
        block_by_id: dict[str, list[BlockPlacement]] = {}
        for block in blocks:
            block_by_id.setdefault(block.block_id, []).append(block)

        segments: list[tuple[BlockPlacement, BlockPlacement, Point, Point]] = []
        if document.block_graph:
            block_graph_nodes = self._block_graph_nodes(document)
            owned_blocks_by_proc = self._resolve_owned_blocks(document, block_graph_nodes)
            resolved_edges = self._resolved_block_graph_edges(
                document,
                document.procedures,
                owned_blocks_by_proc,
            )
            for edge in resolved_edges:
                source_block = block_by_proc_id.get(
                    (edge.source_procedure_id, edge.source_block_id)
                )
                target_block = block_by_proc_id.get(
                    (edge.target_procedure_id, edge.target_block_id)
                )
                if not source_block or not target_block:
                    continue
                start, end = self._block_edge_segment(source_block, target_block)
                segments.append((source_block, target_block, start, end))
            return segments

        for proc in document.procedures:
            for source_id, targets in proc.branches.items():
                source_candidates = block_by_id.get(source_id, [])
                if len(source_candidates) != 1:
                    continue
                source_block = source_candidates[0]
                for target_id in targets:
                    target_candidates = block_by_id.get(target_id, [])
                    if len(target_candidates) != 1:
                        continue
                    target_block = target_candidates[0]
                    start, end = self._block_edge_segment(source_block, target_block)
                    segments.append((source_block, target_block, start, end))
        return segments

    def _block_edge_segment(
        self,
        source_block: BlockPlacement,
        target_block: BlockPlacement,
    ) -> tuple[Point, Point]:
        if target_block.position.x >= source_block.position.x:
            start = self._block_anchor(source_block, side="right")
            end = self._block_anchor(target_block, side="left")
        else:
            start = self._block_anchor(source_block, side="left")
            end = self._block_anchor(target_block, side="right")
        return start, end

    def _block_anchor(
        self,
        placement: BlockPlacement,
        side: str,
    ) -> Point:
        if side == "left":
            return Point(
                placement.position.x,
                placement.position.y + placement.size.height / 2,
            )
        if side == "right":
            return Point(
                placement.position.x + placement.size.width,
                placement.position.y + placement.size.height / 2,
            )
        raise ValueError(f"Unsupported side: {side}")

    def _rect_bounds(self, origin: Point, size: Size) -> tuple[float, float, float, float]:
        return (origin.x, origin.y, origin.x + size.width, origin.y + size.height)

    def _segment_intersects_rect(
        self,
        start: Point,
        end: Point,
        rect: tuple[float, float, float, float],
    ) -> bool:
        x1, y1 = start.x, start.y
        x2, y2 = end.x, end.y
        rx1, ry1, rx2, ry2 = rect

        if rx1 <= x1 <= rx2 and ry1 <= y1 <= ry2:
            return True
        if rx1 <= x2 <= rx2 and ry1 <= y2 <= ry2:
            return True

        def ccw(a: Point, b: Point, c: Point) -> bool:
            return (c.y - a.y) * (b.x - a.x) > (b.y - a.y) * (c.x - a.x)

        def intersects(a: Point, b: Point, c: Point, d: Point) -> bool:
            return ccw(a, c, d) != ccw(b, c, d) and ccw(a, b, c) != ccw(a, b, d)

        edges = [
            (Point(rx1, ry1), Point(rx2, ry1)),
            (Point(rx2, ry1), Point(rx2, ry2)),
            (Point(rx2, ry2), Point(rx1, ry2)),
            (Point(rx1, ry2), Point(rx1, ry1)),
        ]
        for edge_start, edge_end in edges:
            if intersects(start, end, edge_start, edge_end):
                return True
        return False

    def _resolve_owned_blocks(
        self,
        document: MarkupDocument,
        block_graph_nodes: set[str] | None = None,
    ) -> dict[str, set[str]]:
        explicit_owners: dict[str, set[str]] = {}
        for procedure in document.procedures:
            proc_id = procedure.procedure_id
            explicit_blocks = (
                set(procedure.start_block_ids)
                | set(procedure.end_block_ids)
                | set(procedure.branches.keys())
            )
            if block_graph_nodes:
                explicit_blocks.update(
                    set(procedure.block_id_to_block_name.keys()) & block_graph_nodes
                )
            for block_id in explicit_blocks:
                explicit_owners.setdefault(block_id, set()).add(proc_id)

        owned_by_proc: dict[str, set[str]] = {}
        for procedure in document.procedures:
            proc_id = procedure.procedure_id
            owned: set[str] = set()
            for block_id, owners in explicit_owners.items():
                if proc_id in owners:
                    owned.add(block_id)
            for targets in procedure.branches.values():
                for target in targets:
                    if target not in explicit_owners:
                        owned.add(target)
            owned_by_proc[proc_id] = owned
        return owned_by_proc

    def _infer_procedure_graph_from_block_graph(
        self,
        block_graph: Mapping[str, list[str]],
        procedures: Sequence[Procedure],
        owned_blocks_by_proc: Mapping[str, set[str]] | None = None,
    ) -> dict[str, list[str]]:
        proc_for_block: dict[str, str] = {}
        duplicates: set[str] = set()
        for procedure in procedures:
            block_ids = (
                owned_blocks_by_proc.get(procedure.procedure_id)
                if owned_blocks_by_proc is not None
                else procedure.block_ids()
            )
            if block_ids is None:
                block_ids = procedure.block_ids()
            for block_id in block_ids:
                if block_id in proc_for_block:
                    duplicates.add(block_id)
                else:
                    proc_for_block[block_id] = procedure.procedure_id

        adjacency: dict[str, list[str]] = {}
        for source_block, targets in block_graph.items():
            if source_block in duplicates:
                continue
            source_proc = proc_for_block.get(source_block)
            if not source_proc:
                continue
            for target_block in targets:
                if target_block in duplicates:
                    continue
                target_proc = proc_for_block.get(target_block)
                if not target_proc or target_proc == source_proc:
                    continue
                adjacency.setdefault(source_proc, [])
                if target_proc not in adjacency[source_proc]:
                    adjacency[source_proc].append(target_proc)

        for procedure in procedures:
            adjacency.setdefault(procedure.procedure_id, [])
        return adjacency

    def _procedure_components(
        self, proc_ids: list[str], adjacency: dict[str, list[str]]
    ) -> list[set[str]]:
        undirected: dict[str, set[str]] = {proc_id: set() for proc_id in proc_ids}
        for parent, children in adjacency.items():
            for child in children:
                if child not in undirected:
                    continue
                undirected[parent].add(child)
                undirected[child].add(parent)
        visited: set[str] = set()
        components: list[set[str]] = []
        for node in proc_ids:
            if node in visited:
                continue
            stack = [node]
            component: set[str] = set()
            while stack:
                current = stack.pop()
                if current in visited:
                    continue
                visited.add(current)
                component.add(current)
                stack.extend(undirected.get(current, set()) - visited)
            components.append(component)
        return components

    def _procedure_levels(
        self,
        component: set[str],
        adjacency: dict[str, list[str]],
        order_index: dict[str, int],
    ) -> dict[str, int]:
        indegree: dict[str, int] = {proc_id: 0 for proc_id in component}
        for _parent, children in adjacency.items():
            for child in children:
                if child in indegree:
                    indegree[child] += 1
        queue = [
            (order_index.get(proc_id, 0), proc_id) for proc_id, deg in indegree.items() if deg == 0
        ]
        heapq.heapify(queue)
        levels: dict[str, int] = {proc_id: 0 for proc_id in component}
        while queue:
            _, node = heapq.heappop(queue)
            for child in adjacency.get(node, []):
                if child not in levels:
                    continue
                levels[child] = max(levels.get(child, 0), levels.get(node, 0) + 1)
                indegree[child] -= 1
                if indegree[child] == 0:
                    heapq.heappush(queue, (order_index.get(child, 0), child))
        return levels

    def _find_cycle_edges(
        self, adjacency: dict[str, list[str]], order_index: dict[str, int] | None = None
    ) -> set[tuple[str, str]]:
        nodes = set(adjacency.keys())
        for children in adjacency.values():
            nodes.update(children)
        visited: dict[str, int] = {}
        cycle_edges: set[tuple[str, str]] = set()

        def sort_key(node_id: str) -> tuple[int, str]:
            if order_index is None:
                return (0, node_id)
            return (order_index.get(node_id, 0), node_id)

        def dfs(node: str) -> None:
            visited[node] = 1
            for child in sorted(adjacency.get(node, []), key=sort_key):
                state = visited.get(child, 0)
                if state == 0:
                    dfs(child)
                elif state == 1:
                    cycle_edges.add((node, child))
            visited[node] = 2

        for node in sorted(nodes, key=sort_key):
            if visited.get(node, 0) == 0:
                dfs(node)
        return cycle_edges

    def _compute_block_levels(
        self,
        procedure: Procedure,
        owned_blocks: set[str] | None = None,
        layout_edges: Mapping[str, list[str]] | None = None,
        turn_out_blocks: set[str] | None = None,
        end_block_row_offsets: Mapping[str, float] | None = None,
    ) -> tuple[
        dict[str, int],
        int,
        dict[int, float],
        list[str],
        dict[str, float],
        dict[str, NodeInfo],
    ]:
        edges_for_layout = layout_edges if layout_edges is not None else procedure.branches
        start_blocks = list(procedure.start_block_ids)
        end_blocks = list(procedure.end_block_ids)
        end_block_types = procedure.end_block_types
        allowed_blocks: set[str] | None = set(owned_blocks) if owned_blocks is not None else None
        if allowed_blocks is not None:
            allowed_blocks.update(start_blocks)
            allowed_blocks.update(end_blocks)
            allowed_blocks.update(edges_for_layout.keys())
        turn_out_sources = set(turn_out_blocks or set(procedure.branches.keys()))
        if end_blocks:
            end_block_set = set(end_blocks)
            for block_id in list(turn_out_sources):
                if block_id not in end_block_set:
                    continue
                end_type = normalize_end_type(end_block_types.get(block_id)) or END_TYPE_DEFAULT
                if end_type != "intermediate":
                    turn_out_sources.discard(block_id)
        turn_out_block_list = sorted(
            {
                block
                for block in turn_out_sources
                if allowed_blocks is None or block in allowed_blocks
            }
        )

        branches_for_layout: dict[str, list[str]] = {}
        for source, targets in edges_for_layout.items():
            if allowed_blocks is not None and source not in allowed_blocks:
                continue
            seen: set[str] = set()
            cleaned: list[str] = []
            for target in targets:
                if allowed_blocks is not None and target not in allowed_blocks:
                    continue
                if target in seen:
                    continue
                seen.add(target)
                cleaned.append(target)
            branches_for_layout[source] = cleaned

        order_hint: list[str] = []
        seen_nodes: set[str] = set()

        def track(node_id: str) -> None:
            if node_id in seen_nodes:
                return
            seen_nodes.add(node_id)
            order_hint.append(node_id)

        for block_id in start_blocks:
            track(block_id)
        for source, targets in branches_for_layout.items():
            track(source)
            for target in targets:
                track(target)
        for block_id in end_blocks:
            track(block_id)

        order_index = {node_id: idx for idx, node_id in enumerate(order_hint)}
        cycle_edges = self._find_cycle_edges(branches_for_layout, order_index)
        if cycle_edges:
            for source, target in cycle_edges:
                branches_for_layout[source] = [
                    child for child in branches_for_layout.get(source, []) if child != target
                ]

        node_info: dict[str, NodeInfo] = {}
        if allowed_blocks is None:
            all_blocks = set(start_blocks) | set(end_blocks)
            for src, targets in edges_for_layout.items():
                all_blocks.add(src)
                all_blocks.update(targets)
        else:
            all_blocks = set(allowed_blocks)
            all_blocks.update(start_blocks)
            all_blocks.update(end_blocks)

        for block_id in all_blocks:
            node_info.setdefault(block_id, NodeInfo(kind="block", block_id=block_id))

        end_marker_types: dict[str, set[str]] = {}
        for block_id in end_blocks:
            if block_id not in all_blocks:
                continue
            base_type = normalize_end_type(end_block_types.get(block_id)) or END_TYPE_DEFAULT
            end_marker_types.setdefault(block_id, set()).add(base_type)
        for block_id in turn_out_block_list:
            if block_id not in all_blocks:
                continue
            if block_id in end_blocks:
                continue
            end_marker_types.setdefault(block_id, set()).add(END_TYPE_TURN_OUT)

        end_nodes: dict[str, NodeInfo] = {}
        for block_id, types in sorted(end_marker_types.items()):
            for end_type in sorted(types):
                node_id = f"__end_marker__{end_type}::{block_id}"
                end_nodes[node_id] = NodeInfo(
                    kind="end_marker", block_id=block_id, end_type=end_type
                )

        node_info.update(end_nodes)
        all_nodes = set(node_info.keys())

        indegree: dict[str, int] = {node_id: 0 for node_id in all_nodes}
        adj: dict[str, list[str]] = {node_id: [] for node_id in all_nodes}
        for src, targets in branches_for_layout.items():
            for tgt in targets:
                adj[src].append(tgt)
                indegree[tgt] = indegree.get(tgt, 0) + 1

        for node_id, info in end_nodes.items():
            adj[info.block_id].append(node_id)
            indegree[node_id] = indegree.get(node_id, 0) + 1

        start_nodes = set(start_blocks)

        def sort_key(
            node_id: str, levels: dict[str, int] | None = None
        ) -> tuple[int, int, int, str, str]:
            info = node_info.get(node_id)
            level = 0 if levels is None else levels.get(node_id, 0)
            start_rank = 0 if node_id in start_nodes else 1
            kind_rank = 0 if info and info.kind == "block" else 1
            block_id = info.block_id if info else node_id
            end_type = info.end_type if info and info.end_type else ""
            return (level, start_rank, kind_rank, block_id, end_type)

        queue = sorted(all_nodes, key=lambda n: sort_key(n))
        queue = [n for n in queue if indegree.get(n, 0) == 0]
        levels: dict[str, int] = {}
        order: list[str] = []
        while queue:
            node = queue.pop(0)
            level = levels.get(node, 0)
            levels[node] = level
            order.append(node)
            for neighbor in adj.get(node, []):
                levels[neighbor] = max(levels.get(neighbor, 0), level + 1)
                indegree[neighbor] -= 1
                if indegree[neighbor] == 0:
                    queue.append(neighbor)
                    queue.sort(key=lambda n: sort_key(n, levels))

        for node_id in all_nodes:
            levels.setdefault(node_id, 0)

        # Ensure end blocks have at least computed level (do not force extra column to keep arrows short).
        for end_block in end_blocks:
            levels.setdefault(end_block, max(levels.values() or [0]))
        if start_blocks:
            for node_id in all_nodes:
                if node_id not in start_nodes:
                    levels[node_id] = max(levels.get(node_id, 0), 1)

            changed = True
            while changed:
                changed = False
                for src, targets in adj.items():
                    src_level = levels.get(src, 0)
                    for tgt in targets:
                        if levels.get(tgt, 0) < src_level + 1:
                            levels[tgt] = src_level + 1
                            changed = True

        max_level = max(levels.values() or [0])

        branch_counts = {
            block: len(targets)
            for block, targets in edges_for_layout.items()
            if allowed_blocks is None or block in allowed_blocks
        }
        level_buckets: dict[int, list[str]] = {lvl: [] for lvl in range(max_level + 1)}
        for node_id, lvl in levels.items():
            level_buckets.setdefault(lvl, []).append(node_id)

        end_block_set = set(end_blocks)

        def base_order_key(node_id: str) -> tuple[int, int, int, str, str]:
            info = node_info.get(node_id)
            start_rank = 0 if node_id in start_nodes else 1
            kind_rank = 0 if info and info.kind == "block" else 1
            end_type = (
                normalize_end_type(end_block_types.get(info.block_id))
                if info and info.kind == "block"
                else None
            )
            normalized_end_type = end_type or END_TYPE_DEFAULT
            end_rank = (
                1
                if info
                and info.kind == "block"
                and info.block_id in end_block_set
                and normalized_end_type != "intermediate"
                else 0
            )
            block_id = info.block_id if info else node_id
            end_sort = info.end_type if info and info.end_type else ""
            return (start_rank, kind_rank, end_rank, block_id, end_sort)

        order_index = {node_id: idx for idx, node_id in enumerate(order)}
        level_order: dict[int, list[str]] = {}
        for lvl in range(max_level + 1):
            nodes = [
                node_id
                for node_id in level_buckets.get(lvl, [])
                if node_info.get(node_id) and node_info[node_id].kind == "block"
            ]

            def combined_key(node_id: str) -> tuple[int, int, int, int, str, str]:
                base = base_order_key(node_id)
                end_bias = 1 if base[2] == 1 else 0
                return (
                    base[0],
                    base[1],
                    order_index.get(node_id, 0) + end_bias,
                    base[2],
                    base[3],
                    base[4],
                )

            nodes.sort(key=combined_key)
            level_order[lvl] = nodes

        incoming: dict[str, list[str]] = {node_id: [] for node_id in all_nodes}
        for src, targets in adj.items():
            for tgt in targets:
                incoming.setdefault(tgt, []).append(src)

        block_children: dict[str, list[str]] = {}
        for src, targets in adj.items():
            src_info = node_info.get(src)
            if not src_info or src_info.kind != "block":
                continue
            block_targets = [
                tgt for tgt in targets if node_info.get(tgt) and node_info[tgt].kind == "block"
            ]
            if block_targets:
                block_children[src] = block_targets

        child_signatures: dict[str, tuple[str, ...]] = {}
        for node_id, children in block_children.items():
            if children:
                child_signatures[node_id] = tuple(sorted(children))
        if child_signatures:
            for lvl, nodes in level_order.items():
                if len(nodes) < 2:
                    continue
                original_index = {node_id: idx for idx, node_id in enumerate(nodes)}
                first_index: dict[tuple[str, ...], int] = {}
                for node_id in nodes:
                    signature = child_signatures.get(node_id)
                    if signature and signature not in first_index:
                        first_index[signature] = original_index[node_id]
                if not first_index:
                    continue

                def group_key(
                    node_id: str,
                    _original_index: dict[str, int] = original_index,
                    _first_index: dict[tuple[str, ...], int] = first_index,
                ) -> tuple[int, int, str]:
                    idx = _original_index[node_id]
                    signature = child_signatures.get(node_id)
                    if signature is None:
                        anchor = idx
                    else:
                        anchor = _first_index.get(signature, idx)
                    return (anchor, idx, node_id)

                nodes.sort(key=group_key)
                level_order[lvl] = nodes

        descendant_cache: dict[str, int] = {}

        def descendant_count(node_id: str) -> int:
            cached = descendant_cache.get(node_id)
            if cached is not None:
                return cached
            total = 0
            for child in block_children.get(node_id, []):
                total += 1 + descendant_count(child)
            descendant_cache[node_id] = total
            return total

        primary_parent: dict[str, str] = {}
        for parent, targets in block_children.items():
            if len(targets) == 1:
                primary_parent[targets[0]] = parent
                continue
            ranked = sorted(targets, key=lambda tgt: (-descendant_count(tgt), tgt))
            primary_parent[ranked[0]] = parent

        def update_positions() -> dict[str, float]:
            current: dict[str, float] = {}
            for nodes in level_order.values():
                for idx, node_id in enumerate(nodes):
                    current[node_id] = float(idx)
            return current

        positions = update_positions()

        # Barycentric sweeps keep connected nodes closer across columns.
        for _ in range(3):
            for lvl in range(1, max_level + 1):
                nodes = level_order.get(lvl, [])
                if not nodes:
                    continue
                index = {node_id: idx for idx, node_id in enumerate(nodes)}

                def anchor_parent(
                    node_id: str,
                    _lvl: int = lvl,
                    _positions: dict[str, float] = positions,
                    _index: dict[str, int] = index,
                ) -> float:
                    parents = [
                        parent
                        for parent in incoming.get(node_id, [])
                        if levels.get(parent, 0) == _lvl - 1
                        and node_info.get(parent)
                        and node_info[parent].kind == "block"
                    ]
                    if parents:
                        return sum(_positions.get(p, 0.0) for p in parents) / len(parents)
                    return _positions.get(node_id, float(_index[node_id]))

                nodes.sort(key=lambda n: (anchor_parent(n), index[n], n))
                level_order[lvl] = nodes
            positions = update_positions()

            for lvl in range(max_level - 1, -1, -1):
                nodes = level_order.get(lvl, [])
                if not nodes:
                    continue
                index = {node_id: idx for idx, node_id in enumerate(nodes)}

                def anchor_child(
                    node_id: str,
                    _lvl: int = lvl,
                    _positions: dict[str, float] = positions,
                    _index: dict[str, int] = index,
                ) -> float:
                    parents = [
                        parent
                        for parent in incoming.get(node_id, [])
                        if levels.get(parent, 0) == _lvl - 1
                        and node_info.get(parent)
                        and node_info[parent].kind == "block"
                    ]
                    if not parents:
                        return _positions.get(node_id, float(_index[node_id]))
                    children = [
                        child
                        for child in adj.get(node_id, [])
                        if levels.get(child, 0) == _lvl + 1
                        and node_info.get(child)
                        and node_info[child].kind == "block"
                    ]
                    if children:
                        return sum(_positions.get(c, 0.0) for c in children) / len(children)
                    return _positions.get(node_id, float(_index[node_id]))

                nodes.sort(key=lambda n: (anchor_child(n), index[n], n))
                level_order[lvl] = nodes
            positions = update_positions()

        def row_span(node_id: str) -> float:
            info = node_info.get(node_id)
            if info and info.kind == "block":
                branch_count = branch_counts.get(info.block_id, 0)
                return float(max(1, branch_count))
            return 1.0

        row_positions: dict[str, float] = {}
        for lvl in range(max_level + 1):
            row = 0.0
            for node_id in level_order.get(lvl, []):
                row_positions[node_id] = row
                row += row_span(node_id)
        base_row_positions = dict(row_positions)

        def apply_row_smoothing() -> None:
            for lvl in range(max_level + 1):
                nodes = level_order.get(lvl, [])
                if not nodes:
                    continue
                desired: dict[str, float] = {}
                for node_id in nodes:
                    parent_anchors: list[float] = []
                    for parent in incoming.get(node_id, []):
                        if levels.get(parent, 0) == lvl - 1:
                            parent_anchors.append(row_positions.get(parent, 0.0))
                    anchors = list(parent_anchors)
                    if parent_anchors:
                        for child in adj.get(node_id, []):
                            if levels.get(child, 0) == lvl + 1:
                                info = node_info.get(node_id)
                                child_info = node_info.get(child)
                                # Keep end markers aligned to blocks without pulling block rows.
                                if (
                                    info
                                    and info.kind == "block"
                                    and child_info
                                    and child_info.kind == "end_marker"
                                ):
                                    continue
                                anchors.append(row_positions.get(child, 0.0))
                    if anchors:
                        desired[node_id] = sum(anchors) / len(anchors)
                    else:
                        desired[node_id] = base_row_positions.get(
                            node_id, row_positions.get(node_id, 0.0)
                        )
                    parent_id = primary_parent.get(node_id)
                    if (
                        parent_id
                        and levels.get(parent_id, 0) == lvl - 1
                        and len(incoming.get(node_id, [])) == 1
                    ):
                        desired[node_id] = row_positions.get(parent_id, desired[node_id])
                index = {node_id: idx for idx, node_id in enumerate(nodes)}
                nodes.sort(key=lambda n: (desired.get(n, 0.0), index[n], n))
                level_order[lvl] = nodes
                prev_pos: float | None = None
                prev_span = 0.0
                for node_id in nodes:
                    target = desired.get(node_id, 0.0)
                    if prev_pos is None:
                        pos = max(0.0, target)
                    else:
                        pos = max(target, prev_pos + prev_span)
                    row_positions[node_id] = pos
                    prev_pos = pos
                    prev_span = row_span(node_id)

        for _ in range(3):
            apply_row_smoothing()
        apply_row_smoothing()

        if end_block_row_offsets:
            for node_id, info in node_info.items():
                if info.kind != "block":
                    continue
                offset = end_block_row_offsets.get(info.block_id)
                if offset is None:
                    continue
                row_positions[node_id] = row_positions.get(node_id, 0.0) + offset
            for lvl in range(max_level + 1):
                nodes = level_order.get(lvl, [])
                if not nodes:
                    continue
                nodes.sort(key=lambda n: (row_positions.get(n, 0.0), n))
                prev_pos: float | None = None
                prev_span = 0.0
                for node_id in nodes:
                    pos = row_positions.get(node_id, 0.0)
                    if prev_pos is None:
                        pos = max(0.0, pos)
                    else:
                        pos = max(pos, prev_pos + prev_span)
                    row_positions[node_id] = pos
                    prev_pos = pos
                    prev_span = row_span(node_id)

        occupied_rows: dict[int, list[float]] = {}
        for node_id, info in node_info.items():
            if info.kind != "block":
                continue
            lvl = levels.get(node_id, 0)
            occupied_rows.setdefault(lvl, []).append(row_positions.get(node_id, 0.0))

        marker_clearance = (self.config.block_size.height + self.config.marker_size.height) / (
            2 * (self.config.block_size.height + self.config.gap_y)
        )
        marker_clearance += 0.05

        def row_taken(level: int, row: float) -> bool:
            return any(abs(row - occ) < marker_clearance for occ in occupied_rows.get(level, []))

        end_marker_nodes = [
            node_id for node_id, info in node_info.items() if info.kind == "end_marker"
        ]
        end_marker_nodes.sort(
            key=lambda node_id: (
                levels.get(node_id, 0),
                row_positions.get(node_info[node_id].block_id, row_positions.get(node_id, 0.0)),
                node_id,
            )
        )
        for node_id in end_marker_nodes:
            info = node_info[node_id]
            level = levels.get(node_id, 0)
            target_row = row_positions.get(info.block_id, row_positions.get(node_id, 0.0))
            if info.end_type == END_TYPE_TURN_OUT:
                target_row += 1.0
            row = target_row
            while row_taken(level, row):
                row += 1.0
            row_positions[node_id] = row
            occupied_rows.setdefault(level, []).append(row)

        ordered: list[str] = []
        row_counts: dict[int, float] = {}
        for lvl in range(max_level + 1):
            nodes = [node_id for node_id in all_nodes if levels.get(node_id, 0) == lvl]
            nodes.sort(
                key=lambda node_id: (
                    row_positions.get(node_id, 0.0),
                    0 if node_info[node_id].kind == "block" else 1,
                    node_id,
                )
            )
            ordered.extend(nodes)
            if nodes:
                level_max = max(row_positions[node_id] + row_span(node_id) for node_id in nodes)
                row_counts[lvl] = max(level_max, 1.0)
        if not row_counts:
            row_counts[0] = 1.0
        return levels, max_level, row_counts, ordered, row_positions, node_info
