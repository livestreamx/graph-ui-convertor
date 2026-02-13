from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import Path
from typing import cast

import pytest
from fastapi.testclient import TestClient

from adapters.filesystem.catalog_index_repository import FileSystemCatalogIndexRepository
from adapters.s3.markup_catalog_source import S3MarkupCatalogSource
from app.config import AppSettings
from app.web_main import create_app
from domain.catalog import CatalogIndexConfig
from domain.services.build_catalog_index import BuildCatalogIndex
from tests.adapters.s3.s3_utils import add_get_object, stub_s3_catalog
from tests.helpers.markup_fixtures import load_markup_payload, repo_root


def _load_fixture(name: str) -> dict[str, object]:
    return cast(dict[str, object], load_markup_payload(name))


def _repo_root() -> Path:
    return repo_root()


def test_catalog_team_graph_api(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    app_settings_factory: Callable[..., AppSettings],
) -> None:
    excalidraw_in_dir = tmp_path / "excalidraw_in"
    excalidraw_out_dir = tmp_path / "excalidraw_out"
    roundtrip_dir = tmp_path / "roundtrip"
    index_path = tmp_path / "catalog" / "index.json"

    excalidraw_in_dir.mkdir(parents=True)
    excalidraw_out_dir.mkdir(parents=True)
    roundtrip_dir.mkdir(parents=True)

    payload_alpha = {
        "markup_type": "service",
        "finedog_unit_meta": {
            "service_name": "Payments",
            "team_id": "team-1",
            "team_name": "Alpha",
        },
        "procedures": [
            {
                "proc_id": "p1",
                "proc_name": "Authorize",
                "start_block_ids": ["a"],
                "end_block_ids": ["b"],
                "branches": {"a": ["b"]},
            }
        ],
        "procedure_graph": {"p1": []},
    }
    payload_beta = {
        "markup_type": "service",
        "finedog_unit_meta": {
            "service_name": "Refunds",
            "team_id": "team-2",
            "team_name": "Beta",
        },
        "procedures": [
            {
                "proc_id": "p2",
                "proc_name": "Refund",
                "start_block_ids": ["c"],
                "end_block_ids": ["d"],
                "branches": {"c": ["d"]},
            }
        ],
        "procedure_graph": {"p2": []},
    }
    objects = {
        "markup/alpha.json": payload_alpha,
        "markup/beta.json": payload_beta,
    }
    client, stubber = stub_s3_catalog(
        monkeypatch=monkeypatch,
        objects=objects,
        bucket="cjm-bucket",
        prefix="markup/",
        list_repeats=1,
    )
    add_get_object(stubber, bucket="cjm-bucket", key="markup/alpha.json", payload=payload_alpha)
    add_get_object(stubber, bucket="cjm-bucket", key="markup/beta.json", payload=payload_beta)
    add_get_object(stubber, bucket="cjm-bucket", key="markup/alpha.json", payload=payload_alpha)
    add_get_object(stubber, bucket="cjm-bucket", key="markup/beta.json", payload=payload_beta)
    add_get_object(stubber, bucket="cjm-bucket", key="markup/alpha.json", payload=payload_alpha)
    add_get_object(stubber, bucket="cjm-bucket", key="markup/beta.json", payload=payload_beta)

    config = CatalogIndexConfig(
        markup_dir=Path("markup"),
        excalidraw_in_dir=excalidraw_in_dir,
        index_path=index_path,
        group_by=["markup_type"],
        title_field="finedog_unit_meta.service_name",
        tag_fields=[],
        sort_by="title",
        sort_order="asc",
        unknown_value="unknown",
    )
    try:
        BuildCatalogIndex(
            S3MarkupCatalogSource(client, "cjm-bucket", "markup/"),
            FileSystemCatalogIndexRepository(),
        ).build(config)

        settings = app_settings_factory(
            excalidraw_in_dir=excalidraw_in_dir,
            excalidraw_out_dir=excalidraw_out_dir,
            roundtrip_dir=roundtrip_dir,
            index_path=index_path,
            excalidraw_base_url="http://example.com",
        )
        client_api = TestClient(create_app(settings))

        response = client_api.get(
            "/api/teams/graph",
            params={"team_ids": "team-1,team-2"},
        )
        assert response.status_code == 200
        elements = response.json()["elements"]
        assert any(
            element.get("customData", {}).get("cjm", {}).get("role") == "procedure_stat"
            for element in elements
        )

        service_response = client_api.get(
            "/api/teams/graph",
            params={"team_ids": "team-1,team-2", "graph_level": "service"},
        )
        assert service_response.status_code == 200
        service_elements = service_response.json()["elements"]
        service_frames = [
            element.get("customData", {}).get("cjm", {}).get("procedure_id")
            for element in service_elements
            if element.get("customData", {}).get("cjm", {}).get("role") == "frame"
        ]
        assert len(service_frames) == 2
        assert all(
            isinstance(proc_id, str) and proc_id.startswith("service::")
            for proc_id in service_frames
        )
        assert not any(
            str(element.get("customData", {}).get("cjm", {}).get("role", "")).startswith("scenario")
            for element in service_elements
        )

        html_response = client_api.get(
            "/catalog/teams/graph",
            params={"team_ids": "team-1,team-2"},
        )
        assert html_response.status_code == 200
        assert "Merge" in html_response.text
        assert "Alpha" in html_response.text
        assert "Beta" in html_response.text
        assert "markups merged" in html_response.text
        assert "1 markup" in html_response.text
        assert "Cross-team graphs builder" in html_response.text
        assert "Step 1. Select teams" in html_response.text
        assert "Step 2. Feature flags" in html_response.text
        assert "Merge node chain threshold" in html_response.text
        assert "How merge chain threshold works" in html_response.text
        assert "Cycles are excluded from merge-chain detection." in html_response.text
        assert "Branch/fork and join procedures are treated as chain boundaries" in (
            html_response.text
        )
        assert 'id="merge_node_min_chain_size"' in html_response.text
        assert 'name="merge_node_min_chain_size"' in html_response.text
        assert 'min="0"' in html_response.text
        assert 'max="10"' in html_response.text
        assert 'step="1"' in html_response.text
        assert "Merge markups by shared nodes" in html_response.text
        assert "How selected graphs render their components in according to shared nodes." in (
            html_response.text
        )
        assert "Render merge nodes from all available markups" in html_response.text
        assert "Step 3. Merge graphs" in html_response.text
        assert "Step 4. Analyze graphs" in html_response.text
        assert "Step 5. Get diagram" in html_response.text
        assert "Procedure-level diagram" in html_response.text
        assert "Service-level diagram" in html_response.text
        assert "graph_level=service" in html_response.text
        assert "graph_level=procedure" not in html_response.text
        assert "Graphs info" in html_response.text
        assert "Entity integrity" in html_response.text
        assert "Risk hotspots" in html_response.text
        assert "team-graph-dashboard-section-collapsible" in html_response.text
        assert "Click to expand" in html_response.text
        assert "data-team-graph-analysis-host" in html_response.text
        assert "Graphs" in html_response.text
        assert "Unique procedures" in html_response.text
        assert "Multichannel procedures" in html_response.text
        assert "Employee procedures" in html_response.text
        assert "External team overlaps" in html_response.text
        assert "data-overlap-team-toggle" in html_response.text
        assert 'data-team="Alpha"' in html_response.text
        assert 'data-team="Beta"' in html_response.text
        assert "team-graph-ranked-details-list-entity" in html_response.text
        assert "team-graph-graph-entity-type" in html_response.text
        assert "Graph-level breakdown" in html_response.text
        assert "Procedure-level breakdown (graph order, potential merges)" in html_response.text
        assert "data-sortable-table" in html_response.text
        assert "data-sort-trigger" in html_response.text
        assert 'data-sort-key="link-count"' not in html_response.text
        assert "Potential merges" in html_response.text
        assert "Merges" in html_response.text
        assert "Links" in html_response.text
        assert "team-graph-procedure-block-type" in html_response.text
        assert "Starts:" not in html_response.text
        assert "Ends:" not in html_response.text
        assert "End (" not in html_response.text
        assert "team-graph-procedure-order" in html_response.text
        assert "team-graph-procedure-id" in html_response.text
        assert "Data quality note" not in html_response.text
        assert "Ranking priority: cross-entity reuse" in html_response.text
        assert "Ranking priority: merges" in html_response.text
        assert "team-graph-graphs-row-header" in html_response.text
        assert "team-graph-graphs-count-value" in html_response.text
        assert "--team-chip-border" in html_response.text
        assert "const hueForTeam = (teamName)" in html_response.text
        assert 'id="team-graph-page"' in html_response.text
        assert 'hx-get="/catalog/teams/graph"' in html_response.text
        assert 'hx-target="#team-graph-page"' in html_response.text
        assert 'hx-select="#team-graph-page"' in html_response.text
        assert 'hx-push-url="true"' in html_response.text
        assert 'hx-indicator="#team-graph-merge-loader"' in html_response.text
        assert "team-graph-cta-warning is-hidden" in html_response.text
        assert 'id="team-graph-merge-loader"' in html_response.text
        assert (
            "Scene is injected via local storage for same-origin Excalidraw."
            not in html_response.text
        )
        assert (
            "Open the team graph in Excalidraw or download the file for manual import and editing."
            not in html_response.text
        )

        no_selection_response = client_api.get("/catalog/teams/graph")
        assert no_selection_response.status_code == 200
        assert "data-merge-button" in no_selection_response.text
        assert 'disabled aria-disabled="true"' in no_selection_response.text
        assert "Select at least one team to enable Merge." in no_selection_response.text
    finally:
        stubber.deactivate()


