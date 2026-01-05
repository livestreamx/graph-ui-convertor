from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Tuple

from domain.models import (
    BlockPlacement,
    END_TYPE_DEFAULT,
    FramePlacement,
    LayoutPlan,
    MarkerPlacement,
    MarkupDocument,
    Point,
    ScenarioPlacement,
    SeparatorPlacement,
    Size,
    normalize_end_type,
)
from domain.ports.layout import LayoutEngine


@dataclass(frozen=True)
class LayoutConfig:
    block_size: Size = Size(260, 120)
    marker_size: Size = Size(180, 90)
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
    scenario_min_height: float = 180.0


@dataclass(frozen=True)
class NodeInfo:
    kind: str  # "block" or "end_marker"
    block_id: str
    end_type: str | None = None


class GridLayoutEngine(LayoutEngine):
    def __init__(self, config: LayoutConfig | None = None) -> None:
        self.config = config or LayoutConfig()

    def build_plan(self, document: MarkupDocument) -> LayoutPlan:
        frames: List[FramePlacement] = []
        blocks: List[BlockPlacement] = []
        markers: List[MarkerPlacement] = []
        separator_ys: List[float] = []
        scenarios: List[ScenarioPlacement] = []

        procedures = [proc for proc in document.procedures if proc.block_ids()]
        if not procedures:
            return LayoutPlan(
                frames=frames, blocks=blocks, markers=markers, separators=[], scenarios=[]
            )
        proc_ids = [proc.procedure_id for proc in procedures]
        order_hint = self._procedure_order_hint(procedures, document.procedure_graph)
        order_index = {proc_id: idx for idx, proc_id in enumerate(order_hint)}
        adjacency = self._normalize_procedure_graph(proc_ids, document.procedure_graph)
        sizing: Dict[str, Size] = {}

        # Pre-compute frame sizes using left-to-right levels inside each procedure.
        for procedure in procedures:
            _, max_level, row_counts, _, _, _ = self._compute_block_levels(procedure)
            cols = max_level + 1
            rows = max(row_counts.values() or [1])
            start_extra = self.config.marker_size.width + self.config.gap_x * 0.8
            frame_width = (
                self.config.padding * 2
                + start_extra
                + cols * self.config.block_size.width
                + ((cols - 1) * self.config.gap_x)
            )
            frame_height = self.config.padding * 2 + rows * self.config.block_size.height + (
                (rows - 1) * self.config.gap_y
            )
            sizing[procedure.procedure_id] = Size(
                frame_width + self.config.marker_size.width + self.config.gap_x * 0.5,
                frame_height + self.config.padding * 0.25,
            )

        lane_span = max((size.width for size in sizing.values()), default=0) + self.config.lane_gap
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
            level_nodes: Dict[int, List[str]] = {lvl: [] for lvl in range(max_level + 1)}
            for proc_id, lvl in levels.items():
                level_nodes.setdefault(lvl, []).append(proc_id)
            for lvl, nodes in level_nodes.items():
                nodes.sort(key=lambda proc_id: order_index.get(proc_id, 0))

            level_heights: Dict[int, float] = {}
            for lvl, nodes in level_nodes.items():
                if not nodes:
                    level_heights[lvl] = 0.0
                    continue
                total = sum(sizing[node].height for node in nodes)
                total += proc_gap_y * (len(nodes) - 1)
                level_heights[lvl] = total

            component_height = max(level_heights.values() or [0.0])
            for lvl, nodes in level_nodes.items():
                y = origin_y
                for proc_id in nodes:
                    frame_size = sizing[proc_id]
                    frame = FramePlacement(
                        procedure_id=proc_id,
                        origin=Point(origin_x + lvl * lane_span, y),
                        size=frame_size,
                    )
                    frames.append(frame)
                    y += frame_size.height + proc_gap_y

            if idx < len(components) - 1:
                separator_ys.append(origin_y + component_height + component_gap / 2)
                origin_y += component_height + component_gap
            else:
                origin_y += component_height + proc_gap_y

        procedure_map = {proc.procedure_id: proc for proc in procedures}
        for frame in frames:
            procedure = procedure_map.get(frame.procedure_id)
            if procedure is None:
                continue
            placement_by_block: Dict[str, BlockPlacement] = {}
            node_levels, max_level, _, order, row_positions, node_info = self._compute_block_levels(
                procedure
            )
            start_extra = self.config.marker_size.width + self.config.gap_x * 0.8
            level_rows: Dict[int, float] = {lvl: 0.0 for lvl in range(max_level + 1)}
            for node_id in order:
                level_idx = node_levels.get(node_id, 0)
                row_idx = row_positions.get(node_id, level_rows[level_idx])
                level_rows[level_idx] = max(level_rows[level_idx], row_idx + 1)

                x = frame.origin.x + self.config.padding + start_extra + level_idx * (
                    self.config.block_size.width + self.config.gap_x
                )
                y = frame.origin.y + self.config.padding + row_idx * (
                    self.config.block_size.height + self.config.gap_y
                )
                info = node_info.get(node_id)
                if not info:
                    continue
                if info.kind == "block":
                    placement = BlockPlacement(
                        procedure_id=procedure.procedure_id,
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
                            procedure_id=procedure.procedure_id,
                            block_id=info.block_id,
                            role="end_marker",
                            position=Point(x + offset_x, y + offset_y),
                            size=self.config.marker_size,
                            end_type=info.end_type,
                        )
                    )

            for start_block in procedure.start_block_ids:
                block = placement_by_block.get(start_block)
                if not block:
                    continue
                x = block.position.x - (self.config.marker_size.width + self.config.gap_x * 0.8)
                y = block.position.y + (block.size.height - self.config.marker_size.height) / 2
                markers.append(
                    MarkerPlacement(
                        procedure_id=procedure.procedure_id,
                        block_id=start_block,
                        role="start_marker",
                        position=Point(x, y),
                        size=self.config.marker_size,
                    )
                )

        separators: List[SeparatorPlacement] = []
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
                components, frames, procedure_map, document.procedure_graph, order_index
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
        components: List[set[str]],
        frames: List[FramePlacement],
        procedure_map: Dict[str, object],
        procedure_graph: Dict[str, List[str]],
        order_index: Dict[str, int],
    ) -> List[ScenarioPlacement]:
        scenarios: List[ScenarioPlacement] = []
        component_count = len(components)
        frame_lookup = {frame.procedure_id: frame for frame in frames}
        for idx, component in enumerate(components, start=1):
            component_frames = [
                frame_lookup[proc_id]
                for proc_id in component
                if proc_id in frame_lookup
            ]
            if not component_frames:
                continue
            min_x = min(frame.origin.x for frame in component_frames)
            max_x = max(frame.origin.x + frame.size.width for frame in component_frames)
            min_y = min(frame.origin.y for frame in component_frames)
            max_y = max(frame.origin.y + frame.size.height for frame in component_frames)
            title = "Граф" if component_count == 1 else f"Граф {idx}"
            labels = self._component_procedure_labels(
                component, procedure_map, frame_lookup
            )
            starts, ends, variants = self._component_stats(
                component, procedure_map, procedure_graph
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
            title_lines = self._wrap_lines(
                [title], max_width, self.config.scenario_title_font_size
            )
            cycle_lines: List[str] = []
            cycle_height = 0.0
            if cycle_text:
                cycle_lines = self._wrap_lines(
                    [cycle_text], max_width, self.config.scenario_cycle_font_size
                )
                cycle_height = (
                    len(cycle_lines) * self.config.scenario_cycle_font_size * 1.35
                )
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
        procedure_map: Dict[str, object],
        frame_lookup: Dict[str, FramePlacement],
    ) -> List[str]:
        entries: List[Tuple[float, bool, str, str]] = []
        for proc_id in sorted(component):
            proc = procedure_map.get(proc_id)
            if proc is None:
                continue
            frame = frame_lookup.get(proc_id)
            x_pos = frame.origin.x if frame else 0.0
            proc_name = getattr(proc, "procedure_name", None)
            label = f"{proc_name} ({proc_id})" if proc_name else proc_id
            has_start = bool(getattr(proc, "start_block_ids", []))
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

    def _wrap_lines(self, lines: List[str], max_width: float, font_size: float) -> List[str]:
        max_chars = max(1, int(max_width / (font_size * 0.6)))
        wrapped: List[str] = []
        for line in lines:
            if not line:
                wrapped.append("")
                continue
            words = line.split()
            current: List[str] = []
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
        procedure_map: Dict[str, object],
        procedure_graph: Dict[str, List[str]],
    ) -> Tuple[int, int, int]:
        start_blocks: set[str] = set()
        end_blocks: set[str] = set()
        branch_adjacency: Dict[str, List[str]] = {}
        branch_edges = 0
        for proc_id in component:
            proc = procedure_map.get(proc_id)
            if proc is None:
                continue
            for start_id in getattr(proc, "start_block_ids", []):
                start_blocks.add(start_id)
            for end_id in getattr(proc, "end_block_ids", []):
                end_blocks.add(end_id)
            branches = getattr(proc, "branches", {}) or {}
            if isinstance(branches, dict):
                for source, targets in branches.items():
                    if not isinstance(targets, list):
                        continue
                    if targets:
                        branch_edges += len(targets)
                    branch_adjacency.setdefault(str(source), []).extend(
                        str(target) for target in targets
                    )

        if branch_edges > 0:
            combinations = self._count_paths(branch_adjacency, list(start_blocks))
            if combinations <= 0 and component:
                combinations = 1
        else:
            combinations = self._procedure_graph_combinations(component, procedure_graph)

        return len(start_blocks), len(end_blocks), combinations

    def _component_graph_properties(
        self,
        component: set[str],
        procedure_graph: Dict[str, List[str]],
        order_index: Dict[str, int],
    ) -> Tuple[List[str], str | None]:
        adjacency: Dict[str, List[str]] = {node: [] for node in component}
        edge_count = 0
        for parent, children in procedure_graph.items():
            if parent not in component or not isinstance(children, list):
                continue
            for child in children:
                if child in component:
                    adjacency[parent].append(child)
                    edge_count += 1

        indegree: Dict[str, int] = {node: 0 for node in component}
        outdegree: Dict[str, int] = {node: len(adjacency.get(node, [])) for node in component}
        for parent, children in adjacency.items():
            for child in children:
                indegree[child] = indegree.get(child, 0) + 1

        sources = [node for node, deg in indegree.items() if deg == 0]
        sinks = [node for node, deg in outdegree.items() if deg == 0]
        has_branching = any(deg > 1 for deg in outdegree.values())
        has_merging = any(deg > 1 for deg in indegree.values())
        cycle_edges = self._find_cycle_edges(adjacency, order_index)
        cycle_count = len(cycle_edges)
        is_cyclic = cycle_count > 0

        undirected: Dict[str, set[str]] = {node: set() for node in component}
        for parent, children in adjacency.items():
            for child in children:
                undirected[parent].add(child)
                undirected[child].add(parent)
        connected = True
        if component:
            start = next(iter(component))
            stack = [start]
            visited: set[str] = set()
            while stack:
                node = stack.pop()
                if node in visited:
                    continue
                visited.add(node)
                stack.extend(undirected.get(node, set()) - visited)
            connected = visited == component

        cycle_text = None
        properties = []
        if is_cyclic:
            cycle_text = f"- цикличный, кол-во циклов: {cycle_count}"
        else:
            properties.append("- ацикличный")
        properties.extend(
            [
                "- ориентированный",
                "- слабосвязный" if connected else "- несвязный",
                f"- вершин: {len(component)}",
                f"- ребер: {edge_count}",
                f"- источники: {len(sources)}",
                f"- стоки: {len(sinks)}",
                "- разветвляющийся" if has_branching else "- без разветвлений",
                "- слияния есть" if has_merging else "- без слияний",
            ]
        )
        return properties, cycle_text

    def _procedure_graph_combinations(
        self,
        component: set[str],
        procedure_graph: Dict[str, List[str]],
    ) -> int:
        adjacency: Dict[str, List[str]] = {}
        for parent, children in procedure_graph.items():
            if parent not in component or not isinstance(children, list):
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
        adjacency: Dict[str, List[str]],
        start_nodes: List[str],
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
            indegree: Dict[str, int] = {node: 0 for node in nodes}
            for source, targets in adjacency.items():
                for target in targets:
                    indegree[target] = indegree.get(target, 0) + 1
            starts = [node for node, deg in indegree.items() if deg == 0]
            if not starts:
                starts = list(nodes)

        terminals = {node for node in nodes if not adjacency.get(node)}
        memo: Dict[str, int] = {}
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
        self, procedures: List[object], procedure_graph: Dict[str, List[str]]
    ) -> List[str]:
        proc_ids = [proc.procedure_id for proc in procedures]
        proc_by_id = {proc.procedure_id: proc for proc in procedures}
        order_hint: List[str] = []
        seen_hint: set[str] = set()
        for parent, children in procedure_graph.items():
            if parent in proc_by_id and parent not in seen_hint:
                order_hint.append(parent)
                seen_hint.add(parent)
            if not isinstance(children, list):
                continue
            for child in children:
                if child in proc_by_id and child not in seen_hint:
                    order_hint.append(child)
                    seen_hint.add(child)
        for proc_id in proc_ids:
            if proc_id not in seen_hint:
                order_hint.append(proc_id)
        return order_hint

    def _normalize_procedure_graph(
        self, proc_ids: List[str], procedure_graph: Dict[str, List[str]]
    ) -> Dict[str, List[str]]:
        adjacency: Dict[str, List[str]] = {proc_id: [] for proc_id in proc_ids}
        for parent, children in procedure_graph.items():
            if parent not in adjacency or not isinstance(children, list):
                continue
            seen: set[str] = set()
            cleaned: List[str] = []
            for child in children:
                if child in adjacency and child != parent and child not in seen:
                    cleaned.append(child)
                    seen.add(child)
            if cleaned:
                adjacency[parent].extend(cleaned)
        return adjacency

    def _procedure_components(
        self, proc_ids: List[str], adjacency: Dict[str, List[str]]
    ) -> List[set[str]]:
        undirected: Dict[str, set[str]] = {proc_id: set() for proc_id in proc_ids}
        for parent, children in adjacency.items():
            for child in children:
                if child not in undirected:
                    continue
                undirected[parent].add(child)
                undirected[child].add(parent)
        visited: set[str] = set()
        components: List[set[str]] = []
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
        adjacency: Dict[str, List[str]],
        order_index: Dict[str, int],
    ) -> Dict[str, int]:
        indegree: Dict[str, int] = {proc_id: 0 for proc_id in component}
        for parent, children in adjacency.items():
            for child in children:
                if child in indegree:
                    indegree[child] += 1
        queue = [proc_id for proc_id, deg in indegree.items() if deg == 0]
        queue.sort(key=lambda proc_id: order_index.get(proc_id, 0))
        levels: Dict[str, int] = {proc_id: 0 for proc_id in component}
        while queue:
            node = queue.pop(0)
            for child in adjacency.get(node, []):
                if child not in levels:
                    continue
                levels[child] = max(levels.get(child, 0), levels.get(node, 0) + 1)
                indegree[child] -= 1
                if indegree[child] == 0:
                    queue.append(child)
                    queue.sort(key=lambda proc_id: order_index.get(proc_id, 0))
        return levels

    def _find_cycle_edges(
        self, adjacency: Dict[str, List[str]], order_index: Dict[str, int] | None = None
    ) -> set[Tuple[str, str]]:
        nodes = set(adjacency.keys())
        for children in adjacency.values():
            nodes.update(children)
        visited: Dict[str, int] = {}
        cycle_edges: set[Tuple[str, str]] = set()

        def sort_key(node_id: str) -> Tuple[int, str]:
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
        self, procedure: object
    ) -> Tuple[
        Dict[str, int],
        int,
        Dict[int, float],
        List[str],
        Dict[str, float],
        Dict[str, NodeInfo],
    ]:
        branches = getattr(procedure, "branches")
        start_blocks = list(getattr(procedure, "start_block_ids"))
        end_blocks = list(getattr(procedure, "end_block_ids"))
        end_block_types = getattr(procedure, "end_block_types", {})

        branches_for_layout: Dict[str, List[str]] = {}
        for source, targets in branches.items():
            if not isinstance(targets, list):
                continue
            seen: set[str] = set()
            cleaned: List[str] = []
            for target in targets:
                if target in seen:
                    continue
                seen.add(target)
                cleaned.append(target)
            branches_for_layout[source] = cleaned

        cycle_edges = self._find_cycle_edges(branches_for_layout)
        if cycle_edges:
            for source, target in cycle_edges:
                branches_for_layout[source] = [
                    child for child in branches_for_layout.get(source, []) if child != target
                ]

        node_info: Dict[str, NodeInfo] = {}
        all_blocks = set(start_blocks) | set(end_blocks)
        for src, targets in branches.items():
            all_blocks.add(src)
            all_blocks.update(targets)

        for block_id in all_blocks:
            node_info.setdefault(block_id, NodeInfo(kind="block", block_id=block_id))

        end_nodes: Dict[str, NodeInfo] = {}
        for block_id in end_blocks:
            base_type = normalize_end_type(end_block_types.get(block_id)) or END_TYPE_DEFAULT
            node_id = f"__end_marker__{base_type}::{block_id}"
            end_nodes[node_id] = NodeInfo(
                kind="end_marker", block_id=block_id, end_type=base_type
            )

        node_info.update(end_nodes)
        all_nodes = set(node_info.keys())

        indegree: Dict[str, int] = {node_id: 0 for node_id in all_nodes}
        adj: Dict[str, List[str]] = {node_id: [] for node_id in all_nodes}
        for src, targets in branches_for_layout.items():
            for tgt in targets:
                adj[src].append(tgt)
                indegree[tgt] = indegree.get(tgt, 0) + 1

        for node_id, info in end_nodes.items():
            adj[info.block_id].append(node_id)
            indegree[node_id] = indegree.get(node_id, 0) + 1

        start_nodes = set(start_blocks)

        def sort_key(node_id: str, levels: Dict[str, int] | None = None) -> Tuple:
            info = node_info.get(node_id)
            level = 0 if levels is None else levels.get(node_id, 0)
            start_rank = 0 if node_id in start_nodes else 1
            kind_rank = 0 if info and info.kind == "block" else 1
            block_id = info.block_id if info else node_id
            end_type = info.end_type or ""
            return (level, start_rank, kind_rank, block_id, end_type)

        queue = sorted(all_nodes, key=lambda n: sort_key(n))
        queue = [n for n in queue if indegree.get(n, 0) == 0]
        levels: Dict[str, int] = {}
        order: List[str] = []
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

        branch_counts = {block: len(targets) for block, targets in branches_for_layout.items()}

        level_buckets: Dict[int, List[str]] = {lvl: [] for lvl in range(max_level + 1)}
        for node_id, lvl in levels.items():
            level_buckets.setdefault(lvl, []).append(node_id)

        def base_order_key(node_id: str) -> Tuple[int, int, str, str]:
            info = node_info.get(node_id)
            start_rank = 0 if node_id in start_nodes else 1
            kind_rank = 0 if info and info.kind == "block" else 1
            block_id = info.block_id if info else node_id
            end_type = info.end_type or ""
            return (start_rank, kind_rank, block_id, end_type)

        level_order: Dict[int, List[str]] = {}
        for lvl in range(max_level + 1):
            nodes = level_buckets.get(lvl, [])
            nodes.sort(key=base_order_key)
            level_order[lvl] = nodes

        incoming: Dict[str, List[str]] = {node_id: [] for node_id in all_nodes}
        for src, targets in adj.items():
            for tgt in targets:
                incoming.setdefault(tgt, []).append(src)

        block_children: Dict[str, List[str]] = {}
        for src, targets in adj.items():
            src_info = node_info.get(src)
            if not src_info or src_info.kind != "block":
                continue
            block_targets = [
                tgt
                for tgt in targets
                if node_info.get(tgt) and node_info[tgt].kind == "block"
            ]
            if block_targets:
                block_children[src] = block_targets

        descendant_cache: Dict[str, int] = {}

        def descendant_count(node_id: str) -> int:
            cached = descendant_cache.get(node_id)
            if cached is not None:
                return cached
            total = 0
            for child in block_children.get(node_id, []):
                total += 1 + descendant_count(child)
            descendant_cache[node_id] = total
            return total

        primary_parent: Dict[str, str] = {}
        for parent, targets in block_children.items():
            if len(targets) == 1:
                primary_parent[targets[0]] = parent
                continue
            ranked = sorted(targets, key=lambda tgt: (-descendant_count(tgt), tgt))
            primary_parent[ranked[0]] = parent

        def update_positions() -> Dict[str, float]:
            current: Dict[str, float] = {}
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

                def anchor_parent(node_id: str) -> float:
                    parents = [
                        parent
                        for parent in incoming.get(node_id, [])
                        if levels.get(parent, 0) == lvl - 1
                    ]
                    if parents:
                        return sum(positions.get(p, 0.0) for p in parents) / len(parents)
                    return positions.get(node_id, float(index[node_id]))

                nodes.sort(key=lambda n: (anchor_parent(n), index[n], n))
                level_order[lvl] = nodes
            positions = update_positions()

            for lvl in range(max_level - 1, -1, -1):
                nodes = level_order.get(lvl, [])
                if not nodes:
                    continue
                index = {node_id: idx for idx, node_id in enumerate(nodes)}

                def anchor_child(node_id: str) -> float:
                    children = [
                        child
                        for child in adj.get(node_id, [])
                        if levels.get(child, 0) == lvl + 1
                    ]
                    if children:
                        return sum(positions.get(c, 0.0) for c in children) / len(children)
                    return positions.get(node_id, float(index[node_id]))

                nodes.sort(key=lambda n: (anchor_child(n), index[n], n))
                level_order[lvl] = nodes
            positions = update_positions()

        def row_span(node_id: str) -> float:
            info = node_info.get(node_id)
            if info and info.kind == "block":
                return float(max(1, branch_counts.get(info.block_id, 0)))
            return 1.0

        row_positions: Dict[str, float] = {}
        for lvl in range(max_level + 1):
            row = 0.0
            for node_id in level_order.get(lvl, []):
                row_positions[node_id] = row
                row += row_span(node_id)

        def apply_row_smoothing() -> None:
            for lvl in range(max_level + 1):
                nodes = level_order.get(lvl, [])
                if not nodes:
                    continue
                desired: Dict[str, float] = {}
                for node_id in nodes:
                    anchors: List[float] = []
                    for parent in incoming.get(node_id, []):
                        if levels.get(parent, 0) == lvl - 1:
                            anchors.append(row_positions.get(parent, 0.0))
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
                        desired[node_id] = row_positions.get(node_id, 0.0)
                    parent = primary_parent.get(node_id)
                    if (
                        parent
                        and levels.get(parent, 0) == lvl - 1
                        and len(incoming.get(node_id, [])) == 1
                    ):
                        desired[node_id] = row_positions.get(parent, desired[node_id])
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

        ordered: List[str] = []
        row_counts: Dict[int, float] = {}
        for lvl in range(max_level + 1):
            nodes = level_order.get(lvl, [])
            for node_id in nodes:
                ordered.append(node_id)
            if nodes:
                level_max = max(row_positions[node_id] + row_span(node_id) for node_id in nodes)
                row_counts[lvl] = max(level_max, 1.0)
        if not row_counts:
            row_counts[0] = 1.0
        return levels, max_level, row_counts, ordered, row_positions, node_info
