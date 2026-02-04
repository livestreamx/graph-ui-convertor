from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from domain.models import (
    END_TYPE_COLORS,
    END_TYPE_DEFAULT,
    INITIAL_BLOCK_COLOR,
    MarkupDocument,
    merge_end_types,
)
from domain.services.build_team_procedure_graph import BuildTeamProcedureGraph
from domain.services.graph_metrics import compute_graph_metrics
from domain.services.shared_node_merge_rules import (
    ServiceNodeState,
    build_service_node_state,
    collect_pair_merge_nodes,
)


@dataclass(frozen=True)
class MarkupTypeStat:
    markup_type: str
    count: int
    item_labels: tuple[str, ...] = ()


@dataclass(frozen=True)
class TeamIntersectionStat:
    team_name: str
    count: int
    external_depends_on_selected_count: int = 0
    selected_depends_on_external_count: int = 0
    services: tuple[ServiceIntersectionStat, ...] = ()


@dataclass(frozen=True)
class ServiceIntersectionStat:
    service_name: str
    count: int
    external_depends_on_selected_count: int = 0
    selected_depends_on_external_count: int = 0


@dataclass(frozen=True)
class ProcedureLinkStat:
    procedure_id: str
    procedure_name: str | None
    graph_count: int
    usage_in_other_graphs: int
    incoming_edges: int
    outgoing_edges: int
    graph_labels: tuple[str, ...] = ()
    graph_usage_stats: tuple[ProcedureGraphUsageStat, ...] = ()


@dataclass(frozen=True)
class ProcedureGraphUsageStat:
    graph_label: str
    is_cross_entity: bool
    incoming_edges: int
    outgoing_edges: int


@dataclass(frozen=True)
class GraphGroupStat:
    label: str
    graph_count: int
    components: tuple[GraphComponentStat, ...] = ()


@dataclass(frozen=True)
class GraphComponentStat:
    graph_label: str
    merge_nodes: tuple[GraphMergeNodeStat, ...] = ()


@dataclass(frozen=True)
class GraphMergeNodeStat:
    procedure_id: str
    procedure_name: str | None
    entities: tuple[str, ...] = ()


@dataclass(frozen=True)
class ServiceLoadStat:
    team_name: str
    service_name: str
    cycle_count: int
    block_count: int
    in_team_merge_nodes: int
    procedure_count: int
    procedure_ids: tuple[str, ...] = ()
    merge_node_ids: tuple[str, ...] = ()
    weak_component_count: int = 0
    cycle_path: tuple[str, ...] = ()
    procedure_usage_stats: tuple[ServiceProcedureUsageStat, ...] = ()


@dataclass(frozen=True)
class ServiceProcedureUsageStat:
    procedure_id: str
    procedure_name: str | None
    in_team_merge_hits: int
    cycle_hits: int
    linked_procedure_count: int
    block_count: int
    start_block_count: int = 0
    end_block_count: int = 0
    graph_label: str | None = None
    block_type_stats: tuple[ProcedureBlockTypeStat, ...] = ()


@dataclass(frozen=True)
class ProcedureBlockTypeStat:
    type_id: str
    label: str
    count: int
    color: str


@dataclass(frozen=True)
class CrossTeamGraphDashboard:
    markup_type_counts: tuple[MarkupTypeStat, ...]
    unique_graph_count: int
    unique_graphs: tuple[str, ...]
    graph_groups: tuple[GraphGroupStat, ...]
    bot_graph_count: int
    bot_graphs: tuple[str, ...]
    multi_graph_count: int
    multi_graphs: tuple[str, ...]
    bot_procedure_count: int
    bot_procedures: tuple[str, ...]
    multi_procedure_count: int
    multi_procedures: tuple[str, ...]
    employee_procedure_count: int
    employee_procedures: tuple[str, ...]
    unique_procedure_count: int
    total_procedure_count: int
    internal_intersection_markup_count: int
    internal_intersection_entities: tuple[str, ...]
    external_intersection_markup_count: int
    external_intersection_entities: tuple[str, ...]
    external_team_intersections: tuple[TeamIntersectionStat, ...]
    split_service_count: int
    split_entities: tuple[str, ...]
    target_service_count: int
    target_entities: tuple[str, ...]
    total_service_count: int
    linking_procedures: tuple[ProcedureLinkStat, ...]
    overloaded_services: tuple[ServiceLoadStat, ...]


