from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from domain.models import (
    CUSTOM_DATA_KEY,
    END_TYPE_COLORS,
    END_TYPE_DEFAULT,
    END_TYPE_TURN_OUT,
    METADATA_SCHEMA_VERSION,
    MarkupDocument,
    Procedure,
    merge_end_types,
    normalize_end_type,
)

_TAG_SPLIT_RE = re.compile(r"[,\\s]+")
_INLINE_TAG_RE = re.compile(
    r"(?:#|::)(end|exit|all|intermediate|postpone|turn_out)\\b", re.IGNORECASE
)

Metadata = dict[str, Any]
Element = Mapping[str, Any]


@dataclass(frozen=True)
class BlockCandidate:
    procedure_id: str
    block_id: str
    element_id: str | None


@dataclass(frozen=True)
class MarkerCandidate:
    procedure_id: str
    block_id: str
    role: str
    element_id: str | None
    end_type: str | None


class ExcalidrawToMarkupConverter:
    def convert(self, document: Mapping[str, Any]) -> MarkupDocument:
        elements: Iterable[Element] = document.get("elements", [])
        frames, proc_names = self._collect_frames(elements)
        blocks = self._collect_blocks(elements, frames)
        block_initials = self._collect_block_initials(elements)
        markers = self._collect_markers(elements, frames)
        block_names = self._collect_block_names(elements, frames)

        globals_meta = self._infer_globals(elements)
        start_map: dict[str, set[str]] = defaultdict(set)
        end_map: dict[str, dict[str, str]] = defaultdict(dict)
        branch_map: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
        turn_out_sources: dict[str, set[str]] = defaultdict(set)

        marker_end_types = self._merge_marker_end_types(markers)
        for (procedure_id, block_id), end_type in marker_end_types.items():
            end_map[procedure_id][block_id] = merge_end_types(
                end_map[procedure_id].get(block_id), end_type
            )
        for marker in markers.values():
            if marker.role != "end_marker":
                continue
            if marker.end_type != END_TYPE_TURN_OUT:
                continue
            turn_out_sources[marker.procedure_id].add(marker.block_id)

        for arrow in filter(self._is_arrow, elements):
            meta = self._metadata(arrow)
            raw_edge_type = meta.get("edge_type")
            edge_type = raw_edge_type if isinstance(raw_edge_type, str) else ""
            if not edge_type:
                text = arrow.get("text")
                edge_type = text.lower() if isinstance(text, str) else ""
            procedure_id = self._infer_procedure_id(meta, blocks, markers, arrow)
            raw_source = meta.get("source_block_id")
            raw_target = meta.get("target_block_id")
            source_block = raw_source if isinstance(raw_source, str) else None
            target_block = raw_target if isinstance(raw_target, str) else None

            raw_start_binding = arrow.get("startBinding")
            raw_end_binding = arrow.get("endBinding")
            start_binding = raw_start_binding if isinstance(raw_start_binding, dict) else {}
            end_binding = raw_end_binding if isinstance(raw_end_binding, dict) else {}

            source_block = source_block or self._block_from_binding(start_binding, blocks)
            target_block = target_block or self._block_from_binding(end_binding, blocks)

            if edge_type == "start" or (
                self._is_start_arrow(arrow, markers, start_binding, end_binding)
            ):
                if target_block:
                    start_map[procedure_id].add(target_block)
                continue

            if edge_type == "end" or self._is_end_arrow(arrow, markers, start_binding, end_binding):
                if source_block:
                    end_type = self._infer_end_type_from_arrow(
                        arrow, meta, marker_end_types, procedure_id, source_block, markers
                    )
                    if end_type == END_TYPE_TURN_OUT:
                        continue
                    end_map[procedure_id][source_block] = merge_end_types(
                        end_map[procedure_id].get(source_block), end_type
                    )
                continue

            if edge_type in {"branch", "branch_cycle"}:
                if source_block and target_block:
                    branch_map[procedure_id][source_block].add(target_block)
                continue

            if edge_type in {"block_graph", "block_graph_cycle"}:
                continue

            text = arrow.get("text")
            if isinstance(text, str) and text.lower() == "branch" and source_block and target_block:
                branch_map[procedure_id][source_block].add(target_block)

        block_graph = self._collect_block_graph(elements, blocks)
        if block_graph and turn_out_sources:
            inferred_branches = self._branches_from_block_graph(block_graph, blocks)
            for proc_id, sources in turn_out_sources.items():
                for source in sources:
                    if branch_map[proc_id].get(source):
                        continue
                    targets = inferred_branches.get(proc_id, {}).get(source, set())
                    if targets:
                        branch_map[proc_id][source].update(targets)
        procedures = self._build_procedures(
            blocks, start_map, end_map, branch_map, frames, block_names, proc_names
        )
        procedure_graph = self._collect_procedure_graph(elements, procedures)
        if block_graph and not any(procedure_graph.values()):
            procedure_graph = self._infer_procedure_graph_from_block_graph(block_graph, procedures)
        return MarkupDocument(
            markup_type=globals_meta["markup_type"],
            finedog_unit_id=globals_meta.get("finedog_unit_id"),
            service_name=globals_meta.get("service_name"),
            criticality_level=globals_meta.get("criticality_level"),
            team_id=globals_meta.get("team_id"),
            team_name=globals_meta.get("team_name"),
            procedures=procedures,
            procedure_graph=procedure_graph,
            block_graph=block_graph,
            block_graph_initials=block_initials,
        )

    def _collect_frames(self, elements: Iterable[Element]) -> tuple[dict[str, str], dict[str, str]]:
        frames: dict[str, str] = {}
        proc_names: dict[str, str] = {}
        for element in elements:
            if element.get("type") != "frame":
                continue
            meta = self._metadata(element)
            meta_proc = meta.get("procedure_id")
            name_proc = element.get("name")
            procedure_id = meta_proc if isinstance(meta_proc, str) else None
            if not procedure_id and isinstance(name_proc, str):
                procedure_id = name_proc
            if not procedure_id:
                continue
            meta_name = meta.get("procedure_name")
            procedure_name = meta_name if isinstance(meta_name, str) else None
            if not procedure_name and isinstance(name_proc, str):
                procedure_name = name_proc
            frame_id = element.get("id")
            if frame_id:
                frames[frame_id] = procedure_id
            if procedure_name:
                proc_names[procedure_id] = str(procedure_name)
        return frames, proc_names

    def _collect_blocks(
        self,
        elements: Iterable[Element],
        frames: dict[str, str],
    ) -> dict[str, BlockCandidate]:
        blocks: dict[str, BlockCandidate] = {}
        for element in elements:
            if element.get("type") not in {"rectangle", "text"}:
                continue
            meta = self._metadata(element)
            frame_id = element.get("frameId")
            frame_key = frame_id if isinstance(frame_id, str) else ""
            meta_proc = meta.get("procedure_id")
            procedure_id = meta_proc if isinstance(meta_proc, str) else frames.get(frame_key)
            meta_block = meta.get("block_id")
            block_id = meta_block if isinstance(meta_block, str) else None
            if not block_id:
                text = element.get("text")
                block_id = text if isinstance(text, str) else None
            if not procedure_id or not block_id:
                continue
            element_id = element.get("id")
            if not isinstance(element_id, str):
                continue
            blocks[element_id] = BlockCandidate(
                procedure_id=procedure_id,
                block_id=block_id,
                element_id=element_id,
            )
        return blocks

    def _collect_block_initials(self, elements: Iterable[Element]) -> set[str]:
        initials: set[str] = set()
        for element in elements:
            if element.get("type") not in {"rectangle", "text"}:
                continue
            meta = self._metadata(element)
            block_id = meta.get("block_id")
            if not isinstance(block_id, str):
                continue
            if meta.get("block_graph_initial") is True:
                initials.add(block_id)
        return initials

    def _collect_markers(
        self,
        elements: Iterable[Element],
        frames: dict[str, str],
    ) -> dict[str, MarkerCandidate]:
        markers: dict[str, MarkerCandidate] = {}
        for element in elements:
            if element.get("type") not in {"ellipse", "text"}:
                continue
            meta = self._metadata(element)
            role = meta.get("role")
            if role not in {"start_marker", "end_marker"}:
                continue
            frame_id = element.get("frameId")
            frame_key = frame_id if isinstance(frame_id, str) else ""
            meta_proc = meta.get("procedure_id")
            procedure_id = meta_proc if isinstance(meta_proc, str) else frames.get(frame_key)
            meta_block = meta.get("block_id")
            block_id = meta_block if isinstance(meta_block, str) else None
            if not procedure_id or not block_id:
                continue
            element_id = element.get("id")
            if not isinstance(element_id, str):
                continue
            end_type = (
                self._infer_end_type_from_element(element, meta) if role == "end_marker" else None
            )
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
        elements: Iterable[Element],
        frames: dict[str, str],
    ) -> dict[str, dict[str, str]]:
        names: dict[str, dict[str, str]] = defaultdict(dict)
        for element in elements:
            if element.get("type") != "text":
                continue
            meta = self._metadata(element)
            if meta.get("role") != "block_label":
                continue
            frame_id = element.get("frameId")
            frame_key = frame_id if isinstance(frame_id, str) else ""
            meta_proc = meta.get("procedure_id")
            procedure_id = meta_proc if isinstance(meta_proc, str) else frames.get(frame_key)
            meta_block = meta.get("block_id")
            block_id = meta_block if isinstance(meta_block, str) else None
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
        blocks: dict[str, BlockCandidate],
        start_map: dict[str, set[str]],
        end_map: dict[str, dict[str, str]],
        branch_map: dict[str, dict[str, set[str]]],
        frames: dict[str, str],
        block_names: dict[str, dict[str, str]],
        proc_names: dict[str, str],
    ) -> list[Procedure]:
        procedure_ids = set(start_map.keys()) | set(end_map.keys()) | set(branch_map.keys())
        procedure_ids.update(frame_proc for frame_proc in frames.values())
        for block in blocks.values():
            procedure_ids.add(block.procedure_id)

        procedures: list[Procedure] = []
        for procedure_id in sorted(procedure_ids):
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
        self, elements: Iterable[Element], procedures: list[Procedure]
    ) -> dict[str, list[str]]:
        graph: dict[str, list[str]] = {procedure.procedure_id: [] for procedure in procedures}
        for element in elements:
            if not self._is_arrow(element):
                continue
            meta = self._metadata(element)
            if meta.get("edge_type") not in {"procedure_flow", "procedure_cycle"}:
                continue
            source = meta.get("procedure_id")
            target = meta.get("target_procedure_id")
            if not isinstance(source, str) or not isinstance(target, str):
                continue
            if source not in graph or target not in graph:
                continue
            if target not in graph[source]:
                graph[source].append(target)
        return graph

    def _collect_block_graph(
        self,
        elements: Iterable[Element],
        blocks: dict[str, BlockCandidate],
    ) -> dict[str, list[str]]:
        graph: dict[str, list[str]] = {}
        for element in elements:
            if not self._is_arrow(element):
                continue
            meta = self._metadata(element)
            if meta.get("edge_type") not in {"block_graph", "block_graph_cycle"}:
                continue
            source = meta.get("source_block_id")
            target = meta.get("target_block_id")
            if not isinstance(source, str) or not isinstance(target, str):
                raw_start_binding = element.get("startBinding")
                raw_end_binding = element.get("endBinding")
                start_binding = raw_start_binding if isinstance(raw_start_binding, dict) else {}
                end_binding = raw_end_binding if isinstance(raw_end_binding, dict) else {}
                source = (
                    source
                    if isinstance(source, str)
                    else self._block_from_binding(start_binding, blocks)
                )
                target = (
                    target
                    if isinstance(target, str)
                    else self._block_from_binding(end_binding, blocks)
                )
            if not source or not target:
                continue
            graph.setdefault(source, [])
            if target not in graph[source]:
                graph[source].append(target)
            graph.setdefault(target, [])
        return graph

    def _branches_from_block_graph(
        self,
        block_graph: Mapping[str, list[str]],
        blocks: Mapping[str, BlockCandidate],
    ) -> dict[str, dict[str, set[str]]]:
        edges = [(source, target) for source, targets in block_graph.items() for target in targets]
        return self._branches_from_block_edges(edges, blocks, require_same_proc=False)

    def _branches_from_block_edges(
        self,
        edges: Iterable[tuple[str, str]],
        blocks: Mapping[str, BlockCandidate],
        require_same_proc: bool = True,
    ) -> dict[str, dict[str, set[str]]]:
        proc_for_block: dict[str, str] = {}
        duplicates: set[str] = set()
        for block in blocks.values():
            existing_proc = proc_for_block.get(block.block_id)
            if existing_proc and existing_proc != block.procedure_id:
                duplicates.add(block.block_id)
            elif not existing_proc:
                proc_for_block[block.block_id] = block.procedure_id

        branches: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
        for source, target in edges:
            if source in duplicates or target in duplicates:
                continue
            source_proc = proc_for_block.get(source)
            if not source_proc:
                continue
            if require_same_proc:
                target_proc = proc_for_block.get(target)
                if source_proc != target_proc:
                    continue
            branches[source_proc][source].add(target)
        return branches

    def _infer_procedure_graph_from_block_graph(
        self,
        block_graph: Mapping[str, list[str]],
        procedures: Iterable[Procedure],
    ) -> dict[str, list[str]]:
        proc_for_block: dict[str, str] = {}
        duplicates: set[str] = set()
        for procedure in procedures:
            for block_id in procedure.block_ids():
                if block_id in proc_for_block:
                    duplicates.add(block_id)
                else:
                    proc_for_block[block_id] = procedure.procedure_id

        adjacency: dict[str, list[str]] = {}
        for source_block, targets in block_graph.items():
            if source_block in duplicates:
                continue
            source_proc = proc_for_block.get(source_block)
            if not source_proc:
                continue
            for target_block in targets:
                if target_block in duplicates:
                    continue
                target_proc = proc_for_block.get(target_block)
                if not target_proc or target_proc == source_proc:
                    continue
                adjacency.setdefault(source_proc, [])
                if target_proc not in adjacency[source_proc]:
                    adjacency[source_proc].append(target_proc)

        for procedure in procedures:
            adjacency.setdefault(procedure.procedure_id, [])
        return adjacency

    def _metadata(self, element: Element) -> Metadata:
        custom = element.get("customData")
        if not isinstance(custom, dict):
            return {}
        meta_raw = custom.get(CUSTOM_DATA_KEY)
        if not isinstance(meta_raw, dict):
            return {}
        schema_version = meta_raw.get("schema_version")
        if schema_version and str(schema_version) != METADATA_SCHEMA_VERSION:
            return dict(meta_raw)
        return dict(meta_raw)

    def _is_arrow(self, element: Element) -> bool:
        return element.get("type") == "arrow"

    def _block_from_binding(
        self, binding: Mapping[str, Any], blocks: dict[str, BlockCandidate]
    ) -> str | None:
        element_id = binding.get("elementId")
        if not isinstance(element_id, str):
            return None
        block = blocks.get(element_id)
        return block.block_id if block else None

    def _infer_procedure_id(
        self,
        metadata: Mapping[str, Any],
        blocks: dict[str, BlockCandidate],
        markers: dict[str, MarkerCandidate],
        arrow: Element,
    ) -> str:
        procedure_id = metadata.get("procedure_id")
        if isinstance(procedure_id, str) and procedure_id:
            return procedure_id

        for binding_name in ("startBinding", "endBinding"):
            raw_binding = arrow.get(binding_name)
            binding = raw_binding if isinstance(raw_binding, dict) else {}
            element_id = binding.get("elementId")
            if not isinstance(element_id, str):
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
        arrow: Element,
        markers: dict[str, MarkerCandidate],
        start_binding: Mapping[str, Any],
        end_binding: Mapping[str, Any],
    ) -> bool:
        start_id = start_binding.get("elementId")
        end_id = end_binding.get("elementId")
        start_marker = markers.get(start_id) if isinstance(start_id, str) else None
        block_target = end_id if isinstance(end_id, str) else None
        return bool(start_marker and block_target)

    def _is_end_arrow(
        self,
        arrow: Element,
        markers: dict[str, MarkerCandidate],
        start_binding: Mapping[str, Any],
        end_binding: Mapping[str, Any],
    ) -> bool:
        end_id = end_binding.get("elementId")
        end_marker = markers.get(end_id) if isinstance(end_id, str) else None
        if not end_marker or end_marker.role != "end_marker":
            return False
        start_id = start_binding.get("elementId")
        return bool(isinstance(start_id, str) and start_id not in markers)

    def _infer_globals(self, elements: Iterable[Element]) -> dict[str, Any]:
        for element in elements:
            meta = self._metadata(element)
            markup_type = meta.get("markup_type")
            if markup_type:
                return {
                    "markup_type": str(markup_type),
                    "finedog_unit_id": self._normalize_meta_str(meta.get("finedog_unit_id")),
                    "service_name": self._normalize_meta_str(meta.get("service_name")),
                    "criticality_level": self._normalize_meta_str(meta.get("criticality_level")),
                    "team_id": self._normalize_team_id(meta.get("team_id")),
                    "team_name": self._normalize_meta_str(meta.get("team_name")),
                }
        return {
            "markup_type": "service",
            "finedog_unit_id": None,
            "service_name": None,
            "criticality_level": None,
            "team_id": None,
            "team_name": None,
        }

    def _normalize_meta_str(self, value: Any) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        return text if text else None

    def _normalize_team_id(self, value: Any) -> int | str | None:
        if value is None:
            return None
        if isinstance(value, str):
            text = value.strip()
            return text if text else None
        if isinstance(value, int):
            return value
        text = str(value).strip()
        return text if text else None

    def _merge_marker_end_types(
        self, markers: dict[str, MarkerCandidate]
    ) -> dict[tuple[str, str], str]:
        end_types: dict[tuple[str, str], str] = {}
        for marker in markers.values():
            if marker.role != "end_marker":
                continue
            end_type = marker.end_type or END_TYPE_DEFAULT
            if end_type == END_TYPE_TURN_OUT:
                continue
            key = (marker.procedure_id, marker.block_id)
            end_types[key] = merge_end_types(end_types.get(key), end_type)
        return end_types

    def _infer_end_type_from_arrow(
        self,
        arrow: Element,
        meta: Mapping[str, Any],
        marker_end_types: dict[tuple[str, str], str],
        procedure_id: str,
        source_block: str,
        markers: dict[str, MarkerCandidate],
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
        raw_binding = arrow.get("endBinding")
        end_binding = raw_binding if isinstance(raw_binding, dict) else {}
        element_id = end_binding.get("elementId")
        marker = markers.get(element_id) if isinstance(element_id, str) else None
        if marker and marker.end_type:
            return marker.end_type
        return END_TYPE_DEFAULT

    def _infer_end_type_from_element(self, element: Element, meta: Mapping[str, Any]) -> str | None:
        tagged = self._end_type_from_tags(element, meta)
        if tagged:
            return tagged
        end_type = normalize_end_type(meta.get("end_type"))
        if end_type:
            return end_type
        end_type = normalize_end_type(meta.get("end_block_type"))
        if end_type:
            return end_type
        return self._end_type_from_color(element.get("backgroundColor"))

    def _end_type_from_tags(self, element: Element, meta: Mapping[str, Any]) -> str | None:
        tags: list[str] = []
        custom_data = element.get("customData")
        custom_tags: object | None = None
        excalidraw_tags: object | None = None
        if isinstance(custom_data, dict):
            custom_tags = custom_data.get("tags")
            excalidraw_meta = custom_data.get("excalidraw")
            if isinstance(excalidraw_meta, dict):
                excalidraw_tags = excalidraw_meta.get("tags")
        for source in (
            meta.get("tags"),
            element.get("tags"),
            custom_tags,
            excalidraw_tags,
        ):
            tags.extend(self._split_tags(source))
        for field in ("text", "name"):
            value = element.get(field)
            if isinstance(value, str):
                tags.extend(self._extract_inline_tags(value))
        end_type: str | None = None
        for tag in tags:
            normalized = normalize_end_type(tag)
            if not normalized:
                continue
            end_type = merge_end_types(end_type, normalized)
        return end_type

    def _end_type_from_color(self, color: str | None) -> str | None:
        if not color:
            return None
        candidate = str(color).lower()
        for end_type, end_color in END_TYPE_COLORS.items():
            if candidate == end_color.lower():
                return end_type
        return None

    def _split_tags(self, value: object) -> list[str]:
        if isinstance(value, list | tuple | set):
            return [self._normalize_tag(str(item)) for item in value]
        if isinstance(value, str):
            return [self._normalize_tag(chunk) for chunk in _TAG_SPLIT_RE.split(value) if chunk]
        return []

    def _extract_inline_tags(self, value: str) -> list[str]:
        return [match.lower() for match in _INLINE_TAG_RE.findall(value)]

    def _normalize_tag(self, value: str) -> str:
        candidate = value.strip()
        if candidate.startswith("#"):
            candidate = candidate[1:]
        if candidate.startswith("::"):
            candidate = candidate[2:]
        return candidate
