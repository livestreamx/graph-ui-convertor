from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from domain.models import CUSTOM_DATA_KEY

Element = dict[str, Any]


@dataclass(frozen=True)
class ExcalidrawLinkTemplates:
    procedure: str | None = None
    block: str | None = None

    def has_any(self) -> bool:
        return bool(_normalize_template(self.procedure) or _normalize_template(self.block))

    def procedure_link(self, procedure_id: str) -> str | None:
        return _format_template(self.procedure, procedure_id=procedure_id)

    def block_link(self, block_id: str) -> str | None:
        return _format_template(self.block, block_id=block_id)


def build_link_templates(
    procedure_template: str | None,
    block_template: str | None,
) -> ExcalidrawLinkTemplates | None:
    templates = ExcalidrawLinkTemplates(procedure_template, block_template)
    return templates if templates.has_any() else None


def ensure_excalidraw_links(
    elements: list[Element],
    templates: ExcalidrawLinkTemplates | None,
) -> None:
    if not templates or not templates.has_any():
        return
    for element in elements:
        meta = _metadata(element)
        role = meta.get("role")
        if role == "frame":
            procedure_id = meta.get("procedure_id")
            if isinstance(procedure_id, str):
                link = templates.procedure_link(procedure_id)
                if link:
                    element["link"] = link
        elif role in {"block", "block_label"}:
            block_id = meta.get("block_id")
            if isinstance(block_id, str):
                link = templates.block_link(block_id)
                if link:
                    element["link"] = link


def _metadata(element: Mapping[str, Any]) -> dict[str, Any]:
    custom = element.get("customData")
    if not isinstance(custom, Mapping):
        return {}
    meta = custom.get(CUSTOM_DATA_KEY)
    return dict(meta) if isinstance(meta, Mapping) else {}


def _normalize_template(template: str | None) -> str:
    if template is None:
        return ""
    return str(template).strip()


def _format_template(template: str | None, **kwargs: str) -> str | None:
    normalized = _normalize_template(template)
    if not normalized:
        return None
    try:
        return normalized.format(**kwargs)
    except (KeyError, ValueError):
        return normalized
