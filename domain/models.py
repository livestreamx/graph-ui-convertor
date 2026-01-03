from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Set, Tuple

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator, model_validator

METADATA_SCHEMA_VERSION = "1.0"
CUSTOM_DATA_KEY = "cjm"
END_BLOCK_SEPARATOR = "::"
END_TYPE_DEFAULT = "end"
END_TYPE_VALUES = {"end", "exit", "all", "intermediate"}
END_TYPE_COLORS = {
    "end": "#ffe4b5",
    "exit": "#ffb3b3",
    "all": "#fff3b0",
    "intermediate": "#cfe3ff",
}
INTERMEDIATE_BLOCK_COLOR = "#ffb347"


def normalize_end_type(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    candidate = str(value).strip().lower()
    return candidate if candidate in END_TYPE_VALUES else None


def split_end_block_id(raw: str) -> Tuple[str, str]:
    base = str(raw)
    if END_BLOCK_SEPARATOR in base:
        head, suffix = base.rsplit(END_BLOCK_SEPARATOR, 1)
        normalized = normalize_end_type(suffix)
        if normalized:
            return head, normalized
    return base, END_TYPE_DEFAULT


def merge_end_types(existing: Optional[str], new: str) -> str:
    if not existing:
        return new
    if existing == new:
        return existing
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
    procedure_name: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices("procedure_name", "proc_name"),
    )
    start_block_ids: List[str] = Field(default_factory=list)
    end_block_ids: List[str] = Field(default_factory=list)
    end_block_types: Dict[str, str] = Field(default_factory=dict)
    branches: Dict[str, List[str]] = Field(default_factory=dict)
    block_id_to_block_name: Dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def normalize_end_blocks(cls, data: object) -> object:
        if not isinstance(data, dict):
            return data
        end_block_ids = list(data.get("end_block_ids") or [])
        raw_end_block_types = dict(data.get("end_block_types") or {})
        end_block_types: Dict[str, str] = {}
        for block_id, end_type in raw_end_block_types.items():
            normalized = normalize_end_type(end_type)
            if normalized:
                end_block_types[str(block_id)] = normalized
        normalized_end_ids: List[str] = []
        seen_end_ids: Set[str] = set()

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
        cleaned_branches: Dict[str, List[str]] = {}
        for source, targets in branches.items():
            if not isinstance(targets, list):
                continue
            cleaned_targets: List[str] = []
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
    def ensure_unique_targets(cls, branches: Dict[str, List[str]]) -> Dict[str, List[str]]:
        return {key: sorted(set(value)) for key, value in branches.items()}

    def block_ids(self) -> Set[str]:
        referenced: Set[str] = set(self.start_block_ids) | set(self.end_block_ids) | set(
            self.branches.keys()
        )
        for targets in self.branches.values():
            referenced.update(targets)
        return referenced

    def to_markup_dict(self) -> dict:
        payload = {
            "proc_id": self.procedure_id,
            "start_block_ids": _sorted_unique(list(self.start_block_ids)),
            "end_block_ids": _merge_end_block_ids(
                list(self.end_block_ids), self.end_block_types
            ),
            "branches": _sorted_branches(self.branches),
        }
        if self.procedure_name:
            payload["proc_name"] = self.procedure_name
        if self.block_id_to_block_name:
            payload["block_id_to_block_name"] = dict(self.block_id_to_block_name)
        return payload


class MarkupDocument(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    finedog_unit_id: int
    markup_type: str
    service_name: Optional[str] = None
    procedures: List[Procedure] = Field(default_factory=list)
    procedure_graph: Dict[str, List[str]] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def extract_service_name(cls, data: object) -> object:
        if not isinstance(data, dict):
            return data
        service_name = data.get("service_name")
        if service_name:
            return data
        meta = data.get("finedog_unit_meta")
        if isinstance(meta, dict) and meta.get("service_name"):
            updated = dict(data)
            updated["service_name"] = meta.get("service_name")
            return updated
        return data

    @field_validator("procedures", mode="after")
    @classmethod
    def ensure_unique_procedure_ids(cls, procedures: List[Procedure]) -> List[Procedure]:
        seen: Set[str] = set()
        for procedure in procedures:
            if procedure.procedure_id in seen:
                msg = f"Duplicate procedure_id found: {procedure.procedure_id}"
                raise ValueError(msg)
            seen.add(procedure.procedure_id)
        return procedures

    def to_markup_dict(self) -> dict:
        payload = {
            "finedog_unit_id": self.finedog_unit_id,
            "markup_type": self.markup_type,
            "procedures": [proc.to_markup_dict() for proc in self.procedures],
        }
        if self.service_name:
            payload["finedog_unit_meta"] = {"service_name": self.service_name}
        if self.procedure_graph:
            payload["procedure_graph"] = dict(self.procedure_graph)
        return payload


def _format_end_block_id(block_id: str, end_type: Optional[str]) -> str:
    normalized = normalize_end_type(end_type) or END_TYPE_DEFAULT
    if normalized == END_TYPE_DEFAULT:
        return block_id
    return f"{block_id}{END_BLOCK_SEPARATOR}{normalized}"


def _sorted_unique(values: List[str]) -> List[str]:
    seen: Set[str] = set()
    result: List[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def _sorted_branches(branches: Dict[str, List[str]]) -> Dict[str, List[str]]:
    return {key: sorted(set(values)) for key, values in branches.items()}


def _merge_end_block_ids(
    block_ids: List[str], end_types: Dict[str, str]
) -> List[str]:
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
    end_type: Optional[str] = None


@dataclass(frozen=True)
class LayoutPlan:
    frames: List[FramePlacement]
    blocks: List[BlockPlacement]
    markers: List[MarkerPlacement]


@dataclass(frozen=True)
class ExcalidrawDocument:
    elements: List[dict]
    app_state: dict
    files: dict

    def to_dict(self) -> dict:
        return {
            "type": "excalidraw",
            "version": 2,
            "source": "cjm-ui-convertor",
            "elements": self.elements,
            "appState": self.app_state,
            "files": self.files,
        }