@dataclass
class _GraphAggregate:
    key: str
    team_id: str
    team_name: str
    service_name: str
    procedure_ids: set[str] = field(default_factory=set)
    procedure_order: list[str] = field(default_factory=list)
    _procedure_order_index: dict[str, int] = field(default_factory=dict)
    adjacency: dict[str, set[str]] = field(default_factory=dict)
    block_ids_by_procedure: dict[str, set[str]] = field(default_factory=dict)
    start_block_ids_by_procedure: dict[str, set[str]] = field(default_factory=dict)
    end_block_types_by_procedure: dict[str, dict[str, str]] = field(default_factory=dict)

    def add_document(self, document: MarkupDocument) -> None:
        for procedure in document.procedures:
            self._register_procedure_id(procedure.procedure_id)
        for source, targets in document.procedure_graph.items():
            self._register_procedure_id(source)
            for target in targets:
                self._register_procedure_id(target)
        for proc_id in _document_procedure_ids(document):
            self._register_procedure_id(proc_id)
            self.adjacency.setdefault(proc_id, set())
        for source, targets in document.procedure_graph.items():
            self.adjacency.setdefault(source, set())
            for target in targets:
                self.adjacency[source].add(target)
                self.adjacency.setdefault(target, set())
        for procedure in document.procedures:
            start_block_ids = self.start_block_ids_by_procedure.setdefault(
                procedure.procedure_id,
                set(),
            )
            start_block_ids.update(procedure.start_block_ids)
            end_block_types = self.end_block_types_by_procedure.setdefault(
                procedure.procedure_id,
                {},
            )
            for block_id in procedure.end_block_ids:
                end_type = procedure.end_block_types.get(block_id, END_TYPE_DEFAULT)
                end_block_types[block_id] = merge_end_types(end_block_types.get(block_id), end_type)
            block_ids = self.block_ids_by_procedure.setdefault(procedure.procedure_id, set())
            block_ids.update(procedure.block_ids())

    def block_count(self) -> int:
        return sum(len(block_ids) for block_ids in self.block_ids_by_procedure.values())

    def to_adjacency(self, nodes: set[str] | None = None) -> dict[str, list[str]]:
        scoped_nodes = set(nodes) if nodes is not None else set(self.procedure_ids)
        scoped_adjacency = self._scoped_adjacency(scoped_nodes)
        adjacency: dict[str, list[str]] = {}
        for node in sorted(scoped_nodes):
            adjacency[node] = sorted(scoped_adjacency.get(node, set()))
        return adjacency

    def visible_procedure_ids(self) -> set[str]:
        return {proc_id for proc_id, block_ids in self.block_ids_by_procedure.items() if block_ids}

    def ordered_procedure_ids(self, nodes: set[str] | None = None) -> tuple[str, ...]:
        scoped_nodes = set(nodes) if nodes is not None else set(self.procedure_ids)
        if not scoped_nodes:
            return ()

        order_fallback = len(self.procedure_order)

        def order_index(proc_id: str) -> int:
            return self._procedure_order_index.get(proc_id, order_fallback)

        def has_start_blocks(proc_id: str) -> bool:
            return bool(self.start_block_ids_by_procedure.get(proc_id, set()))

        def queue_key(proc_id: str) -> tuple[int, int, str]:
            return (
                0 if has_start_blocks(proc_id) else 1,
                order_index(proc_id),
                proc_id.lower(),
            )

        adjacency = self._scoped_adjacency(scoped_nodes)
        indegree: dict[str, int] = {node: 0 for node in scoped_nodes}
        for targets in adjacency.values():
            for target in targets:
                indegree[target] += 1

        undirected: dict[str, set[str]] = {node: set() for node in scoped_nodes}
        for source, targets in adjacency.items():
            for target in targets:
                undirected[source].add(target)
                undirected[target].add(source)

        visited: set[str] = set()
        components: list[set[str]] = []
        for proc_id in sorted(
            scoped_nodes,
            key=lambda proc_id: (order_index(proc_id), proc_id.lower()),
        ):
            if proc_id in visited:
                continue
            stack = [proc_id]
            component: set[str] = set()
            while stack:
                current = stack.pop()
                if current in visited:
                    continue
                visited.add(current)
                component.add(current)
                stack.extend(undirected.get(current, set()) - visited)
            components.append(component)

        components.sort(
            key=lambda component: min(
                (queue_key(proc_id) for proc_id in component if indegree.get(proc_id, 0) == 0),
                default=min(queue_key(proc_id) for proc_id in component),
            )
        )

        ordered: list[str] = []
        for component in components:
            component_indegree = {proc_id: indegree[proc_id] for proc_id in component}
            queue = sorted(
                (proc_id for proc_id in component if component_indegree[proc_id] == 0),
                key=queue_key,
            )
            component_ordered: list[str] = []
            while queue:
                node = queue.pop(0)
                component_ordered.append(node)
                for target in sorted(adjacency.get(node, ()), key=queue_key):
                    if target not in component_indegree:
                        continue
                    component_indegree[target] -= 1
                    if component_indegree[target] == 0:
                        queue.append(target)
                queue.sort(key=queue_key)

            if len(component_ordered) < len(component):
                remaining = sorted(
                    (proc_id for proc_id in component if proc_id not in component_ordered),
                    key=queue_key,
                )
                component_ordered.extend(remaining)
            ordered.extend(component_ordered)

        return tuple(ordered)

    def _scoped_adjacency(self, scoped_nodes: set[str]) -> dict[str, set[str]]:
        adjacency: dict[str, set[str]] = {node: set() for node in scoped_nodes}
        if not scoped_nodes:
            return adjacency

        hidden_nodes = self.procedure_ids - scoped_nodes
        for source in scoped_nodes:
            direct_targets = self.adjacency.get(source, set())
            for target in direct_targets:
                if target in scoped_nodes and target != source:
                    adjacency[source].add(target)

            hidden_stack = [target for target in direct_targets if target in hidden_nodes]
            visited_hidden: set[str] = set()
            while hidden_stack:
                hidden_node = hidden_stack.pop()
                if hidden_node in visited_hidden:
                    continue
                visited_hidden.add(hidden_node)
                for target in self.adjacency.get(hidden_node, set()):
                    if target == source:
                        continue
                    if target in scoped_nodes:
                        adjacency[source].add(target)
                        continue
                    if target in hidden_nodes and target not in visited_hidden:
                        hidden_stack.append(target)
        return adjacency

    def _register_procedure_id(self, proc_id: str) -> None:
        if proc_id in self.procedure_ids:
            return
        self.procedure_ids.add(proc_id)
        self._procedure_order_index[proc_id] = len(self.procedure_order)
        self.procedure_order.append(proc_id)


@dataclass(frozen=True)
class _ServiceDocumentSnapshot:
    service_key: str
    team_id: str
    team_name: str
    procedure_ids: frozenset[str]


