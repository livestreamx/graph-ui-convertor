from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Protocol

from domain.models import ExcalidrawDocument, MarkupDocument


class MarkupRepository(Protocol):
    def load_all(self, directory: Path) -> Sequence[MarkupDocument]: ...

    def load_all_with_paths(self, directory: Path) -> Sequence[tuple[Path, MarkupDocument]]: ...

    def load_by_path(self, path: Path) -> MarkupDocument: ...

    def load_raw(self, path: Path) -> bytes: ...

    def save(self, document: MarkupDocument, path: Path) -> None: ...


class ExcalidrawRepository(Protocol):
    def load_all(self, directory: Path) -> Sequence[ExcalidrawDocument]: ...

    def load_all_with_paths(self, directory: Path) -> Sequence[tuple[Path, ExcalidrawDocument]]: ...

    def save(self, document: ExcalidrawDocument, path: Path) -> None: ...
