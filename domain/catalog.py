from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from domain.models import MarkupDocument


@dataclass(frozen=True)
class MarkupSourceItem:
    path: Path
    document: MarkupDocument
    raw: dict[str, Any]
    updated_at: datetime


@dataclass(frozen=True)
class CatalogItem:
    scene_id: str
    title: str
    tags: list[str]
    updated_at: str
    markup_type: str
    finedog_unit_id: str
    criticality_level: str
    team_id: str
    team_name: str
    group_values: dict[str, str]
    fields: dict[str, str]
    markup_meta: dict[str, str]
    markup_rel_path: str
    excalidraw_rel_path: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "scene_id": self.scene_id,
            "title": self.title,
            "tags": list(self.tags),
            "updated_at": self.updated_at,
            "markup_type": self.markup_type,
            "finedog_unit_id": self.finedog_unit_id,
            "criticality_level": self.criticality_level,
            "team_id": self.team_id,
            "team_name": self.team_name,
            "group_values": dict(self.group_values),
            "fields": dict(self.fields),
            "markup_meta": dict(self.markup_meta),
            "markup_rel_path": self.markup_rel_path,
            "excalidraw_rel_path": self.excalidraw_rel_path,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> CatalogItem:
        return cls(
            scene_id=str(payload.get("scene_id", "")),
            title=str(payload.get("title", "")),
            tags=list(payload.get("tags", []) or []),
            updated_at=str(payload.get("updated_at", "")),
            markup_type=str(payload.get("markup_type", "")),
            finedog_unit_id=str(payload.get("finedog_unit_id", "")),
            criticality_level=str(payload.get("criticality_level", "")),
            team_id=str(payload.get("team_id", "")),
            team_name=str(payload.get("team_name", "")),
            group_values=dict(payload.get("group_values", {}) or {}),
            fields=dict(payload.get("fields", {}) or {}),
            markup_meta=dict(payload.get("markup_meta", {}) or {}),
            markup_rel_path=str(payload.get("markup_rel_path", "")),
            excalidraw_rel_path=str(payload.get("excalidraw_rel_path", "")),
        )


@dataclass(frozen=True)
class CatalogIndex:
    generated_at: str
    group_by: list[str]
    title_field: str
    tag_fields: list[str]
    sort_by: str
    sort_order: str
    unknown_value: str
    items: list[CatalogItem] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "generated_at": self.generated_at,
            "group_by": list(self.group_by),
            "title_field": self.title_field,
            "tag_fields": list(self.tag_fields),
            "sort_by": self.sort_by,
            "sort_order": self.sort_order,
            "unknown_value": self.unknown_value,
            "items": [item.to_dict() for item in self.items],
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> CatalogIndex:
        items_payload = payload.get("items", [])
        items = [CatalogItem.from_dict(item) for item in items_payload or []]
        return cls(
            generated_at=str(payload.get("generated_at", "")),
            group_by=list(payload.get("group_by", []) or []),
            title_field=str(payload.get("title_field", "")),
            tag_fields=list(payload.get("tag_fields", []) or []),
            sort_by=str(payload.get("sort_by", "")),
            sort_order=str(payload.get("sort_order", "")),
            unknown_value=str(payload.get("unknown_value", "")),
            items=items,
        )


@dataclass(frozen=True)
class CatalogIndexConfig:
    markup_dir: Path
    excalidraw_in_dir: Path
    index_path: Path
    group_by: list[str]
    title_field: str
    tag_fields: list[str]
    sort_by: str
    sort_order: str
    unknown_value: str

    def config_fields(self) -> list[str]:
        fields = [self.title_field, *self.tag_fields, *self.group_by]
        result: list[str] = []
        seen: set[str] = set()
        for field_name in fields:
            if not field_name or field_name in seen:
                continue
            seen.add(field_name)
            result.append(field_name)
        return result

    def created_at(self) -> str:
        return datetime.utcnow().isoformat()
