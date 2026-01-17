from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from filelock import FileLock

from adapters.filesystem.json_utils import load_json, write_json_atomic
from domain.ports.catalog import SceneRepository


class FileSystemSceneRepository(SceneRepository):
    def load(self, path: Path) -> dict[str, Any]:
        return load_json(path)

    def save(self, payload: Mapping[str, Any], path: Path) -> None:
        lock_path = path.with_suffix(f"{path.suffix}.lock")
        with FileLock(str(lock_path)):
            write_json_atomic(path, dict(payload))

    def clear_cache(self, directory: Path) -> int:
        if not directory.exists():
            return 0
        removed = 0
        for path in directory.iterdir():
            if not path.is_file():
                continue
            suffix = path.suffix.lower()
            if suffix in {".excalidraw", ".unidraw", ".json"} or path.name.endswith(".lock"):
                path.unlink()
                removed += 1
        return removed
