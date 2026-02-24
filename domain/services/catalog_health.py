from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from domain.catalog import CatalogItem

GRAPH_ISSUE_MULTIPLE_WITHOUT_BOT = "multiple_graphs_without_bot"
GRAPH_ISSUE_NO_BOT = "no_bot_graphs"
GRAPH_ISSUE_ONLY_BOT = "only_bot_graphs"
GRAPH_ISSUE_TOO_MANY = "too_many_graphs"
GAMING_ISSUE_NO_BRANCH_AND_NO_END = "no_branch_and_no_end_except_postpone"


@dataclass(frozen=True)
class SimilarityMatch:
    scene_id: str
    title: str
    team_id: str
    team_name: str
    overlap_percent: float
    shared_procedure_count: int
    source_procedure_count: int
    target_procedure_count: int


@dataclass(frozen=True)
class SimilarityHealth:
    threshold_percent: float
    top_match: SimilarityMatch | None
    is_problem: bool


@dataclass(frozen=True)
class GraphHealth:
    unique_graph_count: int
    bot_graph_count: int
    non_bot_graph_count: int
    issue_codes: tuple[str, ...]
    is_problem: bool


@dataclass(frozen=True)
class GamingHealth:
    branch_block_count: int
    non_postpone_end_block_count: int
    postpone_end_block_count: int
    issue_codes: tuple[str, ...]
    is_problem: bool


@dataclass(frozen=True)
class CatalogItemHealth:
    scene_id: str
    has_problem: bool
    graph: GraphHealth
    gaming: GamingHealth
    same_team_similarity: SimilarityHealth
    cross_team_similarity: SimilarityHealth


@dataclass(frozen=True)
class TeamHealthSummary:
    team_id: str
    team_name: str
    markup_count: int
    graph_problem_count: int
    gaming_problem_count: int
    same_team_problem_count: int
    cross_team_problem_count: int
    total_problem_markups: int
    total_problem_count: int
    no_bot_graph_count: int
    multiple_graphs_without_bot_count: int
    only_bot_graph_count: int
    too_many_graphs_count: int


@dataclass(frozen=True)
class CatalogHealthReport:
    same_team_threshold_percent: float
    cross_team_threshold_percent: float
    total_markup_count: int
    graph_problem_count: int
    gaming_problem_count: int
    same_team_problem_count: int
    cross_team_problem_count: int
    total_problem_markups: int
    items_by_scene: Mapping[str, CatalogItemHealth]
    team_summaries: tuple[TeamHealthSummary, ...]

    def item(self, scene_id: str) -> CatalogItemHealth | None:
        return self.items_by_scene.get(scene_id)


class BuildCatalogHealthReport:
    def __init__(
        self,
        *,
        same_team_threshold_percent: float = 40.0,
        cross_team_threshold_percent: float = 20.0,
    ) -> None:
        self._same_team_threshold_percent = max(0.0, float(same_team_threshold_percent))
        self._cross_team_threshold_percent = max(0.0, float(cross_team_threshold_percent))

    def build(self, items: Sequence[CatalogItem]) -> CatalogHealthReport:
        if not items:
            return CatalogHealthReport(
                same_team_threshold_percent=self._same_team_threshold_percent,
                cross_team_threshold_percent=self._cross_team_threshold_percent,
                total_markup_count=0,
                graph_problem_count=0,
                gaming_problem_count=0,
                same_team_problem_count=0,
                cross_team_problem_count=0,
                total_problem_markups=0,
                items_by_scene={},
                team_summaries=(),
            )

        procedure_sets = {item.scene_id: _procedure_id_set(item) for item in items}
        graph_health_by_scene = {item.scene_id: _build_graph_health(item) for item in items}

        health_by_scene: dict[str, CatalogItemHealth] = {}
        graph_problem_count = 0
        gaming_problem_count = 0
        same_team_problem_count = 0
        cross_team_problem_count = 0
        total_problem_markups = 0

        for item in items:
            same_team_candidates = [
                candidate
                for candidate in items
                if candidate.scene_id != item.scene_id and candidate.team_id == item.team_id
            ]
            cross_team_candidates = [
                candidate
                for candidate in items
                if candidate.scene_id != item.scene_id and candidate.team_id != item.team_id
            ]
            same_match = _find_top_similarity_match(item, same_team_candidates, procedure_sets)
            cross_match = _find_top_similarity_match(item, cross_team_candidates, procedure_sets)

            same_team_similarity = SimilarityHealth(
                threshold_percent=self._same_team_threshold_percent,
                top_match=same_match,
                is_problem=(
                    same_match is not None
                    and same_match.overlap_percent > self._same_team_threshold_percent
                ),
            )
            cross_team_similarity = SimilarityHealth(
                threshold_percent=self._cross_team_threshold_percent,
                top_match=cross_match,
                is_problem=(
                    cross_match is not None
                    and cross_match.overlap_percent > self._cross_team_threshold_percent
                ),
            )
            graph = graph_health_by_scene[item.scene_id]
            gaming = _build_gaming_health(item, graph.unique_graph_count)
            has_problem = bool(
                graph.is_problem
                or gaming.is_problem
                or same_team_similarity.is_problem
                or cross_team_similarity.is_problem
            )
            if graph.is_problem:
                graph_problem_count += 1
            if gaming.is_problem:
                gaming_problem_count += 1
            if same_team_similarity.is_problem:
                same_team_problem_count += 1
            if cross_team_similarity.is_problem:
                cross_team_problem_count += 1
            if has_problem:
                total_problem_markups += 1

            health_by_scene[item.scene_id] = CatalogItemHealth(
                scene_id=item.scene_id,
                has_problem=has_problem,
                graph=graph,
                gaming=gaming,
                same_team_similarity=same_team_similarity,
                cross_team_similarity=cross_team_similarity,
            )

        team_summaries = _build_team_summaries(items, health_by_scene)

        return CatalogHealthReport(
            same_team_threshold_percent=self._same_team_threshold_percent,
            cross_team_threshold_percent=self._cross_team_threshold_percent,
            total_markup_count=len(items),
            graph_problem_count=graph_problem_count,
            gaming_problem_count=gaming_problem_count,
            same_team_problem_count=same_team_problem_count,
            cross_team_problem_count=cross_team_problem_count,
            total_problem_markups=total_problem_markups,
            items_by_scene=health_by_scene,
            team_summaries=team_summaries,
        )


