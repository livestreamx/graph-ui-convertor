from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Dict, List

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
    block_size: Size = Size(180, 80)
    marker_size: Size = Size(70, 50)
    padding: float = 80.0
    gap_x: float = 60.0
    gap_y: float = 60.0
    lane_gap: float = 200.0
    max_cols: int = 3


class GridLayoutEngine(LayoutEngine):
    def __init__(self, config: LayoutConfig | None = None) -> None:
        self.config = config or LayoutConfig()

    def build_plan(self, document: MarkupDocument) -> LayoutPlan:
        frames: List[FramePlacement] = []
        blocks: List[BlockPlacement] = []
        markers: List[MarkerPlacement] = []

        for idx, procedure in enumerate(document.procedures):
            block_ids = sorted(procedure.block_ids())
            block_count = max(len(block_ids), 1)
            cols = min(self.config.max_cols, max(1, math.ceil(math.sqrt(block_count))))
            rows = math.ceil(block_count / cols)

            frame_width = self.config.padding * 2 + cols * self.config.block_size.width + (
                (cols - 1) * self.config.gap_x
            )
            frame_height = self.config.padding * 2 + rows * self.config.block_size.height + (
                (rows - 1) * self.config.gap_y
            )

            origin_x = idx * (frame_width + self.config.lane_gap)
            origin_y = 0.0
            frame = FramePlacement(
                procedure_id=procedure.procedure_id,
                origin=Point(origin_x, origin_y),
                size=Size(frame_width, frame_height),
            )
            frames.append(frame)

            placement_by_block: Dict[str, BlockPlacement] = {}
            for block_idx, block_id in enumerate(block_ids):
                row, col = divmod(block_idx, cols)
                x = frame.origin.x + self.config.padding + col * (
                    self.config.block_size.width + self.config.gap_x
                )
                y = frame.origin.y + self.config.padding + row * (
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
                x = block.position.x - (self.config.marker_size.width + self.config.gap_x / 2)
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
                x = block.position.x + block.size.width + (self.config.gap_x / 2)
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
