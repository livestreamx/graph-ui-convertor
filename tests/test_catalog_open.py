from __future__ import annotations

import json
from pathlib import Path

from adapters.excalidraw.repository import FileSystemExcalidrawRepository
from adapters.filesystem.catalog_index_repository import FileSystemCatalogIndexRepository
from adapters.filesystem.markup_catalog_source import FileSystemMarkupCatalogSource
from adapters.layout.grid import GridLayoutEngine
from app.config import AppSettings, CatalogSettings
from app.web_main import create_app
from domain.catalog import CatalogIndexConfig
from domain.models import MarkupDocument
from domain.services.build_catalog_index import BuildCatalogIndex
from domain.services.convert_markup_to_excalidraw import MarkupToExcalidrawConverter
from fastapi.testclient import TestClient


def test_catalog_detail_uses_open_route_same_origin(tmp_path: Path) -> None:
    markup_dir = tmp_path / "markup"
    excalidraw_in_dir = tmp_path / "excalidraw_in"
    roundtrip_dir = tmp_path / "roundtrip"
    index_path = tmp_path / "catalog" / "index.json"

    markup_dir.mkdir(parents=True)
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
    markup_path = markup_dir / "billing.json"
    markup_path.write_text(json.dumps(payload), encoding="utf-8")

    markup_doc = MarkupDocument.model_validate(payload)
    excal_doc = MarkupToExcalidrawConverter(GridLayoutEngine()).convert(markup_doc)
    excal_path = excalidraw_in_dir / "billing.excalidraw"
    FileSystemExcalidrawRepository().save(excal_doc, excal_path)

    config = CatalogIndexConfig(
        markup_dir=markup_dir,
        excalidraw_in_dir=excalidraw_in_dir,
        index_path=index_path,
        group_by=["markup_type"],
        title_field="finedog_unit_meta.service_name",
        tag_fields=[],
        sort_by="title",
        sort_order="asc",
        unknown_value="unknown",
    )
    BuildCatalogIndex(
        FileSystemMarkupCatalogSource(),
        FileSystemCatalogIndexRepository(),
    ).build(config)

    settings = AppSettings(
        catalog=CatalogSettings(
            title="Test Catalog",
            markup_dir=markup_dir,
            excalidraw_in_dir=excalidraw_in_dir,
            excalidraw_out_dir=tmp_path / "excalidraw_out",
            roundtrip_dir=roundtrip_dir,
            index_path=index_path,
            group_by=["markup_type"],
            title_field="finedog_unit_meta.service_name",
            tag_fields=[],
            sort_by="title",
            sort_order="asc",
            unknown_value="unknown",
            excalidraw_base_url="http://testserver/excalidraw",
            excalidraw_proxy_upstream=None,
            excalidraw_proxy_prefix="/excalidraw",
            excalidraw_max_url_length=8000,
            rebuild_token=None,
        )
    )

    client = TestClient(create_app(settings))

    index_response = client.get("/api/index")
    scene_id = index_response.json()["items"][0]["scene_id"]

    detail_response = client.get(f"/catalog/{scene_id}")
    assert detail_response.status_code == 200
    assert f"/catalog/{scene_id}/open" in detail_response.text

    open_response = client.get(f"/catalog/{scene_id}/open")
    assert open_response.status_code == 200
    assert "version-dataState" in open_response.text
    assert "excalidraw-state" in open_response.text
