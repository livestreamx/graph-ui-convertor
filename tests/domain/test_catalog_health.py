from __future__ import annotations

from domain.catalog import CatalogItem
from domain.services.catalog_health import (
    GAMING_ISSUE_NO_BRANCH_AND_NO_END,
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
    branch_block_count: int = 1,
    non_postpone_end_block_count: int = 1,
    postpone_end_block_count: int = 0,
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
        markup_type="service",
        finedog_unit_id=scene_id,
        criticality_level="low",
        team_id=team_id,
        team_name=team_name,
        group_values={"markup_type": "service"},
        fields={"markup_type": "service", "team_id": team_id, "team_name": team_name},
        markup_meta={},
        markup_rel_path=f"markup/{scene_id}.json",
        excalidraw_rel_path=f"{scene_id}.excalidraw",
        unidraw_rel_path=f"{scene_id}.unidraw",
        procedure_ids=procedure_ids,
        block_ids=[],
        procedure_blocks={},
        procedure_graph=procedure_graph,
        branch_block_count=branch_block_count,
        non_postpone_end_block_count=non_postpone_end_block_count,
        postpone_end_block_count=postpone_end_block_count,
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

    only_bot = report.item("only-bot")
    assert only_bot is not None
    assert only_bot.graph.issue_codes == (GRAPH_ISSUE_ONLY_BOT,)

    multiple_no_bot = report.item("multiple-no-bot")
    assert multiple_no_bot is not None
    assert multiple_no_bot.graph.issue_codes == (GRAPH_ISSUE_MULTIPLE_WITHOUT_BOT,)

    too_many = report.item("too-many")
    assert too_many is not None
    assert too_many.graph.issue_codes == (GRAPH_ISSUE_TOO_MANY,)


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
    assert health_a1.same_team_similarity.is_problem is True
    assert health_a1.cross_team_similarity.top_match is not None
    assert health_a1.cross_team_similarity.top_match.scene_id == "team-b-1"
    assert health_a1.cross_team_similarity.top_match.overlap_percent == 25.0
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


def test_catalog_health_report_detects_gaming_marker_problem() -> None:
    healthy = _catalog_item(
        scene_id="healthy",
        title="Healthy",
        team_id="team-a",
        team_name="Team A",
        procedure_graph={"bot_entry": ["finish"]},
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
        branch_block_count=0,
        non_postpone_end_block_count=0,
        postpone_end_block_count=2,
    )

    report = BuildCatalogHealthReport().build([healthy, problematic])
    problematic_health = report.item("problematic")
    assert problematic_health is not None
    assert problematic_health.gaming.is_problem is True
    assert problematic_health.gaming.issue_codes == (GAMING_ISSUE_NO_BRANCH_AND_NO_END,)
    assert report.gaming_problem_count == 1
    assert report.total_problem_markups == 2
