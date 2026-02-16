from __future__ import annotations

from typing import Any

from adapters.layout.grid import GridLayoutEngine
from domain.models import INITIAL_BLOCK_COLOR, ExcalidrawDocument, MarkupDocument
from domain.services.convert_excalidraw_to_markup import ExcalidrawToMarkupConverter
from domain.services.convert_markup_to_excalidraw import MarkupToExcalidrawConverter


def test_block_graph_edges_render_between_blocks() -> None:
    payload = {
        "markup_type": "service",
        "procedures": [
            {
                "proc_id": "p1",
                "start_block_ids": ["a_start"],
                "end_block_ids": ["a_end::end"],
                "branches": {"a_start": ["a_end"]},
            },
            {
                "proc_id": "p2",
                "start_block_ids": ["b_start"],
                "end_block_ids": ["b_end::end"],
                "branches": {"b_start": ["b_end"]},
            },
        ],
        "procedure_graph": {"p1": ["p2"], "p2": []},
        "block_graph": {"a_end": ["b_start"]},
    }
    markup = MarkupDocument.model_validate(payload)
    excal: ExcalidrawDocument = MarkupToExcalidrawConverter(GridLayoutEngine()).convert(markup)

    block_edges = [
        element
        for element in excal.elements
        if element.get("type") == "arrow"
        and element.get("customData", {}).get("cjm", {}).get("edge_type")
        in {"block_graph", "block_graph_cycle"}
    ]
    branch_edges = [
        element
        for element in excal.elements
        if element.get("type") == "arrow"
        and element.get("customData", {}).get("cjm", {}).get("edge_type")
        in {"branch", "branch_cycle"}
    ]
    procedure_edges = [
        element
        for element in excal.elements
        if element.get("type") == "arrow"
        and element.get("customData", {}).get("cjm", {}).get("edge_type")
        in {"procedure_flow", "procedure_cycle"}
    ]
    assert block_edges
    assert not branch_edges
    assert not procedure_edges
    meta = block_edges[0].get("customData", {}).get("cjm", {})
    assert meta.get("source_block_id") == "a_end"
    assert meta.get("target_block_id") == "b_start"

    reconstructed = ExcalidrawToMarkupConverter().convert(excal.to_dict())
    assert reconstructed.block_graph.get("a_end") == ["b_start"]
    assert "b_start" in reconstructed.block_graph
    assert reconstructed.procedure_graph.get("p1") == ["p2"]


def test_block_graph_edges_ignore_markup_type() -> None:
    payload = {
        "markup_type": "procedure_graph",
        "procedures": [
            {
                "proc_id": "p1",
                "start_block_ids": ["a_start"],
                "end_block_ids": ["a_end::end"],
                "branches": {"a_start": ["a_end"]},
            },
            {
                "proc_id": "p2",
                "start_block_ids": ["b_start"],
                "end_block_ids": ["b_end::end"],
                "branches": {"b_start": ["b_end"]},
            },
        ],
        "procedure_graph": {"p1": ["p2"], "p2": []},
        "block_graph": {"a_end": ["b_start"]},
    }
    markup = MarkupDocument.model_validate(payload)
    excal: ExcalidrawDocument = MarkupToExcalidrawConverter(GridLayoutEngine()).convert(markup)

    block_edges = [
        element
        for element in excal.elements
        if element.get("type") == "arrow"
        and element.get("customData", {}).get("cjm", {}).get("edge_type")
        in {"block_graph", "block_graph_cycle"}
    ]
    branch_edges = [
        element
        for element in excal.elements
        if element.get("type") == "arrow"
        and element.get("customData", {}).get("cjm", {}).get("edge_type")
        in {"branch", "branch_cycle"}
    ]
    procedure_edges = [
        element
        for element in excal.elements
        if element.get("type") == "arrow"
        and element.get("customData", {}).get("cjm", {}).get("edge_type")
        in {"procedure_flow", "procedure_cycle"}
    ]
    assert block_edges
    assert not branch_edges
    assert not procedure_edges


