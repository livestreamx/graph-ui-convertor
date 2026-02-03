from __future__ import annotations

import json
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


def _repo_root() -> Path:
    for parent in Path(__file__).resolve().parents:
        if (parent / "pyproject.toml").exists():
            return parent
    raise RuntimeError("Repository root not found")


def _load_fixture(name: str) -> dict[str, object]:
    path = _repo_root() / "examples" / "markup" / name
    payload = json.loads(path.read_text(encoding="utf-8"))
    return cast(dict[str, object], payload)


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
        assert "Merge markups by shared nodes" in html_response.text
        assert "How selected graphs render their components in according to shared nodes." in (
            html_response.text
        )
        assert "Render merge nodes from all available markups" in html_response.text
        assert "Step 3. Merge graphs" in html_response.text
        assert "Step 4. Use diagram" in html_response.text
        assert "Graphs info" in html_response.text
        assert "Entity Integrity" in html_response.text
        assert "Risk Hotspots" in html_response.text
        assert "Graphs" in html_response.text
        assert "Unique procedures" in html_response.text
        assert "Multichannel procedures" in html_response.text
        assert "Employee procedures" in html_response.text
        assert "External team overlaps" in html_response.text
        assert "data-overlap-team-toggle" in html_response.text
        assert 'data-team="Alpha"' in html_response.text
        assert 'data-team="Beta"' in html_response.text
        assert "team-graph-graphs-row-header" in html_response.text
        assert "team-graph-graphs-count-value" in html_response.text
        assert "--team-chip-border" in html_response.text
        assert 'id="team-graph-page"' in html_response.text
        assert 'hx-get="/catalog/teams/graph"' in html_response.text
        assert 'hx-target="#team-graph-page"' in html_response.text
        assert 'hx-select="#team-graph-page"' in html_response.text
        assert 'hx-push-url="true"' in html_response.text
        assert 'hx-indicator="#team-graph-merge-loader"' in html_response.text
        assert "team-graph-cta-warning is-hidden" in html_response.text
        assert 'id="team-graph-merge-loader"' in html_response.text

        no_selection_response = client_api.get("/catalog/teams/graph")
        assert no_selection_response.status_code == 200
        assert "data-merge-button" in no_selection_response.text
        assert 'disabled aria-disabled="true"' in no_selection_response.text
        assert "Select at least one team to enable Merge." in no_selection_response.text
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
        assert "proc_shared_intake" not in merge_ids
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
    expected_merge_proc_ids = (basic_proc_ids & graphs_proc_ids) - {"proc_shared_intake"}
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
    assert ".team-graph-flag-item.is-on" in styles
    assert "outline-color: rgba(129, 237, 155, 0.34);" in styles
    assert '.team-graph-flag-button[data-state="on"]' in styles
    assert "background: #1a232c;" in styles
    assert ".team-graph-dashboard-section" in styles
    assert ".team-graph-kpi-card" in styles
    assert ".team-graph-merge-loader.htmx-request" in styles
    assert ".team-graph-merge-button:disabled" in styles


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
