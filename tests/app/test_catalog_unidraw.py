from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from adapters.filesystem.catalog_index_repository import FileSystemCatalogIndexRepository
from adapters.layout.grid import GridLayoutEngine
from adapters.s3.markup_catalog_source import S3MarkupCatalogSource
from adapters.unidraw.repository import FileSystemUnidrawRepository
from app.config import AppSettings, load_settings
from app.web_main import create_app
from domain.catalog import CatalogIndexConfig
from domain.models import MarkupDocument
from domain.services.build_catalog_index import BuildCatalogIndex
from domain.services.convert_markup_to_unidraw import MarkupToUnidrawConverter
from tests.adapters.s3.s3_utils import stub_s3_catalog


def test_catalog_unidraw_open_uses_unidraw_storage(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    app_settings_factory: Callable[..., AppSettings],
) -> None:
    unidraw_in_dir = tmp_path / "unidraw_in"
    roundtrip_dir = tmp_path / "roundtrip"
    index_path = tmp_path / "catalog" / "index.json"

    unidraw_in_dir.mkdir(parents=True)
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
    unidraw_doc = MarkupToUnidrawConverter(GridLayoutEngine()).convert(markup_doc)
    unidraw_path = unidraw_in_dir / "billing.unidraw"
    FileSystemUnidrawRepository().save(unidraw_doc, unidraw_path)

    config = CatalogIndexConfig(
        markup_dir=Path("markup"),
        excalidraw_in_dir=tmp_path / "excalidraw_in",
        unidraw_in_dir=unidraw_in_dir,
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

        monkeypatch.setenv("CJM_CATALOG__UNIDRAW_BASE_URL", "http://testserver/unidraw")
        settings = app_settings_factory(
            diagram_format="unidraw",
            excalidraw_in_dir=tmp_path / "excalidraw_in",
            excalidraw_out_dir=tmp_path / "excalidraw_out",
            unidraw_in_dir=unidraw_in_dir,
            unidraw_out_dir=tmp_path / "unidraw_out",
            roundtrip_dir=roundtrip_dir,
            index_path=index_path,
            unidraw_base_url="http://testserver/unidraw",
        )

        client_api = TestClient(create_app(settings))
        index_response = client_api.get("/api/index")
        scene_id = index_response.json()["items"][0]["scene_id"]

        open_response = client_api.get(f"/catalog/{scene_id}/open")
        assert open_response.status_code == 200
        assert "unidraw-state" in open_response.text

        scene_response = client_api.get(f"/api/scenes/{scene_id}")
        assert scene_response.status_code == 200
        payload = scene_response.json()
        assert payload.get("type") == "unidraw"
        assert payload.get("elements")
    finally:
        stubber.deactivate()


def test_unidraw_requires_external_url_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CJM_CATALOG__DIAGRAM_FORMAT", "unidraw")
    monkeypatch.delenv("CJM_CATALOG__UNIDRAW_BASE_URL", raising=False)
    monkeypatch.delenv("CJM_CONFIG_PATH", raising=False)

    with pytest.raises(ValueError, match="CJM_CATALOG__UNIDRAW_BASE_URL"):
        load_settings()
