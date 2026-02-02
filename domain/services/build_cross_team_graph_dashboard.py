from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from domain.models import MarkupDocument
from domain.services.build_team_procedure_graph import BuildTeamProcedureGraph
from domain.services.graph_metrics import compute_graph_metrics


@dataclass(frozen=True)
class MarkupTypeStat:
    markup_type: str
    count: int
    item_labels: tuple[str, ...] = ()


@dataclass(frozen=True)
class TeamIntersectionStat:
    team_name: str
    count: int
    entities: tuple[str, ...] = ()


@dataclass(frozen=True)
class ProcedureLinkStat:
    procedure_id: str
    graph_count: int
    usage_in_other_graphs: int
    incoming_edges: int
    outgoing_edges: int


@dataclass(frozen=True)
class ServiceLoadStat:
    team_name: str
    service_name: str
    cycle_count: int
    block_count: int
    in_team_merge_nodes: int
    procedure_count: int


@dataclass(frozen=True)
class CrossTeamGraphDashboard:
    markup_type_counts: tuple[MarkupTypeStat, ...]
    unique_graph_count: int
    unique_graphs: tuple[str, ...]
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
    adjacency: dict[str, set[str]] = field(default_factory=dict)
    block_ids_by_procedure: dict[str, set[str]] = field(default_factory=dict)

    def add_document(self, document: MarkupDocument) -> None:
        for proc_id in _document_procedure_ids(document):
            self.procedure_ids.add(proc_id)
            self.adjacency.setdefault(proc_id, set())
        for source, targets in document.procedure_graph.items():
            self.adjacency.setdefault(source, set())
            self.procedure_ids.add(source)
            for target in targets:
                self.adjacency[source].add(target)
                self.adjacency.setdefault(target, set())
                self.procedure_ids.add(target)
        for procedure in document.procedures:
            block_ids = self.block_ids_by_procedure.setdefault(procedure.procedure_id, set())
            block_ids.update(procedure.block_ids())

    def block_count(self) -> int:
        return sum(len(block_ids) for block_ids in self.block_ids_by_procedure.values())

    def to_adjacency(self) -> dict[str, list[str]]:
        adjacency: dict[str, list[str]] = {}
        for node in sorted(self.procedure_ids):
            adjacency[node] = sorted(self.adjacency.get(node, set()))
        return adjacency


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
        top_limit: int = 10,
    ) -> CrossTeamGraphDashboard:
        selected_graphs = self._collect_graphs(selected_documents)
        selected_service_docs = [doc for doc in selected_documents if _is_service_markup(doc)]
        all_service_docs = [doc for doc in all_documents if _is_service_markup(doc)]
        selected_services = self._collect_graphs(selected_service_docs)
        all_services = self._collect_graphs(all_service_docs)

        selected_team_set = {
            team_id for team_id in (str(value).strip() for value in selected_team_ids) if team_id
        }
        (
            unique_graph_labels,
            graph_keys_by_procedure_id,
        ) = self._extract_graph_view(
            selected_documents,
            merge_selected_markups=merge_selected_markups,
        )
        markup_type_counts = tuple(self._build_markup_type_counts(selected_documents))
        total_procedure_count = sum(len(document.procedures) for document in selected_documents)
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
        selected_proc_to_services = self._build_proc_to_services(selected_services)
        all_proc_to_services = self._build_proc_to_services(all_services)

        internal_intersection_entities: set[str] = set()
        external_intersection_entities: set[str] = set()
        external_team_counter: Counter[str] = Counter()
        external_team_entities: dict[str, set[str]] = {}
        for snapshot in selected_snapshots:
            has_internal = False
            has_external = False
            external_teams_for_markup: set[str] = set()
            for proc_id in snapshot.procedure_ids:
                for service_key in selected_proc_to_services.get(proc_id, set()):
                    if service_key != snapshot.service_key:
                        has_internal = True
                        break
                for service_key in all_proc_to_services.get(proc_id, set()):
                    if service_key == snapshot.service_key:
                        continue
                    service = all_services.get(service_key)
                    if service is None:
                        continue
                    if service.team_id in selected_team_set:
                        continue
                    has_external = True
                    external_teams_for_markup.add(service.team_name)
                    external_team_entities.setdefault(service.team_name, set()).add(
                        _entity_label(service.team_name, service.service_name)
                    )
            service = all_services.get(snapshot.service_key)
            entity_label = _entity_label(
                snapshot.team_name,
                service.service_name if service is not None else "Unknown entity",
            )
            if has_internal:
                internal_intersection_entities.add(entity_label)
            if has_external:
                external_intersection_entities.add(entity_label)
            for team_name in external_teams_for_markup:
                external_team_counter[team_name] += 1

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
                any(
                    other_service != service.key
                    for other_service in all_proc_to_services.get(proc_id, set())
                )
                for proc_id in service.procedure_ids
            )
            if not has_split_graph and not has_merge_with_other_service:
                target_service_count += 1
                target_entities.append(entity_label)

        linking_procedures = tuple(
            self._build_linking_procedures(selected_graphs, top_limit=top_limit)
        )
        overloaded_services = tuple(
            self._build_overloaded_services(selected_services, top_limit=top_limit)
        )

        external_team_intersections = tuple(
            TeamIntersectionStat(
                team_name=name,
                count=count,
                entities=tuple(sorted(external_team_entities.get(name, set()), key=str.lower)),
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
    ) -> tuple[list[str], dict[str, set[str]]]:
        graph_document = BuildTeamProcedureGraph().build(
            selected_documents,
            merge_selected_markups=merge_selected_markups,
        )
        graph_keys: set[str] = set()
        graph_keys_by_procedure_id: dict[str, set[str]] = {}
        for proc_id, payload in (graph_document.procedure_meta or {}).items():
            services = payload.get("services")
            keys = _extract_service_keys(services)
            if not keys:
                keys = {
                    _entity_label(
                        str(payload.get("team_name") or "Unknown team"),
                        str(payload.get("service_name") or "Unknown entity"),
                    )
                }
            graph_keys.update(keys)
            graph_keys_by_procedure_id.setdefault(proc_id, set()).update(keys)
        return sorted(graph_keys, key=str.lower), graph_keys_by_procedure_id

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

    def _build_proc_to_services(
        self,
        services: Mapping[str, _GraphAggregate],
    ) -> dict[str, set[str]]:
        proc_to_services: dict[str, set[str]] = {}
        for service in services.values():
            for proc_id in service.procedure_ids:
                proc_to_services.setdefault(proc_id, set()).add(service.key)
        return proc_to_services

    def _build_linking_procedures(
        self,
        graphs: Mapping[str, _GraphAggregate],
        *,
        top_limit: int,
    ) -> list[ProcedureLinkStat]:
        proc_to_graphs: dict[str, set[str]] = {}
        merged_adjacency: dict[str, set[str]] = {}
        for graph in graphs.values():
            for proc_id in graph.procedure_ids:
                proc_to_graphs.setdefault(proc_id, set()).add(graph.key)
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
                graph_count=len(graph_keys),
                usage_in_other_graphs=max(0, len(graph_keys) - 1),
                incoming_edges=metrics.in_degree.get(proc_id, 0),
                outgoing_edges=metrics.out_degree.get(proc_id, 0),
            )
            for proc_id, graph_keys in proc_to_graphs.items()
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

    def _build_overloaded_services(
        self,
        services: Mapping[str, _GraphAggregate],
        *,
        top_limit: int,
    ) -> list[ServiceLoadStat]:
        proc_to_services: dict[str, set[str]] = {}
        team_to_services: dict[str, set[str]] = {}
        for service in services.values():
            team_to_services.setdefault(service.team_id, set()).add(service.key)
            for proc_id in service.procedure_ids:
                proc_to_services.setdefault(proc_id, set()).add(service.key)

        stats: list[ServiceLoadStat] = []
        for service in services.values():
            adjacency = service.to_adjacency()
            graph_metrics = compute_graph_metrics(adjacency)
            team_keys = team_to_services.get(service.team_id, set())
            in_team_merge_nodes = 0
            for proc_id in service.procedure_ids:
                other_services = proc_to_services.get(proc_id, set()) - {service.key}
                if any(other_service in team_keys for other_service in other_services):
                    in_team_merge_nodes += 1
            stats.append(
                ServiceLoadStat(
                    team_name=service.team_name,
                    service_name=service.service_name,
                    cycle_count=graph_metrics.cycle_count,
                    block_count=service.block_count(),
                    in_team_merge_nodes=in_team_merge_nodes,
                    procedure_count=len(service.procedure_ids),
                )
            )
        stats.sort(
            key=lambda item: (
                -item.cycle_count,
                -item.block_count,
                -item.in_team_merge_nodes,
                -item.procedure_count,
                item.team_name.lower(),
                item.service_name.lower(),
            )
        )
        return stats[:top_limit]


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