def test_api_team_graph_localizes_markup_type_column_titles_by_ui_language(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    app_settings_factory: Callable[..., AppSettings],
) -> None:
    excalidraw_in_dir = tmp_path / "excalidraw_in"
    excalidraw_out_dir = tmp_path / "excalidraw_out"
    roundtrip_dir = tmp_path / "roundtrip"
    index_path = tmp_path / "catalog" / "index.json"

    excalidraw_in_dir.mkdir(parents=True)
    excalidraw_out_dir.mkdir(parents=True)
    roundtrip_dir.mkdir(parents=True)

    payload_search = {
        "markup_type": "system_service_search",
        "finedog_unit_meta": {
            "service_name": "Search Service",
            "team_id": "team-a",
            "team_name": "Alpha",
        },
        "procedures": [
            {
                "proc_id": "p_search",
                "proc_name": "Search",
                "start_block_ids": ["a"],
                "end_block_ids": ["b"],
                "branches": {"a": ["b"]},
            }
        ],
        "procedure_graph": {"p_search": []},
    }
    payload_service = {
        "markup_type": "service",
        "finedog_unit_meta": {
            "service_name": "Billing Service",
            "team_id": "team-b",
            "team_name": "Beta",
        },
        "procedures": [
            {
                "proc_id": "p_service",
                "proc_name": "Billing",
                "start_block_ids": ["c"],
                "end_block_ids": ["d"],
                "branches": {"c": ["d"]},
            }
        ],
        "procedure_graph": {"p_service": []},
    }
    objects = {
        "markup/search.json": payload_search,
        "markup/service.json": payload_service,
    }
    client, stubber = stub_s3_catalog(
        monkeypatch=monkeypatch,
        objects=objects,
        bucket="cjm-bucket",
        prefix="markup/",
        list_repeats=1,
    )
    add_get_object(
        stubber,
        bucket="cjm-bucket",
        key="markup/service.json",
        payload=payload_service,
    )
    add_get_object(
        stubber,
        bucket="cjm-bucket",
        key="markup/search.json",
        payload=payload_search,
    )
    add_get_object(
        stubber,
        bucket="cjm-bucket",
        key="markup/service.json",
        payload=payload_service,
    )
    add_get_object(
        stubber,
        bucket="cjm-bucket",
        key="markup/search.json",
        payload=payload_search,
    )

    config = CatalogIndexConfig(
        markup_dir=Path("markup"),
        excalidraw_in_dir=excalidraw_in_dir,
        index_path=index_path,
        group_by=["markup_type"],
        title_field="finedog_unit_meta.service_name",
        tag_fields=[],
        sort_by="title",
        sort_order="asc",
        unknown_value="unknown",
    )

    client_api: TestClient | None = None
    try:
        BuildCatalogIndex(
            S3MarkupCatalogSource(client, "cjm-bucket", "markup/"),
            FileSystemCatalogIndexRepository(),
        ).build(config)

        settings = app_settings_factory(
            excalidraw_in_dir=excalidraw_in_dir,
            excalidraw_out_dir=excalidraw_out_dir,
            roundtrip_dir=roundtrip_dir,
            index_path=index_path,
            excalidraw_base_url="http://example.com",
        )
        client_api = TestClient(create_app(settings))

        params = {"team_ids": "team-a,team-b"}
        ru_response = client_api.get("/api/teams/graph", params={**params, "lang": "ru"})
        assert ru_response.status_code == 200
        ru_titles = {
            str(element.get("text", "")).replace("\n", " ").strip()
            for element in ru_response.json()["elements"]
            if element.get("customData", {}).get("cjm", {}).get("role")
            == "markup_type_column_title"
        }
        assert "Система поиска услуги" in ru_titles
        assert "Услуга" in ru_titles

        en_response = client_api.get("/api/teams/graph", params={**params, "lang": "en"})
        assert en_response.status_code == 200
        en_titles = {
            str(element.get("text", "")).replace("\n", " ").strip()
            for element in en_response.json()["elements"]
            if element.get("customData", {}).get("cjm", {}).get("role")
            == "markup_type_column_title"
        }
        assert "Service Search System" in en_titles
        assert "Service" in en_titles
    finally:
        if client_api is not None:
            client_api.close()
        stubber.deactivate()


def test_catalog_team_graph_excluded_teams_preselected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    app_settings_factory: Callable[..., AppSettings],
) -> None:
    excalidraw_in_dir = tmp_path / "excalidraw_in"
    excalidraw_out_dir = tmp_path / "excalidraw_out"
    roundtrip_dir = tmp_path / "roundtrip"
    index_path = tmp_path / "catalog" / "index.json"

    excalidraw_in_dir.mkdir(parents=True)
    excalidraw_out_dir.mkdir(parents=True)
    roundtrip_dir.mkdir(parents=True)

    payload_alpha = {
        "markup_type": "service",
        "finedog_unit_meta": {
            "service_name": "Payments",
            "team_id": "team-1",
            "team_name": "Alpha",
        },
        "procedures": [
            {
                "proc_id": "p1",
                "proc_name": "Authorize",
                "start_block_ids": ["a"],
                "end_block_ids": ["b"],
                "branches": {"a": ["b"]},
            }
        ],
        "procedure_graph": {"p1": []},
    }
    payload_beta = {
        "markup_type": "service",
        "finedog_unit_meta": {
            "service_name": "Refunds",
            "team_id": "team-2",
            "team_name": "Beta",
        },
        "procedures": [
            {
                "proc_id": "p2",
                "proc_name": "Refund",
                "start_block_ids": ["c"],
                "end_block_ids": ["d"],
                "branches": {"c": ["d"]},
            }
        ],
        "procedure_graph": {"p2": []},
    }
    objects = {
        "markup/alpha.json": payload_alpha,
        "markup/beta.json": payload_beta,
    }
    client, stubber = stub_s3_catalog(
        monkeypatch=monkeypatch,
        objects=objects,
        bucket="cjm-bucket",
        prefix="markup/",
        list_repeats=1,
    )

    config = CatalogIndexConfig(
        markup_dir=Path("markup"),
        excalidraw_in_dir=excalidraw_in_dir,
        index_path=index_path,
        group_by=["markup_type"],
        title_field="finedog_unit_meta.service_name",
        tag_fields=[],
        sort_by="title",
        sort_order="asc",
        unknown_value="unknown",
    )
    try:
        BuildCatalogIndex(
            S3MarkupCatalogSource(client, "cjm-bucket", "markup/"),
            FileSystemCatalogIndexRepository(),
        ).build(config)

        settings = app_settings_factory(
            excalidraw_in_dir=excalidraw_in_dir,
            excalidraw_out_dir=excalidraw_out_dir,
            roundtrip_dir=roundtrip_dir,
            index_path=index_path,
            excalidraw_base_url="http://example.com",
            builder_excluded_team_ids=["team-2"],
        )
        client_api = TestClient(create_app(settings))

        response = client_api.get("/catalog/teams/graph")
        assert response.status_code == 200
        html = response.text
        assert "Disable teams from analytics" in html
        exclude_match = re.search(r'id="team-graph-exclude-select".*?</select>', html, re.S)
        assert exclude_match is not None
        assert re.search(r'value="team-2"[^>]*selected', exclude_match.group(0))
        select_match = re.search(r'id="team-graph-select".*?</select>', html, re.S)
        assert select_match is not None
        assert 'value="team-2"' in select_match.group(0)
        assert 'id="team-graph-exclude-input"' in html
        assert 'value="team-2"' in html
    finally:
        stubber.deactivate()


def test_catalog_team_graph_excluded_team_name_not_overridden_by_unknown_value(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    app_settings_factory: Callable[..., AppSettings],
) -> None:
    excalidraw_in_dir = tmp_path / "excalidraw_in"
    excalidraw_out_dir = tmp_path / "excalidraw_out"
    roundtrip_dir = tmp_path / "roundtrip"
    index_path = tmp_path / "catalog" / "index.json"

    excalidraw_in_dir.mkdir(parents=True)
    excalidraw_out_dir.mkdir(parents=True)
    roundtrip_dir.mkdir(parents=True)

    payload_beta_named = {
        "markup_type": "service",
        "finedog_unit_meta": {
            "service_name": "Refunds",
            "team_id": "team-2",
            "team_name": "Beta",
        },
        "procedures": [
            {
                "proc_id": "p2",
                "proc_name": "Refund",
                "start_block_ids": ["c"],
                "end_block_ids": ["d"],
                "branches": {"c": ["d"]},
            }
        ],
        "procedure_graph": {"p2": []},
    }
    payload_beta_unknown = {
        "markup_type": "service",
        "finedog_unit_meta": {
            "service_name": "Chargebacks",
            "team_id": "team-2",
            "team_name": "unknown",
        },
        "procedures": [
            {
                "proc_id": "p3",
                "proc_name": "Chargeback",
                "start_block_ids": ["e"],
                "end_block_ids": ["f"],
                "branches": {"e": ["f"]},
            }
        ],
        "procedure_graph": {"p3": []},
    }
    objects = {
        "markup/beta-named.json": payload_beta_named,
        "markup/beta-unknown.json": payload_beta_unknown,
    }
    client, stubber = stub_s3_catalog(
        monkeypatch=monkeypatch,
        objects=objects,
        bucket="cjm-bucket",
        prefix="markup/",
        list_repeats=1,
    )

    config = CatalogIndexConfig(
        markup_dir=Path("markup"),
        excalidraw_in_dir=excalidraw_in_dir,
        index_path=index_path,
        group_by=["markup_type"],
        title_field="finedog_unit_meta.service_name",
        tag_fields=[],
        sort_by="title",
        sort_order="asc",
        unknown_value="unknown",
    )
    try:
        BuildCatalogIndex(
            S3MarkupCatalogSource(client, "cjm-bucket", "markup/"),
            FileSystemCatalogIndexRepository(),
        ).build(config)

        settings = app_settings_factory(
            excalidraw_in_dir=excalidraw_in_dir,
            excalidraw_out_dir=excalidraw_out_dir,
            roundtrip_dir=roundtrip_dir,
            index_path=index_path,
            excalidraw_base_url="http://example.com",
            builder_excluded_team_ids=["team-2"],
        )
        client_api = TestClient(create_app(settings))

        response = client_api.get("/catalog/teams/graph")
        assert response.status_code == 200
        html = response.text
        exclude_match = re.search(r'id="team-graph-exclude-select".*?</select>', html, re.S)
        assert exclude_match is not None
        option_match = re.search(
            r'<option[^>]*value="team-2"[^>]*>\s*([^<]+?)\s*</option>',
            exclude_match.group(0),
            re.S,
        )
        assert option_match is not None
        assert option_match.group(1).strip() == "Beta"
    finally:
        stubber.deactivate()


