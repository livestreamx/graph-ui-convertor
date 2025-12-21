from __future__ import annotations

from typing import Protocol

from domain.models import LayoutPlan, MarkupDocument


class LayoutEngine(Protocol):
    def build_plan(self, document: MarkupDocument) -> LayoutPlan:
        ...