def _build_graph_health(item: CatalogItem) -> GraphHealth:
    adjacency = _normalize_graph_adjacency(item)
    components = _collect_weak_components(adjacency)
    unique_graph_count = len(components)

    bot_graph_count = 0
    for component_nodes in components:
        starts = _component_starts(component_nodes, adjacency)
        if any(_is_bot_or_multi(procedure_id) for procedure_id in starts):
            bot_graph_count += 1
    non_bot_graph_count = max(0, unique_graph_count - bot_graph_count)

    issue_codes: list[str] = []
    if unique_graph_count > 3:
        issue_codes.append(GRAPH_ISSUE_TOO_MANY)
    if unique_graph_count >= 2 and bot_graph_count == 0:
        issue_codes.append(GRAPH_ISSUE_MULTIPLE_WITHOUT_BOT)
    elif bot_graph_count == 0:
        issue_codes.append(GRAPH_ISSUE_NO_BOT)
    elif unique_graph_count > 0 and bot_graph_count == unique_graph_count:
        issue_codes.append(GRAPH_ISSUE_ONLY_BOT)

    return GraphHealth(
        unique_graph_count=unique_graph_count,
        bot_graph_count=bot_graph_count,
        non_bot_graph_count=non_bot_graph_count,
        issue_codes=tuple(issue_codes),
        is_problem=bool(issue_codes),
    )


def _build_gaming_health(item: CatalogItem, unique_graph_count: int) -> GamingHealth:
    branch_block_count = max(0, int(item.branch_block_count))
    non_postpone_end_block_count = max(0, int(item.non_postpone_end_block_count))
    postpone_end_block_count = max(0, int(item.postpone_end_block_count))
    is_problem = (
        unique_graph_count > 0 and branch_block_count == 0 and non_postpone_end_block_count == 0
    )
    issue_codes = (GAMING_ISSUE_NO_BRANCH_AND_NO_END,) if is_problem else ()
    return GamingHealth(
        branch_block_count=branch_block_count,
        non_postpone_end_block_count=non_postpone_end_block_count,
        postpone_end_block_count=postpone_end_block_count,
        issue_codes=issue_codes,
        is_problem=is_problem,
    )


def _build_team_summaries(
    items: Sequence[CatalogItem],
    health_by_scene: Mapping[str, CatalogItemHealth],
) -> tuple[TeamHealthSummary, ...]:
    items_by_team: dict[str, list[CatalogItem]] = defaultdict(list)
    for item in items:
        items_by_team[item.team_id].append(item)

    summaries: list[TeamHealthSummary] = []
    for team_id, team_items in items_by_team.items():
        sorted_team_items = sorted(team_items, key=lambda candidate: candidate.title.lower())
        team_name = _resolve_team_name(sorted_team_items, team_id)

        graph_problem_count = 0
        gaming_problem_count = 0
        same_team_problem_count = 0
        cross_team_problem_count = 0
        total_problem_markups = 0
        no_bot_graph_count = 0
        multiple_graphs_without_bot_count = 0
        only_bot_graph_count = 0
        too_many_graphs_count = 0

        for item in sorted_team_items:
            health = health_by_scene[item.scene_id]
            if health.graph.is_problem:
                graph_problem_count += 1
            if health.gaming.is_problem:
                gaming_problem_count += 1
            if health.same_team_similarity.is_problem:
                same_team_problem_count += 1
            if health.cross_team_similarity.is_problem:
                cross_team_problem_count += 1
            if health.has_problem:
                total_problem_markups += 1
            if GRAPH_ISSUE_NO_BOT in health.graph.issue_codes:
                no_bot_graph_count += 1
            if GRAPH_ISSUE_MULTIPLE_WITHOUT_BOT in health.graph.issue_codes:
                multiple_graphs_without_bot_count += 1
            if GRAPH_ISSUE_ONLY_BOT in health.graph.issue_codes:
                only_bot_graph_count += 1
            if GRAPH_ISSUE_TOO_MANY in health.graph.issue_codes:
                too_many_graphs_count += 1

        total_problem_count = (
            graph_problem_count
            + gaming_problem_count
            + same_team_problem_count
            + cross_team_problem_count
        )
        summaries.append(
            TeamHealthSummary(
                team_id=team_id,
                team_name=team_name,
                markup_count=len(sorted_team_items),
                graph_problem_count=graph_problem_count,
                gaming_problem_count=gaming_problem_count,
                same_team_problem_count=same_team_problem_count,
                cross_team_problem_count=cross_team_problem_count,
                total_problem_markups=total_problem_markups,
                total_problem_count=total_problem_count,
                no_bot_graph_count=no_bot_graph_count,
                multiple_graphs_without_bot_count=multiple_graphs_without_bot_count,
                only_bot_graph_count=only_bot_graph_count,
                too_many_graphs_count=too_many_graphs_count,
            )
        )

    summaries.sort(
        key=lambda summary: (
            -summary.total_problem_markups,
            -summary.total_problem_count,
            -summary.graph_problem_count,
            summary.team_name.lower(),
            summary.team_id.lower(),
        )
    )
    return tuple(summaries)


