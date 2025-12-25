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

        procedures = [proc for proc in document.procedures if proc.block_ids()]
        procedure_levels = {proc.procedure_id: idx for idx, proc in enumerate(procedures)}
        sizing: Dict[str, Size] = {}

        # Pre-compute frame sizes using left-to-right levels inside each procedure.
        for procedure in procedures:
            _, max_level, level_counts, _, _, _ = self._compute_block_levels(procedure)
            cols = max_level + 1
            rows = max(level_counts.values() or [1])
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

        for procedure in procedures:
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

        return LayoutPlan(frames=frames, blocks=blocks, markers=markers)

    def _compute_block_levels(
        self, procedure: object
    ) -> Tuple[
        Dict[str, int],
        int,
        Dict[int, int],
        List[str],
        Dict[str, float],
        Dict[str, NodeInfo],
    ]:
        branches = getattr(procedure, "branches")
        start_blocks = list(getattr(procedure, "start_block_ids"))
        end_blocks = list(getattr(procedure, "end_block_ids"))
        end_block_types = getattr(procedure, "end_block_types", {})

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
            if base_type in {"all", "intermediate"}:
                transitions = ["end", "exit"]
            else:
                transitions = [base_type]
            for transition in transitions:
                node_id = f"__end_marker__{transition}::{block_id}"
                end_nodes[node_id] = NodeInfo(
                    kind="end_marker", block_id=block_id, end_type=transition
                )

        node_info.update(end_nodes)
        all_nodes = set(node_info.keys())

        indegree: Dict[str, int] = {node_id: 0 for node_id in all_nodes}
        adj: Dict[str, List[str]] = {node_id: [] for node_id in all_nodes}
        for src, targets in branches.items():
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
        for node_id, lvl in levels.items():
            level_buckets.setdefault(lvl, []).append(node_id)

        positions: Dict[str, int] = {}
        for lvl in reversed(range(max_level + 1)):
            bucket = level_buckets.get(lvl, [])
            if not bucket:
                continue

            def anchor_child(node_id: str) -> float:
                children = [
                    child
                    for child in adj.get(node_id, [])
                    if levels.get(child) == lvl + 1 and child in positions
                ]
                if children:
                    return sum(positions[c] for c in children) / len(children)
                return float("inf")

            bucket.sort(key=lambda n: (anchor_child(n), indegree.get(n, 0), n))
            for idx, node_id in enumerate(bucket):
                positions[node_id] = idx

        ordered: List[str] = []
        for lvl in range(max_level + 1):
            bucket = level_buckets.get(lvl, [])
            bucket.sort(key=lambda n: positions.get(n, 0))
            ordered.extend(bucket)
        row_positions = {node_id: float(positions.get(node_id, 0)) for node_id in ordered}
        return levels, max_level, level_counts, ordered, row_positions, node_info
