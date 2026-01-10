from __future__ import annotations

from pathlib import Path

import pytest
from adapters.excalidraw.repository import FileSystemExcalidrawRepository
from adapters.filesystem.catalog_index_repository import FileSystemCatalogIndexRepository
from adapters.layout.grid import GridLayoutEngine
from adapters.s3.markup_catalog_source import S3MarkupCatalogSource
from app.config import AppSettings, CatalogSettings, S3Settings
from app.web_main import create_app
from domain.catalog import CatalogIndexConfig
from domain.models import MarkupDocument
from domain.services.build_catalog_index import BuildCatalogIndex
from domain.services.convert_markup_to_excalidraw import MarkupToExcalidrawConverter
from fastapi.testclient import TestClient

from tests.s3_utils import stub_s3_catalog


def test_catalog_api_smoke(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    excalidraw_in_dir = tmp_path / "excalidraw_in"
    excalidraw_out_dir = tmp_path / "excalidraw_out"
    roundtrip_dir = tmp_path / "roundtrip"
    index_path = tmp_path / "catalog" / "index.json"

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

        settings = AppSettings(
            catalog=CatalogSettings(
                title="Test Catalog",
                s3=S3Settings(
                    bucket="cjm-bucket",
                    prefix="markup/",
                    region="us-east-1",
                    endpoint_url="http://stubbed-s3.local",
                    access_key_id="test",
                    secret_access_key="test",
                    use_path_style=True,
                ),
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
                excalidraw_proxy_upstream=None,
                excalidraw_proxy_prefix="/excalidraw",
                excalidraw_max_url_length=8000,
                rebuild_token=None,
            )
        )

        client_api = TestClient(create_app(settings))

        index_response = client_api.get("/api/index")
        assert index_response.status_code == 200
        items = index_response.json()["items"]
        assert len(items) == 1
        assert items[0]["created_at"]
        scene_id = items[0]["scene_id"]

        scene_response = client_api.get(f"/api/scenes/{scene_id}")
        assert scene_response.status_code == 200

        with excal_path.open("rb") as handle:
            upload_response = client_api.post(
                f"/api/scenes/{scene_id}/upload",
                files={"file": ("billing.excalidraw", handle, "application/json")},
            )
        assert upload_response.status_code == 200

        convert_response = client_api.post(f"/api/scenes/{scene_id}/convert-back")
        assert convert_response.status_code == 200
        assert (roundtrip_dir / "billing.json").exists()
    finally:
        stubber.deactivate()


def test_catalog_ui_text_overrides(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    excalidraw_in_dir = tmp_path / "excalidraw_in"
    excalidraw_out_dir = tmp_path / "excalidraw_out"
    roundtrip_dir = tmp_path / "roundtrip"
    index_path = tmp_path / "catalog" / "index.json"

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
    objects = {"markup/billing.json": payload}
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

        settings = AppSettings(
            catalog=CatalogSettings(
                title="Test Catalog",
                s3=S3Settings(
                    bucket="cjm-bucket",
                    prefix="markup/",
                    region="us-east-1",
                    endpoint_url="http://stubbed-s3.local",
                    access_key_id="test",
                    secret_access_key="test",
                    use_path_style=True,
                ),
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
                excalidraw_proxy_upstream=None,
                excalidraw_proxy_prefix="/excalidraw",
                excalidraw_max_url_length=8000,
                rebuild_token=None,
                ui_text_overrides={
                    "markup_type": "Kind",
                    "service": "Svc",
                },
            )
        )

        client_api = TestClient(create_app(settings))
        response = client_api.get("/catalog")
        assert response.status_code == 200
        assert "Kind: Svc" in response.text
    finally:
        stubber.deactivate()
