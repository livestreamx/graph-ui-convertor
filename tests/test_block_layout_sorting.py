from __future__ import annotations

from adapters.layout.grid import GridLayoutEngine
from domain.models import MarkupDocument


def test_layout_orders_targets_by_incoming_neighbors() -> None:
    payload = {
        "finedog_unit_id": 101,
        "markup_type": "service",
        "procedures": [
            {
                "proc_id": "p1",
                "start_block_ids": ["a", "b", "c"],
                "end_block_ids": [],
                "branches": {"a": ["f"], "b": ["d"], "c": ["e"]},
            }
        ],
    }
    markup = MarkupDocument.model_validate(payload)
    plan = GridLayoutEngine().build_plan(markup)
    blocks = {block.block_id: block for block in plan.blocks}
    y_positions = {block_id: block.position.y for block_id, block in blocks.items()}
    targets = ["d", "e", "f"]

    def closest_target(source_id: str) -> str:
        return min(targets, key=lambda target: abs(y_positions[target] - y_positions[source_id]))

    assert closest_target("a") == "f"
    assert closest_target("b") == "d"
    assert closest_target("c") == "e"


def test_end_markers_follow_block_order() -> None:
    payload = {
        "finedog_unit_id": 202,
        "markup_type": "service",
        "procedures": [
            {
                "proc_id": "p1",
                "start_block_ids": ["s"],
                "end_block_ids": ["a::end", "b::end", "c::end"],
                "branches": {"s": ["a", "b", "c"]},
            }
        ],
    }
    markup = MarkupDocument.model_validate(payload)
    plan = GridLayoutEngine().build_plan(markup)

    end_blocks = {"a", "b", "c"}
    blocks = [block for block in plan.blocks if block.block_id in end_blocks]
    markers = [
        marker
        for marker in plan.markers
        if marker.role == "end_marker" and marker.block_id in end_blocks
    ]

    block_order = [block.block_id for block in sorted(blocks, key=lambda b: b.position.y)]
    marker_order = [marker.block_id for marker in sorted(markers, key=lambda m: m.position.y)]
    assert marker_order == block_order
