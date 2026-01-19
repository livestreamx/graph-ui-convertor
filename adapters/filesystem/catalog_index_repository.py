from __future__ import annotations

from pathlib import Path

from filelock import FileLock

from adapters.filesystem.json_utils import load_json, write_json_atomic
from domain.catalog import CatalogIndex
from domain.ports.catalog import CatalogIndexRepository


class FileSystemCatalogIndexRepository(CatalogIndexRepository):
    def load(self, path: Path) -> CatalogIndex:
        payload = load_json(path)
        return CatalogIndex.from_dict(payload)

    def save(self, index: CatalogIndex, path: Path) -> None:
        lock_path = path.with_suffix(f"{path.suffix}.lock")
        with FileLock(str(lock_path)):
            write_json_atomic(path, index.to_dict())
