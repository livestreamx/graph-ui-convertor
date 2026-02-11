from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator, model_validator

METADATA_SCHEMA_VERSION = "1.0"
CUSTOM_DATA_KEY = "cjm"
END_BLOCK_SEPARATOR = "::"
END_TYPE_DEFAULT = "end"
END_TYPE_TURN_OUT = "turn_out"
END_TYPE_VALUES = {"end", "exit", "all", "intermediate", "postpone", END_TYPE_TURN_OUT}
BLOCK_GRAPH_INITIAL_SUFFIX = "initial"
END_TYPE_COLORS = {
    "end": "#8fdc8f",
    "exit": "#ffe08a",
    "all": "#ffb347",
    "intermediate": "#ffb347",
    "postpone": "#d9d9d9",
    END_TYPE_TURN_OUT: "#cfe3ff",
}
INTERMEDIATE_BLOCK_COLOR = "#ffb347"
INITIAL_BLOCK_COLOR = "#d1ffd6"


def normalize_end_type(value: str | None) -> str | None:
    if not value:
        return None
    candidate = str(value).strip().lower()
    return candidate if candidate in END_TYPE_VALUES else None


def normalize_finedog_unit_id(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    if isinstance(value, int):
        return str(value)
    return str(value)


def split_end_block_id(raw: str) -> tuple[str, str]:
    base = str(raw)
    if END_BLOCK_SEPARATOR in base:
        head, suffix = base.rsplit(END_BLOCK_SEPARATOR, 1)
        normalized = normalize_end_type(suffix)
        if normalized:
            return head, normalized
    return base, END_TYPE_DEFAULT


def split_block_graph_id(raw: str) -> tuple[str, bool]:
    base = str(raw)
    if END_BLOCK_SEPARATOR in base:
        head, suffix = base.rsplit(END_BLOCK_SEPARATOR, 1)
        if suffix.strip().lower() == BLOCK_GRAPH_INITIAL_SUFFIX:
            return head, True
    return base, False


def merge_end_types(existing: str | None, new: str) -> str:
    if not existing:
        return new
    if existing == new:
        return existing
    if existing == END_TYPE_TURN_OUT:
        return new
    if new == END_TYPE_TURN_OUT:
        return existing
    if existing == "postpone" or new == "postpone":
        return "postpone"
    if existing == "intermediate" or new == "intermediate":
        return "intermediate"
    if existing == "all" or new == "all":
        return "all"
    if {existing, new} == {"end", "exit"}:
        return "all"
    return new


class Procedure(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    procedure_id: str = Field(
        ...,
        min_length=1,
        validation_alias=AliasChoices("procedure_id", "proc_id"),
    )
    procedure_name: str | None = Field(
        default=None,
        validation_alias=AliasChoices("procedure_name", "proc_name"),
    )
    start_block_ids: list[str] = Field(default_factory=list)
    end_block_ids: list[str] = Field(default_factory=list)
    end_block_types: dict[str, str] = Field(default_factory=dict)
    branches: dict[str, list[str]] = Field(default_factory=dict)
    block_id_to_block_name: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def normalize_end_blocks(cls, data: object) -> object:
        if not isinstance(data, dict):
            return data
        end_block_ids = list(data.get("end_block_ids") or [])
        raw_end_block_types = dict(data.get("end_block_types") or {})
        end_block_types: dict[str, str] = {}
        for block_id, end_type in raw_end_block_types.items():
            normalized = normalize_end_type(end_type)
            if normalized:
                end_block_types[str(block_id)] = normalized
        normalized_end_ids: list[str] = []
        seen_end_ids: set[str] = set()

        for raw in end_block_ids:
            raw_value = str(raw)
            has_suffix = END_BLOCK_SEPARATOR in raw_value
            block_id, end_type = split_end_block_id(raw_value)
            if block_id not in seen_end_ids:
                normalized_end_ids.append(block_id)
                seen_end_ids.add(block_id)
            normalized = normalize_end_type(end_type) or END_TYPE_DEFAULT
            if normalized != END_TYPE_DEFAULT or has_suffix:
                end_block_types[block_id] = merge_end_types(
                    end_block_types.get(block_id), normalized
                )

        branches = data.get("branches") or {}
        cleaned_branches: dict[str, list[str]] = {}
        for source, targets in branches.items():
            if not isinstance(targets, list):
                continue
            cleaned_targets: list[str] = []
            for target in targets:
                if isinstance(target, str) and target.lower() == "end":
                    if source not in seen_end_ids:
                        normalized_end_ids.append(source)
                        seen_end_ids.add(source)
                    end_block_types[source] = merge_end_types(
                        end_block_types.get(source), END_TYPE_DEFAULT
                    )
                    continue
                cleaned_targets.append(target)
            if cleaned_targets:
                cleaned_branches[source] = cleaned_targets

        data["end_block_ids"] = normalized_end_ids
        data["branches"] = cleaned_branches
        if end_block_types:
            data["end_block_types"] = end_block_types
        return data

    @field_validator("branches", mode="after")
    @classmethod
    def ensure_unique_targets(cls, branches: dict[str, list[str]]) -> dict[str, list[str]]:
        return {key: sorted(set(value)) for key, value in branches.items()}

    def block_ids(self) -> set[str]:
        referenced: set[str] = (
            set(self.start_block_ids) | set(self.end_block_ids) | set(self.branches.keys())
        )
        for targets in self.branches.values():
            referenced.update(targets)
        return referenced

    def to_markup_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "proc_id": self.procedure_id,
            "start_block_ids": _sorted_unique(list(self.start_block_ids)),
            "end_block_ids": _merge_end_block_ids(list(self.end_block_ids), self.end_block_types),
            "branches": _sorted_branches(self.branches),
        }
        if self.procedure_name:
            payload["proc_name"] = self.procedure_name
        if self.block_id_to_block_name:
            payload["block_id_to_block_name"] = dict(self.block_id_to_block_name)
        return payload


class MarkupDocument(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    markup_type: str
    finedog_unit_id: str | None = None
    service_name: str | None = None
    criticality_level: str | None = None
    team_id: int | str | None = None
    team_name: str | None = None
    procedures: list[Procedure] = Field(default_factory=list)
    procedure_graph: dict[str, list[str]] = Field(default_factory=dict)
    block_graph: dict[str, list[str]] = Field(default_factory=dict)
    block_graph_initials: set[str] = Field(default_factory=set)
    procedure_meta: dict[str, dict[str, object]] = Field(default_factory=dict)

    @field_validator("finedog_unit_id", mode="before")
    @classmethod
    def normalize_finedog_unit_id_field(cls, value: Any) -> str | None:
        return normalize_finedog_unit_id(value)

    @model_validator(mode="before")
    @classmethod
    def extract_finedog_unit_meta(cls, data: object) -> object:
        if not isinstance(data, dict):
            return data
        meta = data.get("finedog_unit_meta")
        if not isinstance(meta, dict):
            return data
        updated: dict[str, Any] | None = None
        field_meta_keys = {
            "service_name": ("service_name",),
            "criticality_level": ("criticality_level",),
            "team_id": ("team_id",),
            "team_name": ("team_name",),
            "finedog_unit_id": ("unit_id", "finedog_unit_id"),
        }
        for field_name, keys in field_meta_keys.items():
            if data.get(field_name) is not None:
                continue
            for key in keys:
                if key in meta and meta.get(key) is not None:
                    if updated is None:
                        updated = dict(data)
                    updated[field_name] = meta.get(key)
                    break
        return updated or data

    @model_validator(mode="before")
    @classmethod
    def normalize_block_graph_initials(cls, data: object) -> object:
        if not isinstance(data, dict):
            return data
        raw_graph = data.get("block_graph")
        if not isinstance(raw_graph, dict):
            return data
        updated = dict(data)
        initial_blocks: set[str] = set()
        existing_initials = data.get("block_graph_initials")
        if isinstance(existing_initials, list | set | tuple):
            initial_blocks.update(str(value) for value in existing_initials)
        normalized: dict[str, list[str]] = {}
        for raw_source, raw_targets in raw_graph.items():
            source_id, source_initial = split_block_graph_id(raw_source)
            if source_initial:
                initial_blocks.add(source_id)
            targets = normalized.setdefault(source_id, [])
            if not isinstance(raw_targets, list):
                raw_targets = list(raw_targets) if raw_targets is not None else []
            for raw_target in raw_targets:
                target_id, target_initial = split_block_graph_id(raw_target)
                if target_initial:
                    initial_blocks.add(target_id)
                if target_id not in targets:
                    targets.append(target_id)
        updated["block_graph"] = normalized
        if initial_blocks:
            updated["block_graph_initials"] = initial_blocks
        elif "block_graph_initials" in data:
            updated["block_graph_initials"] = set()
        return updated

    @field_validator("procedures", mode="after")
    @classmethod
    def ensure_unique_procedure_ids(cls, procedures: list[Procedure]) -> list[Procedure]:
        seen: set[str] = set()
        for procedure in procedures:
            if procedure.procedure_id in seen:
                msg = f"Duplicate procedure_id found: {procedure.procedure_id}"
                raise ValueError(msg)
            seen.add(procedure.procedure_id)
        return procedures

    def to_markup_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "markup_type": self.markup_type,
            "procedures": [proc.to_markup_dict() for proc in self.procedures],
        }
        if self.finedog_unit_id:
            payload["finedog_unit_id"] = self.finedog_unit_id
        meta: dict[str, object] = {}
        if self.service_name:
            meta["service_name"] = self.service_name
        if self.criticality_level:
            meta["criticality_level"] = self.criticality_level
        if self.team_id is not None:
            meta["team_id"] = self.team_id
        if self.team_name:
            meta["team_name"] = self.team_name
        if meta:
            payload["finedog_unit_meta"] = meta
        if self.procedure_graph:
            payload["procedure_graph"] = dict(self.procedure_graph)
        if self.block_graph:
            payload["block_graph"] = _format_block_graph(
                self.block_graph, self.block_graph_initials
            )
        return payload


def _format_end_block_id(block_id: str, end_type: str | None) -> str:
    normalized = normalize_end_type(end_type) or END_TYPE_DEFAULT
    if normalized == END_TYPE_DEFAULT:
        return block_id
    return f"{block_id}{END_BLOCK_SEPARATOR}{normalized}"


def _sorted_unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def _sorted_branches(branches: dict[str, list[str]]) -> dict[str, list[str]]:
    return {key: sorted(set(values)) for key, values in branches.items()}


def _format_block_graph(
    block_graph: dict[str, list[str]], initial_blocks: set[str]
) -> dict[str, list[str]]:
    def decorate(block_id: str) -> str:
        if block_id in initial_blocks:
            return f"{block_id}{END_BLOCK_SEPARATOR}{BLOCK_GRAPH_INITIAL_SUFFIX}"
        return block_id

    formatted: dict[str, list[str]] = {}
    for source, targets in block_graph.items():
        formatted[decorate(source)] = [decorate(target) for target in sorted(set(targets))]
    return formatted


def _merge_end_block_ids(block_ids: list[str], end_types: dict[str, str]) -> list[str]:
    return [
        _format_end_block_id(block_id, end_types.get(block_id))
        for block_id in _sorted_unique(block_ids)
    ]


@dataclass(frozen=True)
class Point:
    x: float
    y: float


@dataclass(frozen=True)
class Size:
    width: float
    height: float


@dataclass(frozen=True)
class FramePlacement:
    procedure_id: str
    origin: Point
    size: Size


@dataclass(frozen=True)
class BlockPlacement:
    procedure_id: str
    block_id: str
    position: Point
    size: Size


@dataclass(frozen=True)
class MarkerPlacement:
    procedure_id: str
    block_id: str
    role: str  # "start_marker" or "end_marker"
    position: Point
    size: Size
    end_type: str | None = None


@dataclass(frozen=True)
class SeparatorPlacement:
    start: Point
    end: Point


@dataclass(frozen=True)
class ServiceZonePlacement:
    service_key: str
    service_name: str
    markup_type: str | None
    team_name: str | None
    team_id: str | int | None
    color: str
    origin: Point
    size: Size
    label_origin: Point
    label_size: Size
    label_font_size: float
    procedure_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class ScenarioPlacement:
    origin: Point
    size: Size
    title_text: str
    body_text: str
    cycle_text: str | None
    title_font_size: float
    body_font_size: float
    cycle_font_size: float
    padding: float
    section_gap: float
    procedures_origin: Point
    procedures_size: Size
    procedures_text: str
    procedures_font_size: float
    procedures_padding: float
    procedures_blocks: tuple[ScenarioProceduresBlock, ...] | None = None
    procedures_block_padding: float | None = None
    merge_origin: Point | None = None
    merge_size: Size | None = None
    merge_text: str | None = None
    merge_font_size: float | None = None
    merge_padding: float | None = None
    merge_blocks: tuple[ScenarioProceduresBlock, ...] | None = None
    merge_block_padding: float | None = None
    merge_node_numbers: dict[str, list[int]] | None = None


@dataclass(frozen=True)
class ScenarioProceduresBlock:
    kind: str
    text: str
    height: float
    color: str | None = None
    font_size: float | None = None
    underline: bool = False
    team_id: str | int | None = None
    finedog_unit_id: str | None = None


@dataclass(frozen=True)
class LayoutPlan:
    frames: list[FramePlacement]
    blocks: list[BlockPlacement]
    markers: list[MarkerPlacement]
    separators: list[SeparatorPlacement] = field(default_factory=list)
    scenarios: list[ScenarioPlacement] = field(default_factory=list)
    service_zones: list[ServiceZonePlacement] = field(default_factory=list)


@dataclass(frozen=True)
class ExcalidrawDocument:
    elements: list[dict[str, Any]]
    app_state: dict[str, Any]
    files: dict[str, Any]

    def to_dict(self) -> dict[str, object]:
        return {
            "type": "excalidraw",
            "version": 2,
            "source": "cjm-ui-convertor",
            "elements": self.elements,
            "appState": self.app_state,
            "files": self.files,
        }


@dataclass(frozen=True)
class UnidrawDocument:
    elements: list[dict[str, Any]]
    app_state: dict[str, Any]
    files: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        return {
            "type": "unidraw",
            "version": 1,
            "source": "cjm-ui-convertor",
            "elements": self.elements,
            "appState": self.app_state,
            "files": self.files,
        }
