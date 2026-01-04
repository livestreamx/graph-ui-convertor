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
