from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from string import Formatter
from typing import Any

from domain.models import CUSTOM_DATA_KEY

Element = dict[str, Any]
_FORMATTER = Formatter()


@dataclass(frozen=True)
class ExcalidrawLinkTemplates:
    procedure: str | None = None
    block: str | None = None

    def has_any(self) -> bool:
        return bool(_normalize_template(self.procedure) or _normalize_template(self.block))

    def procedure_link(self, procedure_id: str) -> str | None:
        return _format_template(self.procedure, procedure_id=procedure_id)

    def block_link(self, block_id: str, procedure_id: str | None = None) -> str | None:
        return _format_template(self.block, block_id=block_id, procedure_id=procedure_id)


def build_link_templates(
    procedure_path: str | None,
    block_path: str | None,
) -> ExcalidrawLinkTemplates | None:
    templates = ExcalidrawLinkTemplates(procedure_path, block_path)
    return templates if templates.has_any() else None


def ensure_excalidraw_links(
    elements: list[Element],
    templates: ExcalidrawLinkTemplates | None,
) -> None:
    if not templates or not templates.has_any():
        return
    for element in elements:
        meta = _metadata_from_excalidraw(element)
        role = meta.get("role")
        if role == "frame":
            procedure_id = meta.get("procedure_id")
            if isinstance(procedure_id, str):
                link = templates.procedure_link(procedure_id)
                if link:
                    element["link"] = link
        elif role in {"block", "block_label"}:
            block_id = meta.get("block_id")
            procedure_id = meta.get("procedure_id")
            if isinstance(block_id, str):
                link = templates.block_link(
                    block_id,
                    procedure_id if isinstance(procedure_id, str) else None,
                )
                if link:
                    element["link"] = link


def ensure_unidraw_links(
    elements: list[Element],
    templates: ExcalidrawLinkTemplates | None,
) -> None:
    if not templates or not templates.has_any():
        return
    for element in elements:
        meta = _metadata_from_unidraw(element)
        role = meta.get("role")
        if role == "frame":
            procedure_id = meta.get("procedure_id")
            if isinstance(procedure_id, str):
                link = templates.procedure_link(procedure_id)
                if link:
                    element["link"] = link
        elif role == "block":
            block_id = meta.get("block_id")
            procedure_id = meta.get("procedure_id")
            if isinstance(block_id, str):
                link = templates.block_link(
                    block_id,
                    procedure_id if isinstance(procedure_id, str) else None,
                )
                if link:
                    element["link"] = link


def _metadata_from_excalidraw(element: Mapping[str, Any]) -> dict[str, Any]:
    custom = element.get("customData")
    if not isinstance(custom, Mapping):
        return {}
    meta = custom.get(CUSTOM_DATA_KEY)
    return dict(meta) if isinstance(meta, Mapping) else {}


def _metadata_from_unidraw(element: Mapping[str, Any]) -> dict[str, Any]:
    meta = element.get(CUSTOM_DATA_KEY)
    return dict(meta) if isinstance(meta, Mapping) else {}


def _normalize_template(template: str | None) -> str:
    if template is None:
        return ""
    normalized = str(template).strip()
    if not normalized:
        return ""
    return (
        normalized.replace("%7B", "{").replace("%7b", "{").replace("%7D", "}").replace("%7d", "}")
    )


def _template_fields(template: str) -> set[str]:
    return {field for _, field, _, _ in _FORMATTER.parse(template) if field}


def _format_template(template: str | None, **kwargs: str | None) -> str | None:
    normalized = _normalize_template(template)
    if not normalized:
        return None
    try:
        fields = _template_fields(normalized)
        if not fields:
            return normalized
        values = {}
        for field in fields:
            value = kwargs.get(field)
            if not isinstance(value, str) or not value:
                return None
            values[field] = value
        return normalized.format(**values)
    except (KeyError, ValueError):
        return normalized
