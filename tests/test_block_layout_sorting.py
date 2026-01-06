from __future__ import annotations

import json
from pathlib import Path

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


def test_end_markers_align_with_blocks_in_large_procedure() -> None:
    payload = json.loads(
        Path("data/markup/43285.json").read_text(encoding="utf-8")
    )
    markup = MarkupDocument.model_validate(payload)
    layout = GridLayoutEngine()
    plan = layout.build_plan(markup)

    proc_id = "arrest_how_to_remove_chatbot_sme"
    block_ids = [
        "-ATBwROMAmnzTBBLdQjQWd",
        "-oiAwdVJjuoFzUTFExjD-Q",
        "AHF-bSHmufnFkvosaPAOTj",
    ]
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
    payload = json.loads(
        Path("data/markup/43285.json").read_text(encoding="utf-8")
    )
    markup = MarkupDocument.model_validate(payload)
    plan = GridLayoutEngine().build_plan(markup)

    proc_id = "arrest_how_to_remove_chatbot_sme"
    block_ids = [
        "NqQmDbgenrSRpCboizdqEk",
        "EfJCMMtxifWXTdNXjNPVKz",
        "MdUmsRreGHsgu_CttLuabJ",
    ]
    blocks = {
        block.block_id: block
        for block in plan.blocks
        if block.procedure_id == proc_id and block.block_id in block_ids
    }
    assert set(blocks.keys()) == set(block_ids)

    ys = [blocks[block_id].position.y for block_id in block_ids]
    assert max(ys) - min(ys) < 1e-6


def test_large_procedure_orders_source_blocks() -> None:
    payload = json.loads(
        Path("data/markup/43285.json").read_text(encoding="utf-8")
    )
    markup = MarkupDocument.model_validate(payload)
    plan = GridLayoutEngine().build_plan(markup)

    proc_id = "arrest_how_to_remove_chatbot_sme"
    block_ids = {
        "start": "LyemLgE_jSkJSoJVLsuJVw",
        "what": "NqQmDbgenrSRpCboizdqEk",
        "noecp": "Lyfju_KvjpSWLkseRzcvJn",
    }
    blocks = {
        block.block_id: block
        for block in plan.blocks
        if block.procedure_id == proc_id and block.block_id in block_ids.values()
    }
    assert set(blocks.keys()) == set(block_ids.values())

    start_y = blocks[block_ids["start"]].position.y
    what_y = blocks[block_ids["what"]].position.y
    noecp_y = blocks[block_ids["noecp"]].position.y
    assert start_y < what_y < noecp_y


def test_end_markers_use_nearest_free_row_in_large_procedure() -> None:
    payload = json.loads(
        Path("data/markup/43285.json").read_text(encoding="utf-8")
    )
    markup = MarkupDocument.model_validate(payload)
    layout = GridLayoutEngine()
    plan = layout.build_plan(markup)

    proc_id = "sme_cancel_block_fns"
    blocks = {
        block.block_id: block
        for block in plan.blocks
        if block.procedure_id == proc_id
    }
    markers = {
        marker.block_id: marker
        for marker in plan.markers
        if marker.procedure_id == proc_id and marker.role == "end_marker"
    }
    offset_y = (layout.config.block_size.height - layout.config.marker_size.height) / 2
    row_step = layout.config.block_size.height + layout.config.gap_y

    aligned_block = "l1exz64z-hlgm"
    aligned_marker = markers.get(aligned_block)
    assert aligned_marker is not None
    assert abs(
        aligned_marker.position.y - (blocks[aligned_block].position.y + offset_y)
    ) < 1e-6

    shifted_block = "l1dngroo-b11o"
    shifted_marker = markers.get(shifted_block)
    assert shifted_marker is not None
    assert abs(
        shifted_marker.position.y
        - (blocks[shifted_block].position.y + row_step + offset_y)
    ) < 1e-6

    parent_block = "l52ercgo-mcwr"
    child_block = "l1ex5zj5-7ri3"
    assert abs(blocks[parent_block].position.y - blocks[child_block].position.y) < 1e-6


def test_shared_child_blocks_group_in_close_gold_account() -> None:
    payload = json.loads(
        Path("data/markup/60371.json").read_text(encoding="utf-8")
    )
    markup = MarkupDocument.model_validate(payload)
    plan = GridLayoutEngine().build_plan(markup)

    proc_id = "close_gold_account"
    block_ids = {
        "close_self": "kv8482s1-fj1n",
        "error": "l4phth8w-griq",
        "success": "kv2dhy0e-77w",
        "consult": "kv2955e1-5qhp",
    }
    blocks = {
        block.block_id: block
        for block in plan.blocks
        if block.procedure_id == proc_id and block.block_id in block_ids.values()
    }
    assert set(blocks.keys()) == set(block_ids.values())

    close_self_y = blocks[block_ids["close_self"]].position.y
    error_y = blocks[block_ids["error"]].position.y
    success_y = blocks[block_ids["success"]].position.y
    consult_y = blocks[block_ids["consult"]].position.y

    assert close_self_y < error_y < success_y
    assert close_self_y < consult_y < error_y
