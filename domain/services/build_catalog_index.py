from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from datetime import UTC
from pathlib import Path
from typing import Any

from domain.catalog import CatalogIndex, CatalogIndexConfig, CatalogItem, MarkupSourceItem
from domain.models import MarkupDocument
from domain.ports.catalog import CatalogIndexRepository, MarkupCatalogSource

_SLUG_RE = re.compile(r"[^a-zA-Z0-9]+")


class BuildCatalogIndex:
    def __init__(
        self,
        source: MarkupCatalogSource,
        index_repo: CatalogIndexRepository,
    ) -> None:
        self._source = source
        self._index_repo = index_repo

    def build(self, config: CatalogIndexConfig) -> CatalogIndex:
        entries = self._source.load_all(config.markup_dir)
        items = [self._build_item(entry, config) for entry in entries]
        items = self._sort_items(items, config)
        index = CatalogIndex(
            generated_at=self._generated_at(entries),
            group_by=list(config.group_by),
            title_field=config.title_field,
            tag_fields=list(config.tag_fields),
            sort_by=config.sort_by,
            sort_order=config.sort_order,
            unknown_value=config.unknown_value,
            items=items,
        )
        self._index_repo.save(index, config.index_path)
        return index

    def source_fingerprint(self, config: CatalogIndexConfig) -> str:
        return self._source.fingerprint(config.markup_dir)

    def _build_item(self, entry: MarkupSourceItem, config: CatalogIndexConfig) -> CatalogItem:
        raw = entry.raw
        document = entry.document
        resolved_finedog_unit_id = self._resolve_first(
            raw,
            document,
            ["finedog_unit_id", "finedog_unit_meta.unit_id"],
            default="",
        )
        scene_id = resolved_finedog_unit_id or self._build_legacy_scene_id(entry.path.stem, raw)

        group_values = {
            field: self._stringify(self._resolve_field(raw, document, field), config.unknown_value)
            for field in config.group_by
        }
        fields = {
            field: self._stringify(self._resolve_field(raw, document, field), config.unknown_value)
            for field in config.config_fields()
        }
        title = self._stringify(
            self._resolve_field(raw, document, config.title_field),
            "",
        )
        if not title:
            title = document.service_name or entry.path.stem

        tags = self._extract_tags(raw, document, config.tag_fields)
        markup_type = document.markup_type
        finedog_unit_id = resolved_finedog_unit_id or config.unknown_value
        criticality_level = self._resolve_first(
            raw,
            document,
            ["criticality_level", "finedog_unit_meta.criticality_level"],
            default=config.unknown_value,
        )
        team_id = self._resolve_first(
            raw,
            document,
            ["team_id", "finedog_unit_meta.team_id"],
            default=config.unknown_value,
        )
        team_name = self._resolve_first(
            raw,
            document,
            ["team_name", "finedog_unit_meta.team_name"],
            default="",
        )
        if not team_name and team_id and team_id != config.unknown_value:
            team_name = team_id
        if not team_name:
            team_name = config.unknown_value
        markup_meta = self._extract_markup_meta(raw)
        procedure_blocks = self._extract_procedure_blocks(document)
        procedure_ids = list(procedure_blocks.keys())
        block_ids = self._collect_block_ids(procedure_blocks)

        markup_rel_path = self._relative_path(entry.path, config.markup_dir)
        excalidraw_rel_path = f"{entry.path.stem}.excalidraw"
        unidraw_rel_path = f"{entry.path.stem}.unidraw"

        updated_at = entry.updated_at
        if updated_at.tzinfo is None:
            updated_at = updated_at.replace(tzinfo=UTC)

        return CatalogItem(
            scene_id=scene_id,
            title=title,
            tags=tags,
            updated_at=updated_at.isoformat(),
            markup_type=markup_type,
            finedog_unit_id=finedog_unit_id,
            criticality_level=criticality_level,
            team_id=team_id,
            team_name=team_name,
            group_values=group_values,
            fields=self._inject_extra_fields(
                fields,
                criticality_level=criticality_level,
                team_id=team_id,
                team_name=team_name,
            ),
            markup_meta=markup_meta,
            markup_rel_path=markup_rel_path,
            excalidraw_rel_path=excalidraw_rel_path,
            unidraw_rel_path=unidraw_rel_path,
            procedure_ids=procedure_ids,
            block_ids=block_ids,
            procedure_blocks=procedure_blocks,
        )

    def _relative_path(self, path: Path, base: Path) -> str:
        try:
            return str(path.relative_to(base).as_posix())
        except Exception:
            return str(path.name)

    def _resolve_first(
        self,
        raw: Mapping[str, Any],
        document: MarkupDocument,
        fields: list[str],
        default: str,
    ) -> str:
        for field in fields:
            value = self._resolve_field(raw, document, field)
            if value is not None:
                return self._stringify(value, default)
        return default

    def _resolve_field(
        self,
        raw: Mapping[str, Any],
        document: MarkupDocument,
        field_path: str,
    ) -> Any:
        value = self._get_by_path(raw, field_path)
        if value is None and hasattr(document, field_path):
            value = getattr(document, field_path)
        return value

    def _extract_tags(
        self,
        raw: Mapping[str, Any],
        document: MarkupDocument,
        fields: list[str],
    ) -> list[str]:
        tags: list[str] = []
        for field in fields:
            value = self._resolve_field(raw, document, field)
            tags.extend(self._normalize_tags(value))
        return self._unique(tags)

    def _extract_markup_meta(self, raw: Mapping[str, Any]) -> dict[str, str]:
        meta = raw.get("finedog_unit_meta")
        if not isinstance(meta, Mapping):
            return {}
        filtered: dict[str, str] = {}
        skip_fields = {
            "service_name",
            "criticality_level",
            "team_id",
            "team_name",
            "unit_id",
        }
        for key, value in meta.items():
            if key in skip_fields:
                continue
            text = self._stringify_meta(value)
            if text:
                filtered[str(key)] = text
        return dict(sorted(filtered.items()))

    def _stringify_meta(self, value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, Mapping):
            return json.dumps(value, sort_keys=True, ensure_ascii=True)
        if isinstance(value, list):
            joined = ", ".join(str(item).strip() for item in value if str(item).strip())
            return joined
        return str(value).strip()

    def _inject_extra_fields(
        self,
        fields: dict[str, str],
        criticality_level: str,
        team_id: str,
        team_name: str,
    ) -> dict[str, str]:
        fields.setdefault("criticality_level", criticality_level)
        fields.setdefault("team_id", team_id)
        fields.setdefault("team_name", team_name)
        return fields

    def _extract_procedure_blocks(self, document: MarkupDocument) -> dict[str, list[str]]:
        result: dict[str, list[str]] = {}
        for procedure in document.procedures:
            procedure_id = str(procedure.procedure_id).strip()
            if not procedure_id or procedure_id in result:
                continue
            block_ids = sorted(procedure.block_ids(), key=str.lower)
            result[procedure_id] = block_ids
        return result

    def _collect_block_ids(self, procedure_blocks: Mapping[str, list[str]]) -> list[str]:
        result: list[str] = []
        seen: set[str] = set()
        for block_ids in procedure_blocks.values():
            for block_id in block_ids:
                normalized = str(block_id).strip()
                if not normalized or normalized in seen:
                    continue
                seen.add(normalized)
                result.append(normalized)
        return result

    def _normalize_tags(self, value: Any) -> list[str]:
        if value is None:
            return []
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()]
        if isinstance(value, str):
            if "," in value:
                return [part.strip() for part in value.split(",") if part.strip()]
            return [value.strip()] if value.strip() else []
        return [str(value).strip()]

    def _unique(self, values: list[str]) -> list[str]:
        result: list[str] = []
        seen: set[str] = set()
        for value in values:
            if value in seen:
                continue
            seen.add(value)
            result.append(value)
        return result

    def _stringify(self, value: Any, default: str) -> str:
        if value is None:
            return default
        if isinstance(value, list):
            joined = ", ".join(str(item).strip() for item in value if str(item).strip())
            return joined if joined else default
        if isinstance(value, str):
            cleaned = value.strip()
            return cleaned if cleaned else default
        return str(value).strip() or default

    def _sort_items(
        self,
        items: list[CatalogItem],
        config: CatalogIndexConfig,
    ) -> list[CatalogItem]:
        sort_by = config.sort_by
        reverse = str(config.sort_order).lower() == "desc"

        def sort_key(item: CatalogItem) -> str:
            if sort_by == "title":
                return item.title.lower()
            if sort_by == "updated_at":
                return item.updated_at
            if sort_by == "markup_type":
                return item.markup_type
            if sort_by == "finedog_unit_id":
                return item.finedog_unit_id
            if sort_by in item.group_values:
                return item.group_values.get(sort_by, "")
            if sort_by in item.fields:
                return item.fields.get(sort_by, "")
            return item.title.lower()

        return sorted(items, key=sort_key, reverse=reverse)

    def _get_by_path(self, data: Mapping[str, Any], path: str) -> Any:
        current: Any = data
        for key in path.split("."):
            if not isinstance(current, Mapping) or key not in current:
                return None
            current = current[key]
        return current

    def _slugify(self, value: str) -> str:
        slug = _SLUG_RE.sub("-", value).strip("-")
        return slug.lower() if slug else "scene"

    def _hash_payload(self, payload: Mapping[str, Any]) -> str:
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        return digest

    def _build_legacy_scene_id(self, stem: str, payload: Mapping[str, Any]) -> str:
        slug = self._slugify(stem)
        payload_hash = self._hash_payload(payload)
        return f"{slug}-{payload_hash[:10]}"

    def _generated_at(self, entries: Sequence[MarkupSourceItem]) -> str:
        if not entries:
            return ""
        latest = max(entry.updated_at for entry in entries)
        if latest.tzinfo is None:
            latest = latest.replace(tzinfo=UTC)
        return latest.isoformat()
