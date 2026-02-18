from __future__ import annotations

from adapters.layout.grid import GridLayoutEngine
from domain.models import MarkupDocument


def test_end_blocks_shifted_for_cross_procedure_edges() -> None:
    payload = {
        "markup_type": "service",
        "procedures": [
            {
                "proc_id": "p1",
                "start_block_ids": ["a"],
                "end_block_ids": ["c::exit"],
                "branches": {"a": ["b"], "b": ["c"]},
            },
            {
                "proc_id": "p2",
                "start_block_ids": ["d"],
                "end_block_ids": [],
                "branches": {},
            },
        ],
        "block_graph": {"a": ["b"], "b": ["c", "d"]},
    }
    markup = MarkupDocument.model_validate(payload)
    layout = GridLayoutEngine()
    plan = layout.build_plan(markup)
    block_b = next(block for block in plan.blocks if block.block_id == "b")
    block_c = next(block for block in plan.blocks if block.block_id == "c")
    expected_shift = layout.config.block_size.height + layout.config.gap_y
    assert block_c.position.y >= block_b.position.y + expected_shift


def test_start_markers_shift_diagonally_when_overlapping_edges() -> None:
    payload = {
        "markup_type": "service",
        "procedures": [
            {
                "proc_id": "p1",
                "start_block_ids": ["a"],
                "end_block_ids": [],
                "branches": {"a": ["b"]},
            },
            {
                "proc_id": "p2",
                "start_block_ids": ["d"],
                "end_block_ids": [],
                "branches": {},
            },
        ],
        "block_graph": {"a": ["b"], "b": ["d"]},
    }
    markup = MarkupDocument.model_validate(payload)
    layout = GridLayoutEngine()
    plan = layout.build_plan(markup)
    block_d = next(block for block in plan.blocks if block.block_id == "d")
    marker_d = next(
        marker
        for marker in plan.markers
        if marker.role == "start_marker" and marker.block_id == "d"
    )
    default_x = block_d.position.x - (layout.config.marker_size.width + layout.config.gap_x * 0.8)
    default_y = block_d.position.y + (block_d.size.height - layout.config.marker_size.height) / 2
    row_shift = layout.config.block_size.height + layout.config.gap_y
    assert marker_d.position.y >= default_y + row_shift
    assert marker_d.position.x < default_x
