from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Tuple

from domain.models import (
    CUSTOM_DATA_KEY,
    END_TYPE_COLORS,
    END_TYPE_DEFAULT,
    MarkupDocument,
    METADATA_SCHEMA_VERSION,
    Procedure,
    merge_end_types,
    normalize_end_type,
)


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
    end_type: Optional[str]


class ExcalidrawToMarkupConverter:
    def convert(self, document: dict) -> MarkupDocument:
        elements: Iterable[dict] = document.get("elements", [])
        frames, proc_names = self._collect_frames(elements)
        blocks = self._collect_blocks(elements, frames)
        markers = self._collect_markers(elements, frames)
        block_names = self._collect_block_names(elements, frames)

        finedog_unit_id, markup_type, service_name = self._infer_globals(elements)
        start_map: Dict[str, set[str]] = defaultdict(set)
        end_map: Dict[str, Dict[str, str]] = defaultdict(dict)
        branch_map: Dict[str, Dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))

        marker_end_types = self._merge_marker_end_types(markers)
        for (procedure_id, block_id), end_type in marker_end_types.items():
            end_map[procedure_id][block_id] = merge_end_types(
                end_map[procedure_id].get(block_id), end_type
            )

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

            if edge_type == "end" or self._is_end_arrow(arrow, markers, start_binding, end_binding):
                if source_block:
                    end_type = self._infer_end_type_from_arrow(
                        arrow, meta, marker_end_types, procedure_id, source_block, markers
                    )
                    end_map[procedure_id][source_block] = merge_end_types(
                        end_map[procedure_id].get(source_block), end_type
                    )
                continue

            if edge_type in {"branch", "branch_cycle"}:
                if source_block and target_block:
                    branch_map[procedure_id][source_block].add(target_block)
                continue

            if arrow.get("text", "").lower() == "branch" and source_block and target_block:
                branch_map[procedure_id][source_block].add(target_block)

        procedures = self._build_procedures(
            blocks, start_map, end_map, branch_map, frames, block_names, proc_names
        )
        procedure_graph = self._collect_procedure_graph(elements, procedures)
        return MarkupDocument(
            finedog_unit_id=finedog_unit_id,
            markup_type=markup_type,
            service_name=service_name,
            procedures=procedures,
            procedure_graph=procedure_graph,
        )

    def _collect_frames(self, elements: Iterable[dict]) -> Tuple[Dict[str, str], Dict[str, str]]:
        frames: Dict[str, str] = {}
        proc_names: Dict[str, str] = {}
        for element in elements:
            if element.get("type") != "frame":
                continue
            meta = self._metadata(element)
            procedure_id = meta.get("procedure_id") or element.get("name")
            if not procedure_id:
                continue
            procedure_name = meta.get("procedure_name") or element.get("name")
            frame_id = element.get("id")
            if frame_id:
                frames[frame_id] = procedure_id
            if procedure_name:
                proc_names[procedure_id] = str(procedure_name)
        return frames, proc_names

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
            end_type = self._infer_end_type_from_element(element, meta) if role == "end_marker" else None
            markers[element_id] = MarkerCandidate(
                procedure_id=procedure_id,
                block_id=block_id,
                role=role,
                element_id=element_id,
                end_type=end_type,
            )
        return markers

    def _collect_block_names(
        self,
        elements: Iterable[dict],
        frames: Dict[str, str],
    ) -> Dict[str, Dict[str, str]]:
        names: Dict[str, Dict[str, str]] = defaultdict(dict)
        for element in elements:
            if element.get("type") != "text":
                continue
            meta = self._metadata(element)
            if meta.get("role") != "block_label":
                continue
            procedure_id = meta.get("procedure_id") or frames.get(element.get("frameId", ""))
            block_id = meta.get("block_id")
            if not procedure_id or not block_id:
                continue
            block_name = meta.get("block_name")
            if not block_name:
                text = element.get("text")
                if isinstance(text, str):
                    block_name = text.replace("\n", " ").strip()
            if block_name and block_name != block_id:
                names[procedure_id][block_id] = block_name
        return names

    def _build_procedures(
        self,
        blocks: Dict[str, BlockCandidate],
        start_map: Dict[str, set[str]],
        end_map: Dict[str, Dict[str, str]],
        branch_map: Dict[str, Dict[str, set[str]]],
        frames: Dict[str, str],
        block_names: Dict[str, Dict[str, str]],
        proc_names: Dict[str, str],
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
            end_types = dict(end_map.get(procedure_id, {}))
            end_blocks = sorted(end_types.keys())

            procedures.append(
                Procedure(
                    procedure_id=procedure_id,
                    procedure_name=proc_names.get(procedure_id),
                    start_block_ids=start_blocks,
                    end_block_ids=end_blocks,
                    end_block_types=end_types,
                    branches=branches,
                    block_id_to_block_name=block_names.get(procedure_id, {}),
                )
            )
        return procedures

    def _collect_procedure_graph(
        self, elements: Iterable[dict], procedures: List[Procedure]
    ) -> Dict[str, List[str]]:
        graph: Dict[str, List[str]] = {
            procedure.procedure_id: [] for procedure in procedures
        }
        for element in elements:
            if not self._is_arrow(element):
                continue
            meta = self._metadata(element)
            if meta.get("edge_type") not in {"procedure_flow", "procedure_cycle"}:
                continue
            source = meta.get("procedure_id")
            target = meta.get("target_procedure_id")
            if not source or not target:
                continue
            if source not in graph or target not in graph:
                continue
            if target not in graph[source]:
                graph[source].append(target)
        return graph

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

    def _is_end_arrow(
        self,
        arrow: dict,
        markers: Dict[str, MarkerCandidate],
        start_binding: dict,
        end_binding: dict,
    ) -> bool:
        end_marker = markers.get(end_binding.get("elementId"))
        if not end_marker or end_marker.role != "end_marker":
            return False
        start_element = start_binding.get("elementId")
        return bool(start_element and start_element not in markers)

    def _infer_globals(self, elements: Iterable[dict]) -> Tuple[int, str, Optional[str]]:
        for element in elements:
            meta = element.get("customData", {}).get(CUSTOM_DATA_KEY, {})
            finedog = meta.get("finedog_unit_id")
            markup_type = meta.get("markup_type")
            service_name = meta.get("service_name")
            if finedog is not None and markup_type:
                return int(finedog), str(markup_type), service_name
        return 0, "service", None

    def _merge_marker_end_types(
        self, markers: Dict[str, MarkerCandidate]
    ) -> Dict[Tuple[str, str], str]:
        end_types: Dict[Tuple[str, str], str] = {}
        for marker in markers.values():
            if marker.role != "end_marker":
                continue
            end_type = marker.end_type or END_TYPE_DEFAULT
            key = (marker.procedure_id, marker.block_id)
            end_types[key] = merge_end_types(end_types.get(key), end_type)
        return end_types

    def _infer_end_type_from_arrow(
        self,
        arrow: dict,
        meta: dict,
        marker_end_types: Dict[Tuple[str, str], str],
        procedure_id: str,
        source_block: str,
        markers: Dict[str, MarkerCandidate],
    ) -> str:
        tagged = self._end_type_from_tags(arrow, meta)
        if tagged:
            return tagged
        end_type = normalize_end_type(meta.get("end_block_type"))
        if end_type:
            return end_type
        end_type = normalize_end_type(meta.get("end_type"))
        if end_type:
            return end_type
        end_type = marker_end_types.get((procedure_id, source_block))
        if end_type:
            return end_type
        end_binding = arrow.get("endBinding") or {}
        marker = markers.get(end_binding.get("elementId"))
        if marker and marker.end_type:
            return marker.end_type
        return END_TYPE_DEFAULT

    def _infer_end_type_from_element(self, element: dict, meta: dict) -> Optional[str]:
        tagged = self._end_type_from_tags(element, meta)
        if tagged:
            return tagged
        end_type = normalize_end_type(meta.get("end_block_type"))
        if end_type:
            return end_type
        end_type = normalize_end_type(meta.get("end_type"))
        if end_type:
            return end_type
        return self._end_type_from_color(element.get("backgroundColor"))

    def _end_type_from_tags(self, element: dict, meta: dict) -> Optional[str]:
        tags: List[str] = []
        for source in (
            meta.get("tags"),
            element.get("tags"),
            element.get("customData", {}).get("tags"),
            element.get("customData", {}).get("excalidraw", {}).get("tags"),
        ):
            tags.extend(self._split_tags(source))
        for field in ("text", "name"):
            value = element.get(field)
            if isinstance(value, str):
                tags.extend(self._extract_inline_tags(value))
        end_type: Optional[str] = None
        for tag in tags:
            normalized = normalize_end_type(tag)
            if not normalized:
                continue
            end_type = merge_end_types(end_type, normalized)
        return end_type

    def _end_type_from_color(self, color: Optional[str]) -> Optional[str]:
        if not color:
            return None
        candidate = str(color).lower()
        for end_type, end_color in END_TYPE_COLORS.items():
            if candidate == end_color.lower():
                return end_type
        return None

    def _split_tags(self, value: object) -> List[str]:
        if isinstance(value, (list, tuple, set)):
            return [self._normalize_tag(str(item)) for item in value]
        if isinstance(value, str):
            return [
                self._normalize_tag(chunk)
                for chunk in re.split(r"[,\\s]+", value)
                if chunk
            ]
        return []

    def _extract_inline_tags(self, value: str) -> List[str]:
        return [
            match.lower()
            for match in re.findall(
                r"(?:#|::)(end|exit|all|intermediate)\\b",
                value,
                flags=re.IGNORECASE,
            )
        ]

    def _normalize_tag(self, value: str) -> str:
        candidate = value.strip()
        if candidate.startswith("#"):
            candidate = candidate[1:]
        if candidate.startswith("::"):
            candidate = candidate[2:]
        return candidate
