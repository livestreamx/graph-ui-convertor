from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from adapters.filesystem.catalog_index_repository import FileSystemCatalogIndexRepository
from adapters.s3.markup_catalog_source import S3MarkupCatalogSource
from app.config import AppSettings
from app.web_main import create_app
from domain.catalog import CatalogIndexConfig
from domain.services.build_catalog_index import BuildCatalogIndex
from tests.adapters.s3.s3_utils import stub_s3_catalog


@contextmanager
def build_catalog_health_context(
    *,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    app_settings_factory: Callable[..., AppSettings],
    settings_overrides: Mapping[str, object] | None = None,
) -> Iterator[TestClient]:
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

    objects = {
        "markup/team_a_main.json": {
            "markup_type": "service",
            "finedog_unit_meta": {
                "service_name": "Team A Main",
                "team_id": "team-a",
                "team_name": "Team A",
            },
            "procedures": [
                {
                    "proc_id": "shared_proc",
                    "start_block_ids": ["a1"],
                    "end_block_ids": ["a2"],
                    "branches": {"a1": ["a2"]},
                },
                {
                    "proc_id": "shared_proc_2",
                    "start_block_ids": ["a3"],
                    "end_block_ids": ["a4"],
                    "branches": {"a3": ["a4"]},
                },
            ],
            "procedure_graph": {"shared_proc": ["shared_proc_2"]},
        },
        "markup/team_a_peer.json": {
            "markup_type": "service",
            "finedog_unit_meta": {
                "service_name": "Team A Peer",
                "team_id": "team-a",
                "team_name": "Team A",
            },
            "procedures": [
                {
                    "proc_id": "shared_proc",
                    "start_block_ids": ["b1"],
                    "end_block_ids": ["b2"],
                    "branches": {"b1": ["b2"]},
                },
                {
                    "proc_id": "shared_proc_2",
                    "start_block_ids": ["b3"],
                    "end_block_ids": ["b4"],
                    "branches": {"b3": ["b4"]},
                },
            ],
            "procedure_graph": {"shared_proc": ["shared_proc_2"]},
        },
        "markup/team_b_overlap.json": {
            "markup_type": "service",
            "finedog_unit_meta": {
                "service_name": "Team B Overlap",
                "team_id": "team-b",
                "team_name": "Team B",
            },
            "procedures": [
                {
                    "proc_id": "shared_proc",
                    "start_block_ids": ["c1"],
                    "end_block_ids": ["c2"],
                    "branches": {"c1": ["c2"]},
                },
                {
                    "proc_id": "team_b_unique",
                    "start_block_ids": ["c3"],
                    "end_block_ids": ["c4"],
                    "branches": {"c3": ["c4"]},
                },
            ],
            "procedure_graph": {"shared_proc": ["team_b_unique"]},
        },
        "markup/team_z_healthy.json": {
            "markup_type": "service",
            "finedog_unit_meta": {
                "service_name": "Team Z Healthy",
                "team_id": "team-z",
                "team_name": "Team Z",
            },
            "procedures": [
                {
                    "proc_id": "bot_team_z",
                    "start_block_ids": ["z1"],
                    "end_block_ids": ["z2"],
                    "branches": {"z1": ["z2"]},
                },
                {
                    "proc_id": "team_z_employee",
                    "start_block_ids": ["z3"],
                    "end_block_ids": ["z4"],
                    "branches": {"z3": ["z4"]},
                },
            ],
            "procedure_graph": {
                "bot_team_z": ["bot_team_z_end"],
                "team_z_employee": ["team_z_employee_end"],
            },
        },
        "markup/team_g_gaming_problem.json": {
            "markup_type": "service",
            "finedog_unit_meta": {
                "service_name": "Team G Gaming Problem",
                "team_id": "team-g",
                "team_name": "Team G",
            },
            "procedures": [
                {
                    "proc_id": "bot_team_g",
                    "start_block_ids": ["g1"],
                    "end_block_ids": ["g2::postpone"],
                    "branches": {"g1": ["g2"]},
                }
            ],
            "procedure_graph": {"bot_team_g": ["bot_team_g_postpone"]},
        },
    }

    client, stubber = stub_s3_catalog(
        monkeypatch=monkeypatch,
        objects=objects,
        bucket="cjm-bucket",
        prefix="markup/",
    )

    config = CatalogIndexConfig(
        markup_dir=Path("markup"),
        excalidraw_in_dir=excalidraw_in_dir,
        unidraw_in_dir=unidraw_in_dir,
        index_path=index_path,
        group_by=["markup_type"],
        title_field="finedog_unit_meta.service_name",
        tag_fields=[],
        sort_by="title",
        sort_order="asc",
        unknown_value="unknown",
    )
    BuildCatalogIndex(
        S3MarkupCatalogSource(client, "cjm-bucket", "markup/"),
        FileSystemCatalogIndexRepository(),
    ).build(config)

    settings_kwargs: dict[str, object] = {
        "diagram_excalidraw_enabled": True,
        "excalidraw_in_dir": excalidraw_in_dir,
        "excalidraw_out_dir": excalidraw_out_dir,
        "unidraw_in_dir": unidraw_in_dir,
        "unidraw_out_dir": unidraw_out_dir,
        "roundtrip_dir": roundtrip_dir,
        "index_path": index_path,
    }
    if settings_overrides:
        settings_kwargs.update(dict(settings_overrides))
    settings = app_settings_factory(**settings_kwargs)

    client_api = TestClient(create_app(settings))
    try:
        yield client_api
    finally:
        client_api.close()
        stubber.deactivate()


