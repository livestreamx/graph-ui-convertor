from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import AppSettings
from app.web_main import create_app


def test_proxy_serves_assets_and_static(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    app_settings_factory: Callable[..., AppSettings],
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/":
            body = b'<html><script src="/assets/app.js"></script></html>'
            return httpx.Response(200, content=body, headers={"Content-Type": "text/html"})
        if request.url.path == "/assets/app.js":
            body = b"console.log('ok')"
            return httpx.Response(
                200, content=body, headers={"Content-Type": "application/javascript"}
            )
        if request.url.path == "/manifest.webmanifest":
            body = b"{}"
            return httpx.Response(
                200, content=body, headers={"Content-Type": "application/manifest+json"}
            )
        return httpx.Response(404)

    transport = httpx.MockTransport(handler)
    original_async_client = httpx.AsyncClient

    def client_factory(*args: Any, **kwargs: Any) -> httpx.AsyncClient:
        kwargs["transport"] = transport
        return original_async_client(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", client_factory)

    settings = app_settings_factory(
        excalidraw_in_dir=tmp_path / "excalidraw_in",
        excalidraw_out_dir=tmp_path / "excalidraw_out",
        roundtrip_dir=tmp_path / "roundtrip",
        index_path=tmp_path / "catalog" / "index.json",
        title_field="service_name",
        excalidraw_base_url="/excalidraw",
        excalidraw_proxy_upstream="http://excalidraw.local",
        excalidraw_proxy_prefix="/excalidraw",
        auto_build_index=False,
    )

    client = TestClient(create_app(settings))

    response = client.get("/excalidraw/")
    assert response.status_code == 200
    assert "/assets/app.js" in response.text

    asset_response = client.get("/assets/app.js")
    assert asset_response.status_code == 200
    assert "console.log" in asset_response.text

    manifest_response = client.get("/manifest.webmanifest")
    assert manifest_response.status_code == 200
    assert manifest_response.text == "{}"