def test_catalog_team_graph_excluded_team_ids_query_bracket_value(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    app_settings_factory: Callable[..., AppSettings],
) -> None:
    excalidraw_in_dir = tmp_path / "excalidraw_in"
    excalidraw_out_dir = tmp_path / "excalidraw_out"
    roundtrip_dir = tmp_path / "roundtrip"
    index_path = tmp_path / "catalog" / "index.json"

    excalidraw_in_dir.mkdir(parents=True)
    excalidraw_out_dir.mkdir(parents=True)
    roundtrip_dir.mkdir(parents=True)

    payload_alpha = {
        "markup_type": "service",
        "finedog_unit_meta": {
            "service_name": "Payments",
            "team_id": "team-1",
            "team_name": "Alpha",
        },
        "procedures": [
            {
                "proc_id": "p1",
                "proc_name": "Authorize",
                "start_block_ids": ["a"],
                "end_block_ids": ["b"],
                "branches": {"a": ["b"]},
            }
        ],
        "procedure_graph": {"p1": []},
    }
    payload_beta = {
        "markup_type": "service",
        "finedog_unit_meta": {
            "service_name": "Refunds",
            "team_id": "team-2",
            "team_name": "Beta",
        },
        "procedures": [
            {
                "proc_id": "p2",
                "proc_name": "Refund",
                "start_block_ids": ["c"],
                "end_block_ids": ["d"],
                "branches": {"c": ["d"]},
            }
        ],
        "procedure_graph": {"p2": []},
    }
    objects = {
        "markup/alpha.json": payload_alpha,
        "markup/beta.json": payload_beta,
    }
    client, stubber = stub_s3_catalog(
        monkeypatch=monkeypatch,
        objects=objects,
        bucket="cjm-bucket",
        prefix="markup/",
        list_repeats=1,
    )

    config = CatalogIndexConfig(
        markup_dir=Path("markup"),
        excalidraw_in_dir=excalidraw_in_dir,
        index_path=index_path,
        group_by=["markup_type"],
        title_field="finedog_unit_meta.service_name",
        tag_fields=[],
        sort_by="title",
        sort_order="asc",
        unknown_value="unknown",
    )
    try:
        BuildCatalogIndex(
            S3MarkupCatalogSource(client, "cjm-bucket", "markup/"),
            FileSystemCatalogIndexRepository(),
        ).build(config)

        settings = app_settings_factory(
            excalidraw_in_dir=excalidraw_in_dir,
            excalidraw_out_dir=excalidraw_out_dir,
            roundtrip_dir=roundtrip_dir,
            index_path=index_path,
            excalidraw_base_url="http://example.com",
        )
        client_api = TestClient(create_app(settings))

        response = client_api.get("/catalog/teams/graph?excluded_team_ids=[team-2]")
        assert response.status_code == 200
        html = response.text

        exclude_match = re.search(r'id="team-graph-exclude-select".*?</select>', html, re.S)
        assert exclude_match is not None
        option_match = re.search(
            r'<option[^>]*value="team-2"[^>]*>\s*([^<]+?)\s*</option>',
            exclude_match.group(0),
            re.S,
        )
        assert option_match is not None
        assert option_match.group(1).strip() == "Beta"
        assert re.search(r'value="team-2"[^>]*selected', exclude_match.group(0))
    finally:
        stubber.deactivate()


def test_api_team_graph_keeps_selected_teams_even_when_excluded(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    app_settings_factory: Callable[..., AppSettings],
) -> None:
    excalidraw_in_dir = tmp_path / "excalidraw_in"
    excalidraw_out_dir = tmp_path / "excalidraw_out"
    roundtrip_dir = tmp_path / "roundtrip"
    index_path = tmp_path / "catalog" / "index.json"

    excalidraw_in_dir.mkdir(parents=True)
    excalidraw_out_dir.mkdir(parents=True)
    roundtrip_dir.mkdir(parents=True)

    payload_beta = {
        "markup_type": "service",
        "finedog_unit_meta": {
            "service_name": "Refunds",
            "team_id": "team-2",
            "team_name": "Beta",
        },
        "procedures": [
            {
                "proc_id": "p2",
                "proc_name": "Refund",
                "start_block_ids": ["c"],
                "end_block_ids": ["d"],
                "branches": {"c": ["d"]},
            }
        ],
        "procedure_graph": {"p2": []},
    }
    objects = {"markup/beta.json": payload_beta}
    client, stubber = stub_s3_catalog(
        monkeypatch=monkeypatch,
        objects=objects,
        bucket="cjm-bucket",
        prefix="markup/",
        list_repeats=1,
    )
    add_get_object(stubber, bucket="cjm-bucket", key="markup/beta.json", payload=payload_beta)

    config = CatalogIndexConfig(
        markup_dir=Path("markup"),
        excalidraw_in_dir=excalidraw_in_dir,
        index_path=index_path,
        group_by=["markup_type"],
        title_field="finedog_unit_meta.service_name",
        tag_fields=[],
        sort_by="title",
        sort_order="asc",
        unknown_value="unknown",
    )
    try:
        BuildCatalogIndex(
            S3MarkupCatalogSource(client, "cjm-bucket", "markup/"),
            FileSystemCatalogIndexRepository(),
        ).build(config)

        settings = app_settings_factory(
            excalidraw_in_dir=excalidraw_in_dir,
            excalidraw_out_dir=excalidraw_out_dir,
            roundtrip_dir=roundtrip_dir,
            index_path=index_path,
            excalidraw_base_url="http://example.com",
        )
        client_api = TestClient(create_app(settings))

        response = client_api.get(
            "/api/teams/graph",
            params={"team_ids": "team-2", "excluded_team_ids": "team-2"},
        )
        assert response.status_code == 200
        elements = response.json()["elements"]
        assert any(
            element.get("customData", {}).get("cjm", {}).get("role") == "procedure_stat"
            for element in elements
        )
    finally:
        stubber.deactivate()


def test_catalog_team_graph_merge_nodes_use_all_markups(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    app_settings_factory: Callable[..., AppSettings],
) -> None:
    excalidraw_in_dir = tmp_path / "excalidraw_in"
    excalidraw_out_dir = tmp_path / "excalidraw_out"
    roundtrip_dir = tmp_path / "roundtrip"
    index_path = tmp_path / "catalog" / "index.json"

    excalidraw_in_dir.mkdir(parents=True)
    excalidraw_out_dir.mkdir(parents=True)
    roundtrip_dir.mkdir(parents=True)

    payload_basic = _load_fixture("basic.json")
    payload_graphs = _load_fixture("graphs_set.json")
    meta = payload_basic.get("finedog_unit_meta")
    assert isinstance(meta, dict)
    team_id = meta.get("team_id")
    assert isinstance(team_id, str)

    objects = {
        "markup/basic.json": payload_basic,
        "markup/graphs_set.json": payload_graphs,
    }
    client, stubber = stub_s3_catalog(
        monkeypatch=monkeypatch,
        objects=objects,
        bucket="cjm-bucket",
        prefix="markup/",
        list_repeats=1,
    )
    add_get_object(stubber, bucket="cjm-bucket", key="markup/basic.json", payload=payload_basic)
    add_get_object(
        stubber, bucket="cjm-bucket", key="markup/graphs_set.json", payload=payload_graphs
    )
    add_get_object(stubber, bucket="cjm-bucket", key="markup/basic.json", payload=payload_basic)
    add_get_object(
        stubber, bucket="cjm-bucket", key="markup/graphs_set.json", payload=payload_graphs
    )
    add_get_object(stubber, bucket="cjm-bucket", key="markup/basic.json", payload=payload_basic)
    add_get_object(
        stubber, bucket="cjm-bucket", key="markup/graphs_set.json", payload=payload_graphs
    )

    config = CatalogIndexConfig(
        markup_dir=Path("markup"),
        excalidraw_in_dir=excalidraw_in_dir,
        index_path=index_path,
        group_by=["markup_type"],
        title_field="finedog_unit_meta.service_name",
        tag_fields=[],
        sort_by="title",
        sort_order="asc",
        unknown_value="unknown",
    )
    try:
        BuildCatalogIndex(
            S3MarkupCatalogSource(client, "cjm-bucket", "markup/"),
            FileSystemCatalogIndexRepository(),
        ).build(config)

        settings = app_settings_factory(
            excalidraw_in_dir=excalidraw_in_dir,
            excalidraw_out_dir=excalidraw_out_dir,
            roundtrip_dir=roundtrip_dir,
            index_path=index_path,
            excalidraw_base_url="http://example.com",
        )
        client_api = TestClient(create_app(settings))

        response = client_api.get(
            "/api/teams/graph",
            params={"team_ids": team_id, "merge_nodes_all_markups": "true"},
        )
        assert response.status_code == 200
        elements = response.json()["elements"]
        merge_ids: set[str] = set()
        for element in elements:
            if element.get("customData", {}).get("cjm", {}).get("role") != "intersection_highlight":
                continue
            proc_id = element.get("customData", {}).get("cjm", {}).get("procedure_id")
            if isinstance(proc_id, str):
                merge_ids.add(proc_id)
        assert "proc_shared_routing" in merge_ids
        assert "proc_shared_intake" in merge_ids
    finally:
        stubber.deactivate()


