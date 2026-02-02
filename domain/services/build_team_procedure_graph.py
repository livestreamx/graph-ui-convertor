from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from domain.models import MarkupDocument, Procedure, merge_end_types

_SERVICE_COLORS = [
    "#d9f5ff",
    "#e3f7d9",
    "#fef3c7",
    "#e9ddff",
    "#ffe4d6",
    "#d6f7f5",
    "#fbd5e5",
    "#e5f0ff",
]
_INTERSECTION_COLOR = "#ffd6d6"


class BuildTeamProcedureGraph:
    def build(
        self,
        documents: Sequence[MarkupDocument],
        merge_documents: Sequence[MarkupDocument] | None = None,
    ) -> MarkupDocument:
        procedures: list[Procedure] = []
        procedure_payloads: dict[str, dict[str, Any]] = {}
        procedure_order: list[str] = []
        procedure_graph: dict[str, list[str]] = {}
        procedure_meta: dict[str, dict[str, object]] = {}
        procedure_services: dict[str, dict[str, dict[str, object]]] = {}
        team_labels: set[str] = set()
        team_ids: set[str | int] = set()
        team_names: set[str] = set()
        service_keys: set[str] = set()

        for document in documents:
            team_label = self._resolve_team_label(document)
            service_label = self._resolve_service_label(document)
            service_key = self._service_key(team_label, service_label)
            if team_label:
                team_labels.add(team_label)
            if document.team_id is not None:
                team_ids.add(document.team_id)
            if document.team_name:
                team_names.add(str(document.team_name))
            service_keys.add(service_key)

            for proc in document.procedures:
                proc_id = proc.procedure_id
                if proc_id not in procedure_payloads:
                    procedure_order.append(proc_id)
                    procedure_payloads[proc_id] = self._procedure_payload(proc)
                else:
                    procedure_payloads[proc_id] = self._merge_procedure_payload(
                        procedure_payloads[proc_id], proc
                    )
                procedure_services.setdefault(proc_id, {})[service_key] = {
                    "team_name": team_label,
                    "service_name": service_label,
                    "team_id": document.team_id,
                    "finedog_unit_id": document.finedog_unit_id,
                }

            for parent, children in document.procedure_graph.items():
                procedure_graph.setdefault(parent, [])
                for child in children:
                    if child not in procedure_graph[parent]:
                        procedure_graph[parent].append(child)

        service_colors = self._apply_service_colors(procedure_services, service_keys)
        for proc_id in procedure_order:
            payload = procedure_payloads[proc_id]
            procedures.append(Procedure.model_validate(payload))

            service_map = procedure_services.get(proc_id, {})
            services = sorted(
                service_map.values(),
                key=lambda item: (
                    str(item.get("team_name", "") or "").lower(),
                    str(item.get("service_name", "") or "").lower(),
                ),
            )
            service_key_list = sorted(service_map.keys())
            if service_key_list:
                is_intersection = len(service_key_list) > 1
                color = (
                    _INTERSECTION_COLOR
                    if is_intersection
                    else service_colors.get(service_key_list[0], _SERVICE_COLORS[0])
                )
                primary = services[0]
                procedure_meta[proc_id] = {
                    "team_name": primary.get("team_name", "Unknown team"),
                    "service_name": primary.get("service_name", "Unknown service"),
                    "team_id": primary.get("team_id"),
                    "finedog_unit_id": primary.get("finedog_unit_id"),
                    "procedure_color": color,
                    "is_intersection": is_intersection,
                    "services": services,
                }
            else:
                procedure_meta[proc_id] = {
                    "team_name": "Unknown team",
                    "service_name": "Unknown service",
                    "team_id": None,
                    "finedog_unit_id": None,
                    "procedure_color": _SERVICE_COLORS[0],
                    "is_intersection": False,
                    "services": [],
                }

        if merge_documents is not None:
            merge_services, merge_service_keys = self._collect_merge_services(merge_documents)
            self._apply_service_colors(merge_services, merge_service_keys)
            self._apply_merge_metadata(procedure_meta, merge_services)

        for proc in procedures:
            procedure_graph.setdefault(proc.procedure_id, [])

        team_list = sorted(team_labels, key=lambda name: name.lower())
        title = self._format_team_title(team_list)
        team_id: str | int | None = None
        team_name: str | None = None
        if len(team_ids) == 1:
            team_id = next(iter(team_ids))
        if len(team_names) == 1:
            team_name = next(iter(team_names))
        if team_name is None and team_id is not None:
            team_name = str(team_id)

        return MarkupDocument(
            markup_type="procedure_graph",
            service_name=title,
            team_id=team_id,
            team_name=team_name,
            procedures=procedures,
            procedure_graph=procedure_graph,
            procedure_meta=procedure_meta,
        )

    def _collect_merge_services(
        self,
        documents: Sequence[MarkupDocument],
    ) -> tuple[dict[str, dict[str, dict[str, object]]], set[str]]:
        procedure_services: dict[str, dict[str, dict[str, object]]] = {}
        service_keys: set[str] = set()
        for document in documents:
            team_label = self._resolve_team_label(document)
            service_label = self._resolve_service_label(document)
            service_key = self._service_key(team_label, service_label)
            service_keys.add(service_key)
            proc_ids = {proc.procedure_id for proc in document.procedures}
            for parent, children in document.procedure_graph.items():
                proc_ids.add(parent)
                proc_ids.update(children)
            for proc_id in proc_ids:
                procedure_services.setdefault(proc_id, {})[service_key] = {
                    "team_name": team_label,
                    "service_name": service_label,
                    "team_id": document.team_id,
                    "finedog_unit_id": document.finedog_unit_id,
                }
        return procedure_services, service_keys

    def _apply_service_colors(
        self,
        procedure_services: dict[str, dict[str, dict[str, object]]],
        service_keys: set[str],
    ) -> dict[str, str]:
        service_key_list = sorted(service_keys, key=lambda value: value.lower())
        service_colors = {
            key: _SERVICE_COLORS[idx % len(_SERVICE_COLORS)]
            for idx, key in enumerate(service_key_list)
        }
        for service_map in procedure_services.values():
            for service_key, payload in service_map.items():
                color = service_colors.get(service_key)
                if color:
                    payload["service_color"] = color
        return service_colors

    def _apply_merge_metadata(
        self,
        procedure_meta: dict[str, dict[str, object]],
        merge_services: dict[str, dict[str, dict[str, object]]],
    ) -> None:
        for proc_id, service_map in merge_services.items():
            if proc_id not in procedure_meta:
                continue
            services = sorted(
                service_map.values(),
                key=lambda item: (
                    str(item.get("team_name", "") or "").lower(),
                    str(item.get("service_name", "") or "").lower(),
                ),
            )
            if services:
                procedure_meta[proc_id]["merge_services"] = services
            merge_keys = set(service_map.keys())
            if len(merge_keys) > 1 or procedure_meta.get(proc_id, {}).get("is_intersection"):
                procedure_meta[proc_id]["is_intersection"] = True
                procedure_meta[proc_id]["procedure_color"] = _INTERSECTION_COLOR

    def _resolve_team_label(self, document: MarkupDocument) -> str:
        if document.team_name:
            return str(document.team_name)
        if document.team_id is not None:
            return str(document.team_id)
        return "Unknown team"

    def _resolve_service_label(self, document: MarkupDocument) -> str:
        if document.service_name:
            return str(document.service_name)
        return "Unknown service"

    def _service_key(self, team_label: str, service_label: str) -> str:
        return f"{team_label}::{service_label}"

    def _format_team_title(self, team_list: Sequence[str]) -> str:
        if not team_list:
            return "Unknown team"
        if len(team_list) <= 3:
            return " + ".join(team_list)
        extra_count = len(team_list) - 3
        return " + ".join(team_list[:3]) + f" + еще {extra_count} команд"

    def _procedure_payload(self, proc: Procedure) -> dict[str, Any]:
        return {
            "procedure_id": proc.procedure_id,
            "procedure_name": proc.procedure_name,
            "start_block_ids": list(proc.start_block_ids),
            "end_block_ids": list(proc.end_block_ids),
            "end_block_types": dict(proc.end_block_types),
            "branches": {key: list(values) for key, values in proc.branches.items()},
            "block_id_to_block_name": dict(proc.block_id_to_block_name),
        }

    def _merge_procedure_payload(self, payload: dict[str, Any], proc: Procedure) -> dict[str, Any]:
        merged = dict(payload)
        if not merged.get("procedure_name") and proc.procedure_name:
            merged["procedure_name"] = proc.procedure_name

        start_ids = set(merged.get("start_block_ids", []) or [])
        start_ids.update(proc.start_block_ids)
        merged["start_block_ids"] = sorted(start_ids)

        end_ids = set(merged.get("end_block_ids", []) or [])
        end_ids.update(proc.end_block_ids)
        merged["end_block_ids"] = sorted(end_ids)

        end_block_types = dict(merged.get("end_block_types", {}) or {})
        for block_id, end_type in proc.end_block_types.items():
            end_block_types[block_id] = merge_end_types(end_block_types.get(block_id), end_type)
        merged["end_block_types"] = end_block_types

        branches = {key: set(values) for key, values in (merged.get("branches", {}) or {}).items()}
        for source, targets in proc.branches.items():
            branches.setdefault(source, set()).update(targets)
        merged["branches"] = {key: sorted(values) for key, values in branches.items()}

        block_names = dict(merged.get("block_id_to_block_name", {}) or {})
        for block_id, name in proc.block_id_to_block_name.items():
            block_names.setdefault(block_id, name)
        merged["block_id_to_block_name"] = block_names

        return merged
