from __future__ import annotations

import json
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
from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import sync_playwright
from tests.s3_utils import stub_s3_catalog


def test_catalog_open_e2e(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
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
    expected_elements = len(excal_doc.elements)
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

        index = FileSystemCatalogIndexRepository().load(index_path)
        scene_id = index.items[0].scene_id

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
                excalidraw_base_url="/excalidraw",
                excalidraw_proxy_upstream="http://excalidraw.local",
                excalidraw_proxy_prefix="/excalidraw",
                excalidraw_max_url_length=8000,
                rebuild_token=None,
            )
        )

        client_api = TestClient(create_app(settings))
        open_html = client_api.get(f"/catalog/{scene_id}/open").text
        scene_json = client_api.get(f"/api/scenes/{scene_id}").json()

        excalidraw_html = (
            "<html><body>"
            "<div id='status'>loading</div>"
            "<script src=\"/assets/app.js\"></script>"
            "</body></html>"
        )
        excalidraw_js = (
            "const raw = localStorage.getItem('excalidraw') || '[]';"
            "const elements = JSON.parse(raw);"
            "document.getElementById('status').textContent = 'elements:' + elements.length;"
        )

        with sync_playwright() as p:
            try:
                browser = p.chromium.launch(headless=True)
            except PlaywrightError as exc:
                pytest.skip(f"Playwright browser not available: {exc}")
            page = browser.new_page()

            page.route(
                "**/api/scenes/**",
                lambda route: route.fulfill(
                    status=200,
                    body=json.dumps(scene_json),
                    headers={"Content-Type": "application/json"},
                ),
            )
            page.route(
                "**/excalidraw/**",
                lambda route: route.fulfill(
                    status=200,
                    body=excalidraw_html,
                    headers={"Content-Type": "text/html"},
                ),
            )
            page.route(
                "**/assets/app.js",
                lambda route: route.fulfill(
                    status=200,
                    body=excalidraw_js,
                    headers={"Content-Type": "application/javascript"},
                ),
            )
            page.route(
                "**/manifest.webmanifest",
                lambda route: route.fulfill(
                    status=200,
                    body="{}",
                    headers={"Content-Type": "application/manifest+json"},
                ),
            )

            page.set_content(open_html, base_url="http://catalog.local/")
            page.wait_for_url("**/excalidraw/**", timeout=10000)
            page.wait_for_selector("#status", timeout=10000)
            text = page.text_content("#status")
            browser.close()
    finally:
        stubber.deactivate()

    assert text == f"elements:{expected_elements}"
