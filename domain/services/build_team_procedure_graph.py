from __future__ import annotations

from collections.abc import Mapping, Sequence
from hashlib import sha1
from typing import Any, Literal

from domain.models import MarkupDocument, Procedure, merge_end_types
from domain.services.shared_node_merge_rules import (
    ServiceNodeState,
    build_service_node_state,
    collect_merge_node_ids,
    collect_pair_merge_node_chunks,
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
GraphLevel = Literal["procedure", "service"]


class BuildTeamProcedureGraph:
    def build(
        self,
        documents: Sequence[MarkupDocument],
        merge_documents: Sequence[MarkupDocument] | None = None,
        merge_selected_markups: bool = True,
        merge_node_min_chain_size: int = 1,
        graph_level: GraphLevel = "procedure",
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
        source_proc_by_scoped: dict[str, str] = {}
        merge_services: dict[str, dict[str, dict[str, object]]] = {}
        merge_node_ids: set[str] = set()
        merge_chain_groups_by_proc: dict[str, tuple[tuple[str, ...], ...]] = {}
        merge_scope = merge_documents if merge_documents is not None else documents
        if merge_scope:
            merge_services, merge_service_keys = self._collect_merge_services(merge_scope)
            self._apply_service_colors(merge_services, merge_service_keys)
            merge_node_ids = self._resolve_merge_node_ids(
                merge_scope,
                merge_selected_markups=merge_selected_markups,
                merge_node_min_chain_size=merge_node_min_chain_size,
            )
            merge_chain_groups_by_proc = self._resolve_merge_chain_groups_by_proc(
                merge_scope,
                merge_selected_markups=merge_selected_markups,
                merge_node_min_chain_size=merge_node_min_chain_size,
            )

        if merge_selected_markups:
            (
                procedure_payloads,
                procedure_order,
                selected_graph,
                procedure_services,
                service_keys,
                source_proc_by_scoped,
            ) = self._collect_documents(
                documents,
                include_graph_nodes=False,
                merge_node_ids=merge_node_ids,
            )
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
                _,
            ) = self._collect_documents(
                merge_documents,
                include_graph_nodes=True,
                merge_node_ids=merge_node_ids,
            )
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
                if merge_scope and proc_id not in merge_node_ids:
                    is_intersection = False
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
                    "source_procedure_id": source_proc_by_scoped.get(proc_id, proc_id),
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
                    "source_procedure_id": source_proc_by_scoped.get(proc_id, proc_id),
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
                self._apply_merge_chain_metadata(
                    procedure_meta,
                    merge_chain_groups_by_proc,
                )
            else:
                self._apply_merge_metadata_for_scoped(
                    procedure_meta,
                    merge_services,
                    source_proc_by_scoped,
                    merge_node_ids=merge_node_ids,
                )
                self._apply_merge_chain_metadata_for_scoped(
                    procedure_meta,
                    merge_chain_groups_by_proc,
                    source_proc_by_scoped,
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

        merged_document = MarkupDocument(
            markup_type="procedure_graph",
            service_name=title,
            team_id=team_id,
            team_name=team_name,
            procedures=procedures,
            procedure_graph=procedure_graph,
            procedure_meta=procedure_meta,
        )
        if graph_level == "service":
            return self._build_service_graph_document(merged_document)
        return merged_document

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
                adjacent_to_merge = False
                for neighbor_proc_id in (*incoming, *outgoing):
                    merge_neighbor_id = (
                        source_proc_by_scoped.get(neighbor_proc_id, neighbor_proc_id)
                        if source_proc_by_scoped is not None
                        else neighbor_proc_id
                    )
                    if merge_neighbor_id in merge_node_ids:
                        adjacent_to_merge = True
                        break
                if adjacent_to_merge:
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
        merge_node_ids: set[str] | None = None,
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
        merge_lookup_ids = merge_node_ids if merge_node_ids is not None else set()
        source_counts: dict[str, int] = {}
        if merge_node_ids is not None:
            for document in documents:
                for proc_id in self._document_procedure_ids(document):
                    if proc_id in merge_lookup_ids:
                        continue
                    source_counts[proc_id] = source_counts.get(proc_id, 0) + 1
        doc_scope_index_by_service: dict[str, int] = {}

        for document in documents:
            team_label = self._resolve_team_label(document)
            service_label = self._resolve_service_label(document)
            service_key = self._service_key(team_label, service_label)
            doc_scope_token = ""
            if merge_node_ids is not None:
                next_index = doc_scope_index_by_service.get(service_key, 0) + 1
                doc_scope_index_by_service[service_key] = next_index
                service_hash = sha1(service_key.encode("utf-8")).hexdigest()[:8]
                doc_scope_token = f"{service_hash}{next_index}"
            service_payload: dict[str, object] = {
                "team_name": team_label,
                "service_name": service_label,
                "team_id": document.team_id,
                "finedog_unit_id": document.finedog_unit_id,
            }
            service_keys.add(service_key)
            scoped_id_map: dict[str, str] = {}
            if merge_node_ids is not None:
                for source_proc_id in self._document_procedure_ids(document):
                    if (
                        source_proc_id in merge_lookup_ids
                        or source_counts.get(source_proc_id, 0) <= 1
                    ):
                        scoped_id_map[source_proc_id] = source_proc_id
                        continue
                    scoped_id_map[source_proc_id] = f"{source_proc_id}::doc{doc_scope_token}"
            for source_proc_id in self._document_procedure_ids(document):
                scoped_id = scoped_id_map.get(source_proc_id, source_proc_id)
                source_proc_by_scoped[scoped_id] = source_proc_id

            for proc in document.procedures:
                proc_id = scoped_id_map.get(proc.procedure_id, proc.procedure_id)
                if proc_id not in procedure_payloads:
                    procedure_order.append(proc_id)
                    payload = self._procedure_payload(proc)
                    payload["procedure_id"] = proc_id
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
        _, _, _, procedure_services, service_keys, _ = self._collect_documents(
            documents,
            include_graph_nodes=True,
        )
        return procedure_services, service_keys

    def _apply_service_colors(
        self,
        procedure_services: dict[str, dict[str, dict[str, object]]],
        service_keys: set[str],
    ) -> dict[str, str]:
        service_colors = self._service_color_map(service_keys)
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
        merge_node_min_chain_size: int,
    ) -> set[str]:
        states = self._build_service_node_states(documents)
        return collect_merge_node_ids(
            states,
            merge_selected_markups=merge_selected_markups,
            merge_node_min_chain_size=merge_node_min_chain_size,
        )

    def _resolve_merge_chain_groups_by_proc(
        self,
        documents: Sequence[MarkupDocument],
        *,
        merge_selected_markups: bool,
        merge_node_min_chain_size: int,
    ) -> dict[str, tuple[tuple[str, ...], ...]]:
        if merge_node_min_chain_size <= 1:
            return {}
        states = self._build_service_node_states(documents)
        pair_chunks = collect_pair_merge_node_chunks(
            states,
            merge_selected_markups=merge_selected_markups,
            merge_node_min_chain_size=merge_node_min_chain_size,
        )
        groups_by_proc: dict[str, set[tuple[str, ...]]] = {}
        for chunks in pair_chunks.values():
            for chunk in chunks:
                if len(chunk) <= 1:
                    continue
                for proc_id in chunk:
                    groups_by_proc.setdefault(proc_id, set()).add(tuple(chunk))
        return {
            proc_id: tuple(sorted(groups, key=lambda group: "|".join(group).lower()))
            for proc_id, groups in groups_by_proc.items()
        }

    def _apply_merge_chain_metadata(
        self,
        procedure_meta: dict[str, dict[str, object]],
        merge_chain_groups_by_proc: Mapping[str, tuple[tuple[str, ...], ...]],
    ) -> None:
        for proc_id, groups in merge_chain_groups_by_proc.items():
            meta = procedure_meta.get(proc_id)
            if meta is None:
                continue
            if not groups:
                continue
            first_group = groups[0]
            group_id = "merge_chain::" + "|".join(first_group)
            meta["merge_chain_group_id"] = group_id
            meta["merge_chain_members"] = list(first_group)

    def _apply_merge_chain_metadata_for_scoped(
        self,
        procedure_meta: dict[str, dict[str, object]],
        merge_chain_groups_by_proc: Mapping[str, tuple[tuple[str, ...], ...]],
        source_proc_by_scoped: Mapping[str, str],
    ) -> None:
        scoped_by_source: dict[str, set[str]] = {}
        for scoped_proc_id, source_proc_id in source_proc_by_scoped.items():
            scoped_by_source.setdefault(source_proc_id, set()).add(scoped_proc_id)

        for scoped_proc_id, source_proc_id in source_proc_by_scoped.items():
            meta = procedure_meta.get(scoped_proc_id)
            if meta is None:
                continue
            groups = merge_chain_groups_by_proc.get(source_proc_id)
            if not groups:
                continue
            first_group = groups[0]
            scoped_members: list[str] = []
            source_prefix = f"{source_proc_id}::"
            scope_suffix = ""
            if scoped_proc_id.startswith(source_prefix):
                scope_suffix = scoped_proc_id[len(source_proc_id) :]
            for source_member in first_group:
                member_id = source_member
                if scope_suffix:
                    candidate_scoped = f"{source_member}{scope_suffix}"
                    if candidate_scoped in procedure_meta:
                        member_id = candidate_scoped
                if member_id == source_member:
                    source_scoped = scoped_by_source.get(source_member, set())
                    if member_id not in procedure_meta and source_scoped:
                        if len(source_scoped) == 1:
                            member_id = next(iter(source_scoped))
                scoped_members.append(member_id)

            unique_scoped_members: list[str] = []
            for member_id in scoped_members:
                if member_id in unique_scoped_members:
                    continue
                unique_scoped_members.append(member_id)
            if not unique_scoped_members:
                continue
            group_id = "merge_chain::" + "|".join(unique_scoped_members)
            meta["merge_chain_group_id"] = group_id
            meta["merge_chain_members"] = unique_scoped_members

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

    def _build_service_graph_document(self, document: MarkupDocument) -> MarkupDocument:
        procedure_meta = document.procedure_meta or {}
        procedure_lookup = {procedure.procedure_id: procedure for procedure in document.procedures}
        procedure_order = [procedure.procedure_id for procedure in document.procedures]
        order_index = {proc_id: idx for idx, proc_id in enumerate(procedure_order)}

        service_info_by_key: dict[str, dict[str, object]] = {}
        service_procs: dict[str, set[str]] = {}
        proc_service_keys: dict[str, list[str]] = {}

        for procedure in document.procedures:
            proc_id = procedure.procedure_id
            meta = procedure_meta.get(proc_id, {})
            entries = self._service_entries(meta)
            keys: list[str] = []
            for entry in entries:
                info = self._service_entry_info(entry)
                service_key = str(info.get("service_key") or "")
                if not service_key:
                    continue
                service_info_by_key.setdefault(service_key, info)
                service_procs.setdefault(service_key, set()).add(proc_id)
                keys.append(service_key)
            if not keys:
                info = self._service_entry_info({})
                service_key = str(info.get("service_key") or "")
                if service_key:
                    service_info_by_key.setdefault(service_key, info)
                    service_procs.setdefault(service_key, set()).add(proc_id)
                    keys.append(service_key)
            proc_service_keys[proc_id] = keys

        undirected: dict[str, set[str]] = {proc_id: set() for proc_id in procedure_order}
        for source_proc_id, target_proc_ids in document.procedure_graph.items():
            for target_proc_id in target_proc_ids:
                if source_proc_id == target_proc_id:
                    continue
                undirected.setdefault(source_proc_id, set()).add(target_proc_id)
                undirected.setdefault(target_proc_id, set()).add(source_proc_id)

        service_nodes: dict[str, dict[str, object]] = {}
        service_node_order: list[str] = []
        service_nodes_by_key: dict[str, list[str]] = {}
        service_nodes_by_procedure: dict[str, list[str]] = {
            proc_id: [] for proc_id in procedure_order
        }
        service_graph: dict[str, set[str]] = {}
        component_counts: dict[str, int] = {}
        component_stats: dict[str, dict[str, int]] = {}

        service_key_order: list[str] = []
        for proc_id in procedure_order:
            for key in proc_service_keys.get(proc_id, []):
                if key not in service_key_order:
                    service_key_order.append(key)

        for service_key in service_key_order:
            proc_ids = [
                proc_id
                for proc_id in procedure_order
                if proc_id in service_procs.get(service_key, set())
            ]
            if not proc_ids:
                continue
            components = self._service_components(proc_ids, undirected, order_index)
            info = service_info_by_key.get(service_key) or self._service_entry_info({})
            for component in components:
                component_ids = sorted(component, key=lambda proc_id: order_index.get(proc_id, 0))
                node_id = self._service_component_node_id(info, component_ids)
                payload = dict(info)
                payload["service_key"] = service_key
                service_nodes[node_id] = payload
                service_node_order.append(node_id)
                service_nodes_by_key.setdefault(service_key, []).append(node_id)
                service_graph.setdefault(node_id, set())
                component_counts[node_id] = len(component_ids)
                stats = {"start": 0, "branch": 0, "end": 0, "postpone": 0}
                for proc_id in component_ids:
                    proc = procedure_lookup.get(proc_id)
                    if proc is None:
                        continue
                    stats["start"] += len(proc.start_block_ids)
                    stats["branch"] += sum(len(targets) for targets in proc.branches.values())
                    stats["postpone"] += sum(
                        1
                        for block_id in proc.end_block_ids
                        if proc.end_block_types.get(block_id) == "postpone"
                    )
                    stats["end"] += sum(
                        1
                        for block_id in proc.end_block_ids
                        if proc.end_block_types.get(block_id) != "postpone"
                    )
                component_stats[node_id] = stats
                for proc_id in component_ids:
                    service_nodes_by_procedure.setdefault(proc_id, []).append(node_id)

        for source_proc_id, target_proc_ids in document.procedure_graph.items():
            source_services = service_nodes_by_procedure.get(source_proc_id, [])
            if not source_services:
                continue
            for target_proc_id in target_proc_ids:
                target_services = service_nodes_by_procedure.get(target_proc_id, [])
                if not target_services:
                    continue
                for source_service in source_services:
                    for target_service in target_services:
                        if source_service == target_service:
                            continue
                        service_graph.setdefault(source_service, set()).add(target_service)

        for service_ids in service_nodes_by_procedure.values():
            if len(service_ids) <= 1:
                continue
            for left_idx, left in enumerate(service_ids):
                for right in service_ids[left_idx + 1 :]:
                    if left == right:
                        continue
                    service_graph.setdefault(left, set()).add(right)
                    service_graph.setdefault(right, set()).add(left)

        service_key_set = set(service_nodes_by_key.keys())
        service_colors = self._service_color_map(service_key_set)
        service_graph_index: dict[str, int] = {}
        service_graph_total: dict[str, int] = {
            key: len(nodes) for key, nodes in service_nodes_by_key.items()
        }
        service_procedures: list[Procedure] = []
        service_meta: dict[str, dict[str, object]] = {}
        for service_node_id in service_node_order:
            payload = service_nodes[service_node_id]
            team_name = str(payload.get("team_name") or "Unknown team")
            service_name = str(payload.get("service_name") or "Unknown service")
            service_key = str(payload.get("service_key") or "")
            current_index = service_graph_index.get(service_key, 0) + 1
            service_graph_index[service_key] = current_index
            total_graphs = service_graph_total.get(service_key, 1)
            label = f"[{team_name}] {service_name}"
            if total_graphs > 1:
                label = f"{label} (Graph #{current_index})"
            color = service_colors.get(service_key, _SERVICE_COLORS[0])
            team_id = payload.get("team_id")
            finedog_unit_id = payload.get("finedog_unit_id")
            service_payload: dict[str, object] = {
                "team_name": team_name,
                "service_name": service_name,
                "team_id": team_id,
                "finedog_unit_id": finedog_unit_id,
                "service_color": color,
            }
            service_procedures.append(
                Procedure(
                    procedure_id=service_node_id,
                    procedure_name=label,
                    start_block_ids=[],
                    end_block_ids=[],
                    branches={},
                )
            )
            service_meta[service_node_id] = {
                "team_name": team_name,
                "service_name": service_name,
                "team_id": team_id,
                "finedog_unit_id": finedog_unit_id,
                "procedure_color": color,
                "is_intersection": False,
                "procedure_count": component_counts.get(service_node_id, 1),
                "graph_stats": component_stats.get(
                    service_node_id, {"start": 0, "branch": 0, "end": 0, "postpone": 0}
                ),
                "services": [service_payload],
            }

        service_graph_payload: dict[str, list[str]] = {}
        for service_node_id in service_node_order:
            targets = service_graph.get(service_node_id, set())
            service_graph_payload[service_node_id] = sorted(targets)

        title = document.service_name.strip() if document.service_name else ""
        graph_title = f"Services · {title}" if title else "Services"
        return MarkupDocument(
            markup_type="service_graph",
            service_name=graph_title,
            team_id=document.team_id,
            team_name=document.team_name,
            procedures=service_procedures,
            procedure_graph=service_graph_payload,
            procedure_meta=service_meta,
        )

    def _service_entries(self, meta: dict[str, object]) -> list[dict[str, object]]:
        services = meta.get("services")
        if isinstance(services, list):
            entries: list[dict[str, object]] = []
            for item in services:
                if isinstance(item, dict):
                    entries.append(dict(item))
            if entries:
                return entries
        return [dict(meta)]

    def _service_entry_info(self, entry: dict[str, object]) -> dict[str, object]:
        team_name = str(entry.get("team_name") or "Unknown team").strip() or "Unknown team"
        raw_team_id = entry.get("team_id")
        team_id = raw_team_id if isinstance(raw_team_id, str | int) else None
        service_name = (
            str(entry.get("service_name") or "Unknown service").strip() or "Unknown service"
        )
        unit_raw = entry.get("finedog_unit_id")
        finedog_unit_id = (
            str(unit_raw).strip() if isinstance(unit_raw, str) and unit_raw.strip() else None
        )
        service_key = self._service_key(team_name, service_name)
        return {
            "team_name": team_name,
            "team_id": team_id,
            "service_name": service_name,
            "finedog_unit_id": finedog_unit_id,
            "service_key": service_key,
        }

    def _service_component_node_id(self, info: dict[str, object], proc_ids: list[str]) -> str:
        team_token = (
            str(info.get("team_id")).strip()
            if info.get("team_id") is not None
            else str(info.get("team_name") or "unknown")
        )
        service_token = str(info.get("finedog_unit_id") or "") or str(
            info.get("service_name") or "unknown"
        )
        component_token = self._slug_token("-".join(proc_ids))
        return (
            f"service::{self._slug_token(team_token)}::"
            f"{self._slug_token(service_token)}::graph::{component_token}"
        )

    def _service_components(
        self,
        proc_ids: list[str],
        adjacency: dict[str, set[str]],
        order_index: dict[str, int],
    ) -> list[list[str]]:
        remaining = set(proc_ids)
        components: list[list[str]] = []
        while remaining:
            start = min(remaining, key=lambda proc_id: order_index.get(proc_id, 0))
            stack = [start]
            component: list[str] = []
            remaining.remove(start)
            while stack:
                current = stack.pop()
                component.append(current)
                for neighbor in adjacency.get(current, set()):
                    if neighbor in remaining:
                        remaining.remove(neighbor)
                        stack.append(neighbor)
            components.append(component)
        components.sort(key=lambda comp: min(order_index.get(proc_id, 0) for proc_id in comp))
        return components

    def _slug_token(self, value: str) -> str:
        chars: list[str] = []
        for char in value.lower():
            if char.isalnum():
                chars.append(char)
                continue
            if chars and chars[-1] == "_":
                continue
            chars.append("_")
        slug = "".join(chars).strip("_")
        return slug if slug else "unknown"

    def _service_color_map(self, service_keys: set[str]) -> dict[str, str]:
        service_key_list = sorted(service_keys, key=lambda value: value.lower())
        return {
            key: _SERVICE_COLORS[idx % len(_SERVICE_COLORS)]
            for idx, key in enumerate(service_key_list)
        }

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