def _scene_id_by_title(client: TestClient, title: str) -> str:
    index_response = client.get("/api/index")
    assert index_response.status_code == 200
    for item in index_response.json()["items"]:
        if item["title"] == title:
            return str(item["scene_id"])
    raise AssertionError(f"Scene not found for title: {title}")


def test_catalog_health_markers_and_problem_filter(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    app_settings_factory: Callable[..., AppSettings],
) -> None:
    with build_catalog_health_context(
        tmp_path=tmp_path,
        monkeypatch=monkeypatch,
        app_settings_factory=app_settings_factory,
    ) as client:
        catalog_response = client.get("/catalog")
        assert catalog_response.status_code == 200
        assert "Analytics by teams" in catalog_response.text
        assert 'data-health-marker="graphs"' in catalog_response.text
        assert 'data-health-marker="same-team"' in catalog_response.text
        assert 'data-health-marker="cross-team"' in catalog_response.text
        assert 'data-health-marker="gaming"' in catalog_response.text

        filtered = client.get("/catalog", params={"health_problem": "1"})
        assert filtered.status_code == 200
        assert "Team A Main" in filtered.text
        assert "Team A Peer" in filtered.text
        assert "Team B Overlap" in filtered.text
        assert "Team G Gaming Problem" in filtered.text
        assert "Team Z Healthy" not in filtered.text


def test_catalog_detail_renders_health_section(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    app_settings_factory: Callable[..., AppSettings],
) -> None:
    with build_catalog_health_context(
        tmp_path=tmp_path,
        monkeypatch=monkeypatch,
        app_settings_factory=app_settings_factory,
    ) as client:
        scene_id = _scene_id_by_title(client, "Team A Main")
        response = client.get(f"/catalog/{scene_id}")
        assert response.status_code == 200
        assert "Markup health markers" in response.text
        assert "Closest markup in team" in response.text
        assert "Closest markup across teams" in response.text
        assert "Problem threshold" in response.text
        assert "Gaming validity" in response.text
        assert "End blocks except postpone" in response.text


def test_catalog_teams_health_page_and_thresholds(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    app_settings_factory: Callable[..., AppSettings],
) -> None:
    with build_catalog_health_context(
        tmp_path=tmp_path,
        monkeypatch=monkeypatch,
        app_settings_factory=app_settings_factory,
        settings_overrides={
            "health_same_team_overlap_threshold_percent": 55.0,
            "health_cross_team_overlap_threshold_percent": 25.0,
        },
    ) as client:
        response = client.get("/catalog/teams/health")
        assert response.status_code == 200
        assert "Ranking by markup health problems" in response.text
        assert "Total health summary" in response.text
        assert "Team A" in response.text
        assert "Team B" in response.text
        assert "Team Z" in response.text
        assert "Team G" in response.text
        assert "Gaming marker problems" in response.text
        assert "&gt;55.0%" in response.text
        assert "&gt;25.0%" in response.text

        catalog_response = client.get("/catalog")
        assert catalog_response.status_code == 200
        assert 'href="/catalog/teams/health?lang=en"' in catalog_response.text
