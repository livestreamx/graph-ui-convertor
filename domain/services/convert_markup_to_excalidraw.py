from __future__ import annotations

import random
import uuid
from typing import Dict, Iterable, List, Tuple

from domain.models import (
    BlockPlacement,
    CUSTOM_DATA_KEY,
    END_TYPE_COLORS,
    END_TYPE_DEFAULT,
    ExcalidrawDocument,
    FramePlacement,
    INTERMEDIATE_BLOCK_COLOR,
    LayoutPlan,
    MarkupDocument,
    METADATA_SCHEMA_VERSION,
    MarkerPlacement,
    Point,
    ScenarioPlacement,
    SeparatorPlacement,
    Size,
)
from domain.ports.layout import LayoutEngine


class MarkupToExcalidrawConverter:
    def __init__(self, layout_engine: LayoutEngine) -> None:
        self.layout_engine = layout_engine
        self.namespace = uuid.uuid5(uuid.NAMESPACE_DNS, "cjm-ui-convertor")

    def convert(self, document: MarkupDocument) -> ExcalidrawDocument:
        plan = self.layout_engine.build_plan(document)
        elements: List[dict] = []
        element_index: Dict[str, dict] = {}
        base_metadata = {
            "schema_version": METADATA_SCHEMA_VERSION,
            "finedog_unit_id": document.finedog_unit_id,
            "markup_type": document.markup_type,
        }
        if document.service_name:
            base_metadata["service_name"] = document.service_name

        def add_element(element: dict) -> None:
            elements.append(element)
            element_index[element["id"]] = element

        proc_name_lookup = {
            proc.procedure_id: proc.procedure_name
            for proc in document.procedures
            if proc.procedure_name
        }
        frame_ids = self._build_frames(
            plan.frames, add_element, base_metadata, proc_name_lookup
        )
        self._build_separators(plan.separators, add_element, base_metadata)
        self._build_scenarios(plan.scenarios, add_element, base_metadata)
        included_procs = {frame.procedure_id for frame in plan.frames}
        end_block_type_lookup = {
            (proc.procedure_id, block_id): proc.end_block_types.get(block_id, END_TYPE_DEFAULT)
            for proc in document.procedures
            if proc.procedure_id in included_procs
            for block_id in proc.end_block_ids
        }
        block_name_lookup = {
            (proc.procedure_id, block_id): name
            for proc in document.procedures
            for block_id, name in proc.block_id_to_block_name.items()
            if name
        }
        blocks = self._build_blocks(
            plan.blocks,
            frame_ids,
            add_element,
            base_metadata,
            end_block_type_lookup,
            block_name_lookup,
        )

        start_label_index: Dict[Tuple[str, str], int] = {}
        start_blocks_global = [
            (proc.procedure_id, blk_id)
            for proc in document.procedures
            if proc.procedure_id in included_procs
            for blk_id in proc.start_block_ids
        ]
        for idx, (proc_id, blk_id) in enumerate(start_blocks_global, start=1):
            start_label_index[(proc_id, blk_id)] = idx
        markers = self._build_markers(
            plan.markers,
            frame_ids,
            add_element,
            base_metadata,
            start_label_index,
            end_block_type_lookup,
        )

        self._build_start_edges(document, blocks, markers, add_element, element_index, base_metadata)
        self._build_end_edges(
            document,
            blocks,
            markers,
            add_element,
            element_index,
            base_metadata,
            end_block_type_lookup,
        )
        self._build_branch_edges(document, blocks, add_element, element_index, base_metadata)
        self._build_procedure_flow_edges(
            document, plan.frames, frame_ids, add_element, element_index, base_metadata
        )

        app_state = {
            "viewBackgroundColor": "#ffffff",
            "gridSize": None,
            "currentItemFontFamily": 1,
            "currentItemFontSize": 20,
            "currentItemStrokeColor": "#1e1e1e",
        }
        return ExcalidrawDocument(elements=elements, app_state=app_state, files={})

    def _build_frames(
        self,
        frames: Iterable[FramePlacement],
        add_element: callable,
        base_metadata: dict,
        proc_name_lookup: Dict[str, str],
    ) -> Dict[str, str]:
        frame_ids: Dict[str, str] = {}
        for frame in frames:
            frame_id = self._stable_id("frame", frame.procedure_id)
            frame_ids[frame.procedure_id] = frame_id
            procedure_name = proc_name_lookup.get(frame.procedure_id)
            label = self._format_procedure_label(procedure_name, frame.procedure_id)
            frame_meta = {
                "procedure_id": frame.procedure_id,
                "role": "frame",
            }
            if procedure_name:
                frame_meta["procedure_name"] = procedure_name
            add_element(
                self._frame_element(
                    element_id=frame_id,
                    frame=frame,
                    metadata=self._with_base_metadata(
                        frame_meta,
                        base_metadata,
                    ),
                    name=label,
                )
            )
        return frame_ids

    def _build_separators(
        self,
        separators: Iterable[SeparatorPlacement],
        add_element: callable,
        base_metadata: dict,
    ) -> None:
        for idx, separator in enumerate(separators):
            element_id = self._stable_id("separator", str(idx), str(separator.start), str(separator.end))
            add_element(
                self._line_element(
                    element_id=element_id,
                    start=separator.start,
                    end=separator.end,
                    metadata=self._with_base_metadata(
                        {"role": "separator", "separator_index": idx},
                        base_metadata,
                    ),
                    stroke_color="#9e9e9e",
                    stroke_style="dashed",
                    stroke_width=2,
                )
            )

    def _build_scenarios(
        self,
        scenarios: Iterable[ScenarioPlacement],
        add_element: callable,
        base_metadata: dict,
    ) -> None:
        for idx, scenario in enumerate(scenarios, start=1):
            group_id = self._stable_id("scenario-group", str(idx))
            panel_id = self._stable_id("scenario-panel", str(idx))
            title_id = self._stable_id("scenario-title", str(idx))
            body_id = self._stable_id("scenario-body", str(idx))
            panel_meta = self._with_base_metadata(
                {"role": "scenario_panel", "scenario_index": idx},
                base_metadata,
            )
            add_element(
                self._scenario_panel_element(
                    element_id=panel_id,
                    origin=scenario.origin,
                    size=scenario.size,
                    metadata=panel_meta,
                    group_ids=[group_id],
                )
            )
            content_width = scenario.size.width - (scenario.padding * 2)
            title_lines = scenario.title_text.splitlines() or [scenario.title_text]
            body_lines = scenario.body_text.splitlines() or [scenario.body_text]
            title_height = len(title_lines) * scenario.title_font_size * 1.35
            body_height = len(body_lines) * scenario.body_font_size * 1.35
            title_origin = Point(
                x=scenario.origin.x + scenario.padding,
                y=scenario.origin.y + scenario.padding,
            )
            body_origin = Point(
                x=scenario.origin.x + scenario.padding,
                y=scenario.origin.y + scenario.padding + title_height,
            )
            add_element(
                self._text_block_element(
                    element_id=title_id,
                    text=scenario.title_text,
                    origin=title_origin,
                    width=content_width,
                    height=title_height,
                    metadata=self._with_base_metadata(
                        {"role": "scenario_title", "scenario_index": idx},
                        base_metadata,
                    ),
                    group_ids=[group_id],
                    font_size=scenario.title_font_size,
                )
            )
            add_element(
                self._text_block_element(
                    element_id=body_id,
                    text=scenario.body_text,
                    origin=body_origin,
                    width=content_width,
                    height=body_height,
                    metadata=self._with_base_metadata(
                        {"role": "scenario_body", "scenario_index": idx},
                        base_metadata,
                    ),
                    group_ids=[group_id],
                    font_size=scenario.body_font_size,
                )
            )

    def _build_blocks(
        self,
        blocks: Iterable[BlockPlacement],
        frame_ids: Dict[str, str],
        add_element: callable,
        base_metadata: dict,
        end_block_type_lookup: Dict[Tuple[str, str], str],
        block_name_lookup: Dict[Tuple[str, str], str],
    ) -> Dict[Tuple[str, str], BlockPlacement]:
        placement_index: Dict[Tuple[str, str], BlockPlacement] = {}
        for block in blocks:
            placement_index[(block.procedure_id, block.block_id)] = block
            group_id = self._stable_id("group", block.procedure_id, block.block_id)
            rect_id = self._stable_id("block", block.procedure_id, block.block_id)
            text_id = self._stable_id("block-text", block.procedure_id, block.block_id)
            end_block_type = end_block_type_lookup.get(
                (block.procedure_id, block.block_id)
            )
            block_meta = {
                "procedure_id": block.procedure_id,
                "block_id": block.block_id,
                "role": "block",
            }
            if end_block_type:
                block_meta["end_block_type"] = end_block_type
            label_text = block_name_lookup.get(
                (block.procedure_id, block.block_id), block.block_id
            )
            add_element(
                self._rectangle_element(
                    element_id=rect_id,
                    position=block.position,
                    size=block.size,
                    frame_id=frame_ids.get(block.procedure_id),
                    group_ids=[group_id],
                    metadata=self._with_base_metadata(block_meta, base_metadata),
                    background_color=(
                        INTERMEDIATE_BLOCK_COLOR
                        if end_block_type == "intermediate"
                        else None
                    ),
                )
            )
            label_meta = {
                "procedure_id": block.procedure_id,
                "block_id": block.block_id,
                "role": "block_label",
                "end_block_type": end_block_type,
            }
            if label_text != block.block_id:
                label_meta["block_name"] = label_text
            add_element(
                self._text_element(
                    element_id=text_id,
                    text=label_text,
                    center=self._center(block.position, block.size.width, block.size.height),
                    container_id=rect_id,
                    group_ids=[group_id],
                    frame_id=frame_ids.get(block.procedure_id),
                    metadata=self._with_base_metadata(label_meta, base_metadata),
                    max_width=max(80.0, block.size.width - 30),
                    max_height=max(24.0, block.size.height - 30),
                    font_size=18.0,
                )
            )
        return placement_index

    def _build_markers(
        self,
        markers: Iterable[MarkerPlacement],
        frame_ids: Dict[str, str],
        add_element: callable,
        base_metadata: dict,
        start_label_index: Dict[Tuple[str, str], int],
        end_block_type_lookup: Dict[Tuple[str, str], str],
    ) -> Dict[Tuple[str, str, str, str | None], MarkerPlacement]:
        marker_index: Dict[Tuple[str, str, str, str | None], MarkerPlacement] = {}
        for marker in markers:
            marker_index[
                (marker.procedure_id, marker.block_id, marker.role, marker.end_type)
            ] = marker
            element_id = self._marker_element_id(
                marker.procedure_id, marker.role, marker.block_id, marker.end_type
            )
            marker_meta = {
                "procedure_id": marker.procedure_id,
                "block_id": marker.block_id,
                "role": marker.role,
            }
            end_type = None
            block_end_type = None
            background_color = None
            if marker.role == "end_marker":
                end_type = marker.end_type or END_TYPE_DEFAULT
                block_end_type = end_block_type_lookup.get(
                    (marker.procedure_id, marker.block_id), END_TYPE_DEFAULT
                )
                marker_meta["end_block_type"] = block_end_type
                marker_meta["end_type"] = end_type
                background_color = END_TYPE_COLORS.get(end_type, END_TYPE_COLORS[END_TYPE_DEFAULT])
            add_element(
                self._ellipse_element(
                    element_id=element_id,
                    position=marker.position,
                    size=marker.size,
                    frame_id=frame_ids.get(marker.procedure_id),
                    metadata=self._with_base_metadata(marker_meta, base_metadata),
                    background_color=background_color,
                )
            )
            label_id = self._stable_id(
                "marker-text", marker.procedure_id, marker.role, marker.block_id, marker.end_type or ""
            )
            label_text = "START"
            if marker.role == "start_marker":
                idx = start_label_index.get((marker.procedure_id, marker.block_id), 1)
                label_text = "START" if len(start_label_index) == 1 else f"START #{idx}"
            elif marker.role == "end_marker":
                if end_type in {"all", "intermediate"}:
                    label_text = "END & EXIT"
                else:
                    label_text = "END" if end_type != "exit" else "EXIT"
            add_element(
                self._text_element(
                    element_id=label_id,
                    text=label_text,
                    center=self._center(marker.position, marker.size.width, marker.size.height),
                    container_id=element_id,
                    frame_id=frame_ids.get(marker.procedure_id),
                    metadata=self._with_base_metadata(marker_meta, base_metadata),
                    max_width=marker.size.width - 24,
                    max_height=min(52.0, marker.size.height - 14),
                    font_size=None,
                )
            )
        return marker_index

    def _build_start_edges(
        self,
        document: MarkupDocument,
        blocks: Dict[Tuple[str, str], BlockPlacement],
        markers: Dict[Tuple[str, str, str, str | None], MarkerPlacement],
        add_element: callable,
        element_index: Dict[str, dict],
        base_metadata: dict,
    ) -> None:
        for procedure in document.procedures:
            for start_block_id in procedure.start_block_ids:
                marker = markers.get(
                    (procedure.procedure_id, start_block_id, "start_marker", None)
                )
                block = blocks.get((procedure.procedure_id, start_block_id))
                if not marker or not block:
                    continue
                start_center = self._marker_anchor(marker, side="right")
                end_center = self._block_anchor(block, side="left")
                arrow = self._arrow_element(
                    start=start_center,
                    end=end_center,
                    label="start",
                    metadata=self._with_base_metadata(
                        {
                            "procedure_id": procedure.procedure_id,
                            "role": "edge",
                            "edge_type": "start",
                            "target_block_id": start_block_id,
                        },
                        base_metadata,
                    ),
                    start_binding=self._marker_element_id(
                        procedure.procedure_id, "start_marker", start_block_id, None
                    ),
                    end_binding=self._stable_id(
                        "block", procedure.procedure_id, start_block_id
                    ),
                )
                add_element(arrow)
                self._bind_arrow(element_index, arrow)

    def _build_end_edges(
        self,
        document: MarkupDocument,
        blocks: Dict[Tuple[str, str], BlockPlacement],
        markers: Dict[Tuple[str, str, str, str | None], MarkerPlacement],
        add_element: callable,
        element_index: Dict[str, dict],
        base_metadata: dict,
        end_block_type_lookup: Dict[Tuple[str, str], str],
    ) -> None:
        for (proc_id, block_id, role, marker_end_type), marker in markers.items():
            if role != "end_marker":
                continue
            block = blocks.get((proc_id, block_id))
            if not block:
                continue
            end_type = marker_end_type or END_TYPE_DEFAULT
            block_end_type = end_block_type_lookup.get((proc_id, block_id), end_type)
            start_center = self._block_anchor(block, side="right")
            end_center = self._marker_anchor(marker, side="left")
            arrow = self._arrow_element(
                start=start_center,
                end=end_center,
                label="end",
                metadata=self._with_base_metadata(
                    {
                        "procedure_id": proc_id,
                        "role": "edge",
                        "edge_type": "end",
                        "end_type": end_type,
                        "end_block_type": block_end_type,
                        "source_block_id": block_id,
                    },
                    base_metadata,
                ),
                start_binding=self._stable_id(
                    "block", proc_id, block_id
                ),
                end_binding=self._marker_element_id(
                    proc_id, "end_marker", block_id, marker_end_type
                ),
            )
            add_element(arrow)
            self._bind_arrow(element_index, arrow)

    def _build_branch_edges(
        self,
        document: MarkupDocument,
        blocks: Dict[Tuple[str, str], BlockPlacement],
        add_element: callable,
        element_index: Dict[str, dict],
        base_metadata: dict,
    ) -> None:
        cycle_edges_by_proc: Dict[str, set[Tuple[str, str]]] = {
            procedure.procedure_id: self._find_cycle_edges(procedure.branches)
            for procedure in document.procedures
        }
        branch_offsets: Dict[Tuple[str, str], List[float]] = {}
        for procedure in document.procedures:
            for source_block, targets in procedure.branches.items():
                count = max(1, len(targets))
                offsets = [
                    (idx - (count - 1) / 2) * 15.0
                    for idx in range(count)
                ]
                branch_offsets[(procedure.procedure_id, source_block)] = offsets
        branch_index: Dict[Tuple[str, str], int] = {}

        # Index blocks by block_id for potential cross-procedure branches (best-effort).
        block_by_id: Dict[str, List[Tuple[str, BlockPlacement]]] = {}
        for (proc_id, blk_id), placement in blocks.items():
            block_by_id.setdefault(blk_id, []).append((proc_id, placement))

        for procedure in document.procedures:
            for source_block, targets in procedure.branches.items():
                source = blocks.get((procedure.procedure_id, source_block))
                if not source:
                    continue
                for target_block in targets:
                    target = blocks.get((procedure.procedure_id, target_block))
                    target_proc_id = procedure.procedure_id
                    if not target:
                        candidates = block_by_id.get(target_block, [])
                        if len(candidates) == 1:
                            target_proc_id, target = candidates[0]
                    if not target:
                        continue
                    offset_key = (procedure.procedure_id, source_block)
                    offset_idx = branch_index.get(offset_key, 0)
                    branch_index[offset_key] = offset_idx + 1
                    is_cycle = (source_block, target_block) in cycle_edges_by_proc.get(
                        procedure.procedure_id, set()
                    )
                    dy = branch_offsets.get(offset_key, [0])[
                        min(offset_idx, len(branch_offsets.get(offset_key, [0])) - 1)
                    ]
                    if is_cycle:
                        start_center = self._block_anchor(source, side="top")
                        end_center = self._block_anchor(target, side="top")
                    else:
                        start_center = self._block_anchor(
                            source, side="right", y_offset=dy
                        )
                        end_center = self._block_anchor(
                            target, side="left", y_offset=dy
                        )
                    edge_type = "branch_cycle" if is_cycle else "branch"
                    label = "ЦИКЛ" if is_cycle else "branch"
                    arrow = self._arrow_element(
                        start=start_center,
                        end=end_center,
                        label=label,
                        metadata=self._with_base_metadata(
                            {
                                "procedure_id": procedure.procedure_id,
                                "target_procedure_id": target_proc_id,
                                "role": "edge",
                                "edge_type": edge_type,
                                "is_cycle": is_cycle,
                                "source_block_id": source_block,
                                "target_block_id": target_block,
                            },
                            base_metadata,
                        ),
                        start_binding=self._stable_id(
                            "block", procedure.procedure_id, source_block
                        ),
                        end_binding=self._stable_id(
                            "block", target_proc_id, target_block
                        ),
                        smoothing=0.15,
                        stroke_style="dashed" if is_cycle else None,
                        stroke_color="#d32f2f" if is_cycle else None,
                        curve_offset=80.0 if is_cycle else None,
                        curve_direction=-1.0 if is_cycle else None,
                        start_arrowhead="arrow" if is_cycle else None,
                        end_arrowhead="arrow" if is_cycle else None,
                    )
                    add_element(arrow)
                    self._bind_arrow(element_index, arrow)

    def _build_procedure_flow_edges(
        self,
        document: MarkupDocument,
        frames: Iterable[FramePlacement],
        frame_ids: Dict[str, str],
        add_element: callable,
        element_index: Dict[str, dict],
        base_metadata: dict,
    ) -> None:
        frames_list = list(frames)
        if len(frames_list) <= 1:
            return
        frame_lookup: Dict[str, FramePlacement] = {f.procedure_id: f for f in frames_list}
        graph_edges: List[Tuple[str, str]] = []
        cycle_edges: set[Tuple[str, str]] = set()
        for parent, children in document.procedure_graph.items():
            if parent not in frame_lookup:
                continue
            if not isinstance(children, list):
                continue
            for child in children:
                if child in frame_lookup:
                    graph_edges.append((parent, child))

        if graph_edges:
            cycle_edges = self._find_cycle_edges(document.procedure_graph)
            seen: set[Tuple[str, str]] = set()
            edges_to_draw = []
            for edge in graph_edges:
                if edge in seen:
                    continue
                seen.add(edge)
                edges_to_draw.append(edge)
        else:
            # Connect procedures when no explicit block-to-block cross edges.
            proc_for_block: Dict[str, str] = {}
            for proc in document.procedures:
                for blk in proc.block_ids():
                    proc_for_block[blk] = proc.procedure_id

            cross_edges = []
            for proc in document.procedures:
                for src, targets in proc.branches.items():
                    for tgt in targets:
                        tgt_proc = proc_for_block.get(tgt)
                        if tgt_proc and tgt_proc != proc.procedure_id:
                            cross_edges.append((proc.procedure_id, tgt_proc))
            seen_edges: set[Tuple[str, str]] = set()
            edges_to_draw = []
            for edge in cross_edges:
                if edge in seen_edges:
                    continue
                seen_edges.add(edge)
                edges_to_draw.append(edge)

        for left_id, right_id in edges_to_draw:
            left_frame = frame_lookup.get(left_id)
            right_frame = frame_lookup.get(right_id)
            if not left_frame or not right_frame:
                continue
            is_cycle = bool(graph_edges) and (left_id, right_id) in cycle_edges
            edge_type = "procedure_cycle" if is_cycle else "procedure_flow"
            label = "ЦИКЛ" if is_cycle else "procedure"
            if is_cycle:
                start = Point(
                    x=left_frame.origin.x + left_frame.size.width / 2,
                    y=left_frame.origin.y,
                )
                end = Point(
                    x=right_frame.origin.x + right_frame.size.width / 2,
                    y=right_frame.origin.y,
                )
            else:
                start = Point(
                    x=left_frame.origin.x + left_frame.size.width,
                    y=left_frame.origin.y + left_frame.size.height / 2,
                )
                end = Point(
                    x=right_frame.origin.x,
                    y=right_frame.origin.y + right_frame.size.height / 2,
                )
            arrow = self._arrow_element(
                start=start,
                end=end,
                label=label,
                metadata=self._with_base_metadata(
                    {
                        "procedure_id": left_id,
                        "target_procedure_id": right_id,
                        "role": "edge",
                        "edge_type": edge_type,
                        "is_cycle": is_cycle,
                    },
                    base_metadata,
                ),
                start_binding=self._stable_id("frame", left_id),
                end_binding=self._stable_id("frame", right_id),
                smoothing=0.1,
                stroke_style="dashed" if is_cycle else None,
                stroke_color="#d32f2f" if is_cycle else None,
                curve_offset=100.0 if is_cycle else None,
                curve_direction=-1.0 if is_cycle else None,
                start_arrowhead="arrow" if is_cycle else None,
                end_arrowhead="arrow" if is_cycle else None,
            )
            add_element(arrow)
            self._bind_arrow(element_index, arrow)

    def _format_procedure_label(self, procedure_name: str | None, procedure_id: str) -> str:
        if procedure_name:
            return f"{procedure_name} ({procedure_id})"
        return procedure_id

    def _frame_element(
        self,
        element_id: str,
        frame: FramePlacement,
        metadata: dict,
        name: str | None = None,
    ) -> dict:
        return self._base_shape(
            element_id=element_id,
            type_name="frame",
            position=frame.origin,
            width=frame.size.width,
            height=frame.size.height,
            extra={
                "name": name or frame.procedure_id,
                "strokeColor": "#1e1e1e",
                "backgroundColor": "transparent",
                "fillStyle": "solid",
                "seed": self._rand_seed(),
                "version": 1,
                "versionNonce": self._rand_seed(),
                "nameFontSize": 28,
            },
            metadata=metadata,
        )

    def _rectangle_element(
        self,
        element_id: str,
        position: Point,
        size: Size,
        frame_id: str | None,
        group_ids: List[str],
        metadata: dict,
        background_color: str | None = None,
    ) -> dict:
        return self._base_shape(
            element_id=element_id,
            type_name="rectangle",
            position=position,
            width=size.width,
            height=size.height,
            frame_id=frame_id,
            group_ids=group_ids,
            extra={
                "strokeColor": "#1e1e1e",
                "backgroundColor": background_color or "#cce5ff",
                "fillStyle": "hachure",
                "seed": self._rand_seed(),
                "version": 1,
                "versionNonce": self._rand_seed(),
                "boundElements": [],
            },
            metadata=metadata,
        )

    def _scenario_panel_element(
        self,
        element_id: str,
        origin: Point,
        size: Size,
        metadata: dict,
        group_ids: List[str],
    ) -> dict:
        return self._base_shape(
            element_id=element_id,
            type_name="rectangle",
            position=origin,
            width=size.width,
            height=size.height,
            group_ids=group_ids,
            extra={
                "strokeColor": "#c7bba3",
                "backgroundColor": "#f7f3ea",
                "fillStyle": "solid",
                "roughness": 0,
                "seed": self._rand_seed(),
                "version": 1,
                "versionNonce": self._rand_seed(),
                "roundness": {"type": 3},
            },
            metadata=metadata,
        )

    def _ellipse_element(
        self,
        element_id: str,
        position: Point,
        size: Size,
        frame_id: str | None,
        metadata: dict,
        background_color: str | None = None,
    ) -> dict:
        return self._base_shape(
            element_id=element_id,
            type_name="ellipse",
            position=position,
            width=size.width,
            height=size.height,
            frame_id=frame_id,
            extra={
                "strokeColor": "#1e1e1e",
                "backgroundColor": background_color or "#d1ffd6",
                "fillStyle": "solid",
                "seed": self._rand_seed(),
                "version": 1,
                "versionNonce": self._rand_seed(),
            },
            metadata=metadata,
        )

    def _text_block_element(
        self,
        element_id: str,
        text: str,
        origin: Point,
        width: float,
        height: float,
        metadata: dict,
        group_ids: List[str] | None = None,
        font_size: float = 16.0,
    ) -> dict:
        return {
            "id": element_id,
            "type": "text",
            "x": origin.x,
            "y": origin.y,
            "width": width,
            "height": height,
            "angle": 0,
            "strokeColor": "#2b2b2b",
            "backgroundColor": "transparent",
            "fillStyle": "solid",
            "strokeWidth": 1,
            "strokeStyle": "solid",
            "roughness": 0,
            "opacity": 100,
            "groupIds": group_ids or [],
            "frameId": None,
            "roundness": None,
            "seed": self._rand_seed(),
            "version": 1,
            "versionNonce": self._rand_seed(),
            "isDeleted": False,
            "boundElements": [],
            "locked": False,
            "text": text,
            "fontSize": font_size,
            "fontFamily": 1,
            "textAlign": "left",
            "verticalAlign": "top",
            "baseline": font_size,
            "customData": {CUSTOM_DATA_KEY: metadata},
        }

    def _text_element(
        self,
        element_id: str,
        text: str,
        center: Point,
        container_id: str | None,
        frame_id: str | None,
        metadata: dict,
        group_ids: List[str] | None = None,
        max_width: float | None = None,
        max_height: float | None = None,
        font_size: float | None = None,
    ) -> dict:
        width = max(80.0, len(text) * 9.0)
        if max_width is not None:
            width = max_width
        max_size = font_size or 20.0
        size = max_size
        content = text
        if max_width is not None and max_height is not None and len(text) > 0:
            content, size, height = self._fit_text(
                text=text,
                max_width=max_width,
                max_height=max_height,
                min_size=11.0,
                max_size=max_size,
            )
        else:
            if max_width is not None and len(text) > 0:
                ratio = max_width / (len(text) * 7.5)
                size = max(11.0, min(max_size, max_size * ratio))
            height = (size * 1.35) if max_height is None else max_height
        x = center.x - width / 2
        y = center.y - height / 2
        return {
            "id": element_id,
            "type": "text",
            "x": x,
            "y": y,
            "width": width,
            "height": height,
            "angle": 0,
            "strokeColor": "#1e1e1e",
            "backgroundColor": "transparent",
            "fillStyle": "solid",
            "strokeWidth": 1,
            "strokeStyle": "solid",
            "roughness": 0,
            "opacity": 100,
            "groupIds": group_ids or [],
            "frameId": frame_id,
            "roundness": None,
            "seed": self._rand_seed(),
            "version": 1,
            "versionNonce": self._rand_seed(),
            "isDeleted": False,
            "boundElements": [],
            "locked": False,
            "text": content,
            "fontSize": size,
            "fontFamily": 1,
            "textAlign": "center",
            "verticalAlign": "middle",
            "baseline": height / 2,
            "containerId": container_id,
            "customData": {CUSTOM_DATA_KEY: metadata},
        }

    def _marker_element_id(
        self,
        procedure_id: str,
        role: str,
        block_id: str,
        end_type: str | None,
    ) -> str:
        if role == "end_marker" and end_type:
            return self._stable_id("marker", procedure_id, role, block_id, end_type)
        return self._stable_id("marker", procedure_id, role, block_id)

    def _line_element(
        self,
        element_id: str,
        start: Point,
        end: Point,
        metadata: dict,
        stroke_color: str | None = None,
        stroke_style: str | None = None,
        stroke_width: float = 1.0,
    ) -> dict:
        dx = end.x - start.x
        dy = end.y - start.y
        points = [[0.0, 0.0], [dx, dy]]
        min_x = min(point[0] for point in points)
        max_x = max(point[0] for point in points)
        min_y = min(point[1] for point in points)
        max_y = max(point[1] for point in points)
        width = max_x - min_x
        height = max_y - min_y
        adjusted_points = [[point[0] - min_x, point[1] - min_y] for point in points]
        return {
            "id": element_id,
            "type": "line",
            "x": start.x + min_x,
            "y": start.y + min_y,
            "width": width,
            "height": height,
            "angle": 0,
            "strokeColor": stroke_color or "#1e1e1e",
            "backgroundColor": "transparent",
            "fillStyle": "solid",
            "strokeWidth": stroke_width,
            "strokeStyle": stroke_style or "solid",
            "roughness": 0,
            "opacity": 100,
            "groupIds": [],
            "roundness": None,
            "seed": self._rand_seed(),
            "version": 1,
            "versionNonce": self._rand_seed(),
            "isDeleted": False,
            "boundElements": [],
            "locked": False,
            "points": adjusted_points,
            "customData": {CUSTOM_DATA_KEY: metadata},
        }

    def _arrow_element(
        self,
        start: Point,
        end: Point,
        label: str,
        metadata: dict,
        start_binding: str | None = None,
        end_binding: str | None = None,
        smoothing: float = 0.0,
        stroke_style: str | None = None,
        stroke_color: str | None = None,
        curve_offset: float | None = None,
        curve_direction: float | None = None,
        start_arrowhead: str | None = None,
        end_arrowhead: str | None = None,
    ) -> dict:
        dx = end.x - start.x
        dy = end.y - start.y
        arrow_id = self._stable_id("arrow", metadata.get("procedure_id", ""), label, str(start), str(end))
        edge_type = metadata.get("edge_type")
        show_text = edge_type in {"branch", "branch_cycle", "procedure_cycle"}
        points = [[0.0, 0.0], [dx, dy]]
        roundness = {"type": 2}
        if curve_offset is not None:
            mid_x = dx / 2
            direction = curve_direction if curve_direction is not None else (1.0 if dy >= 0 else -1.0)
            mid_y = dy / 2 + (curve_offset * direction)
            points = [[0.0, 0.0], [mid_x, mid_y], [dx, dy]]
            roundness = {"type": 3}

        min_x = min(point[0] for point in points)
        max_x = max(point[0] for point in points)
        min_y = min(point[1] for point in points)
        max_y = max(point[1] for point in points)
        width = max_x - min_x
        height = max_y - min_y
        adjusted_points = [[point[0] - min_x, point[1] - min_y] for point in points]
        arrow = {
            "id": arrow_id,
            "type": "arrow",
            "x": start.x + min_x,
            "y": start.y + min_y,
            "width": width,
            "height": height,
            "angle": 0,
            "strokeColor": stroke_color or "#1e1e1e",
            "backgroundColor": "transparent",
            "fillStyle": "solid",
            "strokeWidth": 1,
            "strokeStyle": stroke_style or "solid",
            "roughness": 0,
            "opacity": 100,
            "groupIds": [],
            "roundness": roundness,
            "seed": self._rand_seed(),
            "version": 1,
            "versionNonce": self._rand_seed(),
            "isDeleted": False,
            "boundElements": [],
            "locked": False,
            "points": adjusted_points,
            "startBinding": {"elementId": start_binding, "focus": 0.0, "gap": 8} if start_binding else None,
            "endBinding": {"elementId": end_binding, "focus": 0.0, "gap": 8} if end_binding else None,
            "label": label,
            "text": label if show_text else "",
            "customData": {CUSTOM_DATA_KEY: metadata},
        }
        if start_arrowhead is not None:
            arrow["startArrowhead"] = start_arrowhead
        if end_arrowhead is not None:
            arrow["endArrowhead"] = end_arrowhead
        return arrow

    def _find_cycle_edges(self, adjacency: Dict[str, List[str]]) -> set[Tuple[str, str]]:
        normalized: Dict[str, List[str]] = {}
        for node, children in adjacency.items():
            if isinstance(children, list):
                normalized[node] = children
            else:
                normalized[node] = []

        nodes = set(normalized.keys())
        for children in normalized.values():
            nodes.update(children)
        visited: Dict[str, int] = {}
        cycle_edges: set[Tuple[str, str]] = set()

        def dfs(node: str) -> None:
            visited[node] = 1
            for child in normalized.get(node, []):
                state = visited.get(child, 0)
                if state == 0:
                    dfs(child)
                elif state == 1:
                    cycle_edges.add((node, child))
            visited[node] = 2

        for node in nodes:
            if visited.get(node, 0) == 0:
                dfs(node)
        return cycle_edges

    def _base_shape(
        self,
        element_id: str,
        type_name: str,
        position: Point,
        width: float,
        height: float,
        metadata: dict,
        frame_id: str | None = None,
        group_ids: List[str] | None = None,
        extra: dict | None = None,
    ) -> dict:
        return {
            "id": element_id,
            "type": type_name,
            "x": position.x,
            "y": position.y,
            "width": width,
            "height": height,
            "angle": 0,
            "strokeWidth": 1,
            "strokeStyle": "solid",
            "roughness": 0,
            "opacity": 100,
            "groupIds": group_ids or [],
            "roundness": None,
            "seed": self._rand_seed(),
            "version": 1,
            "versionNonce": self._rand_seed(),
            "isDeleted": False,
            "boundElements": [],
            "locked": False,
            "frameId": frame_id,
            "customData": {CUSTOM_DATA_KEY: metadata},
            **(extra or {}),
        }

    def _center(self, position: Point, width: float, height: float) -> Point:
        return Point(x=position.x + width / 2, y=position.y + height / 2)

    def _block_anchor(
        self,
        block: BlockPlacement,
        side: str,
        x_offset: float = 0.0,
        y_offset: float = 0.0,
    ) -> Point:
        if side == "left":
            return Point(
                x=block.position.x + x_offset,
                y=block.position.y + block.size.height / 2 + y_offset,
            )
        if side == "top":
            return Point(
                x=block.position.x + block.size.width / 2 + x_offset,
                y=block.position.y + y_offset,
            )
        return Point(
            x=block.position.x + block.size.width + x_offset,
            y=block.position.y + block.size.height / 2 + y_offset,
        )

    def _marker_anchor(self, marker: MarkerPlacement, side: str) -> Point:
        if side == "left":
            return Point(
                x=marker.position.x,
                y=marker.position.y + marker.size.height / 2,
            )
        return Point(
            x=marker.position.x + marker.size.width,
            y=marker.position.y + marker.size.height / 2,
        )

    def _fit_text(
        self,
        text: str,
        max_width: float,
        max_height: float,
        min_size: float,
        max_size: float,
    ) -> Tuple[str, float, float]:
        if not text.strip():
            size = max_size
            height = min(max_height, size * 1.35)
            return text, size, height

        words = text.split()
        width_factor = 0.6
        line_height = 1.35

        def wrap_words(max_chars: int) -> List[str]:
            lines: List[str] = []
            current: List[str] = []
            count = 0
            for word in words:
                if not current:
                    if len(word) <= max_chars:
                        current = [word]
                        count = len(word)
                    else:
                        for idx in range(0, len(word), max_chars):
                            chunk = word[idx : idx + max_chars]
                            if current:
                                lines.append(" ".join(current))
                            current = [chunk]
                            count = len(chunk)
                    continue
                if count + 1 + len(word) <= max_chars:
                    current.append(word)
                    count += 1 + len(word)
                else:
                    lines.append(" ".join(current))
                    current = [word]
                    count = len(word)
            if current:
                lines.append(" ".join(current))
            return lines

        start = int(max_size)
        end = int(min_size)
        for size in range(start, end - 1, -1):
            max_chars = max(1, int(max_width / (size * width_factor)))
            lines = wrap_words(max_chars)
            height_needed = len(lines) * size * line_height
            if height_needed <= max_height:
                return "\n".join(lines), float(size), min(max_height, height_needed)

        size = max(min_size, 1.0)
        max_chars = max(1, int(max_width / (size * width_factor)))
        lines = wrap_words(max_chars)
        height_needed = len(lines) * size * line_height
        return "\n".join(lines), size, min(max_height, height_needed)

    def _bind_arrow(self, element_index: Dict[str, dict], arrow: dict) -> None:
        arrow_id = arrow["id"]
        for key in ("startBinding", "endBinding"):
            binding = arrow.get(key)
            if not binding:
                continue
            target_id = binding.get("elementId")
            target = element_index.get(target_id)
            if target is not None:
                target.setdefault("boundElements", []).append({"id": arrow_id, "type": "arrow"})

    def _stable_id(self, *parts: str) -> str:
        return str(uuid.uuid5(self.namespace, "|".join(parts)))

    def _rand_seed(self) -> int:
        return random.randint(1, 2**31 - 1)

    def _with_base_metadata(self, metadata: dict, base: dict) -> dict:
        merged = dict(base)
        merged.update(metadata)
        return merged
