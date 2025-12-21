from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Tuple

from domain.models import CUSTOM_DATA_KEY, MarkupDocument, METADATA_SCHEMA_VERSION, Procedure


@dataclass(frozen=True)
class BlockCandidate:
    procedure_id: str
    block_id: str
    element_id: Optional[str]


@dataclass(frozen=True)
class MarkerCandidate:
    procedure_id: str
    block_id: str
    role: str
    element_id: Optional[str]


class ExcalidrawToMarkupConverter:
    def convert(self, document: dict) -> MarkupDocument:
        elements: Iterable[dict] = document.get("elements", [])
        frames = self._collect_frames(elements)
        blocks = self._collect_blocks(elements, frames)
        markers = self._collect_markers(elements, frames)

        finedog_unit_id, markup_type = self._infer_globals(elements)
        start_map: Dict[str, set[str]] = defaultdict(set)
        end_map: Dict[str, set[str]] = defaultdict(set)
        branch_map: Dict[str, Dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))

        for arrow in filter(self._is_arrow, elements):
            meta = self._metadata(arrow)
            edge_type = meta.get("edge_type") or arrow.get("text", "").lower()
            procedure_id = self._infer_procedure_id(meta, blocks, markers, arrow)
            source_block = meta.get("source_block_id")
            target_block = meta.get("target_block_id")

            start_binding = arrow.get("startBinding", {}) or {}
            end_binding = arrow.get("endBinding", {}) or {}

            source_block = source_block or self._block_from_binding(start_binding, blocks)
            target_block = target_block or self._block_from_binding(end_binding, blocks)

            if edge_type == "start" or (self._is_start_arrow(arrow, markers, start_binding, end_binding)):
                if target_block:
                    start_map[procedure_id].add(target_block)
                continue

            if edge_type == "end":
                if source_block:
                    end_map[procedure_id].add(source_block)
                continue

            if edge_type == "branch":
                if source_block and target_block:
                    branch_map[procedure_id][source_block].add(target_block)
                continue

            if arrow.get("text", "").lower() == "branch" and source_block and target_block:
                branch_map[procedure_id][source_block].add(target_block)

        procedures = self._build_procedures(blocks, start_map, end_map, branch_map, frames)
        return MarkupDocument(
            finedog_unit_id=finedog_unit_id,
            markup_type=markup_type,
            procedures=procedures,
        )

    def _collect_frames(self, elements: Iterable[dict]) -> Dict[str, str]:
        frames: Dict[str, str] = {}
        for element in elements:
            if element.get("type") != "frame":
                continue
            meta = self._metadata(element)
            procedure_id = meta.get("procedure_id") or element.get("name")
            if not procedure_id:
                continue
            frame_id = element.get("id")
            if frame_id:
                frames[frame_id] = procedure_id
        return frames

    def _collect_blocks(
        self,
        elements: Iterable[dict],
        frames: Dict[str, str],
    ) -> Dict[str, BlockCandidate]:
        blocks: Dict[str, BlockCandidate] = {}
        for element in elements:
            if element.get("type") not in {"rectangle", "text"}:
                continue
            meta = self._metadata(element)
            procedure_id = meta.get("procedure_id") or frames.get(element.get("frameId", ""))
            block_id = meta.get("block_id") or element.get("text")
            if not procedure_id or not block_id:
                continue
            element_id = element.get("id")
            blocks[element_id] = BlockCandidate(
                procedure_id=procedure_id,
                block_id=block_id,
                element_id=element_id,
            )
        return blocks

    def _collect_markers(
        self,
        elements: Iterable[dict],
        frames: Dict[str, str],
    ) -> Dict[str, MarkerCandidate]:
        markers: Dict[str, MarkerCandidate] = {}
        for element in elements:
            if element.get("type") not in {"ellipse", "text"}:
                continue
            meta = self._metadata(element)
            role = meta.get("role")
            if role not in {"start_marker", "end_marker"}:
                continue
            procedure_id = meta.get("procedure_id") or frames.get(element.get("frameId", ""))
            block_id = meta.get("block_id")
            if not procedure_id or not block_id:
                continue
            element_id = element.get("id")
            markers[element_id] = MarkerCandidate(
                procedure_id=procedure_id,
                block_id=block_id,
                role=role,
                element_id=element_id,
            )
        return markers

    def _build_procedures(
        self,
        blocks: Dict[str, BlockCandidate],
        start_map: Dict[str, set[str]],
        end_map: Dict[str, set[str]],
        branch_map: Dict[str, Dict[str, set[str]]],
        frames: Dict[str, str],
    ) -> List[Procedure]:
        procedure_ids = set(start_map.keys()) | set(end_map.keys()) | set(branch_map.keys())
        procedure_ids.update(frame_proc for frame_proc in frames.values())
        for block in blocks.values():
            procedure_ids.add(block.procedure_id)

        procedures: List[Procedure] = []
        for procedure_id in sorted(procedure_ids):
            blocks_in_proc = {b.block_id for b in blocks.values() if b.procedure_id == procedure_id}
            branches = {
                source: sorted(targets)
                for source, targets in sorted(branch_map.get(procedure_id, {}).items())
            }
            start_blocks = sorted(start_map.get(procedure_id, set()))
            end_blocks = sorted(end_map.get(procedure_id, set()))

            # Add standalone blocks to ensure they are preserved.
            for block_id in blocks_in_proc:
                branches.setdefault(block_id, branches.get(block_id, []))

            procedures.append(
                Procedure(
                    procedure_id=procedure_id,
                    start_block_ids=start_blocks,
                    end_block_ids=end_blocks,
                    branches=branches,
                )
            )
        return procedures

    def _metadata(self, element: dict) -> dict:
        meta = element.get("customData", {}).get(CUSTOM_DATA_KEY, {})
        schema_version = meta.get("schema_version")
        if schema_version and str(schema_version) != METADATA_SCHEMA_VERSION:
            return meta
        return meta

    def _is_arrow(self, element: dict) -> bool:
        return element.get("type") == "arrow"

    def _block_from_binding(self, binding: dict, blocks: Dict[str, BlockCandidate]) -> Optional[str]:
        element_id = binding.get("elementId")
        if not element_id:
            return None
        block = blocks.get(element_id)
        return block.block_id if block else None

    def _infer_procedure_id(
        self,
        metadata: dict,
        blocks: Dict[str, BlockCandidate],
        markers: Dict[str, MarkerCandidate],
        arrow: dict,
    ) -> str:
        procedure_id = metadata.get("procedure_id")
        if procedure_id:
            return procedure_id

        for binding_name in ("startBinding", "endBinding"):
            binding = arrow.get(binding_name) or {}
            element_id = binding.get("elementId")
            if not element_id:
                continue
            block = blocks.get(element_id)
            if block:
                return block.procedure_id
            marker = markers.get(element_id)
            if marker:
                return marker.procedure_id

        if blocks:
            return next(iter(blocks.values())).procedure_id
        if markers:
            return next(iter(markers.values())).procedure_id
        return "unknown_procedure"

    def _is_start_arrow(
        self,
        arrow: dict,
        markers: Dict[str, MarkerCandidate],
        start_binding: dict,
        end_binding: dict,
    ) -> bool:
        start_marker = markers.get(start_binding.get("elementId"))
        block_target = end_binding.get("elementId")
        return bool(start_marker and block_target)

    def _infer_globals(self, elements: Iterable[dict]) -> Tuple[int, str]:
        for element in elements:
            meta = element.get("customData", {}).get(CUSTOM_DATA_KEY, {})
            finedog = meta.get("finedog_unit_id")
            markup_type = meta.get("markup_type")
            if finedog is not None and markup_type:
                return int(finedog), str(markup_type)
        return 0, "service"