def test_block_graph_edges_disambiguate_duplicate_block_ids_by_procedure_graph() -> None:
    payload = {
        "markup_type": "service",
        "procedures": [
            {
                "proc_id": "p1",
                "start_block_ids": ["entry"],
                "end_block_ids": ["local_end::end"],
                "branches": {
                    "entry": ["handoff", "shared"],
                    "handoff": ["local_end"],
                    "shared": ["local_end"],
                },
            },
            {
                "proc_id": "p2",
                "start_block_ids": ["shared"],
                "end_block_ids": ["done::end"],
                "branches": {"shared": ["done"]},
            },
        ],
        "procedure_graph": {"p1": ["p2"], "p2": []},
        "block_graph": {"handoff": ["shared"]},
    }
    markup = MarkupDocument.model_validate(payload)
    excal: ExcalidrawDocument = MarkupToExcalidrawConverter(GridLayoutEngine()).convert(markup)

    block_edges = [
        element
        for element in excal.elements
        if element.get("type") == "arrow"
        and element.get("customData", {}).get("cjm", {}).get("edge_type")
        in {"block_graph", "block_graph_cycle"}
    ]
    assert len(block_edges) == 1

    blocks_by_proc_and_id = {
        (
            element.get("customData", {}).get("cjm", {}).get("procedure_id"),
            element.get("customData", {}).get("cjm", {}).get("block_id"),
        ): element
        for element in excal.elements
        if element.get("type") == "rectangle"
        and element.get("customData", {}).get("cjm", {}).get("role") == "block"
    }
    assert ("p1", "shared") in blocks_by_proc_and_id
    assert ("p2", "shared") in blocks_by_proc_and_id

    edge = block_edges[0]
    edge_meta = edge.get("customData", {}).get("cjm", {})
    assert edge_meta.get("procedure_id") == "p1"
    assert edge_meta.get("target_procedure_id") == "p2"
    assert edge_meta.get("source_block_id") == "handoff"
    assert edge_meta.get("target_block_id") == "shared"
    assert edge.get("endBinding", {}).get("elementId") == blocks_by_proc_and_id[
        ("p2", "shared")
    ].get("id")
    assert edge.get("endBinding", {}).get("elementId") != blocks_by_proc_and_id[
        ("p1", "shared")
    ].get("id")


def test_block_graph_cycle_edges_are_marked() -> None:
    payload = {
        "markup_type": "service",
        "procedures": [
            {
                "proc_id": "p1",
                "start_block_ids": ["a"],
                "end_block_ids": ["b::end"],
                "branches": {"a": ["b"]},
            },
            {
                "proc_id": "p2",
                "start_block_ids": ["c"],
                "end_block_ids": ["d::end"],
                "branches": {"c": ["d"]},
            },
        ],
        "block_graph": {"b": ["c"], "c": ["b"]},
    }
    markup = MarkupDocument.model_validate(payload)
    excal: ExcalidrawDocument = MarkupToExcalidrawConverter(GridLayoutEngine()).convert(markup)

    cycle_edges = [
        element
        for element in excal.elements
        if element.get("type") == "arrow"
        and element.get("customData", {}).get("cjm", {}).get("edge_type") == "block_graph_cycle"
    ]
    flow_edges = [
        element
        for element in excal.elements
        if element.get("type") == "arrow"
        and element.get("customData", {}).get("cjm", {}).get("edge_type") == "block_graph"
    ]
    assert len(cycle_edges) == 1
    assert len(flow_edges) == 1
    assert all(edge.get("text") == "ЦИКЛ" for edge in cycle_edges)
    assert all(edge.get("strokeColor") == "#d32f2f" for edge in cycle_edges)
    assert all(edge.get("strokeStyle") == "dashed" for edge in cycle_edges)
    assert all(edge.get("strokeWidth") == 1 for edge in cycle_edges)

    cycle_edge = cycle_edges[0]
    meta = cycle_edge.get("customData", {}).get("cjm", {})
    assert meta.get("source_block_id") == "c"
    assert meta.get("target_block_id") == "b"

    def block_element(block_id: str) -> dict[str, Any]:
        for element in excal.elements:
            if element.get("type") != "rectangle":
                continue
            elem_meta = element.get("customData", {}).get("cjm", {})
            if elem_meta.get("block_id") == block_id:
                return element
        raise AssertionError(f"Block {block_id} not found")

    source_block = block_element("c")
    target_block = block_element("b")
    start_expected = (
        float(source_block["x"]) + float(source_block["width"]) / 2,
        float(source_block["y"]) + float(source_block["height"]),
    )
    end_expected = (
        float(target_block["x"]),
        float(target_block["y"]) + float(target_block["height"]) / 2,
    )
    points = cycle_edge.get("points")
    assert isinstance(points, list)
    start_actual = (
        float(cycle_edge["x"]) + float(points[0][0]),
        float(cycle_edge["y"]) + float(points[0][1]),
    )
    end_actual = (
        float(cycle_edge["x"]) + float(points[-1][0]),
        float(cycle_edge["y"]) + float(points[-1][1]),
    )
    assert abs(start_actual[0] - start_expected[0]) < 1e-6
    assert abs(start_actual[1] - start_expected[1]) < 1e-6
    assert abs(end_actual[0] - end_expected[0]) < 1e-6
    assert abs(end_actual[1] - end_expected[1]) < 1e-6

    reconstructed = ExcalidrawToMarkupConverter().convert(excal.to_dict())
    graph = {key: sorted(values) for key, values in reconstructed.block_graph.items()}
    assert graph == {"b": ["c"], "c": ["b"]}