def test_catalog_team_graph_open_preserves_merge_flag_in_scene_api_url(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    app_settings_factory: Callable[..., AppSettings],
) -> None:
    excalidraw_in_dir = tmp_path / "excalidraw_in"
    excalidraw_out_dir = tmp_path / "excalidraw_out"
    roundtrip_dir = tmp_path / "roundtrip"
    index_path = tmp_path / "catalog" / "index.json"

    excalidraw_in_dir.mkdir(parents=True)
    excalidraw_out_dir.mkdir(parents=True)
    roundtrip_dir.mkdir(parents=True)

    payload_basic = _load_fixture("basic.json")
    payload_graphs = _load_fixture("graphs_set.json")
    objects = {
        "markup/basic.json": payload_basic,
        "markup/graphs_set.json": payload_graphs,
    }
    client, stubber = stub_s3_catalog(
        monkeypatch=monkeypatch,
        objects=objects,
        bucket="cjm-bucket",
        prefix="markup/",
        list_repeats=1,
    )
    add_get_object(stubber, bucket="cjm-bucket", key="markup/basic.json", payload=payload_basic)
    add_get_object(
        stubber, bucket="cjm-bucket", key="markup/graphs_set.json", payload=payload_graphs
    )

    config = CatalogIndexConfig(
        markup_dir=Path("markup"),
        excalidraw_in_dir=excalidraw_in_dir,
        index_path=index_path,
        group_by=["markup_type"],
        title_field="finedog_unit_meta.service_name",
        tag_fields=[],
        sort_by="title",
        sort_order="asc",
        unknown_value="unknown",
    )
    try:
        BuildCatalogIndex(
            S3MarkupCatalogSource(client, "cjm-bucket", "markup/"),
            FileSystemCatalogIndexRepository(),
        ).build(config)

        settings = app_settings_factory(
            excalidraw_in_dir=excalidraw_in_dir,
            excalidraw_out_dir=excalidraw_out_dir,
            roundtrip_dir=roundtrip_dir,
            index_path=index_path,
            excalidraw_base_url="/excalidraw",
        )
        client_api = TestClient(create_app(settings))

        response = client_api.get(
            "/catalog/teams/graph/open",
            params={"team_ids": "team-alpha", "merge_nodes_all_markups": "true"},
        )
        assert response.status_code == 200
        assert "\\u0026merge_nodes_all_markups=true" in response.text
        assert "amp;merge_nodes_all_markups" not in response.text
    finally:
        stubber.deactivate()


def test_catalog_team_graph_open_preserves_selected_merge_flag_in_scene_api_url(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    app_settings_factory: Callable[..., AppSettings],
) -> None:
    excalidraw_in_dir = tmp_path / "excalidraw_in"
    excalidraw_out_dir = tmp_path / "excalidraw_out"
    roundtrip_dir = tmp_path / "roundtrip"
    index_path = tmp_path / "catalog" / "index.json"

    excalidraw_in_dir.mkdir(parents=True)
    excalidraw_out_dir.mkdir(parents=True)
    roundtrip_dir.mkdir(parents=True)

    payload_basic = _load_fixture("basic.json")
    objects = {
        "markup/basic.json": payload_basic,
    }
    client, stubber = stub_s3_catalog(
        monkeypatch=monkeypatch,
        objects=objects,
        bucket="cjm-bucket",
        prefix="markup/",
        list_repeats=1,
    )
    add_get_object(stubber, bucket="cjm-bucket", key="markup/basic.json", payload=payload_basic)

    config = CatalogIndexConfig(
        markup_dir=Path("markup"),
        excalidraw_in_dir=excalidraw_in_dir,
        index_path=index_path,
        group_by=["markup_type"],
        title_field="finedog_unit_meta.service_name",
        tag_fields=[],
        sort_by="title",
        sort_order="asc",
        unknown_value="unknown",
    )
    try:
        BuildCatalogIndex(
            S3MarkupCatalogSource(client, "cjm-bucket", "markup/"),
            FileSystemCatalogIndexRepository(),
        ).build(config)

        settings = app_settings_factory(
            excalidraw_in_dir=excalidraw_in_dir,
            excalidraw_out_dir=excalidraw_out_dir,
            roundtrip_dir=roundtrip_dir,
            index_path=index_path,
            excalidraw_base_url="/excalidraw",
        )
        client_api = TestClient(create_app(settings))

        response = client_api.get(
            "/catalog/teams/graph/open",
            params={"team_ids": "team-alpha", "merge_selected_markups": "true"},
        )
        assert response.status_code == 200
        assert "\\u0026merge_selected_markups=true" in response.text
        assert "amp;merge_selected_markups" not in response.text
    finally:
        stubber.deactivate()


def test_catalog_team_graph_open_preserves_merge_threshold_in_scene_api_url(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    app_settings_factory: Callable[..., AppSettings],
) -> None:
    excalidraw_in_dir = tmp_path / "excalidraw_in"
    excalidraw_out_dir = tmp_path / "excalidraw_out"
    roundtrip_dir = tmp_path / "roundtrip"
    index_path = tmp_path / "catalog" / "index.json"

    excalidraw_in_dir.mkdir(parents=True)
    excalidraw_out_dir.mkdir(parents=True)
    roundtrip_dir.mkdir(parents=True)

    payload_basic = _load_fixture("basic.json")
    objects = {
        "markup/basic.json": payload_basic,
    }
    client, stubber = stub_s3_catalog(
        monkeypatch=monkeypatch,
        objects=objects,
        bucket="cjm-bucket",
        prefix="markup/",
        list_repeats=1,
    )
    add_get_object(stubber, bucket="cjm-bucket", key="markup/basic.json", payload=payload_basic)

    config = CatalogIndexConfig(
        markup_dir=Path("markup"),
        excalidraw_in_dir=excalidraw_in_dir,
        index_path=index_path,
        group_by=["markup_type"],
        title_field="finedog_unit_meta.service_name",
        tag_fields=[],
        sort_by="title",
        sort_order="asc",
        unknown_value="unknown",
    )
    try:
        BuildCatalogIndex(
            S3MarkupCatalogSource(client, "cjm-bucket", "markup/"),
            FileSystemCatalogIndexRepository(),
        ).build(config)

        settings = app_settings_factory(
            excalidraw_in_dir=excalidraw_in_dir,
            excalidraw_out_dir=excalidraw_out_dir,
            roundtrip_dir=roundtrip_dir,
            index_path=index_path,
            excalidraw_base_url="/excalidraw",
        )
        client_api = TestClient(create_app(settings))

        response = client_api.get(
            "/catalog/teams/graph/open",
            params={"team_ids": "team-alpha", "merge_node_min_chain_size": "3"},
        )
        assert response.status_code == 200
        assert "\\u0026merge_node_min_chain_size=3" in response.text
        assert "amp;merge_node_min_chain_size" not in response.text
    finally:
        stubber.deactivate()


def test_catalog_team_graph_open_preserves_graph_level_in_scene_api_url(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    app_settings_factory: Callable[..., AppSettings],
) -> None:
    excalidraw_in_dir = tmp_path / "excalidraw_in"
    excalidraw_out_dir = tmp_path / "excalidraw_out"
    roundtrip_dir = tmp_path / "roundtrip"
    index_path = tmp_path / "catalog" / "index.json"

    excalidraw_in_dir.mkdir(parents=True)
    excalidraw_out_dir.mkdir(parents=True)
    roundtrip_dir.mkdir(parents=True)

    payload_basic = _load_fixture("basic.json")
    objects = {
        "markup/basic.json": payload_basic,
    }
    client, stubber = stub_s3_catalog(
        monkeypatch=monkeypatch,
        objects=objects,
        bucket="cjm-bucket",
        prefix="markup/",
        list_repeats=1,
    )
    add_get_object(stubber, bucket="cjm-bucket", key="markup/basic.json", payload=payload_basic)

    config = CatalogIndexConfig(
        markup_dir=Path("markup"),
        excalidraw_in_dir=excalidraw_in_dir,
        index_path=index_path,
        group_by=["markup_type"],
        title_field="finedog_unit_meta.service_name",
        tag_fields=[],
        sort_by="title",
        sort_order="asc",
        unknown_value="unknown",
    )
    try:
        BuildCatalogIndex(
            S3MarkupCatalogSource(client, "cjm-bucket", "markup/"),
            FileSystemCatalogIndexRepository(),
        ).build(config)

        settings = app_settings_factory(
            excalidraw_in_dir=excalidraw_in_dir,
            excalidraw_out_dir=excalidraw_out_dir,
            roundtrip_dir=roundtrip_dir,
            index_path=index_path,
            excalidraw_base_url="/excalidraw",
        )
        client_api = TestClient(create_app(settings))

        response = client_api.get(
            "/catalog/teams/graph/open",
            params={"team_ids": "team-alpha", "graph_level": "service"},
        )
        assert response.status_code == 200
        assert "\\u0026graph_level=service" in response.text
        assert "amp;graph_level" not in response.text
        assert "const inlineScene = {" in response.text
    finally:
        stubber.deactivate()


