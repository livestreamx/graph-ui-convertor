from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Dict, List, Tuple

from domain.models import (
    BlockPlacement,
    FramePlacement,
    LayoutPlan,
    MarkerPlacement,
    MarkupDocument,
    Point,
    Size,
)
from domain.ports.layout import LayoutEngine


@dataclass(frozen=True)
class LayoutConfig:
    block_size: Size = Size(260, 120)
    marker_size: Size = Size(100, 60)
    padding: float = 150.0
    gap_x: float = 120.0
    gap_y: float = 80.0
    lane_gap: float = 300.0
    max_cols: int = 4


class GridLayoutEngine(LayoutEngine):
    def __init__(self, config: LayoutConfig | None = None) -> None:
        self.config = config or LayoutConfig()

    def build_plan(self, document: MarkupDocument) -> LayoutPlan:
        frames: List[FramePlacement] = []
        blocks: List[BlockPlacement] = []
        markers: List[MarkerPlacement] = []

        procedure_levels = self._compute_procedure_levels(document)
        sizing: Dict[str, Size] = {}

        # Pre-compute frame sizes using left-to-right levels inside each procedure.
        for procedure in document.procedures:
            _, max_level, level_counts, _ = self._compute_block_levels(procedure)
            cols = max_level + 1
            rows = max(level_counts.values() or [1])
            frame_width = self.config.padding * 2 + cols * self.config.block_size.width + (
                (cols - 1) * self.config.gap_x
            )
            frame_height = self.config.padding * 2 + rows * self.config.block_size.height + (
                (rows - 1) * self.config.gap_y
            )
            sizing[procedure.procedure_id] = Size(
                frame_width + self.config.marker_size.width + self.config.gap_x * 0.5,
                frame_height + self.config.padding * 0.25,
            )

        lane_span = max((size.width for size in sizing.values()), default=0) + self.config.lane_gap

        for procedure in document.procedures:
            level = procedure_levels.get(procedure.procedure_id, 0)
            frame_size = sizing[procedure.procedure_id]
            origin_x = level * lane_span
            origin_y = 0.0
            frame = FramePlacement(
                procedure_id=procedure.procedure_id,
                origin=Point(origin_x, origin_y),
                size=frame_size,
            )
            frames.append(frame)

            placement_by_block: Dict[str, BlockPlacement] = {}
            block_levels, max_level, level_counts, order = self._compute_block_levels(procedure)
            level_rows: Dict[int, int] = {lvl: 0 for lvl in range(max_level + 1)}

            for block_id in order:
                level_idx = block_levels.get(block_id, 0)
                row_idx = level_rows[level_idx]
                level_rows[level_idx] += 1

                x = frame.origin.x + self.config.padding + level_idx * (
                    self.config.block_size.width + self.config.gap_x
                )
                y = frame.origin.y + self.config.padding + row_idx * (
                    self.config.block_size.height + self.config.gap_y
                )
                placement = BlockPlacement(
                    procedure_id=procedure.procedure_id,
                    block_id=block_id,
                    position=Point(x, y),
                    size=self.config.block_size,
                )
                blocks.append(placement)
                placement_by_block[block_id] = placement

            for start_block in procedure.start_block_ids:
                block = placement_by_block.get(start_block)
                if not block:
                    continue
                x = block.position.x - (self.config.marker_size.width + self.config.gap_x * 0.3)
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

            for end_block in procedure.end_block_ids:
                block = placement_by_block.get(end_block)
                if not block:
                    continue
                x = block.position.x + block.size.width + (self.config.gap_x * 0.3)
                y = block.position.y + (block.size.height - self.config.marker_size.height) / 2
                markers.append(
                    MarkerPlacement(
                        procedure_id=procedure.procedure_id,
                        block_id=end_block,
                        role="end_marker",
                        position=Point(x, y),
                        size=self.config.marker_size,
                    )
            )

        return LayoutPlan(frames=frames, blocks=blocks, markers=markers)

    def _compute_block_levels(
        self, procedure: object
    ) -> Tuple[Dict[str, int], int, Dict[int, int], List[str]]:
        branches = getattr(procedure, "branches")
        start_blocks = list(getattr(procedure, "start_block_ids"))
        end_blocks = list(getattr(procedure, "end_block_ids"))

        all_blocks = set(start_blocks) | set(end_blocks)
        for src, targets in branches.items():
            all_blocks.add(src)
            all_blocks.update(targets)

        indegree: Dict[str, int] = {b: 0 for b in all_blocks}
        adj: Dict[str, List[str]] = {b: [] for b in all_blocks}
        for src, targets in branches.items():
            for tgt in targets:
                adj[src].append(tgt)
                indegree[tgt] = indegree.get(tgt, 0) + 1

        queue = sorted(all_blocks, key=lambda b: (0 if b in start_blocks else 1, b))
        queue = [b for b in queue if indegree.get(b, 0) == 0]
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
                    queue.sort(key=lambda b: (levels.get(b, 0), 0 if b in start_blocks else 1, b))

        # Ensure end blocks have at least computed level (do not force extra column to keep arrows short).
        for end_block in end_blocks:
            levels.setdefault(end_block, max(levels.values() or [0]))
        max_level = max(levels.values() or [0])

        level_counts: Dict[int, int] = {}
        for lvl in levels.values():
            level_counts[lvl] = level_counts.get(lvl, 0) + 1
        if not order:
            order = sorted(levels.keys())
        return levels, max_level, level_counts, order

    def _compute_procedure_levels(self, document: MarkupDocument) -> Dict[str, int]:
        block_to_proc: Dict[str, str] = {}
        for procedure in document.procedures:
            for block_id in procedure.block_ids():
                block_to_proc[block_id] = procedure.procedure_id

        edges: List[Tuple[str, str]] = []
        for procedure in document.procedures:
            for source_block, targets in procedure.branches.items():
                for target in targets:
                    target_proc = block_to_proc.get(target)
                    if target_proc and target_proc != procedure.procedure_id:
                        edges.append((procedure.procedure_id, target_proc))

        nodes = {proc.procedure_id for proc in document.procedures}
        indegree: Dict[str, int] = {node: 0 for node in nodes}
        adj: Dict[str, List[str]] = {node: [] for node in nodes}
        for src, dst in edges:
            adj[src].append(dst)
            indegree[dst] += 1

        def is_start(proc_id: str) -> bool:
            proc = next(p for p in document.procedures if p.procedure_id == proc_id)
            return bool(proc.start_block_ids)

        def is_end(proc_id: str) -> bool:
            proc = next(p for p in document.procedures if p.procedure_id == proc_id)
            return bool(proc.end_block_ids)

        def start_count(proc_id: str) -> int:
            proc = next(p for p in document.procedures if p.procedure_id == proc_id)
            return len(proc.start_block_ids)

        queue = [
            node
            for node in sorted(nodes)
            if indegree.get(node, 0) == 0
        ]
        # Prioritize start procedures at the head.
        queue.sort(key=lambda n: (0 if is_start(n) else 1, -start_count(n), n))

        level: Dict[str, int] = {node: 0 for node in nodes}
        visited = 0
        order_offset = 0
        while queue:
            node = queue.pop(0)
            if level[node] == 0:
                level[node] = order_offset
                order_offset += 1
            visited += 1
            for neighbor in adj.get(node, []):
                level[neighbor] = max(level[neighbor], level[node] + 1)
                indegree[neighbor] -= 1
                if indegree[neighbor] == 0:
                    queue.append(neighbor)
                    queue.sort(key=lambda n: (0 if is_start(n) else 1, -start_count(n), n))

        # Push end procedures to the rightmost layer.
        max_level = max(level.values() or [0])
        for node in nodes:
            if is_end(node):
                level[node] = max_level + 1
        # Ensure unique ordering left->right even if levels equal.
        deduped: Dict[str, int] = {}
        current = 0
        for proc_id in sorted(nodes, key=lambda n: (level[n], 0 if is_start(n) else 1, -start_count(n), n)):
            deduped[proc_id] = current
            current += 1

        return deduped
