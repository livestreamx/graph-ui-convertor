from __future__ import annotations

from domain.services.convert_excalidraw_to_markup import ExcalidrawToMarkupConverter


def _base_meta(procedure_id: str, block_id: str | None = None) -> dict[str, dict[str, object]]:
    meta = {
        "schema_version": "1.0",
        "procedure_id": procedure_id,
        "finedog_unit_id": 1,
        "markup_type": "service",
    }
    if block_id:
        meta["block_id"] = block_id
    return {"cjm": meta}


def test_branch_arrow_label_roundtrip() -> None:
    procedure_id = "p1"
    frame_id = "frame-1"
    source_id = "block-1"
    target_id = "block-2"
    arrow_id = "arrow-1"

    excal = {
        "elements": [
            {
                "id": frame_id,
                "type": "frame",
                "x": 0,
                "y": 0,
                "width": 400,
                "height": 400,
                "name": procedure_id,
                "customData": _base_meta(procedure_id),
            },
            {
                "id": source_id,
                "type": "rectangle",
                "x": 10,
                "y": 10,
                "width": 100,
                "height": 80,
                "frameId": frame_id,
                "customData": _base_meta(procedure_id, "a"),
            },
            {
                "id": target_id,
                "type": "rectangle",
                "x": 200,
                "y": 10,
                "width": 100,
                "height": 80,
                "frameId": frame_id,
                "customData": _base_meta(procedure_id, "b"),
            },
            {
                "id": arrow_id,
                "type": "arrow",
                "x": 10,
                "y": 10,
                "width": 200,
                "height": 0,
                "text": "branch",
                "points": [[0, 0], [200, 0]],
                "startBinding": {"elementId": source_id},
                "endBinding": {"elementId": target_id},
                "customData": {
                    "cjm": {
                        "schema_version": "1.0",
                        "edge_type": "branch",
                        "procedure_id": procedure_id,
                    }
                },
            },
        ],
        "appState": {},
        "files": {},
    }

    markup = ExcalidrawToMarkupConverter().convert(excal)
    assert markup.procedures[0].branches == {"a": ["b"]}
