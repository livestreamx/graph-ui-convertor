from __future__ import annotations

from domain.catalog import CatalogItem
from domain.services.catalog_health import (
    GAMING_ISSUE_MULTIPLE_STARTS_WITHOUT_BRANCH,
    GAMING_ISSUE_NO_BRANCH_AND_NO_END,
    GAMING_ISSUE_SAME_START_AND_END_BLOCK,
    GRAPH_ISSUE_MULTIPLE_WITHOUT_BOT,
    GRAPH_ISSUE_NO_BOT,
    GRAPH_ISSUE_ONLY_BOT,
    GRAPH_ISSUE_TOO_MANY,
    BuildCatalogHealthReport,
)


def _catalog_item(
    *,
    scene_id: str,
    title: str,
    team_id: str,
    team_name: str,
    procedure_graph: dict[str, list[str]],
    procedure_blocks: dict[str, list[str]] | None = None,
    procedure_block_graphs: dict[str, dict[str, list[str]]] | None = None,
    procedure_start_blocks: dict[str, list[str]] | None = None,
    procedure_end_blocks: dict[str, list[str]] | None = None,
    procedure_branch_counts: dict[str, int] | None = None,
    start_block_count: int = 1,
    branch_block_count: int = 1,
    non_postpone_end_block_count: int = 1,
    postpone_end_block_count: int = 0,
    has_start_end_overlap: bool = False,
    markup_type: str = "service",
) -> CatalogItem:
    procedure_ids: list[str] = []
    seen: set[str] = set()
    for source, targets in procedure_graph.items():
        if source not in seen:
            seen.add(source)
            procedure_ids.append(source)
        for target in targets:
            if target in seen:
                continue
            seen.add(target)
            procedure_ids.append(target)
    return CatalogItem(
        scene_id=scene_id,
        title=title,
        tags=[],
        updated_at="2026-02-01T00:00:00+00:00",
        markup_type=markup_type,
        finedog_unit_id=scene_id,
        criticality_level="low",
        team_id=team_id,
        team_name=team_name,
        group_values={"markup_type": markup_type},
        fields={"markup_type": markup_type, "team_id": team_id, "team_name": team_name},
        markup_meta={},
        markup_rel_path=f"markup/{scene_id}.json",
        excalidraw_rel_path=f"{scene_id}.excalidraw",
        unidraw_rel_path=f"{scene_id}.unidraw",
        procedure_ids=procedure_ids,
        block_ids=[],
        procedure_blocks=procedure_blocks or {},
        procedure_block_graphs=procedure_block_graphs or {},
        procedure_start_blocks=procedure_start_blocks or {},
        procedure_end_blocks=procedure_end_blocks or {},
        procedure_branch_counts=procedure_branch_counts or {},
        procedure_graph=procedure_graph,
        start_block_count=start_block_count,
        branch_block_count=branch_block_count,
        non_postpone_end_block_count=non_postpone_end_block_count,
        postpone_end_block_count=postpone_end_block_count,
        has_start_end_overlap=has_start_end_overlap,
    )


def test_catalog_health_report_graph_issue_classification() -> None:
    items = [
        _catalog_item(
            scene_id="single-no-bot",
            title="Single no bot",
            team_id="team-a",
            team_name="Team A",
            procedure_graph={"entry": ["finish"]},
        ),
        _catalog_item(
            scene_id="only-bot",
            title="Only bot",
            team_id="team-a",
            team_name="Team A",
            procedure_graph={"bot_entry": ["bot_finish"]},
        ),
        _catalog_item(
            scene_id="multiple-no-bot",
            title="Multiple no bot",
            team_id="team-b",
            team_name="Team B",
            procedure_graph={
                "entry_a": ["finish_a"],
                "entry_b": ["finish_b"],
            },
        ),
        _catalog_item(
            scene_id="too-many",
            title="Too many",
            team_id="team-c",
            team_name="Team C",
            procedure_graph={
                "bot_a": [],
                "graph_b": [],
                "graph_c": [],
                "graph_d": [],
            },
        ),
    ]

    report = BuildCatalogHealthReport().build(items)

    single_no_bot = report.item("single-no-bot")
    assert single_no_bot is not None
    assert single_no_bot.graph.issue_codes == (GRAPH_ISSUE_NO_BOT,)
    assert single_no_bot.graph.bot_graph_count == 0
    assert single_no_bot.graph.multi_graph_count == 0
    assert single_no_bot.graph.employee_graph_count == 1

    only_bot = report.item("only-bot")
    assert only_bot is not None
    assert only_bot.graph.issue_codes == (GRAPH_ISSUE_ONLY_BOT,)
    assert only_bot.graph.bot_graph_count == 1
    assert only_bot.graph.multi_graph_count == 0
    assert only_bot.graph.employee_graph_count == 0

    multiple_no_bot = report.item("multiple-no-bot")
    assert multiple_no_bot is not None
    assert multiple_no_bot.graph.issue_codes == (GRAPH_ISSUE_MULTIPLE_WITHOUT_BOT,)
    assert multiple_no_bot.graph.bot_graph_count == 0
    assert multiple_no_bot.graph.multi_graph_count == 0
    assert multiple_no_bot.graph.employee_graph_count == 2

    too_many = report.item("too-many")
    assert too_many is not None
    assert too_many.graph.issue_codes == (GRAPH_ISSUE_TOO_MANY,)
    assert too_many.graph.bot_graph_count == 1
    assert too_many.graph.multi_graph_count == 0
    assert too_many.graph.employee_graph_count == 3


