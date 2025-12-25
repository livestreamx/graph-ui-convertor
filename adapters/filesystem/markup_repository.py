from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable, List

from domain.models import MarkupDocument
from domain.ports.repositories import MarkupRepository


class FileSystemMarkupRepository(MarkupRepository):
    def load_all(self, directory: Path) -> List[MarkupDocument]:
        return [document for _, document in self.load_all_with_paths(directory)]

    def load_all_with_paths(self, directory: Path) -> List[tuple[Path, MarkupDocument]]:
        documents: List[tuple[Path, MarkupDocument]] = []
        for path in sorted(self._iter_paths(directory)):
            text = path.read_text(encoding="utf-8")
            content = json.loads(self._strip_comments(text))
            documents.append((path, MarkupDocument.model_validate(content)))
        return documents

    def save(self, document: MarkupDocument, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = document.to_markup_dict()
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def _iter_paths(self, directory: Path) -> Iterable[Path]:
        for path in directory.glob("*.json"):
            yield path
        for path in directory.glob("*.excalidraw.json"):
            yield path
        for path in directory.glob("*.txt"):
            yield path

    def _strip_comments(self, content: str) -> str:
        result_lines: List[str] = []
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
