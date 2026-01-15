from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path

from domain.models import UnidrawDocument
from domain.ports.repositories import UnidrawRepository


class FileSystemUnidrawRepository(UnidrawRepository):
    def load_all(self, directory: Path) -> list[UnidrawDocument]:
        return [document for _, document in self.load_all_with_paths(directory)]

    def load_all_with_paths(self, directory: Path) -> list[tuple[Path, UnidrawDocument]]:
        documents: list[tuple[Path, UnidrawDocument]] = []
        for path in sorted(self._iter_paths(directory)):
            data = json.loads(path.read_text(encoding="utf-8"))
            documents.append(
                (
                    path,
                    UnidrawDocument(
                        elements=data.get("elements", []),
                        app_state=data.get("appState", {}),
                    ),
                )
            )
        return documents

    def save(self, document: UnidrawDocument, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(document.to_dict(), indent=2), encoding="utf-8")

    def _iter_paths(self, directory: Path) -> Iterable[Path]:
        for pattern in ("*.unidraw", "*.json"):
            yield from directory.glob(pattern)
