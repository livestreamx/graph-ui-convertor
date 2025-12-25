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
    marker_size: Size = Size(180, 90)
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
            has_end = bool(procedure.end_block_ids)
            _, max_level, level_counts, _, _ = self._compute_block_levels(procedure)
            cols = max_level + 1
            rows = max(level_counts.values() or [1])
            start_extra = self.config.marker_size.width + self.config.gap_x * 0.8
            end_extra = (self.config.marker_size.width + self.config.gap_x * 0.4) if has_end else 0
            frame_width = (
                self.config.padding * 2
                + start_extra
                + cols * self.config.block_size.width
                + ((cols - 1) * self.config.gap_x)
                + end_extra
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
            block_levels, max_level, level_counts, order, row_positions = self._compute_block_levels(procedure)
            start_extra = self.config.marker_size.width + self.config.gap_x * 0.8
            level_rows: Dict[int, float] = {lvl: 0.0 for lvl in range(max_level + 1)}
            for block_id in order:
                level_idx = block_levels.get(block_id, 0)
                row_idx = row_positions.get(block_id, level_rows[level_idx])
                level_rows[level_idx] = max(level_rows[level_idx], row_idx + 1)

                x = frame.origin.x + self.config.padding + start_extra + level_idx * (
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

            for end_block in procedure.end_block_ids:
                block = placement_by_block.get(end_block)
                if not block:
                    continue
                right_x = block.position.x + block.size.width + (self.config.gap_x * 0.3)
                fits_right = right_x + self.config.marker_size.width <= frame.origin.x + frame.size.width - self.config.padding * 0.2
                if fits_right:
                    x = right_x
                    y = block.position.y + (block.size.height - self.config.marker_size.height) / 2
                else:
                    x = block.position.x + (block.size.width - self.config.marker_size.width) / 2
                    y = block.position.y + block.size.height + (self.config.gap_y * 0.4)
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
    ) -> Tuple[Dict[str, int], int, Dict[int, int], List[str], Dict[str, float]]:
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

        # Reorder blocks inside each level to reduce crossings using child anchors (right-to-left pass).
        level_buckets: Dict[int, List[str]] = {lvl: [] for lvl in range(max_level + 1)}
        for block_id, lvl in levels.items():
            level_buckets.setdefault(lvl, []).append(block_id)

        positions: Dict[str, int] = {}
        for lvl in reversed(range(max_level + 1)):
            bucket = level_buckets.get(lvl, [])
            if not bucket:
                continue

            def anchor_child(b: str) -> float:
                children = [c for c in adj.get(b, []) if levels.get(c) == lvl + 1 and c in positions]
                if children:
                    return sum(positions[c] for c in children) / len(children)
                return float("inf")

            bucket.sort(key=lambda b: (anchor_child(b), indegree.get(b, 0), b))
            for idx, b in enumerate(bucket):
                positions[b] = idx

        ordered: List[str] = []
        for lvl in range(max_level + 1):
            bucket = level_buckets.get(lvl, [])
            bucket.sort(key=lambda b: positions.get(b, 0))
            ordered.extend(bucket)
        row_positions = {b: float(positions.get(b, 0)) for b in ordered}
        return levels, max_level, level_counts, ordered, row_positions

    def _compute_procedure_levels(self, document: MarkupDocument) -> Dict[str, int]:
        # Use declared order in JSON to keep left->right flow consistent.
        return {proc.procedure_id: idx for idx, proc in enumerate(document.procedures)}
