from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

from app.config import AppSettings
from tests.app.catalog_test_setup import build_catalog_test_context


def test_catalog_detail_uses_open_route_same_origin(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    app_settings_factory: Callable[..., AppSettings],
) -> None:
    with build_catalog_test_context(
        tmp_path=tmp_path,
        monkeypatch=monkeypatch,
        app_settings_factory=app_settings_factory,
    ) as context:
        index_response = context.client.get("/api/index")
        scene_id = index_response.json()["items"][0]["scene_id"]

        detail_response = context.client.get(f"/catalog/{scene_id}")
        assert detail_response.status_code == 200
        assert f"/catalog/{scene_id}/open" in detail_response.text

        open_response = context.client.get(f"/catalog/{scene_id}/open")
        assert open_response.status_code == 200
        assert "version-dataState" in open_response.text
        assert "excalidraw-state" in open_response.text
        assert 'cache: "no-store"' in open_response.text
        assert "localStorage.removeItem" in open_response.text
        assert "_open_ts" in open_response.text
        assert "Failed to load the latest scene. Please retry." in open_response.text
        assert "Reason:" in open_response.text
        assert "extractResponseDetail" in open_response.text
        assert "HTTP ${response.status}" in open_response.text
        assert 'id="retry-open"' in open_response.text
        assert "showRetry" in open_response.text
