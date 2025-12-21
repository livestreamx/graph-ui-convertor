from __future__ import annotations

import random
import uuid
from typing import Dict, Iterable, List, Tuple

from domain.models import (
    BlockPlacement,
    CUSTOM_DATA_KEY,
    ExcalidrawDocument,
    FramePlacement,
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
        base_metadata = {
            "schema_version": METADATA_SCHEMA_VERSION,
            "finedog_unit_id": document.finedog_unit_id,
            "markup_type": document.markup_type,
        }

        frame_ids = self._build_frames(plan.frames, elements, base_metadata)
        blocks = self._build_blocks(plan.blocks, frame_ids, elements, base_metadata)
        markers = self._build_markers(plan.markers, frame_ids, elements, base_metadata)

        self._build_start_edges(document, blocks, markers, elements, base_metadata)
        self._build_end_edges(document, blocks, markers, elements, base_metadata)
        self._build_branch_edges(document, blocks, elements, base_metadata)

        app_state = {
            "viewBackgroundColor": "#ffffff",
            "gridSize": None,
            "currentItemFontFamily": 1,
            "currentItemFontSize": 20,
            "currentItemStrokeColor": "#1e1e1e",
        }
        return ExcalidrawDocument(elements=elements, app_state=app_state, files={})

    def _build_frames(
        self, frames: Iterable[FramePlacement], elements: List[dict], base_metadata: dict
    ) -> Dict[str, str]:
        frame_ids: Dict[str, str] = {}
        for frame in frames:
            frame_id = self._stable_id("frame", frame.procedure_id)
            frame_ids[frame.procedure_id] = frame_id
            elements.append(
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
        elements: List[dict],
        base_metadata: dict,
    ) -> Dict[Tuple[str, str], BlockPlacement]:
        placement_index: Dict[Tuple[str, str], BlockPlacement] = {}
        for block in blocks:
            placement_index[(block.procedure_id, block.block_id)] = block
            group_id = self._stable_id("group", block.procedure_id, block.block_id)
            rect_id = self._stable_id("block", block.procedure_id, block.block_id)
            text_id = self._stable_id("block-text", block.procedure_id, block.block_id)
            elements.append(
                self._rectangle_element(
                    element_id=rect_id,
                    position=block.position,
                    size=block.size,
                    frame_id=frame_ids.get(block.procedure_id),
                    group_ids=[group_id],
                    metadata=self._with_base_metadata(
                        {
                            "procedure_id": block.procedure_id,
                            "block_id": block.block_id,
                            "role": "block",
                        },
                        base_metadata,
                    ),
                )
            )
            elements.append(
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
                        },
                        base_metadata,
                    ),
                )
            )
        return placement_index

    def _build_markers(
        self,
        markers: Iterable[MarkerPlacement],
        frame_ids: Dict[str, str],
        elements: List[dict],
        base_metadata: dict,
    ) -> Dict[Tuple[str, str, str], MarkerPlacement]:
        marker_index: Dict[Tuple[str, str, str], MarkerPlacement] = {}
        for marker in markers:
            marker_index[(marker.procedure_id, marker.block_id, marker.role)] = marker
            element_id = self._stable_id("marker", marker.procedure_id, marker.role, marker.block_id)
            elements.append(
                self._ellipse_element(
                    element_id=element_id,
                    position=marker.position,
                    size=marker.size,
                    frame_id=frame_ids.get(marker.procedure_id),
                    metadata=self._with_base_metadata(
                        {
                            "procedure_id": marker.procedure_id,
                            "block_id": marker.block_id,
                            "role": marker.role,
                        },
                        base_metadata,
                    ),
                )
            )
            label_id = self._stable_id(
                "marker-text", marker.procedure_id, marker.role, marker.block_id
            )
            elements.append(
                self._text_element(
                    element_id=label_id,
                    text="START" if marker.role == "start_marker" else "END",
                    center=self._center(marker.position, marker.size.width, marker.size.height),
                    container_id=element_id,
                    frame_id=frame_ids.get(marker.procedure_id),
                    metadata=self._with_base_metadata(
                        {
                            "procedure_id": marker.procedure_id,
                            "block_id": marker.block_id,
                            "role": marker.role,
                        },
                        base_metadata,
                    ),
                )
            )
        return marker_index

    def _build_start_edges(
        self,
        document: MarkupDocument,
        blocks: Dict[Tuple[str, str], BlockPlacement],
        markers: Dict[Tuple[str, str, str], MarkerPlacement],
        elements: List[dict],
        base_metadata: dict,
    ) -> None:
        for procedure in document.procedures:
            for start_block_id in procedure.start_block_ids:
                marker = markers.get((procedure.procedure_id, start_block_id, "start_marker"))
                block = blocks.get((procedure.procedure_id, start_block_id))
                if not marker or not block:
                    continue
                start_center = self._marker_anchor(marker, side="right")
                end_center = self._block_anchor(block, side="left")
                elements.append(
                    self._arrow_element(
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
                        start_binding=self._stable_id(
                            "marker", procedure.procedure_id, "start_marker", start_block_id
                        ),
                        end_binding=self._stable_id(
                            "block", procedure.procedure_id, start_block_id
                        ),
                    )
                )

    def _build_end_edges(
        self,
        document: MarkupDocument,
        blocks: Dict[Tuple[str, str], BlockPlacement],
        markers: Dict[Tuple[str, str, str], MarkerPlacement],
        elements: List[dict],
        base_metadata: dict,
    ) -> None:
        for procedure in document.procedures:
            for end_block_id in procedure.end_block_ids:
                block = blocks.get((procedure.procedure_id, end_block_id))
                marker = markers.get((procedure.procedure_id, end_block_id, "end_marker"))
                if not block or not marker:
                    continue
                start_center = self._block_anchor(block, side="right")
                end_center = self._marker_anchor(marker, side="left")
                elements.append(
                    self._arrow_element(
                        start=start_center,
                        end=end_center,
                        label="end",
                        metadata=self._with_base_metadata(
                            {
                                "procedure_id": procedure.procedure_id,
                                "role": "edge",
                                "edge_type": "end",
                                "source_block_id": end_block_id,
                            },
                            base_metadata,
                        ),
                        start_binding=self._stable_id(
                            "block", procedure.procedure_id, end_block_id
                        ),
                        end_binding=self._stable_id(
                            "marker", procedure.procedure_id, "end_marker", end_block_id
                        ),
                    )
                )

    def _build_branch_edges(
        self,
        document: MarkupDocument,
        blocks: Dict[Tuple[str, str], BlockPlacement],
        elements: List[dict],
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
                    elements.append(
                        self._arrow_element(
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
                        )
                    )

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
                "backgroundColor": "#cce5ff",
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
                "backgroundColor": "#d1ffd6",
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
    ) -> dict:
        width = max(80.0, len(text) * 8.0)
        height = 30.0
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
            "fontSize": 20,
            "fontFamily": 1,
            "textAlign": "center",
            "verticalAlign": "middle",
            "baseline": height / 2,
            "containerId": container_id,
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
    ) -> dict:
        dx = end.x - start.x
        dy = end.y - start.y
        return {
            "id": self._stable_id("arrow", metadata.get("procedure_id", ""), label, str(start), str(end)),
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

    def _stable_id(self, *parts: str) -> str:
        return str(uuid.uuid5(self.namespace, "|".join(parts)))

    def _rand_seed(self) -> int:
        return random.randint(1, 2**31 - 1)

    def _with_base_metadata(self, metadata: dict, base: dict) -> dict:
        merged = dict(base)
        merged.update(metadata)
        return merged