def test_catalog_health_report_counts_multi_and_employee_graphs() -> None:
    item = _catalog_item(
        scene_id="mixed-graphs",
        title="Mixed graphs",
        team_id="team-a",
        team_name="Team A",
        procedure_graph={
            "bot_entry": ["bot_finish"],
            "multi_entry": ["multi_finish"],
            "employee_entry": ["employee_finish"],
        },
    )

    report = BuildCatalogHealthReport().build([item])

    health = report.item("mixed-graphs")
    assert health is not None
    assert health.graph.unique_graph_count == 3
    assert health.graph.bot_graph_count == 1
    assert health.graph.multi_graph_count == 1
    assert health.graph.employee_graph_count == 1


def test_catalog_health_report_similarity_thresholds_and_team_ranking() -> None:
    item_a1 = _catalog_item(
        scene_id="team-a-1",
        title="Team A / 1",
        team_id="team-a",
        team_name="Team A",
        procedure_graph={
            "bot_a": ["bot_b"],
            "proc_shared": ["proc_shared_2"],
        },
    )
    item_a2 = _catalog_item(
        scene_id="team-a-2",
        title="Team A / 2",
        team_id="team-a",
        team_name="Team A",
        procedure_graph={
            "bot_c": ["bot_d"],
            "proc_shared": ["proc_shared_2"],
        },
    )
    item_b1 = _catalog_item(
        scene_id="team-b-1",
        title="Team B / 1",
        team_id="team-b",
        team_name="Team B",
        procedure_graph={
            "bot_e": ["bot_f"],
            "proc_shared": ["proc_x"],
        },
    )
    item_c1 = _catalog_item(
        scene_id="team-c-1",
        title="Team C / 1",
        team_id="team-c",
        team_name="Team C",
        procedure_graph={
            "bot_g": ["bot_h"],
            "proc_y": ["proc_z"],
        },
    )

    report = BuildCatalogHealthReport().build([item_a1, item_a2, item_b1, item_c1])

    health_a1 = report.item("team-a-1")
    assert health_a1 is not None
    assert health_a1.graph.is_problem is False
    assert health_a1.same_team_similarity.top_match is not None
    assert health_a1.same_team_similarity.top_match.scene_id == "team-a-2"
    assert health_a1.same_team_similarity.top_match.overlap_percent == 50.0
    assert [match.scene_id for match in health_a1.same_team_similarity.matches] == ["team-a-2"]
    assert health_a1.same_team_similarity.is_problem is True
    assert health_a1.cross_team_similarity.top_match is not None
    assert health_a1.cross_team_similarity.top_match.scene_id == "team-b-1"
    assert health_a1.cross_team_similarity.top_match.overlap_percent == 25.0
    assert [match.scene_id for match in health_a1.cross_team_similarity.matches] == [
        "team-b-1",
        "team-c-1",
    ]
    assert health_a1.cross_team_similarity.is_problem is True

    assert report.total_problem_markups == 3
    assert report.same_team_problem_count == 2
    assert report.cross_team_problem_count == 3

    assert report.team_summaries[0].team_id == "team-a"
    assert report.team_summaries[0].total_problem_markups == 2

    strict_report = BuildCatalogHealthReport(
        same_team_threshold_percent=60.0,
        cross_team_threshold_percent=30.0,
    ).build([item_a1, item_a2, item_b1, item_c1])
    strict_a1 = strict_report.item("team-a-1")
    assert strict_a1 is not None
    assert strict_a1.same_team_similarity.is_problem is False
    assert strict_a1.cross_team_similarity.is_problem is False


