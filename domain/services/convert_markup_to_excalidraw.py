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

        frame_ids = self._build_frames(plan.frames, add_element, base_metadata)
        included_procs = {frame.procedure_id for frame in plan.frames}
        end_block_type_lookup = {
            (proc.procedure_id, block_id): proc.end_block_types.get(block_id, END_TYPE_DEFAULT)
            for proc in document.procedures
            if proc.procedure_id in included_procs
            for block_id in proc.end_block_ids
        }
        blocks = self._build_blocks(
            plan.blocks, frame_ids, add_element, base_metadata, end_block_type_lookup
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
        self, frames: Iterable[FramePlacement], add_element: callable, base_metadata: dict
    ) -> Dict[str, str]:
        frame_ids: Dict[str, str] = {}
        for frame in frames:
            frame_id = self._stable_id("frame", frame.procedure_id)
            frame_ids[frame.procedure_id] = frame_id
            add_element(
                self._frame_element(
                    element_id=frame_id,
                    frame=frame,
                    metadata=self._with_base_metadata(
                        {
                            "procedure_id": frame.procedure_id,
                            "role": "frame",
                        },
                        base_metadata,
                    ),
                )
            )
        return frame_ids

    def _build_blocks(
        self,
        blocks: Iterable[BlockPlacement],
        frame_ids: Dict[str, str],
        add_element: callable,
        base_metadata: dict,
        end_block_type_lookup: Dict[Tuple[str, str], str],
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
            add_element(
                self._text_element(
                    element_id=text_id,
                    text=block.block_id,
                    center=self._center(block.position, block.size.width, block.size.height),
                    container_id=rect_id,
                    group_ids=[group_id],
                    frame_id=frame_ids.get(block.procedure_id),
                    metadata=self._with_base_metadata(
                        {
                            "procedure_id": block.procedure_id,
                            "block_id": block.block_id,
                            "role": "block_label",
                            "end_block_type": end_block_type,
                        },
                        base_metadata,
                    ),
                    max_width=block.size.width - 20,
                    max_height=min(56.0, block.size.height - 20),
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
                    dy = branch_offsets.get(offset_key, [0])[min(offset_idx, len(branch_offsets.get(offset_key, [0])) - 1)]
                    start_center = self._block_anchor(
                        source, side="right", y_offset=dy
                    )
                    end_center = self._block_anchor(
                        target, side="left", y_offset=dy
                    )
                    arrow = self._arrow_element(
                            start=start_center,
                            end=end_center,
                            label="branch",
                            metadata=self._with_base_metadata(
                                {
                                    "procedure_id": procedure.procedure_id,
                                    "target_procedure_id": target_proc_id,
                                    "role": "edge",
                            "edge_type": "branch",
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

        frame_lookup: Dict[str, FramePlacement] = {f.procedure_id: f for f in frames_list}
        ordered = sorted(
            [proc for proc in document.procedures if proc.procedure_id in frame_lookup],
            key=lambda p: frame_lookup.get(p.procedure_id).origin.x if frame_lookup.get(p.procedure_id) else 0.0,
        )
        sequential_edges = [
            (left.procedure_id, right.procedure_id) for left, right in zip(ordered, ordered[1:])
        ]
        edges_to_draw = list({*cross_edges, *sequential_edges})

        min_height = min((frame.size.height for frame in frames_list), default=0.0)
        baseline_y = frames_list[0].origin.y + (min_height / 2 if min_height else 0.0)
        for left_id, right_id in edges_to_draw:
            left_frame = frame_lookup.get(left_id)
            right_frame = frame_lookup.get(right_id)
            if not left_frame or not right_frame:
                continue
            start = Point(
                x=left_frame.origin.x + left_frame.size.width,
                y=baseline_y,
            )
            end = Point(
                x=right_frame.origin.x,
                y=baseline_y,
            )
            arrow = self._arrow_element(
                start=start,
                end=end,
                label="procedure",
                metadata=self._with_base_metadata(
                    {
                        "procedure_id": left_id,
                        "target_procedure_id": right_id,
                        "role": "edge",
                        "edge_type": "procedure_flow",
                    },
                    base_metadata,
                ),
                start_binding=self._stable_id("frame", left_id),
                end_binding=self._stable_id("frame", right_id),
                smoothing=0.1,
            )
            add_element(arrow)
            self._bind_arrow(element_index, arrow)

    def _frame_element(self, element_id: str, frame: FramePlacement, metadata: dict) -> dict:
        return self._base_shape(
            element_id=element_id,
            type_name="frame",
            position=frame.origin,
            width=frame.size.width,
            height=frame.size.height,
            extra={
                "name": frame.procedure_id,
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
        size = font_size or 20.0
        if max_width is not None and len(text) > 0:
            ratio = max_width / (len(text) * 7.5)
            size = max(11.0, min(20.0, 20.0 * ratio))
        height = (size * 1.3) if max_height is None else max_height
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
            "text": text,
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

    def _arrow_element(
        self,
        start: Point,
        end: Point,
        label: str,
        metadata: dict,
        start_binding: str | None = None,
        end_binding: str | None = None,
        smoothing: float = 0.0,
    ) -> dict:
        dx = end.x - start.x
        dy = end.y - start.y
        arrow_id = self._stable_id("arrow", metadata.get("procedure_id", ""), label, str(start), str(end))
        return {
            "id": arrow_id,
            "type": "arrow",
            "x": start.x,
            "y": start.y,
            "width": abs(dx),
            "height": abs(dy),
            "angle": 0,
            "strokeColor": "#1e1e1e",
            "backgroundColor": "transparent",
            "fillStyle": "solid",
            "strokeWidth": 1,
            "strokeStyle": "solid",
            "roughness": 0,
            "opacity": 100,
            "groupIds": [],
            "roundness": {"type": 2},
            "seed": self._rand_seed(),
            "version": 1,
            "versionNonce": self._rand_seed(),
            "isDeleted": False,
            "boundElements": [],
            "locked": False,
            "points": [[0, 0], [dx, dy]],
            "startBinding": {"elementId": start_binding, "focus": 0.0, "gap": 8} if start_binding else None,
            "endBinding": {"elementId": end_binding, "focus": 0.0, "gap": 8} if end_binding else None,
            "label": label,
            "text": label if metadata.get("edge_type") == "branch" else "",
            "customData": {CUSTOM_DATA_KEY: metadata},
        }

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

    def _block_anchor(self, block: BlockPlacement, side: str, y_offset: float = 0.0) -> Point:
        if side == "left":
            return Point(
                x=block.position.x,
                y=block.position.y + block.size.height / 2 + y_offset,
            )
        return Point(
            x=block.position.x + block.size.width,
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
