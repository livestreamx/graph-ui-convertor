from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Protocol

from domain.catalog import CatalogIndex, MarkupSourceItem


class MarkupCatalogSource(Protocol):
    def load_all(self, directory: Path) -> Sequence[MarkupSourceItem]: ...

    def fingerprint(self, directory: Path) -> str: ...


class CatalogIndexRepository(Protocol):
    def load(self, path: Path) -> CatalogIndex: ...

    def save(self, index: CatalogIndex, path: Path) -> None: ...


class SceneRepository(Protocol):
    def load(self, path: Path) -> dict[str, Any]: ...

    def save(self, payload: Mapping[str, Any], path: Path) -> None: ...
