from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from domain.ports.catalog import SceneRepository
from filelock import FileLock

from adapters.filesystem.json_utils import load_json, write_json_atomic


class FileSystemSceneRepository(SceneRepository):
    def load(self, path: Path) -> dict[str, Any]:
        return load_json(path)

    def save(self, payload: Mapping[str, Any], path: Path) -> None:
        lock_path = path.with_suffix(f"{path.suffix}.lock")
        with FileLock(str(lock_path)):
            write_json_atomic(path, dict(payload))
