from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import orjson


def load_json(path: Path) -> dict[str, Any]:
    data = orjson.loads(path.read_bytes())
    return data if isinstance(data, dict) else {}


def dump_json_bytes(payload: Any) -> bytes:
    try:
        return orjson.dumps(payload, option=orjson.OPT_INDENT_2)
    except TypeError:
        return json.dumps(payload, ensure_ascii=True, indent=2).encode("utf-8")


def write_json_atomic(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(f"{path.suffix}.tmp")
    tmp_path.write_bytes(dump_json_bytes(payload))
    tmp_path.replace(path)
