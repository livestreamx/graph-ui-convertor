from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

from app.config import AppSettings
from tests.app.catalog_test_setup import build_catalog_test_context


def test_catalog_api_smoke(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    app_settings_factory: Callable[..., AppSettings],
) -> None:
    with build_catalog_test_context(
        tmp_path=tmp_path,
        monkeypatch=monkeypatch,
        app_settings_factory=app_settings_factory,
        include_upload_stub=True,
    ) as context:
        roundtrip_dir = tmp_path / "roundtrip"
        index_response = context.client.get("/api/index")
        assert index_response.status_code == 200
        items = index_response.json()["items"]
        assert len(items) == 1
        assert items[0]["updated_at"]
        scene_id = items[0]["scene_id"]

        scene_response = context.client.get(f"/api/scenes/{scene_id}")
        assert scene_response.status_code == 200

        markup_response = context.client.get(f"/api/markup/{scene_id}?download=true")
        assert markup_response.status_code == 200
        assert "attachment" in markup_response.headers.get("content-disposition", "").lower()
        assert markup_response.json() == context.payload

        with context.scene_path.open("rb") as handle:
            upload_response = context.client.post(
                f"/api/scenes/{scene_id}/upload",
                files={"file": ("billing.excalidraw", handle, "application/json")},
            )
        assert upload_response.status_code == 200

        convert_response = context.client.post(f"/api/scenes/{scene_id}/convert-back")
        assert convert_response.status_code == 200
        assert (roundtrip_dir / "billing.json").exists()


def test_catalog_scene_links_applied(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    app_settings_factory: Callable[..., AppSettings],
) -> None:
    with build_catalog_test_context(
        tmp_path=tmp_path,
        monkeypatch=monkeypatch,
        app_settings_factory=app_settings_factory,
        settings_overrides={
            "procedure_link_path": "https://example.com/procedures/{procedure_id}",
            "block_link_path": "https://example.com/procedures/{procedure_id}/blocks/{block_id}",
        },
    ) as context:
        index_response = context.client.get("/api/index")
        scene_id = index_response.json()["items"][0]["scene_id"]

        scene_response = context.client.get(f"/api/scenes/{scene_id}")
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


def test_catalog_ui_text_overrides(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    app_settings_factory: Callable[..., AppSettings],
) -> None:
    with build_catalog_test_context(
        tmp_path=tmp_path,
        monkeypatch=monkeypatch,
        app_settings_factory=app_settings_factory,
        settings_overrides={
            "ui_text_overrides": {
                "markup_type": "Kind",
                "service": "Svc",
            }
        },
    ) as context:
        response = context.client.get("/catalog")
        assert response.status_code == 200
        assert "Kind: Svc" in response.text