def test_catalog_team_graph_selected_team_scene_keeps_merge_nodes_from_all_markups(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    app_settings_factory: Callable[..., AppSettings],
) -> None:
    excalidraw_in_dir = tmp_path / "excalidraw_in"
    excalidraw_out_dir = tmp_path / "excalidraw_out"
    roundtrip_dir = tmp_path / "roundtrip"
    index_path = tmp_path / "catalog" / "index.json"

    excalidraw_in_dir.mkdir(parents=True)
    excalidraw_out_dir.mkdir(parents=True)
    roundtrip_dir.mkdir(parents=True)

    payload_basic = _load_fixture("basic.json")
    payload_graphs = _load_fixture("graphs_set.json")

    basic_meta = payload_basic.get("finedog_unit_meta")
    assert isinstance(basic_meta, dict)
    basic_team_id = basic_meta.get("team_id")
    assert isinstance(basic_team_id, str)

    basic_procedures = payload_basic.get("procedures")
    graphs_procedures = payload_graphs.get("procedures")
    assert isinstance(basic_procedures, list)
    assert isinstance(graphs_procedures, list)
    basic_proc_ids = {proc["proc_id"] for proc in basic_procedures if isinstance(proc, dict)}
    graphs_proc_ids = {proc["proc_id"] for proc in graphs_procedures if isinstance(proc, dict)}
    expected_merge_proc_ids = basic_proc_ids & graphs_proc_ids
    graphs_only_proc_ids = graphs_proc_ids - basic_proc_ids
    assert expected_merge_proc_ids
    assert graphs_only_proc_ids

    objects = {
        "markup/basic.json": payload_basic,
        "markup/graphs_set.json": payload_graphs,
    }
    client, stubber = stub_s3_catalog(
        monkeypatch=monkeypatch,
        objects=objects,
        bucket="cjm-bucket",
        prefix="markup/",
        list_repeats=1,
    )
    add_get_object(stubber, bucket="cjm-bucket", key="markup/basic.json", payload=payload_basic)
    add_get_object(
        stubber, bucket="cjm-bucket", key="markup/graphs_set.json", payload=payload_graphs
    )

    config = CatalogIndexConfig(
        markup_dir=Path("markup"),
        excalidraw_in_dir=excalidraw_in_dir,
        index_path=index_path,
        group_by=["markup_type"],
        title_field="finedog_unit_meta.service_name",
        tag_fields=[],
        sort_by="title",
        sort_order="asc",
        unknown_value="unknown",
    )
    try:
        BuildCatalogIndex(
            S3MarkupCatalogSource(client, "cjm-bucket", "markup/"),
            FileSystemCatalogIndexRepository(),
        ).build(config)

        settings = app_settings_factory(
            excalidraw_in_dir=excalidraw_in_dir,
            excalidraw_out_dir=excalidraw_out_dir,
            roundtrip_dir=roundtrip_dir,
            index_path=index_path,
            excalidraw_base_url="http://example.com",
        )
        client_api = TestClient(create_app(settings))

        response = client_api.get(
            "/api/teams/graph",
            params={"team_ids": basic_team_id, "merge_nodes_all_markups": "true"},
        )
        assert response.status_code == 200
        elements = response.json()["elements"]

        frame_proc_ids: set[str] = set()
        intersection_proc_ids: set[str] = set()
        for element in elements:
            cjm = element.get("customData", {}).get("cjm", {})
            if not isinstance(cjm, dict):
                continue
            role = cjm.get("role")
            proc_id = cjm.get("procedure_id")
            if not isinstance(proc_id, str):
                continue
            if role == "frame":
                frame_proc_ids.add(proc_id)
            if role == "intersection_highlight":
                intersection_proc_ids.add(proc_id)

        assert expected_merge_proc_ids.issubset(frame_proc_ids)
        assert expected_merge_proc_ids.issubset(intersection_proc_ids)
        assert frame_proc_ids.isdisjoint(graphs_only_proc_ids)
    finally:
        stubber.deactivate()


def test_catalog_team_graph_selected_team_scene_chain_threshold_keeps_routing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    app_settings_factory: Callable[..., AppSettings],
) -> None:
    excalidraw_in_dir = tmp_path / "excalidraw_in"
    excalidraw_out_dir = tmp_path / "excalidraw_out"
    roundtrip_dir = tmp_path / "roundtrip"
    index_path = tmp_path / "catalog" / "index.json"

    excalidraw_in_dir.mkdir(parents=True)
    excalidraw_out_dir.mkdir(parents=True)
    roundtrip_dir.mkdir(parents=True)

    payload_basic = _load_fixture("basic.json")
    payload_graphs = _load_fixture("graphs_set.json")

    basic_meta = payload_basic.get("finedog_unit_meta")
    assert isinstance(basic_meta, dict)
    basic_team_id = basic_meta.get("team_id")
    assert isinstance(basic_team_id, str)

    objects = {
        "markup/basic.json": payload_basic,
        "markup/graphs_set.json": payload_graphs,
    }
    client, stubber = stub_s3_catalog(
        monkeypatch=monkeypatch,
        objects=objects,
        bucket="cjm-bucket",
        prefix="markup/",
        list_repeats=1,
    )
    add_get_object(stubber, bucket="cjm-bucket", key="markup/basic.json", payload=payload_basic)
    add_get_object(
        stubber, bucket="cjm-bucket", key="markup/graphs_set.json", payload=payload_graphs
    )

    config = CatalogIndexConfig(
        markup_dir=Path("markup"),
        excalidraw_in_dir=excalidraw_in_dir,
        index_path=index_path,
        group_by=["markup_type"],
        title_field="finedog_unit_meta.service_name",
        tag_fields=[],
        sort_by="title",
        sort_order="asc",
        unknown_value="unknown",
    )
    try:
        BuildCatalogIndex(
            S3MarkupCatalogSource(client, "cjm-bucket", "markup/"),
            FileSystemCatalogIndexRepository(),
        ).build(config)

        settings = app_settings_factory(
            excalidraw_in_dir=excalidraw_in_dir,
            excalidraw_out_dir=excalidraw_out_dir,
            roundtrip_dir=roundtrip_dir,
            index_path=index_path,
            excalidraw_base_url="http://example.com",
        )
        client_api = TestClient(create_app(settings))

        response = client_api.get(
            "/api/teams/graph",
            params={
                "team_ids": basic_team_id,
                "merge_nodes_all_markups": "true",
                "merge_node_min_chain_size": "2",
            },
        )
        assert response.status_code == 200
        elements = response.json()["elements"]

        frame_proc_ids: set[str] = set()
        intersection_proc_ids: set[str] = set()
        for element in elements:
            cjm = element.get("customData", {}).get("cjm", {})
            if not isinstance(cjm, dict):
                continue
            role = cjm.get("role")
            proc_id = cjm.get("procedure_id")
            if not isinstance(proc_id, str):
                continue
            if role == "frame":
                frame_proc_ids.add(proc_id)
            if role == "intersection_highlight":
                intersection_proc_ids.add(proc_id)

        assert "proc_shared_intake" in frame_proc_ids
        assert "proc_shared_handoff" in frame_proc_ids
        assert "proc_shared_routing" in frame_proc_ids
        assert "proc_shared_intake" in intersection_proc_ids
        assert "proc_shared_handoff" not in intersection_proc_ids
        assert "proc_shared_routing" not in intersection_proc_ids
    finally:
        stubber.deactivate()


def test_catalog_team_graph_hides_unselected_merge_nodes_from_other_teams(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    app_settings_factory: Callable[..., AppSettings],
) -> None:
    excalidraw_in_dir = tmp_path / "excalidraw_in"
    excalidraw_out_dir = tmp_path / "excalidraw_out"
    roundtrip_dir = tmp_path / "roundtrip"
    index_path = tmp_path / "catalog" / "index.json"

    excalidraw_in_dir.mkdir(parents=True)
    excalidraw_out_dir.mkdir(parents=True)
    roundtrip_dir.mkdir(parents=True)

    payload_alpha = {
        "markup_type": "service",
        "finedog_unit_meta": {
            "service_name": "Payments",
            "team_id": "team-alpha",
            "team_name": "Alpha",
        },
        "procedures": [
            {
                "proc_id": "entry",
                "proc_name": "Entry",
                "start_block_ids": ["a"],
                "end_block_ids": ["b"],
                "branches": {"a": ["b"]},
            }
        ],
        "procedure_graph": {"entry": ["shared"], "shared": []},
    }
    payload_beta = {
        "markup_type": "service",
        "finedog_unit_meta": {
            "service_name": "Loans",
            "team_id": "team-beta",
            "team_name": "Beta",
        },
        "procedures": [
            {
                "proc_id": "shared",
                "proc_name": "Shared",
                "start_block_ids": ["c"],
                "end_block_ids": ["d"],
                "branches": {"c": ["d"]},
            }
        ],
        "procedure_graph": {"shared": []},
    }

    objects = {
        "markup/alpha.json": payload_alpha,
        "markup/beta.json": payload_beta,
    }
    client, stubber = stub_s3_catalog(
        monkeypatch=monkeypatch,
        objects=objects,
        bucket="cjm-bucket",
        prefix="markup/",
        list_repeats=1,
    )
    add_get_object(stubber, bucket="cjm-bucket", key="markup/alpha.json", payload=payload_alpha)
    add_get_object(stubber, bucket="cjm-bucket", key="markup/beta.json", payload=payload_beta)

    config = CatalogIndexConfig(
        markup_dir=Path("markup"),
        excalidraw_in_dir=excalidraw_in_dir,
        index_path=index_path,
        group_by=["markup_type"],
        title_field="finedog_unit_meta.service_name",
        tag_fields=[],
        sort_by="title",
        sort_order="asc",
        unknown_value="unknown",
    )
    try:
        BuildCatalogIndex(
            S3MarkupCatalogSource(client, "cjm-bucket", "markup/"),
            FileSystemCatalogIndexRepository(),
        ).build(config)

        settings = app_settings_factory(
            excalidraw_in_dir=excalidraw_in_dir,
            excalidraw_out_dir=excalidraw_out_dir,
            roundtrip_dir=roundtrip_dir,
            index_path=index_path,
            excalidraw_base_url="http://example.com",
        )
        client_api = TestClient(create_app(settings))

        response = client_api.get(
            "/api/teams/graph",
            params={"team_ids": "team-alpha", "merge_nodes_all_markups": "true"},
        )
        assert response.status_code == 200
        elements = response.json()["elements"]

        frame_proc_ids: set[str] = set()
        intersection_proc_ids: set[str] = set()
        for element in elements:
            cjm = element.get("customData", {}).get("cjm", {})
            if not isinstance(cjm, dict):
                continue
            proc_id = cjm.get("procedure_id")
            if not isinstance(proc_id, str):
                continue
            role = cjm.get("role")
            if role == "frame":
                frame_proc_ids.add(proc_id)
            if role == "intersection_highlight":
                intersection_proc_ids.add(proc_id)

        assert frame_proc_ids == {"entry"}
        assert not intersection_proc_ids
    finally:
        stubber.deactivate()


