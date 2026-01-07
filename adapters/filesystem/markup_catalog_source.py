from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from domain.catalog import MarkupSourceItem
from domain.models import MarkupDocument
from domain.ports.catalog import MarkupCatalogSource

from adapters.filesystem.markup_utils import iter_markup_paths, strip_markup_comments


class FileSystemMarkupCatalogSource(MarkupCatalogSource):
    def load_all(self, directory: Path) -> list[MarkupSourceItem]:
        items: list[MarkupSourceItem] = []
        for path in sorted(iter_markup_paths(directory)):
            raw = self._load_raw(path)
            document = MarkupDocument.model_validate(raw)
            updated_at = datetime.fromtimestamp(path.stat().st_mtime, tz=UTC)
            items.append(
                MarkupSourceItem(
                    path=path,
                    document=document,
                    raw=raw,
                    updated_at=updated_at,
                )
            )
        return items

    def _load_raw(self, path: Path) -> dict[str, Any]:
        text = path.read_text(encoding="utf-8")
        cleaned = strip_markup_comments(text)
        content = json.loads(cleaned)
        return content if isinstance(content, dict) else {}
