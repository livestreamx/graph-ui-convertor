from __future__ import annotations

import json
from pathlib import Path

from adapters.layout.grid import GridLayoutEngine
from domain.models import END_TYPE_DEFAULT, MarkerPlacement, MarkupDocument


def repo_root() -> Path:
    for parent in Path(__file__).resolve().parents:
        if (parent / "pyproject.toml").exists():
            return parent
    raise RuntimeError("Repository root not found")


def load_markup_fixture(name: str) -> MarkupDocument:
    fixture_path = repo_root() / "examples" / "markup" / name
    return MarkupDocument.model_validate(json.loads(fixture_path.read_text(encoding="utf-8")))


def test_layout_orders_targets_by_incoming_neighbors() -> None:
    payload = {
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


def test_block_graph_infers_procedure_order_for_layout() -> None:
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
                "start_block_ids": ["c"],
                "end_block_ids": [],
                "branches": {"c": ["d"]},
            },
        ],
        "block_graph": {"b": ["c"]},
    }
    markup = MarkupDocument.model_validate(payload)
    plan = GridLayoutEngine().build_plan(markup)
    frames = {frame.procedure_id: frame for frame in plan.frames}
    assert set(frames.keys()) == {"p1", "p2"}
    assert frames["p1"].origin.x < frames["p2"].origin.x
    assert not plan.separators


def test_basic_procedure_frames_use_uniform_gap() -> None:
    markup = load_markup_fixture("basic.json")
    layout = GridLayoutEngine()
    plan = layout.build_plan(markup)

    frames = sorted(plan.frames, key=lambda frame: frame.origin.x)
    gaps = [
        frames[idx + 1].origin.x - (frames[idx].origin.x + frames[idx].size.width)
        for idx in range(len(frames) - 1)
    ]
    assert gaps
    assert max(gaps) - min(gaps) < 1e-6


def test_end_markers_follow_block_order() -> None:
    payload = {
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


def test_end_markers_align_with_blocks_in_large_procedure() -> None:
    markup = load_markup_fixture("graphs_set.json")
    layout = GridLayoutEngine()
    plan = layout.build_plan(markup)

    proc_id = "proc_end_markers"
    block_ids = ["end_a", "end_b", "end_c"]
    blocks = {
        block.block_id: block
        for block in plan.blocks
        if block.procedure_id == proc_id and block.block_id in block_ids
    }
    markers = {
        marker.block_id: marker
        for marker in plan.markers
        if marker.procedure_id == proc_id
        and marker.role == "end_marker"
        and marker.block_id in block_ids
    }
    offset_y = (layout.config.block_size.height - layout.config.marker_size.height) / 2
    for block_id in block_ids:
        block = blocks.get(block_id)
        marker = markers.get(block_id)
        assert block is not None
        assert marker is not None
        assert abs(marker.position.y - (block.position.y + offset_y)) < 1e-6


def test_primary_branch_aligns_rows_in_large_procedure() -> None:
    markup = load_markup_fixture("graphs_set.json")
    plan = GridLayoutEngine().build_plan(markup)

    proc_id = "proc_primary_chain"
    block_ids = ["chain_a", "chain_b", "chain_c"]
    blocks = {
        block.block_id: block
        for block in plan.blocks
        if block.procedure_id == proc_id and block.block_id in block_ids
    }
    assert set(blocks.keys()) == set(block_ids)

    ys = [blocks[block_id].position.y for block_id in block_ids]
    assert max(ys) - min(ys) < 1e-6


def test_large_procedure_orders_source_blocks() -> None:
    markup = load_markup_fixture("graphs_set.json")
    plan = GridLayoutEngine().build_plan(markup)

    proc_id = "proc_source_order"
    block_ids = {
        "first": "source_a",
        "second": "source_b",
        "third": "source_c",
    }
    blocks = {
        block.block_id: block
        for block in plan.blocks
        if block.procedure_id == proc_id and block.block_id in block_ids.values()
    }
    assert set(blocks.keys()) == set(block_ids.values())

    first_y = blocks[block_ids["first"]].position.y
    second_y = blocks[block_ids["second"]].position.y
    third_y = blocks[block_ids["third"]].position.y
    assert first_y < second_y < third_y


def test_end_markers_use_nearest_free_row_in_large_procedure() -> None:
    markup = load_markup_fixture("graphs_set.json")
    layout = GridLayoutEngine()
    plan = layout.build_plan(markup)

    proc_id = "proc_marker_shift"
    blocks = {block.block_id: block for block in plan.blocks if block.procedure_id == proc_id}
    markers = [
        marker
        for marker in plan.markers
        if marker.procedure_id == proc_id and marker.role == "end_marker"
    ]
    offset_y = (layout.config.block_size.height - layout.config.marker_size.height) / 2
    row_step = layout.config.block_size.height + layout.config.gap_y

    aligned_block = "aligned"

    def marker_for(block_id: str, end_type: str | None = None) -> MarkerPlacement | None:
        candidates = [marker for marker in markers if marker.block_id == block_id]
        if end_type is None:
            return candidates[0] if candidates else None
        for marker in candidates:
            if marker.end_type == end_type:
                return marker
        return None

    aligned_marker = marker_for(aligned_block, END_TYPE_DEFAULT)
    assert aligned_marker is not None
    assert abs(aligned_marker.position.y - (blocks[aligned_block].position.y + offset_y)) < 1e-6

    shifted_block = "shifted"
    shifted_marker = marker_for(shifted_block, END_TYPE_DEFAULT)
    assert shifted_marker is not None
    assert (
        abs(shifted_marker.position.y - (blocks[shifted_block].position.y + row_step + offset_y))
        < 1e-6
    )

    parent_block = "shifted"
    child_block = "blocker"
    assert abs(blocks[parent_block].position.y - blocks[child_block].position.y) < 1e-6


def test_shared_child_blocks_group_in_shared_children_fixture() -> None:
    markup = load_markup_fixture("graphs_set.json")
    plan = GridLayoutEngine().build_plan(markup)

    proc_id = "proc_shared_children"
    block_ids = {
        "parent": "parent_a",
        "child_error": "child_err",
        "child_success": "child_ok",
        "parent_peer": "parent_b",
    }
    blocks = {
        block.block_id: block
        for block in plan.blocks
        if block.procedure_id == proc_id and block.block_id in block_ids.values()
    }
    assert set(blocks.keys()) == set(block_ids.values())

    parent_y = blocks[block_ids["parent"]].position.y
    error_y = blocks[block_ids["child_error"]].position.y
    success_y = blocks[block_ids["child_success"]].position.y
    peer_y = blocks[block_ids["parent_peer"]].position.y

    assert parent_y < error_y < success_y
    assert parent_y < peer_y < error_y