def test_catalog_team_graph_styles_for_merge_and_flags() -> None:
    style_path = _repo_root() / "app" / "web" / "static" / "style.css"
    styles = style_path.read_text(encoding="utf-8")

    assert ".team-graph-cta-action" in styles
    assert "justify-self: end;" in styles
    assert ".team-graph-merge-button" in styles
    assert ".team-graph-merge-threshold-card" in styles
    assert ".team-graph-merge-threshold-title-row" in styles
    assert ".team-graph-merge-threshold-rules" in styles
    assert '.team-graph-merge-threshold-input input[type="range"]' in styles
    assert ".team-graph-flag-item.is-on" in styles
    assert "outline-color: rgba(129, 237, 155, 0.34);" in styles
    assert '.team-graph-flag-button[data-state="on"]' in styles
    assert "background: #1a232c;" in styles
    assert ".team-graph-dashboard-section" in styles
    assert ".team-graph-kpi-card" in styles
    assert ".team-graph-merge-loader.htmx-request" in styles
    assert ".team-graph-merge-button:disabled" in styles
    assert ".team-graph-procedure-order" in styles
    assert ".team-graph-sort-button" in styles
    assert ".team-graph-actions-split" in styles
    assert '.team-graph-actions-group[data-graph-level="service"]' in styles


def test_catalog_team_graph_default_does_not_merge_selected_markups(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    app_settings_factory: Callable[..., AppSettings],
) -> None:
    excalidraw_in_dir = tmp_path / "excalidraw_in"
    excalidraw_out_dir = tmp_path / "excalidraw_out"
    roundtrip_dir = tmp_path / "roundtrip"
    index_path = tmp_path / "catalog" / "index.json"

    excalidraw_in_dir.mkdir(parents=True)
    excalidraw_out_dir.mkdir(parents=True)
    roundtrip_dir.mkdir(parents=True)

    payload_alpha = {
        "markup_type": "service",
        "finedog_unit_meta": {
            "service_name": "Payments",
            "team_id": "team-alpha",
            "team_name": "Alpha",
        },
        "procedures": [
            {
                "proc_id": "entry-alpha",
                "proc_name": "Entry alpha",
                "start_block_ids": ["a0"],
                "end_block_ids": ["a1"],
                "branches": {"a0": ["a1"]},
            },
            {
                "proc_id": "shared",
                "proc_name": "Shared",
                "start_block_ids": ["a"],
                "end_block_ids": ["b"],
                "branches": {"a": ["b"]},
            },
        ],
        "procedure_graph": {"entry-alpha": ["shared"], "shared": []},
    }
    payload_beta = {
        "markup_type": "service",
        "finedog_unit_meta": {
            "service_name": "Loans",
            "team_id": "team-beta",
            "team_name": "Beta",
        },
        "procedures": [
            {
                "proc_id": "shared",
                "proc_name": "Shared",
                "start_block_ids": ["c"],
                "end_block_ids": ["d"],
                "branches": {"c": ["d"]},
            },
            {
                "proc_id": "tail-beta",
                "proc_name": "Tail beta",
                "start_block_ids": ["e"],
                "end_block_ids": ["f"],
                "branches": {"e": ["f"]},
            },
        ],
        "procedure_graph": {"shared": ["tail-beta"], "tail-beta": []},
    }
    objects = {
        "markup/alpha.json": payload_alpha,
        "markup/beta.json": payload_beta,
    }
    client, stubber = stub_s3_catalog(
        monkeypatch=monkeypatch,
        objects=objects,
        bucket="cjm-bucket",
        prefix="markup/",
        list_repeats=1,
    )
    add_get_object(stubber, bucket="cjm-bucket", key="markup/beta.json", payload=payload_beta)
    add_get_object(stubber, bucket="cjm-bucket", key="markup/alpha.json", payload=payload_alpha)
    add_get_object(stubber, bucket="cjm-bucket", key="markup/beta.json", payload=payload_beta)
    add_get_object(stubber, bucket="cjm-bucket", key="markup/alpha.json", payload=payload_alpha)
    add_get_object(stubber, bucket="cjm-bucket", key="markup/beta.json", payload=payload_beta)
    add_get_object(stubber, bucket="cjm-bucket", key="markup/alpha.json", payload=payload_alpha)

    config = CatalogIndexConfig(
        markup_dir=Path("markup"),
        excalidraw_in_dir=excalidraw_in_dir,
        index_path=index_path,
        group_by=["markup_type"],
        title_field="finedog_unit_meta.service_name",
        tag_fields=[],
        sort_by="title",
        sort_order="asc",
        unknown_value="unknown",
    )
    try:
        BuildCatalogIndex(
            S3MarkupCatalogSource(client, "cjm-bucket", "markup/"),
            FileSystemCatalogIndexRepository(),
        ).build(config)

        settings = app_settings_factory(
            excalidraw_in_dir=excalidraw_in_dir,
            excalidraw_out_dir=excalidraw_out_dir,
            roundtrip_dir=roundtrip_dir,
            index_path=index_path,
            excalidraw_base_url="http://example.com",
        )
        client_api = TestClient(create_app(settings))

        response = client_api.get(
            "/api/teams/graph",
            params={"team_ids": "team-alpha,team-beta"},
        )
        assert response.status_code == 200
        elements = response.json()["elements"]
        frame_ids = [
            element.get("customData", {}).get("cjm", {}).get("procedure_id")
            for element in elements
            if element.get("customData", {}).get("cjm", {}).get("role") == "frame"
        ]
        assert len(frame_ids) == 4
        assert all(isinstance(proc_id, str) for proc_id in frame_ids)
        shared_ids = [
            proc_id
            for proc_id in frame_ids
            if isinstance(proc_id, str) and proc_id.startswith("shared::doc")
        ]
        assert len(shared_ids) == 2
    finally:
        stubber.deactivate()


def test_catalog_team_graph_can_merge_selected_markups_by_flag(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    app_settings_factory: Callable[..., AppSettings],
) -> None:
    excalidraw_in_dir = tmp_path / "excalidraw_in"
    excalidraw_out_dir = tmp_path / "excalidraw_out"
    roundtrip_dir = tmp_path / "roundtrip"
    index_path = tmp_path / "catalog" / "index.json"

    excalidraw_in_dir.mkdir(parents=True)
    excalidraw_out_dir.mkdir(parents=True)
    roundtrip_dir.mkdir(parents=True)

    payload_alpha = {
        "markup_type": "service",
        "finedog_unit_meta": {
            "service_name": "Payments",
            "team_id": "team-alpha",
            "team_name": "Alpha",
        },
        "procedures": [
            {
                "proc_id": "shared",
                "proc_name": "Shared",
                "start_block_ids": ["a"],
                "end_block_ids": ["b"],
                "branches": {"a": ["b"]},
            }
        ],
        "procedure_graph": {"shared": []},
    }
    payload_beta = {
        "markup_type": "service",
        "finedog_unit_meta": {
            "service_name": "Loans",
            "team_id": "team-beta",
            "team_name": "Beta",
        },
        "procedures": [
            {
                "proc_id": "shared",
                "proc_name": "Shared",
                "start_block_ids": ["c"],
                "end_block_ids": ["d"],
                "branches": {"c": ["d"]},
            }
        ],
        "procedure_graph": {"shared": []},
    }
    objects = {
        "markup/alpha.json": payload_alpha,
        "markup/beta.json": payload_beta,
    }
    client, stubber = stub_s3_catalog(
        monkeypatch=monkeypatch,
        objects=objects,
        bucket="cjm-bucket",
        prefix="markup/",
        list_repeats=1,
    )
    add_get_object(stubber, bucket="cjm-bucket", key="markup/beta.json", payload=payload_beta)
    add_get_object(stubber, bucket="cjm-bucket", key="markup/alpha.json", payload=payload_alpha)

    config = CatalogIndexConfig(
        markup_dir=Path("markup"),
        excalidraw_in_dir=excalidraw_in_dir,
        index_path=index_path,
        group_by=["markup_type"],
        title_field="finedog_unit_meta.service_name",
        tag_fields=[],
        sort_by="title",
        sort_order="asc",
        unknown_value="unknown",
    )
    try:
        BuildCatalogIndex(
            S3MarkupCatalogSource(client, "cjm-bucket", "markup/"),
            FileSystemCatalogIndexRepository(),
        ).build(config)

        settings = app_settings_factory(
            excalidraw_in_dir=excalidraw_in_dir,
            excalidraw_out_dir=excalidraw_out_dir,
            roundtrip_dir=roundtrip_dir,
            index_path=index_path,
            excalidraw_base_url="http://example.com",
        )
        client_api = TestClient(create_app(settings))

        response = client_api.get(
            "/api/teams/graph",
            params={"team_ids": "team-alpha,team-beta", "merge_selected_markups": "true"},
        )
        assert response.status_code == 200
        elements = response.json()["elements"]
        frame_ids = [
            element.get("customData", {}).get("cjm", {}).get("procedure_id")
            for element in elements
            if element.get("customData", {}).get("cjm", {}).get("role") == "frame"
        ]
        assert frame_ids == ["shared"]
    finally:
        stubber.deactivate()