class BuildCrossTeamGraphDashboard:
    def build(
        self,
        selected_documents: Sequence[MarkupDocument],
        all_documents: Sequence[MarkupDocument],
        selected_team_ids: Sequence[str],
        merge_selected_markups: bool = False,
        merge_documents: Sequence[MarkupDocument] | None = None,
        top_limit: int = 10,
    ) -> CrossTeamGraphDashboard:
        selected_graphs = self._collect_graphs(selected_documents)
        selected_service_docs = [doc for doc in selected_documents if _is_service_markup(doc)]
        all_service_docs = [doc for doc in all_documents if _is_service_markup(doc)]
        selected_services = self._collect_graphs(selected_service_docs)
        all_services = self._collect_graphs(all_service_docs)
        procedure_names = self._collect_procedure_names(selected_documents)

        selected_team_set = {
            team_id for team_id in (str(value).strip() for value in selected_team_ids) if team_id
        }
        (
            flow_document,
            unique_graph_labels,
            graph_keys_by_procedure_id,
            graph_groups,
        ) = self._extract_graph_view(
            selected_documents,
            merge_selected_markups=merge_selected_markups,
            merge_documents=merge_documents,
        )
        markup_type_counts = tuple(self._build_markup_type_counts(selected_documents))
        total_procedure_count = sum(len(document.procedures) for document in selected_documents)
        unique_procedure_ids = {
            procedure.procedure_id
            for document in selected_documents
            for procedure in document.procedures
        }
        bot_procedures = sorted(
            {
                procedure.procedure_id
                for document in selected_documents
                for procedure in document.procedures
                if _has_substring(procedure.procedure_id, "bot")
            },
            key=str.lower,
        )
        multi_procedures = sorted(
            {
                procedure.procedure_id
                for document in selected_documents
                for procedure in document.procedures
                if _has_substring(procedure.procedure_id, "multi")
            },
            key=str.lower,
        )
        employee_procedures = sorted(
            {
                procedure.procedure_id
                for document in selected_documents
                for procedure in document.procedures
                if not _has_substring(procedure.procedure_id, "bot")
                and not _has_substring(procedure.procedure_id, "multi")
            },
            key=str.lower,
        )
        bot_procedure_count = sum(
            1
            for document in selected_documents
            for procedure in document.procedures
            if _has_substring(procedure.procedure_id, "bot")
        )
        multi_procedure_count = sum(
            1
            for document in selected_documents
            for procedure in document.procedures
            if _has_substring(procedure.procedure_id, "multi")
        )
        employee_procedure_count = sum(
            1
            for document in selected_documents
            for procedure in document.procedures
            if not _has_substring(procedure.procedure_id, "bot")
            and not _has_substring(procedure.procedure_id, "multi")
        )

        bot_graph_labels = sorted(
            {
                graph_label
                for proc_id, graph_keys in graph_keys_by_procedure_id.items()
                if _has_substring(proc_id, "bot")
                for graph_label in graph_keys
            },
            key=str.lower,
        )
        multi_graph_labels = sorted(
            {
                graph_label
                for proc_id, graph_keys in graph_keys_by_procedure_id.items()
                if _has_substring(proc_id, "multi")
                for graph_label in graph_keys
            },
            key=str.lower,
        )

        selected_snapshots = self._collect_service_snapshots(selected_service_docs)
        all_service_states = self._build_service_node_states(all_services)
        pair_merge_nodes = collect_pair_merge_nodes(
            all_service_states,
            merge_selected_markups=merge_selected_markups,
        )
        pair_merge_counts = self._build_pair_merge_counts(pair_merge_nodes)
        selected_service_keys = set(selected_services.keys())

        internal_intersection_entities: set[str] = set()
        external_intersection_entities: set[str] = set()
        external_team_counter: Counter[str] = Counter()
        external_team_external_depends_counter: Counter[str] = Counter()
        external_team_selected_depends_counter: Counter[str] = Counter()
        external_team_services: dict[str, Counter[str]] = {}
        external_team_services_external_depends: dict[str, Counter[str]] = {}
        external_team_services_selected_depends: dict[str, Counter[str]] = {}
        for snapshot in selected_snapshots:
            has_internal = False
            has_external = False
            for service_key in pair_merge_counts.get(snapshot.service_key, {}):
                service = all_services.get(service_key)
                if service is None:
                    continue
                is_selected_service = (
                    service_key in selected_service_keys and service.team_id in selected_team_set
                )
                if is_selected_service:
                    has_internal = True
                    continue
                if service.team_id in selected_team_set:
                    continue
                shared_proc_ids = pair_merge_nodes.get(
                    _sorted_pair(snapshot.service_key, service_key),
                    set(),
                )
                if not shared_proc_ids:
                    continue
                selected_service = all_services.get(snapshot.service_key)
                if selected_service is None:
                    continue
                external_depends_count, selected_depends_count = (
                    self._split_external_overlap_dependency_counts(
                        shared_proc_ids,
                        selected_service=selected_service,
                        external_service=service,
                        selected_state=all_service_states.get(snapshot.service_key),
                        external_state=all_service_states.get(service_key),
                    )
                )
                merge_count = external_depends_count + selected_depends_count
                if merge_count <= 0:
                    continue
                has_external = True
                external_team_counter[service.team_name] += merge_count
                external_team_external_depends_counter[service.team_name] += external_depends_count
                external_team_selected_depends_counter[service.team_name] += selected_depends_count
                external_team_services.setdefault(service.team_name, Counter())[
                    service.service_name
                ] += merge_count
                external_team_services_external_depends.setdefault(
                    service.team_name,
                    Counter(),
                )[service.service_name] += external_depends_count
                external_team_services_selected_depends.setdefault(
                    service.team_name,
                    Counter(),
                )[service.service_name] += selected_depends_count
            service = all_services.get(snapshot.service_key)
            entity_label = _entity_label(
                snapshot.team_name,
                service.service_name if service is not None else "Unknown entity",
            )
            if has_internal:
                internal_intersection_entities.add(entity_label)
            if has_external:
                external_intersection_entities.add(entity_label)

        split_service_count = 0
        target_service_count = 0
        split_entities: list[str] = []
        target_entities: list[str] = []
        for service in selected_services.values():
            entity_label = _entity_label(service.team_name, service.service_name)
            component_count = _count_weak_components(service.procedure_ids, service.adjacency)
            has_split_graph = component_count > 1
            if has_split_graph:
                split_service_count += 1
                split_entities.append(entity_label)
            has_merge_with_other_service = any(
                count > 0 for count in pair_merge_counts.get(service.key, {}).values()
            )
            if not has_split_graph and not has_merge_with_other_service:
                target_service_count += 1
                target_entities.append(entity_label)

        linking_procedures = tuple(
            self._build_linking_procedures(
                selected_graphs,
                procedure_names=procedure_names,
                top_limit=top_limit,
            )
        )
        flow_graph = _GraphAggregate(
            key="__flow__",
            team_id="__flow__",
            team_name="Flow",
            service_name="Flow",
        )
        flow_graph.add_document(flow_document)
        normalized_flow_graph = _normalize_flow_graph(flow_graph)
        global_display_proc_ids = normalized_flow_graph.visible_procedure_ids()
        global_proc_order = list(
            normalized_flow_graph.ordered_procedure_ids(global_display_proc_ids)
        )
        global_adjacency = normalized_flow_graph.to_adjacency(global_display_proc_ids)
        global_graph_labels_by_proc = _build_graph_labels(
            global_proc_order,
            {node: set(children) for node, children in global_adjacency.items()},
        )
        overloaded_services = tuple(
            self._build_overloaded_services(
                selected_services,
                flow_graph=normalized_flow_graph,
                global_proc_order=global_proc_order,
                global_graph_labels_by_proc=global_graph_labels_by_proc,
                procedure_names=procedure_names,
                merge_selected_markups=merge_selected_markups,
                top_limit=top_limit,
            )
        )

        external_team_intersections = tuple(
            TeamIntersectionStat(
                team_name=name,
                count=count,
                external_depends_on_selected_count=external_team_external_depends_counter.get(
                    name, 0
                ),
                selected_depends_on_external_count=external_team_selected_depends_counter.get(
                    name, 0
                ),
                services=tuple(
                    ServiceIntersectionStat(
                        service_name=service_name,
                        count=service_count,
                        external_depends_on_selected_count=external_team_services_external_depends.get(
                            name, Counter()
                        ).get(service_name, 0),
                        selected_depends_on_external_count=external_team_services_selected_depends.get(
                            name, Counter()
                        ).get(service_name, 0),
                    )
                    for service_name, service_count in sorted(
                        external_team_services.get(name, Counter()).items(),
                        key=lambda item: (-item[1], item[0].lower()),
                    )
                ),
            )
            for name, count in sorted(
                external_team_counter.items(),
                key=lambda item: (-item[1], item[0].lower()),
            )
        )

        return CrossTeamGraphDashboard(
            markup_type_counts=markup_type_counts,
            unique_graph_count=len(unique_graph_labels),
            unique_graphs=tuple(unique_graph_labels),
            graph_groups=graph_groups,
            bot_graph_count=len(bot_graph_labels),
            bot_graphs=tuple(bot_graph_labels),
            multi_graph_count=len(multi_graph_labels),
            multi_graphs=tuple(multi_graph_labels),
            bot_procedure_count=bot_procedure_count,
            bot_procedures=tuple(bot_procedures),
            multi_procedure_count=multi_procedure_count,
            multi_procedures=tuple(multi_procedures),
            employee_procedure_count=employee_procedure_count,
            employee_procedures=tuple(employee_procedures),
            unique_procedure_count=len(unique_procedure_ids),
            total_procedure_count=total_procedure_count,
            internal_intersection_markup_count=len(internal_intersection_entities),
            internal_intersection_entities=tuple(
                sorted(internal_intersection_entities, key=str.lower)
            ),
            external_intersection_markup_count=len(external_intersection_entities),
            external_intersection_entities=tuple(
                sorted(external_intersection_entities, key=str.lower)
            ),
            external_team_intersections=external_team_intersections,
            split_service_count=split_service_count,
            split_entities=tuple(sorted(split_entities, key=str.lower)),
            target_service_count=target_service_count,
            target_entities=tuple(sorted(target_entities, key=str.lower)),
            total_service_count=len(selected_services),
            linking_procedures=linking_procedures,
            overloaded_services=overloaded_services,
        )

    def _extract_graph_view(
        self,
        selected_documents: Sequence[MarkupDocument],
        *,
        merge_selected_markups: bool,
        merge_documents: Sequence[MarkupDocument] | None = None,
    ) -> tuple[MarkupDocument, list[str], dict[str, set[str]], tuple[GraphGroupStat, ...]]:
        graph_document = BuildTeamProcedureGraph().build(
            selected_documents,
            merge_documents=merge_documents,
            merge_selected_markups=merge_selected_markups,
        )
        components = _collect_graph_components(graph_document)
        graph_keys_by_procedure_id: dict[str, set[str]] = {}
        procedure_meta = graph_document.procedure_meta or {}
        procedure_names = {
            proc.procedure_id: proc.procedure_name
            for proc in graph_document.procedures
            if proc.procedure_name
        }

        component_payloads: list[tuple[str, list[str], tuple[GraphMergeNodeStat, ...]]] = []
        for component_nodes in components:
            service_labels: set[str] = set()
            merge_nodes: list[GraphMergeNodeStat] = []
            for proc_id in component_nodes:
                payload = procedure_meta.get(proc_id, {})
                services = payload.get("services")
                keys = _extract_service_keys(services)
                if not keys:
                    keys = {
                        _entity_label(
                            str(payload.get("team_name") or "Unknown team"),
                            str(payload.get("service_name") or "Unknown entity"),
                        )
                    }
                service_labels.update(keys)
                if bool(payload.get("is_intersection")):
                    merge_services = payload.get("merge_services")
                    merge_keys = _extract_service_keys(merge_services)
                    if not merge_keys:
                        merge_keys = keys
                    merge_nodes.append(
                        GraphMergeNodeStat(
                            procedure_id=proc_id,
                            procedure_name=procedure_names.get(proc_id),
                            entities=tuple(sorted(merge_keys, key=str.lower)),
                        )
                    )
            if len(service_labels) > 1:
                service_labels.discard(_entity_label("Unknown team", "Unknown entity"))
            sorted_services = sorted(service_labels, key=str.lower)
            if len(sorted_services) <= 1:
                base_label = sorted_services[0] if sorted_services else "Unknown graph"
            else:
                base_label = " + ".join(sorted_services)
            component_payloads.append(
                (
                    base_label,
                    sorted(component_nodes, key=str.lower),
                    tuple(
                        sorted(
                            merge_nodes,
                            key=lambda item: (-len(item.entities), item.procedure_id.lower()),
                        )
                    ),
                )
            )

        base_label_counts: Counter[str] = Counter(base for base, _, _ in component_payloads)
        base_label_index: Counter[str] = Counter()
        graph_keys: list[str] = []
        components_by_base_label: dict[str, list[GraphComponentStat]] = {}
        for base_label, proc_ids, merge_node_stats in sorted(
            component_payloads,
            key=lambda item: (item[0].lower(), item[1][0].lower() if item[1] else ""),
        ):
            base_label_index[base_label] += 1
            label = base_label
            if base_label_counts[base_label] > 1:
                label = f"{base_label} #{base_label_index[base_label]}"
            graph_keys.append(label)
            for proc_id in proc_ids:
                graph_keys_by_procedure_id.setdefault(proc_id, set()).add(label)
            components_by_base_label.setdefault(base_label, []).append(
                GraphComponentStat(
                    graph_label=label,
                    merge_nodes=tuple(
                        sorted(
                            merge_node_stats,
                            key=lambda item: (-len(item.entities), item.procedure_id.lower()),
                        )
                    ),
                )
            )
        graph_groups = tuple(
            GraphGroupStat(
                label=label,
                graph_count=count,
                components=tuple(
                    sorted(
                        components_by_base_label.get(label, []),
                        key=lambda item: item.graph_label.lower(),
                    )
                ),
            )
            for label, count in sorted(
                base_label_counts.items(),
                key=lambda item: (-item[1], item[0].lower()),
            )
        )
        return graph_document, graph_keys, graph_keys_by_procedure_id, graph_groups

    def _collect_graphs(self, documents: Sequence[MarkupDocument]) -> dict[str, _GraphAggregate]:
        graphs: dict[str, _GraphAggregate] = {}
        for document in documents:
            graph_key, team_id, team_name, service_name = _graph_key(document)
            graph = graphs.get(graph_key)
            if graph is None:
                graph = _GraphAggregate(
                    key=graph_key,
                    team_id=team_id,
                    team_name=team_name,
                    service_name=service_name,
                )
                graphs[graph_key] = graph
            graph.add_document(document)
        return graphs

    def _collect_service_snapshots(
        self,
        documents: Sequence[MarkupDocument],
    ) -> tuple[_ServiceDocumentSnapshot, ...]:
        snapshots: list[_ServiceDocumentSnapshot] = []
        for document in documents:
            graph_key, team_id, team_name, _service_name = _graph_key(document)
            snapshots.append(
                _ServiceDocumentSnapshot(
                    service_key=graph_key,
                    team_id=team_id,
                    team_name=team_name,
                    procedure_ids=frozenset(_document_procedure_ids(document)),
                )
            )
        return tuple(snapshots)

    def _build_markup_type_counts(
        self,
        documents: Sequence[MarkupDocument],
    ) -> list[MarkupTypeStat]:
        counts: Counter[str] = Counter()
        by_type_labels: dict[str, set[str]] = {}
        for document in documents:
            markup_type = str(document.markup_type or "").strip() or "unknown"
            counts[markup_type] += 1
            by_type_labels.setdefault(markup_type, set()).add(
                _entity_label(
                    str(document.team_name or document.team_id or "").strip() or "Unknown team",
                    str(document.service_name or "").strip() or "Unknown entity",
                )
            )
        return [
            MarkupTypeStat(
                markup_type=markup_type,
                count=count,
                item_labels=tuple(sorted(by_type_labels.get(markup_type, set()), key=str.lower)),
            )
            for markup_type, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))
        ]

    def _collect_procedure_names(
        self,
        documents: Sequence[MarkupDocument],
    ) -> dict[str, str]:
        names: dict[str, str] = {}
        for document in documents:
            for proc in document.procedures:
                if not proc.procedure_name:
                    continue
                names.setdefault(proc.procedure_id, proc.procedure_name)
        return names

    def _build_service_node_states(
        self,
        services: Mapping[str, _GraphAggregate],
    ) -> dict[str, ServiceNodeState]:
        return {
            service.key: build_service_node_state(
                service.key,
                service.procedure_ids,
                service.adjacency,
            )
            for service in services.values()
        }

    def _build_pair_merge_counts(
        self,
        pair_merge_nodes: Mapping[tuple[str, str], set[str]],
    ) -> dict[str, dict[str, int]]:
        pair_counts: dict[str, dict[str, int]] = {}
        for (left, right), proc_ids in pair_merge_nodes.items():
            merge_count = len(proc_ids)
            if merge_count <= 0:
                continue
            pair_counts.setdefault(left, {})[right] = merge_count
            pair_counts.setdefault(right, {})[left] = merge_count
        return pair_counts

    def _build_linking_procedures(
        self,
        graphs: Mapping[str, _GraphAggregate],
        *,
        procedure_names: Mapping[str, str],
        top_limit: int,
    ) -> list[ProcedureLinkStat]:
        proc_to_graph_keys: dict[str, set[str]] = {}
        graph_labels_by_key: dict[str, str] = {}
        graph_metrics_by_key = {
            graph.key: compute_graph_metrics(graph.to_adjacency()) for graph in graphs.values()
        }
        merged_adjacency: dict[str, set[str]] = {}
        for graph in graphs.values():
            graph_label = _entity_label(graph.team_name, graph.service_name)
            graph_labels_by_key[graph.key] = graph_label
            for proc_id in graph.procedure_ids:
                proc_to_graph_keys.setdefault(proc_id, set()).add(graph.key)
                merged_adjacency.setdefault(proc_id, set())
            for source, targets in graph.adjacency.items():
                merged_adjacency.setdefault(source, set()).update(targets)
                for target in targets:
                    merged_adjacency.setdefault(target, set())
        metrics = compute_graph_metrics(
            {node: sorted(targets) for node, targets in merged_adjacency.items()}
        )
        stats = [
            ProcedureLinkStat(
                procedure_id=proc_id,
                procedure_name=procedure_names.get(proc_id),
                graph_count=len(graph_keys),
                usage_in_other_graphs=max(0, len(graph_keys) - 1),
                incoming_edges=metrics.in_degree.get(proc_id, 0),
                outgoing_edges=metrics.out_degree.get(proc_id, 0),
                graph_labels=tuple(
                    sorted(
                        (graph_labels_by_key.get(graph_key, graph_key) for graph_key in graph_keys),
                        key=str.lower,
                    )
                ),
                graph_usage_stats=tuple(
                    ProcedureGraphUsageStat(
                        graph_label=_resolve_graph_label(graph_labels_by_key, graph_key),
                        is_cross_entity=len(graph_keys) > 1,
                        incoming_edges=graph_metrics_by_key.get(graph_key, metrics).in_degree.get(
                            proc_id,
                            0,
                        ),
                        outgoing_edges=graph_metrics_by_key.get(graph_key, metrics).out_degree.get(
                            proc_id,
                            0,
                        ),
                    )
                    for graph_key in sorted(
                        graph_keys,
                        key=lambda key: _resolve_graph_label(graph_labels_by_key, key).lower(),
                    )
                ),
            )
            for proc_id, graph_keys in proc_to_graph_keys.items()
        ]
        stats.sort(
            key=lambda item: (
                -item.usage_in_other_graphs,
                -(item.incoming_edges + item.outgoing_edges),
                -item.incoming_edges,
                -item.outgoing_edges,
                item.procedure_id.lower(),
            )
        )
        return stats[:top_limit]

    def _split_external_overlap_dependency_counts(
        self,
        shared_proc_ids: set[str],
        *,
        selected_service: _GraphAggregate,
        external_service: _GraphAggregate,
        selected_state: ServiceNodeState | None,
        external_state: ServiceNodeState | None,
    ) -> tuple[int, int]:
        external_depends_on_selected = 0
        selected_depends_on_external = 0
        selected_defined_proc_ids = set(selected_service.block_ids_by_procedure.keys())
        external_defined_proc_ids = set(external_service.block_ids_by_procedure.keys())

        for proc_id in shared_proc_ids:
            selected_defines_proc = proc_id in selected_defined_proc_ids
            external_defines_proc = proc_id in external_defined_proc_ids
            if selected_defines_proc and not external_defines_proc:
                external_depends_on_selected += 1
                continue
            if external_defines_proc and not selected_defines_proc:
                selected_depends_on_external += 1
                continue

            if selected_state is not None and external_state is not None:
                selected_is_start = selected_state.is_start(proc_id)
                selected_is_end = selected_state.is_end(proc_id)
                external_is_start = external_state.is_start(proc_id)
                external_is_end = external_state.is_end(proc_id)
                if external_is_end and selected_is_start:
                    external_depends_on_selected += 1
                    continue
                if selected_is_end and external_is_start:
                    selected_depends_on_external += 1
                    continue

                selected_degree = selected_state.incoming_by_proc.get(
                    proc_id, 0
                ) + selected_state.outgoing_by_proc.get(proc_id, 0)
                external_degree = external_state.incoming_by_proc.get(
                    proc_id, 0
                ) + external_state.outgoing_by_proc.get(proc_id, 0)
                if external_degree < selected_degree:
                    external_depends_on_selected += 1
                else:
                    selected_depends_on_external += 1
                continue

            selected_depends_on_external += 1

        return external_depends_on_selected, selected_depends_on_external

    def _build_overloaded_services(
        self,
        services: Mapping[str, _GraphAggregate],
        *,
        flow_graph: _GraphAggregate,
        global_proc_order: Sequence[str],
        global_graph_labels_by_proc: Mapping[str, str | None],
        procedure_names: Mapping[str, str],
        merge_selected_markups: bool,
        top_limit: int,
    ) -> list[ServiceLoadStat]:
        merge_node_ids_by_service: dict[str, set[str]] = {}
        states = self._build_service_node_states(services)
        pair_merge_nodes = collect_pair_merge_nodes(
            states,
            merge_selected_markups=merge_selected_markups,
        )
        for (left_key, right_key), proc_ids in pair_merge_nodes.items():
            merge_node_ids_by_service.setdefault(left_key, set()).update(proc_ids)
            merge_node_ids_by_service.setdefault(right_key, set()).update(proc_ids)

        stats: list[ServiceLoadStat] = []
        for service in services.values():
            visible_proc_ids = service.visible_procedure_ids()
            display_proc_ids = visible_proc_ids & flow_graph.procedure_ids
            if not display_proc_ids:
                continue
            adjacency = flow_graph.to_adjacency(display_proc_ids)
            graph_metrics = compute_graph_metrics(adjacency)
            visible_adjacency = {node: set(children) for node, children in adjacency.items()}
            merge_nodes = merge_node_ids_by_service.get(service.key, set()) & display_proc_ids
            in_team_merge_nodes = len(merge_nodes)
            weak_component_count = _count_weak_components(display_proc_ids, visible_adjacency)
            cycle_nodes = set(graph_metrics.cycle_path or ())
            ordered_proc_ids = [
                proc_id for proc_id in global_proc_order if proc_id in display_proc_ids
            ]
            if len(ordered_proc_ids) < len(display_proc_ids):
                ordered_proc_ids.extend(
                    sorted(display_proc_ids - set(ordered_proc_ids), key=str.lower)
                )
            stats.append(
                ServiceLoadStat(
                    team_name=service.team_name,
                    service_name=service.service_name,
                    cycle_count=graph_metrics.cycle_count,
                    block_count=sum(
                        len(service.block_ids_by_procedure.get(proc_id, set()))
                        for proc_id in display_proc_ids
                    ),
                    in_team_merge_nodes=in_team_merge_nodes,
                    procedure_count=len(display_proc_ids),
                    procedure_ids=tuple(sorted(display_proc_ids, key=str.lower)),
                    merge_node_ids=tuple(sorted(merge_nodes, key=str.lower)),
                    weak_component_count=weak_component_count,
                    cycle_path=tuple(graph_metrics.cycle_path or ()),
                    procedure_usage_stats=tuple(
                        ServiceProcedureUsageStat(
                            procedure_id=proc_id,
                            procedure_name=procedure_names.get(proc_id),
                            in_team_merge_hits=1 if proc_id in merge_nodes else 0,
                            cycle_hits=1 if proc_id in cycle_nodes else 0,
                            linked_procedure_count=graph_metrics.in_degree.get(proc_id, 0)
                            + graph_metrics.out_degree.get(proc_id, 0),
                            block_count=len(service.block_ids_by_procedure.get(proc_id, set())),
                            start_block_count=len(
                                service.start_block_ids_by_procedure.get(proc_id, set())
                            ),
                            end_block_count=len(
                                service.end_block_types_by_procedure.get(proc_id, {})
                            ),
                            graph_label=global_graph_labels_by_proc.get(proc_id),
                            block_type_stats=self._build_procedure_block_type_stats(
                                service,
                                proc_id,
                            ),
                        )
                        for proc_id in ordered_proc_ids
                    ),
                )
            )
        stats.sort(
            key=lambda item: (
                -item.in_team_merge_nodes,
                -item.cycle_count,
                -item.procedure_count,
                -item.block_count,
                item.team_name.lower(),
                item.service_name.lower(),
            )
        )
        return stats[:top_limit]

    def _build_procedure_block_type_stats(
        self,
        service: _GraphAggregate,
        procedure_id: str,
    ) -> tuple[ProcedureBlockTypeStat, ...]:
        stats: list[ProcedureBlockTypeStat] = []
        start_count = len(service.start_block_ids_by_procedure.get(procedure_id, set()))
        if start_count > 0:
            stats.append(
                ProcedureBlockTypeStat(
                    type_id="start",
                    label="Start",
                    count=start_count,
                    color=INITIAL_BLOCK_COLOR,
                )
            )

        end_type_counts: Counter[str] = Counter(
            service.end_block_types_by_procedure.get(procedure_id, {}).values()
        )
        end_type_order = (
            "end",
            "exit",
            "all",
            "intermediate",
            "postpone",
            "turn_out",
        )
        for end_type in end_type_order:
            count = end_type_counts.get(end_type, 0)
            if count <= 0:
                continue
            label = "End" if end_type == END_TYPE_DEFAULT else f"End ({end_type})"
            stats.append(
                ProcedureBlockTypeStat(
                    type_id=f"end:{end_type}",
                    label=label,
                    count=count,
                    color=END_TYPE_COLORS.get(end_type, END_TYPE_COLORS[END_TYPE_DEFAULT]),
                )
            )
        return tuple(stats)


