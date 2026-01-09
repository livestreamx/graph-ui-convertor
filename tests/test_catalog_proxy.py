from __future__ import annotations

import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from app.config import AppSettings, CatalogSettings
from app.web_main import create_app
from fastapi.testclient import TestClient


class UpstreamHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802 - signature required by BaseHTTPRequestHandler
        if self.path == "/":
            body = b"<html><script src=\"/assets/app.js\"></script></html>"
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if self.path == "/assets/app.js":
            body = b"console.log('ok')"
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


def test_proxy_serves_assets_and_static(tmp_path: Path) -> None:
    server = ThreadingHTTPServer(("127.0.0.1", 0), UpstreamHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]

    settings = AppSettings(
        catalog=CatalogSettings(
            title="Test Catalog",
            markup_dir=tmp_path / "markup",
            excalidraw_in_dir=tmp_path / "excalidraw_in",
            excalidraw_out_dir=tmp_path / "excalidraw_out",
            roundtrip_dir=tmp_path / "roundtrip",
            index_path=tmp_path / "catalog" / "index.json",
            group_by=["markup_type"],
            title_field="service_name",
            tag_fields=[],
            sort_by="title",
            sort_order="asc",
            unknown_value="unknown",
            excalidraw_base_url="/excalidraw",
            excalidraw_proxy_upstream=f"http://127.0.0.1:{port}",
            excalidraw_proxy_prefix="/excalidraw",
            excalidraw_max_url_length=8000,
            rebuild_token=None,
        )
    )

    client = TestClient(create_app(settings))

    try:
        response = client.get("/excalidraw/")
        assert response.status_code == 200
        assert "/assets/app.js" in response.text

        asset_response = client.get("/assets/app.js")
        assert asset_response.status_code == 200
        assert "console.log" in asset_response.text

        manifest_response = client.get("/manifest.webmanifest")
        assert manifest_response.status_code == 200
        assert manifest_response.text == "{}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=1)