def test_catalog_health_report_ranks_similarity_matches() -> None:
    focus = _catalog_item(
        scene_id="focus",
        title="Focus",
        team_id="team-a",
        team_name="Team A",
        procedure_graph={
            "proc_1": ["proc_2"],
            "proc_2": ["proc_3"],
            "proc_3": ["proc_4"],
        },
    )
    same_100 = _catalog_item(
        scene_id="same-100",
        title="Same 100",
        team_id="team-a",
        team_name="Team A",
        procedure_graph={
            "proc_1": ["proc_2"],
            "proc_2": ["proc_3"],
            "proc_3": ["proc_4"],
        },
    )
    same_75 = _catalog_item(
        scene_id="same-75",
        title="Same 75",
        team_id="team-a",
        team_name="Team A",
        procedure_graph={
            "proc_1": ["proc_2"],
            "proc_2": ["proc_3"],
        },
    )
    same_50 = _catalog_item(
        scene_id="same-50",
        title="Same 50",
        team_id="team-a",
        team_name="Team A",
        procedure_graph={"proc_1": ["proc_2"]},
    )
    same_25 = _catalog_item(
        scene_id="same-25",
        title="Same 25",
        team_id="team-a",
        team_name="Team A",
        procedure_graph={"proc_1": []},
    )
    cross_100 = _catalog_item(
        scene_id="cross-100",
        title="Cross 100",
        team_id="team-b",
        team_name="Team B",
        procedure_graph={
            "proc_1": ["proc_2"],
            "proc_2": ["proc_3"],
            "proc_3": ["proc_4"],
        },
    )
    cross_75 = _catalog_item(
        scene_id="cross-75",
        title="Cross 75",
        team_id="team-c",
        team_name="Team C",
        procedure_graph={
            "proc_1": ["proc_2"],
            "proc_2": ["proc_3"],
        },
    )
    cross_50 = _catalog_item(
        scene_id="cross-50",
        title="Cross 50",
        team_id="team-d",
        team_name="Team D",
        procedure_graph={"proc_1": ["proc_2"]},
    )
    cross_25 = _catalog_item(
        scene_id="cross-25",
        title="Cross 25",
        team_id="team-e",
        team_name="Team E",
        procedure_graph={"proc_1": []},
    )

    report = BuildCatalogHealthReport().build(
        [focus, same_100, same_75, same_50, same_25, cross_100, cross_75, cross_50, cross_25]
    )

    health = report.item("focus")
    assert health is not None
    assert [match.scene_id for match in health.same_team_similarity.matches] == [
        "same-100",
        "same-75",
        "same-50",
        "same-25",
    ]
    assert [match.scene_id for match in health.cross_team_similarity.matches] == [
        "cross-100",
        "cross-75",
        "cross-50",
        "cross-25",
    ]


def test_catalog_health_report_detects_gaming_marker_problem() -> None:
    healthy = _catalog_item(
        scene_id="healthy",
        title="Healthy",
        team_id="team-a",
        team_name="Team A",
        procedure_graph={"bot_entry": ["finish"]},
        start_block_count=1,
        branch_block_count=1,
        non_postpone_end_block_count=1,
        postpone_end_block_count=0,
    )
    problematic = _catalog_item(
        scene_id="problematic",
        title="Problematic",
        team_id="team-a",
        team_name="Team A",
        procedure_graph={"bot_entry": ["postpone_only"]},
        start_block_count=1,
        branch_block_count=0,
        non_postpone_end_block_count=0,
        postpone_end_block_count=2,
    )

    report = BuildCatalogHealthReport().build([healthy, problematic])
    problematic_health = report.item("problematic")
    assert problematic_health is not None
    assert problematic_health.gaming.is_problem is True
    assert problematic_health.gaming.start_block_count == 1
    assert problematic_health.gaming.issue_codes == (GAMING_ISSUE_NO_BRANCH_AND_NO_END,)
    assert report.gaming_problem_count == 1
    assert report.total_problem_markups == 2