def _is_service_markup(document: MarkupDocument) -> bool:
    return str(document.markup_type or "").strip().lower() == "service"


def _graph_key(document: MarkupDocument) -> tuple[str, str, str, str]:
    team_id = str(document.team_id or "").strip() or "unknown-team"
    team_name = str(document.team_name or "").strip() or team_id
    service_name = str(document.service_name or "").strip() or "Unknown service"
    service_id = str(document.finedog_unit_id or "").strip() or service_name.lower()
    return f"{team_id}::{service_id}", team_id, team_name, service_name


def _document_procedure_ids(document: MarkupDocument) -> set[str]:
    proc_ids = {procedure.procedure_id for procedure in document.procedures}
    for source, targets in document.procedure_graph.items():
        proc_ids.add(source)
        proc_ids.update(targets)
    return proc_ids


def _count_weak_components(nodes: set[str], adjacency: Mapping[str, set[str]]) -> int:
    if not nodes:
        return 0
    undirected: dict[str, set[str]] = {node: set() for node in nodes}
    for source, targets in adjacency.items():
        undirected.setdefault(source, set())
        for target in targets:
            undirected.setdefault(target, set())
            undirected[source].add(target)
            undirected[target].add(source)
    visited: set[str] = set()
    components = 0
    for node in undirected:
        if node in visited:
            continue
        components += 1
        stack = [node]
        while stack:
            current = stack.pop()
            if current in visited:
                continue
            visited.add(current)
            stack.extend(undirected.get(current, set()) - visited)
    return components