def _resolve_team_name(items: Sequence[CatalogItem], team_id: str) -> str:
    for item in items:
        team_name = str(item.team_name or "").strip()
        if team_name and team_name != team_id:
            return team_name
    return team_id


def _find_top_similarity_match(
    item: CatalogItem,
    candidates: Sequence[CatalogItem],
    procedure_sets: Mapping[str, set[str]],
) -> SimilarityMatch | None:
    if not candidates:
        return None

    source_set = procedure_sets.get(item.scene_id, set())
    source_count = len(source_set)
    best_match: SimilarityMatch | None = None
    best_key: tuple[float, int, int, str] | None = None

    for candidate in candidates:
        target_set = procedure_sets.get(candidate.scene_id, set())
        shared_count = len(source_set & target_set)
        overlap_percent = 0.0
        if source_count > 0:
            overlap_percent = (shared_count / source_count) * 100.0
        similarity = SimilarityMatch(
            scene_id=candidate.scene_id,
            title=candidate.title,
            team_id=candidate.team_id,
            team_name=candidate.team_name,
            overlap_percent=round(overlap_percent, 2),
            shared_procedure_count=shared_count,
            source_procedure_count=source_count,
            target_procedure_count=len(target_set),
        )
        candidate_key = (
            similarity.overlap_percent,
            similarity.shared_procedure_count,
            -similarity.target_procedure_count,
            similarity.scene_id,
        )
        if best_key is None or candidate_key > best_key:
            best_key = candidate_key
            best_match = similarity
    return best_match


def _procedure_id_set(item: CatalogItem) -> set[str]:
    result: set[str] = set()
    for procedure_id in item.procedure_ids:
        normalized = str(procedure_id).strip()
        if normalized:
            result.add(normalized)
    for source_id, targets in item.procedure_graph.items():
        source = str(source_id).strip()
        if source:
            result.add(source)
        for target in targets:
            normalized_target = str(target).strip()
            if normalized_target:
                result.add(normalized_target)
    return result


def _normalize_graph_adjacency(item: CatalogItem) -> dict[str, set[str]]:
    nodes = _procedure_id_set(item)
    adjacency: dict[str, set[str]] = {node: set() for node in nodes}
    for source_id, targets in item.procedure_graph.items():
        source = str(source_id).strip()
        if not source:
            continue
        adjacency.setdefault(source, set())
        for target in targets:
            normalized_target = str(target).strip()
            if not normalized_target:
                continue
            adjacency[source].add(normalized_target)
            adjacency.setdefault(normalized_target, set())
    return adjacency


def _collect_weak_components(adjacency: Mapping[str, set[str]]) -> list[set[str]]:
    if not adjacency:
        return []
    undirected: dict[str, set[str]] = {node: set() for node in adjacency}
    for source, targets in adjacency.items():
        for target in targets:
            undirected.setdefault(source, set()).add(target)
            undirected.setdefault(target, set()).add(source)

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


def _component_starts(
    component_nodes: set[str], adjacency: Mapping[str, set[str]]
) -> tuple[str, ...]:
    in_degree: dict[str, int] = {node: 0 for node in component_nodes}
    for source in component_nodes:
        for target in adjacency.get(source, set()):
            if target in component_nodes:
                in_degree[target] = in_degree.get(target, 0) + 1
    starts = sorted(
        (node for node, degree in in_degree.items() if degree == 0),
        key=str.lower,
    )
    if starts:
        return tuple(starts)
    if not component_nodes:
        return ()
    fallback = min(component_nodes, key=str.lower)
    return (fallback,)


def _is_bot_or_multi(value: str) -> bool:
    normalized = str(value).lower()
    return "bot" in normalized or "multi" in normalized
