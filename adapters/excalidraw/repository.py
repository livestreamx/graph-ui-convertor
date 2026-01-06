from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path

from domain.models import ExcalidrawDocument
from domain.ports.repositories import ExcalidrawRepository


class FileSystemExcalidrawRepository(ExcalidrawRepository):
    def load_all(self, directory: Path) -> list[ExcalidrawDocument]:
        return [document for _, document in self.load_all_with_paths(directory)]

    def load_all_with_paths(self, directory: Path) -> list[tuple[Path, ExcalidrawDocument]]:
        documents: list[tuple[Path, ExcalidrawDocument]] = []
        for path in sorted(self._iter_paths(directory)):
            data = json.loads(path.read_text(encoding="utf-8"))
            documents.append(
                (
                    path,
                    ExcalidrawDocument(
                        elements=data.get("elements", []),
                        app_state=data.get("appState", {}),
                        files=data.get("files", {}),
                    ),
                )
            )
        return documents

    def save(self, document: ExcalidrawDocument, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(document.to_dict(), indent=2), encoding="utf-8")

    def _iter_paths(self, directory: Path) -> Iterable[Path]:
        for pattern in ("*.excalidraw", "*.json"):
            yield from directory.glob(pattern)