def _normalize_flow_graph(flow_graph: _GraphAggregate) -> _GraphAggregate:
    normalized = _GraphAggregate(
        key=flow_graph.key,
        team_id=flow_graph.team_id,
        team_name=flow_graph.team_name,
        service_name=flow_graph.service_name,
    )
    for proc_id in flow_graph.procedure_order:
        normalized._register_procedure_id(_normalize_scoped_procedure_id(proc_id))
    for proc_id in flow_graph.procedure_ids:
        normalized._register_procedure_id(_normalize_scoped_procedure_id(proc_id))

    for source, targets in flow_graph.adjacency.items():
        normalized_source = _normalize_scoped_procedure_id(source)
        normalized.adjacency.setdefault(normalized_source, set())
        for target in targets:
            normalized_target = _normalize_scoped_procedure_id(target)
            if normalized_target == normalized_source:
                continue
            normalized.adjacency[normalized_source].add(normalized_target)
            normalized.adjacency.setdefault(normalized_target, set())

    for proc_id, start_block_ids in flow_graph.start_block_ids_by_procedure.items():
        normalized_proc_id = _normalize_scoped_procedure_id(proc_id)
        normalized.start_block_ids_by_procedure.setdefault(normalized_proc_id, set()).update(
            start_block_ids
        )
    for proc_id, block_ids in flow_graph.block_ids_by_procedure.items():
        normalized_proc_id = _normalize_scoped_procedure_id(proc_id)
        normalized.block_ids_by_procedure.setdefault(normalized_proc_id, set()).update(block_ids)
    for proc_id, end_block_types in flow_graph.end_block_types_by_procedure.items():
        normalized_proc_id = _normalize_scoped_procedure_id(proc_id)
        normalized.end_block_types_by_procedure.setdefault(normalized_proc_id, {}).update(
            end_block_types
        )
    return normalized


