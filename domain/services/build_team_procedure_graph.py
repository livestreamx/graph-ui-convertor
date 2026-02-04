from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from domain.models import MarkupDocument, Procedure, merge_end_types
from domain.services.shared_node_merge_rules import (
    ServiceNodeState,
    build_service_node_state,
    collect_merge_node_ids,
)

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
        merge_selected_markups: bool = True,
    ) -> MarkupDocument:
        procedures: list[Procedure] = []
        procedure_meta: dict[str, dict[str, object]] = {}
        team_labels: set[str] = set()
        team_ids: set[str | int] = set()
        team_names: set[str] = set()
        procedure_payloads: dict[str, dict[str, Any]]
        procedure_order: list[str]
        procedure_graph: dict[str, list[str]]
        procedure_services: dict[str, dict[str, dict[str, object]]]
        service_keys: set[str]
        source_proc_by_scoped: dict[str, str] | None = None
        merge_services: dict[str, dict[str, dict[str, object]]] = {}
        merge_node_ids: set[str] = set()
        if merge_selected_markups:
            (
                procedure_payloads,
                procedure_order,
                selected_graph,
                procedure_services,
                service_keys,
            ) = self._collect_documents(documents, include_graph_nodes=False)
            procedure_graph = selected_graph
        else:
            (
                procedure_payloads,
                procedure_order,
                procedure_graph,
                procedure_services,
                service_keys,
                source_proc_by_scoped,
            ) = self._collect_documents_as_is(documents, include_graph_nodes=False)
        for document in documents:
            team_label = self._resolve_team_label(document)
            if team_label:
                team_labels.add(team_label)
            if document.team_id is not None:
                team_ids.add(document.team_id)
            if document.team_name:
                team_names.add(str(document.team_name))

        service_colors = self._apply_service_colors(procedure_services, service_keys)

        if merge_documents is not None and merge_selected_markups:
            (
                merge_payloads,
                merge_order,
                merge_graph,
                merge_services,
                merge_service_keys,
            ) = self._collect_documents(merge_documents, include_graph_nodes=True)
            self._apply_service_colors(merge_services, merge_service_keys)

            visible_proc_ids = set(procedure_services.keys())
            if visible_proc_ids:
                procedure_graph = self._filter_procedure_graph(merge_graph, visible_proc_ids)
                for proc_id in merge_order:
                    if proc_id in visible_proc_ids and proc_id not in procedure_payloads:
                        payload = merge_payloads.get(proc_id)
                        if payload is None:
                            continue
                        procedure_payloads[proc_id] = dict(payload)
                        procedure_order.append(proc_id)

        merge_scope = merge_documents if merge_documents is not None else documents
        if merge_scope:
            merge_services, merge_service_keys = self._collect_merge_services(merge_scope)
            self._apply_service_colors(merge_services, merge_service_keys)
            merge_node_ids = self._resolve_merge_node_ids(
                merge_scope,
                merge_selected_markups=merge_selected_markups,
            )

        removed_proc_ids, procedure_graph = self._drop_intermediate_procedures(
            procedure_payloads,
            procedure_order,
            procedure_graph,
            merge_node_ids=merge_node_ids,
            source_proc_by_scoped=source_proc_by_scoped,
        )
        if removed_proc_ids:
            procedure_order = [
                proc_id for proc_id in procedure_order if proc_id not in removed_proc_ids
            ]
            for proc_id in removed_proc_ids:
                procedure_payloads.pop(proc_id, None)
                procedure_services.pop(proc_id, None)

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

        if merge_scope:
            if merge_selected_markups:
                self._apply_merge_metadata(
                    procedure_meta,
                    merge_services,
                    merge_node_ids=merge_node_ids,
                )
            elif source_proc_by_scoped is not None:
                self._apply_merge_metadata_for_scoped(
                    procedure_meta,
                    merge_services,
                    source_proc_by_scoped,
                    merge_node_ids=merge_node_ids,
                )

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

    def _drop_intermediate_procedures(
        self,
        procedure_payloads: dict[str, dict[str, Any]],
        procedure_order: Sequence[str],
        procedure_graph: dict[str, list[str]],
        *,
        merge_node_ids: set[str],
        source_proc_by_scoped: dict[str, str] | None = None,
    ) -> tuple[set[str], dict[str, list[str]]]:
        adjacency: dict[str, list[str]] = {
            source: list(dict.fromkeys(targets)) for source, targets in procedure_graph.items()
        }
        for proc_id in procedure_payloads:
            adjacency.setdefault(proc_id, [])
        for targets in list(adjacency.values()):
            for target in targets:
                adjacency.setdefault(target, [])

        removed: set[str] = set()
        while True:
            incoming_by_proc: dict[str, set[str]] = {proc_id: set() for proc_id in adjacency}
            for source, targets in adjacency.items():
                for target in targets:
                    incoming_by_proc.setdefault(target, set()).add(source)

            candidate: tuple[str, str, str] | None = None
            for proc_id in procedure_order:
                if proc_id in removed:
                    continue
                if proc_id not in procedure_payloads:
                    continue
                merge_lookup_id = (
                    source_proc_by_scoped.get(proc_id, proc_id)
                    if source_proc_by_scoped is not None
                    else proc_id
                )
                if merge_lookup_id in merge_node_ids:
                    continue
                payload = procedure_payloads.get(proc_id, {})
                if self._has_start_or_end_blocks(payload):
                    continue
                incoming = incoming_by_proc.get(proc_id, set())
                outgoing = adjacency.get(proc_id, [])
                if len(incoming) != 1 or len(outgoing) != 1:
                    continue
                parent_id = next(iter(incoming))
                child_id = outgoing[0]
                if parent_id == proc_id or child_id == proc_id or parent_id == child_id:
                    continue
                candidate = (proc_id, parent_id, child_id)
                break

            if candidate is None:
                break

            proc_id, parent_id, child_id = candidate
            removed.add(proc_id)

            parent_targets = [
                target for target in adjacency.get(parent_id, []) if target != proc_id
            ]
            if child_id not in parent_targets:
                parent_targets.append(child_id)
            adjacency[parent_id] = parent_targets

            adjacency.pop(proc_id, None)
            for source, targets in list(adjacency.items()):
                if source == parent_id:
                    continue
                filtered_targets = [target for target in targets if target != proc_id]
                if len(filtered_targets) != len(targets):
                    adjacency[source] = filtered_targets

        filtered_graph: dict[str, list[str]] = {}
        for source, targets in adjacency.items():
            if source in removed:
                continue
            filtered_targets = [target for target in targets if target not in removed]
            if not filtered_targets and source not in procedure_payloads:
                continue
            filtered_graph[source] = filtered_targets
        return removed, filtered_graph

    def _has_start_or_end_blocks(self, payload: dict[str, Any]) -> bool:
        if payload.get("start_block_ids"):
            return True
        if payload.get("end_block_ids"):
            return True
        return bool(payload.get("end_block_types"))

    def _collect_documents(
        self,
        documents: Sequence[MarkupDocument],
        *,
        include_graph_nodes: bool,
    ) -> tuple[
        dict[str, dict[str, Any]],
        list[str],
        dict[str, list[str]],
        dict[str, dict[str, dict[str, object]]],
        set[str],
    ]:
        procedure_payloads: dict[str, dict[str, Any]] = {}
        procedure_order: list[str] = []
        procedure_graph: dict[str, list[str]] = {}
        procedure_services: dict[str, dict[str, dict[str, object]]] = {}
        service_keys: set[str] = set()

        for document in documents:
            team_label = self._resolve_team_label(document)
            service_label = self._resolve_service_label(document)
            service_key = self._service_key(team_label, service_label)
            service_payload: dict[str, object] = {
                "team_name": team_label,
                "service_name": service_label,
                "team_id": document.team_id,
                "finedog_unit_id": document.finedog_unit_id,
            }
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
                procedure_services.setdefault(proc_id, {})[service_key] = dict(service_payload)

            for parent, children in document.procedure_graph.items():
                procedure_graph.setdefault(parent, [])
                if include_graph_nodes:
                    procedure_services.setdefault(parent, {})[service_key] = dict(service_payload)
                for child in children:
                    if child not in procedure_graph[parent]:
                        procedure_graph[parent].append(child)
                    if include_graph_nodes:
                        procedure_services.setdefault(child, {})[service_key] = dict(
                            service_payload
                        )

        return (
            procedure_payloads,
            procedure_order,
            procedure_graph,
            procedure_services,
            service_keys,
        )

    def _collect_documents_as_is(
        self,
        documents: Sequence[MarkupDocument],
        *,
        include_graph_nodes: bool,
    ) -> tuple[
        dict[str, dict[str, Any]],
        list[str],
        dict[str, list[str]],
        dict[str, dict[str, dict[str, object]]],
        set[str],
        dict[str, str],
    ]:
        procedure_payloads: dict[str, dict[str, Any]] = {}
        procedure_order: list[str] = []
        procedure_graph: dict[str, list[str]] = {}
        procedure_services: dict[str, dict[str, dict[str, object]]] = {}
        service_keys: set[str] = set()
        source_proc_by_scoped: dict[str, str] = {}

        source_counts: dict[str, int] = {}
        for document in documents:
            for proc_id in self._document_procedure_ids(document):
                source_counts[proc_id] = source_counts.get(proc_id, 0) + 1

        for doc_idx, document in enumerate(documents):
            scoped_id_map: dict[str, str] = {}
            for proc_id in self._document_procedure_ids(document):
                if source_counts.get(proc_id, 0) > 1:
                    scoped_id = f"{proc_id}::doc{doc_idx + 1}"
                else:
                    scoped_id = proc_id
                scoped_id_map[proc_id] = scoped_id
                source_proc_by_scoped[scoped_id] = proc_id

            team_label = self._resolve_team_label(document)
            service_label = self._resolve_service_label(document)
            service_key = self._service_key(team_label, service_label)
            service_payload: dict[str, object] = {
                "team_name": team_label,
                "service_name": service_label,
                "team_id": document.team_id,
                "finedog_unit_id": document.finedog_unit_id,
            }
            service_keys.add(service_key)

            for proc in document.procedures:
                proc_id = scoped_id_map.get(proc.procedure_id, proc.procedure_id)
                payload = self._procedure_payload(proc)
                payload["procedure_id"] = proc_id
                if proc_id not in procedure_payloads:
                    procedure_order.append(proc_id)
                    procedure_payloads[proc_id] = payload
                else:
                    procedure_payloads[proc_id] = self._merge_procedure_payload(
                        procedure_payloads[proc_id], proc
                    )
                    procedure_payloads[proc_id]["procedure_id"] = proc_id
                procedure_services.setdefault(proc_id, {})[service_key] = dict(service_payload)

            for parent, children in document.procedure_graph.items():
                parent_id = scoped_id_map.get(parent, parent)
                procedure_graph.setdefault(parent_id, [])
                if include_graph_nodes:
                    procedure_services.setdefault(parent_id, {})[service_key] = dict(
                        service_payload
                    )
                for child in children:
                    child_id = scoped_id_map.get(child, child)
                    if child_id not in procedure_graph[parent_id]:
                        procedure_graph[parent_id].append(child_id)
                    if include_graph_nodes:
                        procedure_services.setdefault(child_id, {})[service_key] = dict(
                            service_payload
                        )

        return (
            procedure_payloads,
            procedure_order,
            procedure_graph,
            procedure_services,
            service_keys,
            source_proc_by_scoped,
        )

    def _filter_procedure_graph(
        self,
        procedure_graph: dict[str, list[str]],
        visible_proc_ids: set[str],
    ) -> dict[str, list[str]]:
        filtered: dict[str, list[str]] = {}
        for parent, children in procedure_graph.items():
            if parent not in visible_proc_ids:
                continue
            filtered[parent] = [child for child in children if child in visible_proc_ids]
        return filtered

    def _collect_merge_services(
        self,
        documents: Sequence[MarkupDocument],
    ) -> tuple[dict[str, dict[str, dict[str, object]]], set[str]]:
        _, _, _, procedure_services, service_keys = self._collect_documents(
            documents,
            include_graph_nodes=True,
        )
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
        *,
        merge_node_ids: set[str],
    ) -> None:
        for proc_id, service_map in merge_services.items():
            if proc_id not in procedure_meta:
                continue
            if proc_id not in merge_node_ids:
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

    def _apply_merge_metadata_for_scoped(
        self,
        procedure_meta: dict[str, dict[str, object]],
        merge_services: dict[str, dict[str, dict[str, object]]],
        source_proc_by_scoped: dict[str, str],
        *,
        merge_node_ids: set[str],
    ) -> None:
        for scoped_proc_id, source_proc_id in source_proc_by_scoped.items():
            if scoped_proc_id not in procedure_meta:
                continue
            if source_proc_id not in merge_node_ids:
                continue
            service_map = merge_services.get(source_proc_id)
            if not service_map:
                continue
            services = sorted(
                service_map.values(),
                key=lambda item: (
                    str(item.get("team_name", "") or "").lower(),
                    str(item.get("service_name", "") or "").lower(),
                ),
            )
            if services:
                procedure_meta[scoped_proc_id]["merge_services"] = services
            merge_keys = set(service_map.keys())
            if len(merge_keys) > 1 or procedure_meta.get(scoped_proc_id, {}).get("is_intersection"):
                procedure_meta[scoped_proc_id]["is_intersection"] = True
                procedure_meta[scoped_proc_id]["procedure_color"] = _INTERSECTION_COLOR

    def _resolve_merge_node_ids(
        self,
        documents: Sequence[MarkupDocument],
        *,
        merge_selected_markups: bool,
    ) -> set[str]:
        states = self._build_service_node_states(documents)
        return collect_merge_node_ids(
            states,
            merge_selected_markups=merge_selected_markups,
        )

    def _build_service_node_states(
        self,
        documents: Sequence[MarkupDocument],
    ) -> dict[str, ServiceNodeState]:
        procedure_ids_by_service: dict[str, set[str]] = {}
        adjacency_by_service: dict[str, dict[str, set[str]]] = {}
        for document in documents:
            team_label = self._resolve_team_label(document)
            service_label = self._resolve_service_label(document)
            service_key = self._service_key(team_label, service_label)
            procedure_ids = procedure_ids_by_service.setdefault(service_key, set())
            procedure_ids.update(self._document_procedure_ids(document))
            adjacency = adjacency_by_service.setdefault(service_key, {})
            for source, targets in document.procedure_graph.items():
                adjacency.setdefault(source, set()).update(targets)
                for target in targets:
                    adjacency.setdefault(target, set())

        states: dict[str, ServiceNodeState] = {}
        for service_key, procedure_ids in procedure_ids_by_service.items():
            adjacency = adjacency_by_service.get(service_key, {})
            states[service_key] = build_service_node_state(
                service_key,
                procedure_ids,
                adjacency,
            )
        return states

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

    def _document_procedure_ids(self, document: MarkupDocument) -> list[str]:
        ordered: list[str] = []
        seen: set[str] = set()
        for proc in document.procedures:
            proc_id = proc.procedure_id
            if proc_id in seen:
                continue
            seen.add(proc_id)
            ordered.append(proc_id)
        for parent, children in document.procedure_graph.items():
            if parent not in seen:
                seen.add(parent)
                ordered.append(parent)
            for child in children:
                if child in seen:
                    continue
                seen.add(child)
                ordered.append(child)
        return ordered

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