def test_catalog_team_graph_merge_threshold_zero_disables_shared_node_merging(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    app_settings_factory: Callable[..., AppSettings],
) -> None:
    excalidraw_in_dir = tmp_path / "excalidraw_in"
    excalidraw_out_dir = tmp_path / "excalidraw_out"
    roundtrip_dir = tmp_path / "roundtrip"
    index_path = tmp_path / "catalog" / "index.json"

    excalidraw_in_dir.mkdir(parents=True)
    excalidraw_out_dir.mkdir(parents=True)
    roundtrip_dir.mkdir(parents=True)

    payload_alpha = {
        "markup_type": "service",
        "finedog_unit_meta": {
            "service_name": "Payments",
            "team_id": "team-alpha",
            "team_name": "Alpha",
        },
        "procedures": [
            {
                "proc_id": "shared",
                "proc_name": "Shared",
                "start_block_ids": ["a"],
                "end_block_ids": ["b"],
                "branches": {"a": ["b"]},
            }
        ],
        "procedure_graph": {"shared": []},
    }
    payload_beta = {
        "markup_type": "service",
        "finedog_unit_meta": {
            "service_name": "Loans",
            "team_id": "team-beta",
            "team_name": "Beta",
        },
        "procedures": [
            {
                "proc_id": "shared",
                "proc_name": "Shared",
                "start_block_ids": ["c"],
                "end_block_ids": ["d"],
                "branches": {"c": ["d"]},
            }
        ],
        "procedure_graph": {"shared": []},
    }
    objects = {
        "markup/alpha.json": payload_alpha,
        "markup/beta.json": payload_beta,
    }
    client, stubber = stub_s3_catalog(
        monkeypatch=monkeypatch,
        objects=objects,
        bucket="cjm-bucket",
        prefix="markup/",
        list_repeats=1,
    )
    add_get_object(stubber, bucket="cjm-bucket", key="markup/beta.json", payload=payload_beta)
    add_get_object(stubber, bucket="cjm-bucket", key="markup/alpha.json", payload=payload_alpha)

    config = CatalogIndexConfig(
        markup_dir=Path("markup"),
        excalidraw_in_dir=excalidraw_in_dir,
        index_path=index_path,
        group_by=["markup_type"],
        title_field="finedog_unit_meta.service_name",
        tag_fields=[],
        sort_by="title",
        sort_order="asc",
        unknown_value="unknown",
    )
    try:
        BuildCatalogIndex(
            S3MarkupCatalogSource(client, "cjm-bucket", "markup/"),
            FileSystemCatalogIndexRepository(),
        ).build(config)

        settings = app_settings_factory(
            excalidraw_in_dir=excalidraw_in_dir,
            excalidraw_out_dir=excalidraw_out_dir,
            roundtrip_dir=roundtrip_dir,
            index_path=index_path,
            excalidraw_base_url="http://example.com",
        )
        client_api = TestClient(create_app(settings))

        response = client_api.get(
            "/api/teams/graph",
            params={
                "team_ids": "team-alpha,team-beta",
                "merge_selected_markups": "true",
                "merge_node_min_chain_size": "0",
            },
        )
        assert response.status_code == 200
        elements = response.json()["elements"]
        frame_ids = [
            element.get("customData", {}).get("cjm", {}).get("procedure_id")
            for element in elements
            if element.get("customData", {}).get("cjm", {}).get("role") == "frame"
        ]
        shared_ids = [
            proc_id
            for proc_id in frame_ids
            if isinstance(proc_id, str) and proc_id.startswith("shared::doc")
        ]
        assert len(shared_ids) == 2
        assert "shared" not in frame_ids
    finally:
        stubber.deactivate()


def test_catalog_team_graph_fixture_markups_do_not_merge_when_flag_is_off(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    app_settings_factory: Callable[..., AppSettings],
) -> None:
    excalidraw_in_dir = tmp_path / "excalidraw_in"
    excalidraw_out_dir = tmp_path / "excalidraw_out"
    roundtrip_dir = tmp_path / "roundtrip"
    index_path = tmp_path / "catalog" / "index.json"

    excalidraw_in_dir.mkdir(parents=True)
    excalidraw_out_dir.mkdir(parents=True)
    roundtrip_dir.mkdir(parents=True)

    payload_basic = _load_fixture("basic.json")
    payload_graphs = _load_fixture("graphs_set.json")
    basic_meta = payload_basic.get("finedog_unit_meta")
    graphs_meta = payload_graphs.get("finedog_unit_meta")
    assert isinstance(basic_meta, dict)
    assert isinstance(graphs_meta, dict)
    basic_team_id = basic_meta.get("team_id")
    graphs_team_id = graphs_meta.get("team_id")
    assert isinstance(basic_team_id, str)
    assert isinstance(graphs_team_id, str)

    objects = {
        "markup/basic.json": payload_basic,
        "markup/graphs_set.json": payload_graphs,
    }
    client, stubber = stub_s3_catalog(
        monkeypatch=monkeypatch,
        objects=objects,
        bucket="cjm-bucket",
        prefix="markup/",
        list_repeats=1,
    )
    add_get_object(stubber, bucket="cjm-bucket", key="markup/basic.json", payload=payload_basic)
    add_get_object(
        stubber, bucket="cjm-bucket", key="markup/graphs_set.json", payload=payload_graphs
    )

    config = CatalogIndexConfig(
        markup_dir=Path("markup"),
        excalidraw_in_dir=excalidraw_in_dir,
        index_path=index_path,
        group_by=["markup_type"],
        title_field="finedog_unit_meta.service_name",
        tag_fields=[],
        sort_by="title",
        sort_order="asc",
        unknown_value="unknown",
    )
    try:
        BuildCatalogIndex(
            S3MarkupCatalogSource(client, "cjm-bucket", "markup/"),
            FileSystemCatalogIndexRepository(),
        ).build(config)

        settings = app_settings_factory(
            excalidraw_in_dir=excalidraw_in_dir,
            excalidraw_out_dir=excalidraw_out_dir,
            roundtrip_dir=roundtrip_dir,
            index_path=index_path,
            excalidraw_base_url="http://example.com",
        )
        client_api = TestClient(create_app(settings))

        response = client_api.get(
            "/api/teams/graph",
            params={"team_ids": f"{basic_team_id},{graphs_team_id}"},
        )
        assert response.status_code == 200
        elements = response.json()["elements"]
        frame_ids = [
            element.get("customData", {}).get("cjm", {}).get("procedure_id")
            for element in elements
            if element.get("customData", {}).get("cjm", {}).get("role") == "frame"
        ]
        highlight_ids = {
            element.get("customData", {}).get("cjm", {}).get("procedure_id")
            for element in elements
            if element.get("customData", {}).get("cjm", {}).get("role") == "intersection_highlight"
        }
        assert "proc_shared_routing" not in frame_ids
        assert "proc_shared_routing::doc1" in frame_ids
        assert "proc_shared_routing::doc2" in frame_ids
        assert "proc_shared_intake" not in frame_ids
        assert "proc_shared_intake::doc1" in frame_ids
        assert "proc_shared_intake::doc2" in frame_ids
        assert "proc_shared_routing::doc1" in highlight_ids
        assert "proc_shared_routing::doc2" in highlight_ids
        assert "proc_shared_intake::doc1" in highlight_ids
        assert "proc_shared_intake::doc2" in highlight_ids
        assert all(
            element.get("customData", {}).get("cjm", {}).get("role") != "service_zone"
            for element in elements
        )
    finally:
        stubber.deactivate()


def test_catalog_team_graph_fixture_markups_merge_when_flag_is_on(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    app_settings_factory: Callable[..., AppSettings],
) -> None:
    excalidraw_in_dir = tmp_path / "excalidraw_in"
    excalidraw_out_dir = tmp_path / "excalidraw_out"
    roundtrip_dir = tmp_path / "roundtrip"
    index_path = tmp_path / "catalog" / "index.json"

    excalidraw_in_dir.mkdir(parents=True)
    excalidraw_out_dir.mkdir(parents=True)
    roundtrip_dir.mkdir(parents=True)

    payload_basic = _load_fixture("basic.json")
    payload_graphs = _load_fixture("graphs_set.json")
    basic_meta = payload_basic.get("finedog_unit_meta")
    graphs_meta = payload_graphs.get("finedog_unit_meta")
    assert isinstance(basic_meta, dict)
    assert isinstance(graphs_meta, dict)
    basic_team_id = basic_meta.get("team_id")
    graphs_team_id = graphs_meta.get("team_id")
    assert isinstance(basic_team_id, str)
    assert isinstance(graphs_team_id, str)

    objects = {
        "markup/basic.json": payload_basic,
        "markup/graphs_set.json": payload_graphs,
    }
    client, stubber = stub_s3_catalog(
        monkeypatch=monkeypatch,
        objects=objects,
        bucket="cjm-bucket",
        prefix="markup/",
        list_repeats=1,
    )
    add_get_object(stubber, bucket="cjm-bucket", key="markup/basic.json", payload=payload_basic)
    add_get_object(
        stubber, bucket="cjm-bucket", key="markup/graphs_set.json", payload=payload_graphs
    )
    add_get_object(stubber, bucket="cjm-bucket", key="markup/basic.json", payload=payload_basic)
    add_get_object(
        stubber, bucket="cjm-bucket", key="markup/graphs_set.json", payload=payload_graphs
    )

    config = CatalogIndexConfig(
        markup_dir=Path("markup"),
        excalidraw_in_dir=excalidraw_in_dir,
        index_path=index_path,
        group_by=["markup_type"],
        title_field="finedog_unit_meta.service_name",
        tag_fields=[],
        sort_by="title",
        sort_order="asc",
        unknown_value="unknown",
    )
    try:
        BuildCatalogIndex(
            S3MarkupCatalogSource(client, "cjm-bucket", "markup/"),
            FileSystemCatalogIndexRepository(),
        ).build(config)

        settings = app_settings_factory(
            excalidraw_in_dir=excalidraw_in_dir,
            excalidraw_out_dir=excalidraw_out_dir,
            roundtrip_dir=roundtrip_dir,
            index_path=index_path,
            excalidraw_base_url="http://example.com",
        )
        client_api = TestClient(create_app(settings))

        response = client_api.get(
            "/api/teams/graph",
            params={
                "team_ids": f"{basic_team_id},{graphs_team_id}",
                "merge_selected_markups": "true",
            },
        )
        assert response.status_code == 200
        elements = response.json()["elements"]
        frame_ids = [
            element.get("customData", {}).get("cjm", {}).get("procedure_id")
            for element in elements
            if element.get("customData", {}).get("cjm", {}).get("role") == "frame"
        ]
        assert "proc_shared_routing" in frame_ids
        assert "proc_shared_routing::doc1" not in frame_ids
        assert "proc_shared_routing::doc2" not in frame_ids
        assert any(
            element.get("customData", {}).get("cjm", {}).get("role") == "service_zone"
            for element in elements
        )

        html_response = client_api.get(
            "/catalog/teams/graph",
            params={
                "team_ids": f"{basic_team_id},{graphs_team_id}",
                "merge_selected_markups": "true",
            },
        )
        assert html_response.status_code == 200
        assert "Intersection node breakdown" in html_response.text
        assert "team-graph-merge-node-card" in html_response.text
        assert "team-graph-procedure-id" in html_response.text
        assert "proc_shared_intake" in html_response.text
        assert "proc_shared_routing" in html_response.text
    finally:
        stubber.deactivate()


