from __future__ import annotations

import json
from pathlib import Path

from adapters.filesystem.markup_utils import iter_markup_paths, strip_markup_comments
from domain.models import MarkupDocument
from domain.ports.repositories import MarkupRepository


class FileSystemMarkupRepository(MarkupRepository):
    def load_all(self, directory: Path) -> list[MarkupDocument]:
        return [document for _, document in self.load_all_with_paths(directory)]

    def load_all_with_paths(self, directory: Path) -> list[tuple[Path, MarkupDocument]]:
        documents: list[tuple[Path, MarkupDocument]] = []
        for path in sorted(iter_markup_paths(directory)):
            text = path.read_text(encoding="utf-8")
            content = json.loads(strip_markup_comments(text))
            documents.append((path, MarkupDocument.model_validate(content)))
        return documents

    def load_by_path(self, path: Path) -> MarkupDocument:
        text = path.read_text(encoding="utf-8")
        content = json.loads(strip_markup_comments(text))
        return MarkupDocument.model_validate(content)

    def load_raw(self, path: Path) -> bytes:
        return path.read_bytes()

    def save(self, document: MarkupDocument, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = document.to_markup_dict()
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