def test_block_graph_initial_suffix_roundtrip() -> None:
    payload = {
        "markup_type": "service",
        "procedures": [
            {
                "proc_id": "p1",
                "start_block_ids": ["root"],
                "end_block_ids": ["leaf::end"],
                "branches": {"root": ["leaf"]},
            }
        ],
        "block_graph": {"root::initial": ["child", "leaf::initial"]},
    }
    markup = MarkupDocument.model_validate(payload)
    assert markup.block_graph == {"root": ["child", "leaf"]}
    assert markup.block_graph_initials == {"root", "leaf"}

    serialized = markup.to_markup_dict()
    block_graph = serialized.get("block_graph")
    assert block_graph == {"root::initial": ["child", "leaf::initial"]}


def test_initial_block_styling_in_excalidraw() -> None:
    payload = {
        "markup_type": "service",
        "procedures": [
            {
                "proc_id": "p1",
                "start_block_ids": ["root"],
                "end_block_ids": ["child::end"],
                "branches": {"root": ["child"]},
                "block_id_to_block_name": {
                    "root": "Root block",
                    "child": "Child block",
                },
            }
        ],
        "block_graph": {"root::initial": ["child"]},
    }
    markup = MarkupDocument.model_validate(payload)
    excal: ExcalidrawDocument = MarkupToExcalidrawConverter(GridLayoutEngine()).convert(markup)

    block = next(
        element
        for element in excal.elements
        if element.get("type") == "rectangle"
        and element.get("customData", {}).get("cjm", {}).get("block_id") == "root"
    )
    meta = block.get("customData", {}).get("cjm", {})
    assert meta.get("block_graph_initial") is True
    assert block.get("backgroundColor") == INITIAL_BLOCK_COLOR
    assert block.get("strokeStyle") == "dashed"
    assert block.get("fillStyle") == "hachure"


def test_block_graph_skips_ambiguous_nodes_in_cycle_detection() -> None:
    payload = {
        "markup_type": "service",
        "procedures": [
            {
                "proc_id": "p1",
                "start_block_ids": ["a"],
                "end_block_ids": ["b::end"],
                "branches": {"a": ["b"]},
            },
            {
                "proc_id": "p2",
                "start_block_ids": ["a"],
                "end_block_ids": ["c::end"],
                "branches": {"a": ["c"]},
            },
        ],
        "block_graph": {"a": ["b"], "b": ["c"], "c": ["a"]},
    }
    markup = MarkupDocument.model_validate(payload)
    excal: ExcalidrawDocument = MarkupToExcalidrawConverter(GridLayoutEngine()).convert(markup)

    cycle_edges = [
        element
        for element in excal.elements
        if element.get("type") == "arrow"
        and element.get("customData", {}).get("cjm", {}).get("edge_type") == "block_graph_cycle"
    ]
    flow_edges = [
        element
        for element in excal.elements
        if element.get("type") == "arrow"
        and element.get("customData", {}).get("cjm", {}).get("edge_type") == "block_graph"
    ]
    assert not cycle_edges
    assert len(flow_edges) == 3
    edge_pairs = {
        (
            edge.get("customData", {}).get("cjm", {}).get("procedure_id"),
            edge.get("customData", {}).get("cjm", {}).get("source_block_id"),
            edge.get("customData", {}).get("cjm", {}).get("target_procedure_id"),
            edge.get("customData", {}).get("cjm", {}).get("target_block_id"),
        )
        for edge in flow_edges
    }
    assert edge_pairs == {
        ("p1", "a", "p1", "b"),
        ("p1", "b", "p2", "c"),
        ("p2", "c", "p2", "a"),
    }