def test_catalog_health_report_detects_multiple_starts_without_branches() -> None:
    item = _catalog_item(
        scene_id="multiple-starts-no-branch",
        title="Multiple starts without branches",
        team_id="team-a",
        team_name="Team A",
        procedure_graph={"bot_entry": ["finish"]},
        procedure_blocks={"p1": ["a", "b", "c", "d"]},
        procedure_block_graphs={"p1": {"a": ["c"], "b": ["d"], "c": [], "d": []}},
        procedure_start_blocks={"p1": ["a", "b"]},
        procedure_branch_counts={"p1": 0},
        start_block_count=2,
        branch_block_count=0,
        non_postpone_end_block_count=1,
        postpone_end_block_count=0,
    )

    report = BuildCatalogHealthReport().build([item])

    health = report.item("multiple-starts-no-branch")
    assert health is not None
    assert health.gaming.is_problem is True
    assert health.gaming.issue_codes == (GAMING_ISSUE_MULTIPLE_STARTS_WITHOUT_BRANCH,)
    assert report.gaming_problem_count == 1


def test_catalog_health_report_allows_sequential_multiple_starts_without_branches() -> None:
    item = _catalog_item(
        scene_id="multiple-starts-sequential",
        title="Multiple starts sequential",
        team_id="team-a",
        team_name="Team A",
        procedure_graph={"bot_entry": ["finish"]},
        procedure_blocks={"p1": ["a", "b", "c"]},
        procedure_block_graphs={"p1": {"a": ["b"], "b": ["c"], "c": []}},
        procedure_start_blocks={"p1": ["a", "b"]},
        procedure_branch_counts={"p1": 0},
        start_block_count=2,
        branch_block_count=0,
        non_postpone_end_block_count=1,
        postpone_end_block_count=0,
    )

    report = BuildCatalogHealthReport().build([item])

    health = report.item("multiple-starts-sequential")
    assert health is not None
    assert health.gaming.is_problem is False
    assert health.gaming.issue_codes == ()


def test_catalog_health_report_allows_multiple_starts_that_merge_into_one_block() -> None:
    item = _catalog_item(
        scene_id="multiple-starts-merge",
        title="Multiple starts merge",
        team_id="team-a",
        team_name="Team A",
        procedure_graph={"bot_entry": ["finish"]},
        procedure_blocks={"p1": ["a", "b", "c", "d"]},
        procedure_block_graphs={"p1": {"a": ["c"], "b": ["c"], "c": ["d"], "d": []}},
        procedure_start_blocks={"p1": ["a", "b"]},
        procedure_branch_counts={"p1": 0},
        start_block_count=2,
        branch_block_count=0,
        non_postpone_end_block_count=1,
        postpone_end_block_count=0,
    )

    report = BuildCatalogHealthReport().build([item])

    health = report.item("multiple-starts-merge")
    assert health is not None
    assert health.gaming.is_problem is False
    assert health.gaming.issue_codes == ()


def test_catalog_health_report_detects_same_block_used_as_start_and_end() -> None:
    item = _catalog_item(
        scene_id="same-start-end",
        title="Same start and end",
        team_id="team-a",
        team_name="Team A",
        procedure_graph={"bot_entry": ["finish"]},
        has_start_end_overlap=True,
    )

    report = BuildCatalogHealthReport().build([item])

    health = report.item("same-start-end")
    assert health is not None
    assert health.gaming.is_problem is True
    assert health.gaming.issue_codes == (GAMING_ISSUE_SAME_START_AND_END_BLOCK,)
    assert report.gaming_problem_count == 1


def test_catalog_health_report_skips_bot_multi_validity_checks_for_task_processor() -> None:
    item = _catalog_item(
        scene_id="task-processor-without-bot-or-multi",
        title="Task processor without bot or multi",
        team_id="team-a",
        team_name="Team A",
        markup_type="system_task_processor",
        procedure_graph={"entry": ["finish"]},
    )

    report = BuildCatalogHealthReport().build([item])

    health = report.item("task-processor-without-bot-or-multi")
    assert health is not None
    assert health.graph.issue_codes == ()
    assert health.graph.is_problem is False
