from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

import pytest
from fastapi.testclient import TestClient

from adapters.filesystem.catalog_index_repository import FileSystemCatalogIndexRepository
from app.config import AppSettings
from app.web_main import create_app
from domain.catalog import CatalogIndex, CatalogItem


def test_excalidraw_cache_invalidated_on_start(
    tmp_path: Path,
    app_settings_factory: Callable[..., AppSettings],
) -> None:
    excalidraw_in_dir = tmp_path / "excalidraw_in"
    excalidraw_in_dir.mkdir(parents=True)
    scene_path = excalidraw_in_dir / "demo.excalidraw"
    scene_path.write_text("{}", encoding="utf-8")

    settings = app_settings_factory(
        excalidraw_in_dir=excalidraw_in_dir,
        excalidraw_out_dir=tmp_path / "excalidraw_out",
        roundtrip_dir=tmp_path / "roundtrip",
        index_path=tmp_path / "catalog" / "index.json",
        auto_build_index=False,
        generate_excalidraw_on_demand=True,
        invalidate_excalidraw_cache_on_start=True,
    )

    with TestClient(create_app(settings)) as client:
        response = client.get("/catalog")
        assert response.status_code == 200

    assert not scene_path.exists()


def test_catalog_index_cache_reuses_large_index_until_file_changes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    app_settings_factory: Callable[..., AppSettings],
) -> None:
    excalidraw_in_dir = tmp_path / "excalidraw_in"
    excalidraw_out_dir = tmp_path / "excalidraw_out"
    unidraw_in_dir = tmp_path / "unidraw_in"
    unidraw_out_dir = tmp_path / "unidraw_out"
    roundtrip_dir = tmp_path / "roundtrip"
    index_path = tmp_path / "catalog" / "index.json"
    for path in (
        excalidraw_in_dir,
        excalidraw_out_dir,
        unidraw_in_dir,
        unidraw_out_dir,
        roundtrip_dir,
    ):
        path.mkdir(parents=True)

    repo = FileSystemCatalogIndexRepository()
    repo.save(_build_large_catalog_index(320), index_path)

    settings = app_settings_factory(
        excalidraw_in_dir=excalidraw_in_dir,
        excalidraw_out_dir=excalidraw_out_dir,
        unidraw_in_dir=unidraw_in_dir,
        unidraw_out_dir=unidraw_out_dir,
        roundtrip_dir=roundtrip_dir,
        index_path=index_path,
        auto_build_index=False,
        generate_excalidraw_on_demand=False,
    )

    with TestClient(create_app(settings)) as client:
        app = cast(Any, client.app)
        context = cast(Any, app.state.context)
        original_load = cast(Callable[[Path], CatalogIndex], context.index_repo.load)
        load_calls = 0

        def counting_load(path: Path) -> CatalogIndex:
            nonlocal load_calls
            load_calls += 1
            return original_load(path)

        monkeypatch.setattr(context.index_repo, "load", counting_load)

        first_response = client.get("/catalog")
        second_response = client.get("/catalog")

        assert first_response.status_code == 200
        assert second_response.status_code == 200
        assert "320 scenes" in first_response.text
        assert "Service 0319" in first_response.text
        assert load_calls == 1

        repo.save(_build_large_catalog_index(321), index_path)

        third_response = client.get("/catalog")

        assert third_response.status_code == 200
        assert "321 scenes" in third_response.text
        assert "Service 0320" in third_response.text
        assert load_calls == 2


def _build_large_catalog_index(item_count: int) -> CatalogIndex:
    items = [_build_large_catalog_item(index) for index in range(item_count)]
    return CatalogIndex(
        generated_at="2026-03-02T00:00:00+00:00",
        group_by=["markup_type"],
        title_field="finedog_unit_meta.service_name",
        tag_fields=[],
        sort_by="title",
        sort_order="asc",
        unknown_value="unknown",
        items=items,
    )


def _build_large_catalog_item(index: int) -> CatalogItem:
    procedure_ids = [f"proc_{index:04d}_{step:02d}" for step in range(6)]
    procedure_blocks = {
        procedure_id: [f"{procedure_id}_block_{block_index:02d}" for block_index in range(3)]
        for procedure_id in procedure_ids
    }
    procedure_graph: dict[str, list[str]] = {}
    for position, procedure_id in enumerate(procedure_ids):
        next_procedures = procedure_ids[position + 1 : position + 2]
        procedure_graph[procedure_id] = next_procedures

    block_ids = [block_id for block_list in procedure_blocks.values() for block_id in block_list]

    return CatalogItem(
        scene_id=f"scene-{index:04d}",
        title=f"Service {index:04d}",
        tags=[f"team-{index % 8}"],
        updated_at="2026-03-02T00:00:00+00:00",
        markup_type="service",
        finedog_unit_id=f"unit-{index:04d}",
        criticality_level="medium",
        team_id=f"team-{index % 12:02d}",
        team_name=f"Team {index % 12:02d}",
        group_values={"markup_type": "service"},
        fields={
            "criticality_level": "medium",
            "team_id": f"team-{index % 12:02d}",
            "team_name": f"Team {index % 12:02d}",
            "finedog_unit_meta.service_name": f"Service {index:04d}",
        },
        markup_meta={},
        markup_rel_path=f"markup/service_{index:04d}.json",
        excalidraw_rel_path=f"service_{index:04d}.excalidraw",
        unidraw_rel_path=f"service_{index:04d}.unidraw",
        procedure_ids=procedure_ids,
        block_ids=block_ids,
        procedure_blocks=procedure_blocks,
        procedure_graph=procedure_graph,
        start_block_count=6,
        branch_block_count=1,
        non_postpone_end_block_count=6,
        postpone_end_block_count=0,
    )