def _normalize_scoped_procedure_id(proc_id: str) -> str:
    base, sep, suffix = proc_id.rpartition("::doc")
    if sep and suffix.isdigit():
        return base
    return proc_id


def _build_graph_labels(
    ordered_proc_ids: Sequence[str],
    adjacency: Mapping[str, set[str]],
) -> dict[str, str | None]:
    if not ordered_proc_ids:
        return {}

    nodes = set(ordered_proc_ids)
    undirected: dict[str, set[str]] = {proc_id: set() for proc_id in nodes}
    for source, targets in adjacency.items():
        if source not in nodes:
            continue
        for target in targets:
            if target not in nodes:
                continue
            undirected[source].add(target)
            undirected[target].add(source)

    component_index_by_proc: dict[str, int] = {}
    component_count = 0
    for proc_id in ordered_proc_ids:
        if proc_id in component_index_by_proc:
            continue
        stack = [proc_id]
        while stack:
            current = stack.pop()
            if current in component_index_by_proc:
                continue
            component_index_by_proc[current] = component_count
            stack.extend(undirected.get(current, set()) - set(component_index_by_proc))
        component_count += 1

    if component_count <= 1:
        return {proc_id: None for proc_id in ordered_proc_ids}
    return {
        proc_id: f"Graph {component_index_by_proc.get(proc_id, 0) + 1}"
        for proc_id in ordered_proc_ids
    }


