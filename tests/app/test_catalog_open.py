from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from adapters.excalidraw.repository import FileSystemExcalidrawRepository
from adapters.filesystem.catalog_index_repository import FileSystemCatalogIndexRepository
from adapters.layout.grid import GridLayoutEngine
from adapters.s3.markup_catalog_source import S3MarkupCatalogSource
from app.config import AppSettings
from app.web_main import create_app
from domain.catalog import CatalogIndexConfig
from domain.models import MarkupDocument
from domain.services.build_catalog_index import BuildCatalogIndex
from domain.services.convert_markup_to_excalidraw import MarkupToExcalidrawConverter
from tests.adapters.s3.s3_utils import stub_s3_catalog


def test_catalog_detail_uses_open_route_same_origin(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    app_settings_factory: Callable[..., AppSettings],
) -> None:
    excalidraw_in_dir = tmp_path / "excalidraw_in"
    roundtrip_dir = tmp_path / "roundtrip"
    index_path = tmp_path / "catalog" / "index.json"

    excalidraw_in_dir.mkdir(parents=True)
    roundtrip_dir.mkdir(parents=True)

    payload = {
        "markup_type": "service",
        "finedog_unit_meta": {"service_name": "Billing"},
        "procedures": [
            {
                "proc_id": "p1",
                "start_block_ids": ["a"],
                "end_block_ids": ["b"],
                "branches": {"a": ["b"]},
            }
        ],
    }
    objects = {"markup/billing.json": payload}
    client, stubber = stub_s3_catalog(
        monkeypatch=monkeypatch,
        objects=objects,
        bucket="cjm-bucket",
        prefix="markup/",
        list_repeats=1,
    )

    markup_doc = MarkupDocument.model_validate(payload)
    excal_doc = MarkupToExcalidrawConverter(GridLayoutEngine()).convert(markup_doc)
    excal_path = excalidraw_in_dir / "billing.excalidraw"
    FileSystemExcalidrawRepository().save(excal_doc, excal_path)

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
            excalidraw_out_dir=tmp_path / "excalidraw_out",
            roundtrip_dir=roundtrip_dir,
            index_path=index_path,
        )

        client_api = TestClient(create_app(settings))

        index_response = client_api.get("/api/index")
        scene_id = index_response.json()["items"][0]["scene_id"]

        detail_response = client_api.get(f"/catalog/{scene_id}")
        assert detail_response.status_code == 200
        assert f"/catalog/{scene_id}/open" in detail_response.text

        open_response = client_api.get(f"/catalog/{scene_id}/open")
        assert open_response.status_code == 200
        assert "version-dataState" in open_response.text
        assert "excalidraw-state" in open_response.text
    finally:
        stubber.deactivate()
