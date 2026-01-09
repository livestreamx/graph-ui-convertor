from __future__ import annotations

import json
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
import uvicorn
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
from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import sync_playwright


class ExcalidrawStubHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802 - signature required by BaseHTTPRequestHandler
        if self.path in {"", "/"}:
            body = (
                "<html><body>"
                "<div id='status'>loading</div>"
                "<script src=\"/assets/app.js\"></script>"
                "</body></html>"
            ).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if self.path == "/assets/app.js":
            body = (
                "const raw = localStorage.getItem('excalidraw') || '[]';"
                "const elements = JSON.parse(raw);"
                "document.getElementById('status').textContent = 'elements:' + elements.length;"
            ).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/javascript")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if self.path == "/manifest.webmanifest":
            body = b"{}"
            self.send_response(200)
            self.send_header("Content-Type", "application/manifest+json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        self.send_response(404)
        self.end_headers()

    def do_HEAD(self) -> None:  # noqa: N802 - signature required by BaseHTTPRequestHandler
        self.send_response(200)
        self.end_headers()

    def log_message(self, format: str, *args: object) -> None:
        return


def find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def start_catalog_server(settings: AppSettings) -> tuple[uvicorn.Server, threading.Thread, int]:
    port = find_free_port()
    config = uvicorn.Config(
        create_app(settings),
        host="127.0.0.1",
        port=port,
        log_level="error",
    )
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    deadline = time.time() + 5
    while time.time() < deadline:
        if server.started:
            return server, thread, port
        time.sleep(0.05)
    raise RuntimeError("Catalog server did not start in time")


def test_catalog_open_e2e(tmp_path: Path) -> None:
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
    expected_elements = len(excal_doc.elements)
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

    index = FileSystemCatalogIndexRepository().load(index_path)
    scene_id = index.items[0].scene_id

    upstream = ThreadingHTTPServer(("127.0.0.1", 0), ExcalidrawStubHandler)
    upstream_thread = threading.Thread(target=upstream.serve_forever, daemon=True)
    upstream_thread.start()

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
            excalidraw_base_url="/excalidraw",
            excalidraw_proxy_upstream=f"http://127.0.0.1:{upstream.server_address[1]}",
            excalidraw_proxy_prefix="/excalidraw",
            excalidraw_max_url_length=8000,
            rebuild_token=None,
        )
    )

    server, server_thread, port = start_catalog_server(settings)

    try:
        with sync_playwright() as p:
            try:
                browser = p.chromium.launch(headless=True)
            except PlaywrightError as exc:
                pytest.skip(f"Playwright browser not available: {exc}")
            page = browser.new_page()
            page.goto(f"http://127.0.0.1:{port}/catalog/{scene_id}/open")
            page.wait_for_url("**/excalidraw/**", timeout=10000)
            page.wait_for_selector("#status", timeout=10000)
            text = page.text_content("#status")
            browser.close()
            assert text == f"elements:{expected_elements}"
    finally:
        server.should_exit = True
        server_thread.join(timeout=5)
        upstream.shutdown()
        upstream.server_close()
        upstream_thread.join(timeout=5)
