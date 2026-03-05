from __future__ import annotations

from app.web_main import build_group_tree
from domain.catalog import CatalogItem


def _item(scene_id: str, markup_type: str) -> CatalogItem:
    return CatalogItem(
        scene_id=scene_id,
        title=scene_id,
        tags=[],
        updated_at="2026-01-01T00:00:00+00:00",
        markup_type=markup_type,
        finedog_unit_id="unit",
        criticality_level="unknown",
        team_id="team",
        team_name="Team",
        group_values={"markup_type": markup_type},
        fields={},
        markup_meta={},
        markup_rel_path=f"markup/{scene_id}.json",
        excalidraw_rel_path=f"{scene_id}.excalidraw",
        unidraw_rel_path=f"{scene_id}.unidraw",
    )


def test_build_group_tree_sorts_markup_type_with_service_search_before_service() -> None:
    items = [
        _item("svc", "service"),
        _item("search", "system_service_search"),
        _item("processor", "system_task_processor"),
    ]

    groups = build_group_tree(items, ["markup_type"])

    assert [group.value for group in groups] == [
        "system_service_search",
        "service",
        "system_task_processor",
    ]
