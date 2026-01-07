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


def test_catalog_api_smoke(tmp_path: Path) -> None:
    markup_dir = tmp_path / "markup"
    excalidraw_in_dir = tmp_path / "excalidraw_in"
    excalidraw_out_dir = tmp_path / "excalidraw_out"
    roundtrip_dir = tmp_path / "roundtrip"
    index_path = tmp_path / "catalog" / "index.json"

    markup_dir.mkdir(parents=True)
    excalidraw_in_dir.mkdir(parents=True)
    excalidraw_out_dir.mkdir(parents=True)
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
            excalidraw_out_dir=excalidraw_out_dir,
            roundtrip_dir=roundtrip_dir,
            index_path=index_path,
            group_by=["markup_type"],
            title_field="finedog_unit_meta.service_name",
            tag_fields=[],
            sort_by="title",
            sort_order="asc",
            unknown_value="unknown",
            excalidraw_base_url="http://example.com",
            rebuild_token=None,
        )
    )

    client = TestClient(create_app(settings))

    index_response = client.get("/api/index")
    assert index_response.status_code == 200
    items = index_response.json()["items"]
    assert len(items) == 1
    scene_id = items[0]["scene_id"]

    scene_response = client.get(f"/api/scenes/{scene_id}")
    assert scene_response.status_code == 200

    with excal_path.open("rb") as handle:
        upload_response = client.post(
            f"/api/scenes/{scene_id}/upload",
            files={"file": ("billing.excalidraw", handle, "application/json")},
        )
    assert upload_response.status_code == 200

    convert_response = client.post(f"/api/scenes/{scene_id}/convert-back")
    assert convert_response.status_code == 200
    assert (roundtrip_dir / "billing.json").exists()