def _collect_graph_components(document: MarkupDocument) -> list[set[str]]:
    nodes: set[str] = {procedure.procedure_id for procedure in document.procedures}
    for source, targets in document.procedure_graph.items():
        nodes.add(source)
        nodes.update(targets)
    if not nodes:
        return []

    undirected: dict[str, set[str]] = {node: set() for node in nodes}
    for source, targets in document.procedure_graph.items():
        undirected.setdefault(source, set())
        for target in targets:
            undirected.setdefault(target, set())
            undirected[source].add(target)
            undirected[target].add(source)

    visited: set[str] = set()
    components: list[set[str]] = []
    for node in sorted(undirected, key=str.lower):
        if node in visited:
            continue
        stack = [node]
        component: set[str] = set()
        while stack:
            current = stack.pop()
            if current in visited:
                continue
            visited.add(current)
            component.add(current)
            stack.extend(sorted(undirected.get(current, set()) - visited, key=str.lower))
        components.append(component)
    return components


def _has_substring(value: str, fragment: str) -> bool:
    return fragment.lower() in str(value).lower()


def _entity_label(team_name: str, service_name: str) -> str:
    normalized_team = str(team_name or "").strip() or "Unknown team"
    normalized_service = str(service_name or "").strip() or "Unknown entity"
    return f"{normalized_team} / {normalized_service}"


def _extract_service_keys(services: object) -> set[str]:
    if not isinstance(services, list):
        return set()
    result: set[str] = set()
    for item in services:
        if not isinstance(item, dict):
            continue
        result.add(
            _entity_label(
                str(item.get("team_name") or "Unknown team"),
                str(item.get("service_name") or "Unknown entity"),
            )
        )
    return result


def _sorted_pair(left: str, right: str) -> tuple[str, str]:
    return (left, right) if left <= right else (right, left)


def _resolve_graph_label(graph_labels_by_key: Mapping[str, str], graph_key: str) -> str:
    return graph_labels_by_key[graph_key] if graph_key in graph_labels_by_key else graph_key
