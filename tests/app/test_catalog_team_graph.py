from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from adapters.filesystem.catalog_index_repository import FileSystemCatalogIndexRepository
from adapters.s3.markup_catalog_source import S3MarkupCatalogSource
from app.config import AppSettings
from app.web_main import create_app
from domain.catalog import CatalogIndexConfig
from domain.services.build_catalog_index import BuildCatalogIndex
from tests.adapters.s3.s3_utils import add_get_object, stub_s3_catalog


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
        assert "Flags" in html_response.text
        assert "Use all available markups when rendering merge nodes." in html_response.text
    finally:
        stubber.deactivate()