def test_catalog_team_graph_dashboard_graph_count_matches_merged_diagram_graph(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    app_settings_factory: Callable[..., AppSettings],
) -> None:
    excalidraw_in_dir = tmp_path / "excalidraw_in"
    excalidraw_out_dir = tmp_path / "excalidraw_out"
    roundtrip_dir = tmp_path / "roundtrip"
    index_path = tmp_path / "catalog" / "index.json"

    excalidraw_in_dir.mkdir(parents=True)
    excalidraw_out_dir.mkdir(parents=True)
    roundtrip_dir.mkdir(parents=True)

    payload_alpha = {
        "markup_type": "service",
        "finedog_unit_meta": {
            "service_name": "Payments",
            "team_id": "team-alpha",
            "team_name": "Alpha",
        },
        "procedures": [
            {
                "proc_id": "entry",
                "proc_name": "Entry",
                "start_block_ids": ["a"],
                "end_block_ids": ["b"],
                "branches": {"a": ["b"]},
            },
            {
                "proc_id": "shared",
                "proc_name": "Shared",
                "start_block_ids": ["c"],
                "end_block_ids": ["d"],
                "branches": {"c": ["d"]},
            },
        ],
        "procedure_graph": {"entry": [], "shared": []},
    }
    payload_beta = {
        "markup_type": "service",
        "finedog_unit_meta": {
            "service_name": "Loans",
            "team_id": "team-beta",
            "team_name": "Beta",
        },
        "procedures": [
            {
                "proc_id": "entry",
                "proc_name": "Entry",
                "start_block_ids": ["x"],
                "end_block_ids": ["y"],
                "branches": {"x": ["y"]},
            },
            {
                "proc_id": "shared",
                "proc_name": "Shared",
                "start_block_ids": ["z"],
                "end_block_ids": ["w"],
                "branches": {"z": ["w"]},
            },
        ],
        "procedure_graph": {"entry": ["shared"], "shared": []},
    }
    objects = {
        "markup/alpha.json": payload_alpha,
        "markup/beta.json": payload_beta,
    }
    client, stubber = stub_s3_catalog(
        monkeypatch=monkeypatch,
        objects=objects,
        bucket="cjm-bucket",
        prefix="markup/",
        list_repeats=1,
    )
    add_get_object(stubber, bucket="cjm-bucket", key="markup/alpha.json", payload=payload_alpha)
    add_get_object(stubber, bucket="cjm-bucket", key="markup/beta.json", payload=payload_beta)
    add_get_object(stubber, bucket="cjm-bucket", key="markup/alpha.json", payload=payload_alpha)
    add_get_object(stubber, bucket="cjm-bucket", key="markup/beta.json", payload=payload_beta)

    config = CatalogIndexConfig(
        markup_dir=Path("markup"),
        excalidraw_in_dir=excalidraw_in_dir,
        index_path=index_path,
        group_by=["markup_type"],
        title_field="finedog_unit_meta.service_name",
        tag_fields=[],
        sort_by="title",
        sort_order="asc",
        unknown_value="unknown",
    )
    try:
        BuildCatalogIndex(
            S3MarkupCatalogSource(client, "cjm-bucket", "markup/"),
            FileSystemCatalogIndexRepository(),
        ).build(config)

        settings = app_settings_factory(
            excalidraw_in_dir=excalidraw_in_dir,
            excalidraw_out_dir=excalidraw_out_dir,
            roundtrip_dir=roundtrip_dir,
            index_path=index_path,
            excalidraw_base_url="http://example.com",
        )
        client_api = TestClient(create_app(settings))

        html_response = client_api.get(
            "/catalog/teams/graph",
            params={
                "team_ids": "team-alpha",
                "merge_selected_markups": "true",
                "merge_nodes_all_markups": "true",
            },
        )
        assert html_response.status_code == 200
        match = re.search(
            r"<div class=\"team-graph-kpi-label\">Graphs</div>\s*.*?<div class=\"team-graph-kpi-value\">(\d+)</div>",
            html_response.text,
            flags=re.DOTALL,
        )
        assert match is not None
        assert match.group(1) == "1"

        api_response = client_api.get(
            "/api/teams/graph",
            params={
                "team_ids": "team-alpha",
                "merge_selected_markups": "true",
                "merge_nodes_all_markups": "true",
            },
        )
        assert api_response.status_code == 200
        elements = api_response.json()["elements"]
        frame_ids = [
            element.get("customData", {}).get("cjm", {}).get("procedure_id")
            for element in elements
            if element.get("customData", {}).get("cjm", {}).get("role") == "frame"
        ]
        assert set(frame_ids) == {"entry", "shared"}
    finally:
        stubber.deactivate()


def test_catalog_team_graph_default_keeps_singleton_shared_nodes_separate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    app_settings_factory: Callable[..., AppSettings],
) -> None:
    excalidraw_in_dir = tmp_path / "excalidraw_in"
    excalidraw_out_dir = tmp_path / "excalidraw_out"
    roundtrip_dir = tmp_path / "roundtrip"
    index_path = tmp_path / "catalog" / "index.json"

    excalidraw_in_dir.mkdir(parents=True)
    excalidraw_out_dir.mkdir(parents=True)
    roundtrip_dir.mkdir(parents=True)

    payload_alpha = {
        "markup_type": "service",
        "finedog_unit_meta": {
            "service_name": "Payments",
            "team_id": "team-alpha",
            "team_name": "Alpha",
        },
        "procedures": [
            {
                "proc_id": "shared",
                "proc_name": "Shared",
                "start_block_ids": ["a"],
                "end_block_ids": ["b"],
                "branches": {"a": ["b"]},
            }
        ],
        "procedure_graph": {"shared": []},
    }
    payload_beta = {
        "markup_type": "service",
        "finedog_unit_meta": {
            "service_name": "Loans",
            "team_id": "team-beta",
            "team_name": "Beta",
        },
        "procedures": [
            {
                "proc_id": "shared",
                "proc_name": "Shared",
                "start_block_ids": ["c"],
                "end_block_ids": ["d"],
                "branches": {"c": ["d"]},
            }
        ],
        "procedure_graph": {"shared": []},
    }
    objects = {
        "markup/alpha.json": payload_alpha,
        "markup/beta.json": payload_beta,
    }
    client, stubber = stub_s3_catalog(
        monkeypatch=monkeypatch,
        objects=objects,
        bucket="cjm-bucket",
        prefix="markup/",
        list_repeats=1,
    )
    add_get_object(stubber, bucket="cjm-bucket", key="markup/beta.json", payload=payload_beta)
    add_get_object(stubber, bucket="cjm-bucket", key="markup/alpha.json", payload=payload_alpha)
    add_get_object(stubber, bucket="cjm-bucket", key="markup/beta.json", payload=payload_beta)
    add_get_object(stubber, bucket="cjm-bucket", key="markup/alpha.json", payload=payload_alpha)

    config = CatalogIndexConfig(
        markup_dir=Path("markup"),
        excalidraw_in_dir=excalidraw_in_dir,
        index_path=index_path,
        group_by=["markup_type"],
        title_field="finedog_unit_meta.service_name",
        tag_fields=[],
        sort_by="title",
        sort_order="asc",
        unknown_value="unknown",
    )
    try:
        BuildCatalogIndex(
            S3MarkupCatalogSource(client, "cjm-bucket", "markup/"),
            FileSystemCatalogIndexRepository(),
        ).build(config)

        settings = app_settings_factory(
            excalidraw_in_dir=excalidraw_in_dir,
            excalidraw_out_dir=excalidraw_out_dir,
            roundtrip_dir=roundtrip_dir,
            index_path=index_path,
            excalidraw_base_url="http://example.com",
        )
        client_api = TestClient(create_app(settings))

        response = client_api.get(
            "/api/teams/graph",
            params={"team_ids": "team-alpha,team-beta"},
        )
        assert response.status_code == 200
        elements = response.json()["elements"]
        frame_ids = [
            element.get("customData", {}).get("cjm", {}).get("procedure_id")
            for element in elements
            if element.get("customData", {}).get("cjm", {}).get("role") == "frame"
        ]
        assert len(frame_ids) == 2
        shared_ids = [
            proc_id
            for proc_id in frame_ids
            if isinstance(proc_id, str) and proc_id.startswith("shared::doc")
        ]
        assert len(shared_ids) == 2

        html_response = client_api.get(
            "/catalog/teams/graph",
            params={"team_ids": "team-alpha,team-beta"},
        )
        assert html_response.status_code == 200
        assert "Potential intersection node breakdown" in html_response.text
        assert "Procedure-level breakdown (graph order, potential merges)" in html_response.text
        assert "Potential merges" in html_response.text
    finally:
        stubber.deactivate()
