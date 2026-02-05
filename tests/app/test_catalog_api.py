from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from botocore.stub import Stubber  # type: ignore[import-untyped]
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
from tests.adapters.s3.s3_utils import add_get_object, stub_s3_catalog


def _billing_payload() -> dict[str, Any]:
    return {
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


def _build_catalog_test_client(
    *,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    app_settings_factory: Callable[..., AppSettings],
    settings_overrides: dict[str, Any] | None = None,
    include_upload_stub: bool = False,
) -> tuple[TestClient, Path, dict[str, Any], Stubber]:
    excalidraw_in_dir = tmp_path / "excalidraw_in"
    excalidraw_out_dir = tmp_path / "excalidraw_out"
    roundtrip_dir = tmp_path / "roundtrip"
    index_path = tmp_path / "catalog" / "index.json"

    excalidraw_in_dir.mkdir(parents=True)
    excalidraw_out_dir.mkdir(parents=True)
    roundtrip_dir.mkdir(parents=True)

    payload = _billing_payload()
    objects = {"markup/billing.json": payload}
    client, stubber = stub_s3_catalog(
        monkeypatch=monkeypatch,
        objects=objects,
        bucket="cjm-bucket",
        prefix="markup/",
        list_repeats=1,
    )
    if include_upload_stub:
        add_get_object(stubber, bucket="cjm-bucket", key="markup/billing.json", payload=payload)

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
        **(settings_overrides or {}),
    )

    return TestClient(create_app(settings)), excal_path, payload, stubber


def test_catalog_api_smoke(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    app_settings_factory: Callable[..., AppSettings],
) -> None:
    client_api, excal_path, payload, stubber = _build_catalog_test_client(
        tmp_path=tmp_path,
        monkeypatch=monkeypatch,
        app_settings_factory=app_settings_factory,
        include_upload_stub=True,
    )
    roundtrip_dir = tmp_path / "roundtrip"
    try:
        index_response = client_api.get("/api/index")
        assert index_response.status_code == 200
        items = index_response.json()["items"]
        assert len(items) == 1
        assert items[0]["updated_at"]
        scene_id = items[0]["scene_id"]

        scene_response = client_api.get(f"/api/scenes/{scene_id}")
        assert scene_response.status_code == 200

        markup_response = client_api.get(f"/api/markup/{scene_id}?download=true")
        assert markup_response.status_code == 200
        assert "attachment" in markup_response.headers.get("content-disposition", "").lower()
        assert markup_response.json() == payload

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


def test_catalog_scene_links_applied(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    app_settings_factory: Callable[..., AppSettings],
) -> None:
    client_api, _excal_path, _payload, stubber = _build_catalog_test_client(
        tmp_path=tmp_path,
        monkeypatch=monkeypatch,
        app_settings_factory=app_settings_factory,
        settings_overrides={
            "procedure_link_path": "https://example.com/procedures/{procedure_id}",
            "block_link_path": "https://example.com/procedures/{procedure_id}/blocks/{block_id}",
        },
    )
    try:
        index_response = client_api.get("/api/index")
        scene_id = index_response.json()["items"][0]["scene_id"]

        scene_response = client_api.get(f"/api/scenes/{scene_id}")
        assert scene_response.status_code == 200
        elements = scene_response.json()["elements"]
        frame = next(
            element
            for element in elements
            if element.get("customData", {}).get("cjm", {}).get("role") == "frame"
        )
        block = next(
            element
            for element in elements
            if element.get("customData", {}).get("cjm", {}).get("role") == "block"
            and element.get("customData", {}).get("cjm", {}).get("block_id") == "a"
        )
        assert frame.get("link") == "https://example.com/procedures/p1"
        assert block.get("link") == "https://example.com/procedures/p1/blocks/a"
    finally:
        stubber.deactivate()


def test_catalog_ui_text_overrides(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    app_settings_factory: Callable[..., AppSettings],
) -> None:
    client_api, _excal_path, _payload, stubber = _build_catalog_test_client(
        tmp_path=tmp_path,
        monkeypatch=monkeypatch,
        app_settings_factory=app_settings_factory,
        settings_overrides={
            "ui_text_overrides": {
                "markup_type": "Kind",
                "service": "Svc",
            }
        },
    )
    try:
        response = client_api.get("/catalog")
        assert response.status_code == 200
        assert "Kind: Svc" in response.text
    finally:
        stubber.deactivate()
