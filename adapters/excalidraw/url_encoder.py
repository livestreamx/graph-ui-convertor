from __future__ import annotations

import json
from typing import Any, cast

from lzstring import LZString  # type: ignore[import-untyped]


def encode_scene_payload(scene: dict[str, Any]) -> str:
    payload = json.dumps(scene, ensure_ascii=True, separators=(",", ":"))
    encoded = LZString().compressToEncodedURIComponent(payload)
    return cast(str, encoded)


def build_excalidraw_url(base_url: str, scene: dict[str, Any]) -> str:
    clean_base = base_url.split("#", 1)[0]
    encoded = encode_scene_payload(scene)
    return f"{clean_base}#json={encoded}"
