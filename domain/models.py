from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Set

from pydantic import BaseModel, Field, field_validator

METADATA_SCHEMA_VERSION = "1.0"
CUSTOM_DATA_KEY = "cjm"


class Procedure(BaseModel):
    procedure_id: str = Field(..., min_length=1)
    start_block_ids: List[str] = Field(default_factory=list)
    end_block_ids: List[str] = Field(default_factory=list)
    branches: Dict[str, List[str]] = Field(default_factory=dict)

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


class MarkupDocument(BaseModel):
    finedog_unit_id: int
    markup_type: str
    procedures: List[Procedure] = Field(default_factory=list)

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
