from __future__ import annotations

import json

from lzstring import LZString  # type: ignore[import-untyped]

from adapters.excalidraw.url_encoder import encode_scene_payload


def test_encode_scene_payload_roundtrip() -> None:
    payload = {
        "elements": [],
        "appState": {"theme": "light"},
        "files": {},
    }
    encoded = encode_scene_payload(payload)
    decoded = LZString().decompressFromEncodedURIComponent(encoded)
    assert json.loads(decoded) == payload
