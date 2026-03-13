from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path
from typing import Any


def iter_markup_paths(directory: Path) -> Iterable[Path]:
    for pattern in ("*.json", "*.excalidraw.json", "*.txt"):
        yield from directory.glob(pattern)


def strip_markup_comments(content: str) -> str:
    result_lines: list[str] = []
    for line in content.splitlines():
        in_string = False
        escaped = False
        cleaned = []
        for idx, char in enumerate(line):
            if not escaped and char == '"' and (idx == 0 or line[idx - 1] != "\\"):
                in_string = not in_string
            if not in_string and char == "/" and idx + 1 < len(line) and line[idx + 1] == "/":
                break
            cleaned.append(char)
            escaped = char == "\\" and not escaped
        result_lines.append("".join(cleaned))
    return "\n".join(result_lines)


def parse_markup_json(content: str) -> dict[str, Any]:
    cleaned = strip_markup_comments(content)
    data = json.loads(cleaned, strict=False)
    return data if isinstance(data, dict) else {}
