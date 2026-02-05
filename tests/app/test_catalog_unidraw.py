from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

from app.config import AppSettings, load_settings
from tests.app.catalog_test_setup import build_catalog_test_context


def test_catalog_unidraw_open_uses_unidraw_storage(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    app_settings_factory: Callable[..., AppSettings],
) -> None:
    monkeypatch.setenv("CJM_CATALOG__UNIDRAW_BASE_URL", "http://testserver/unidraw")
    with build_catalog_test_context(
        tmp_path=tmp_path,
        monkeypatch=monkeypatch,
        app_settings_factory=app_settings_factory,
        diagram_format="unidraw",
        settings_overrides={
            "unidraw_base_url": "http://testserver/unidraw",
        },
    ) as context:
        index_response = context.client.get("/api/index")
        scene_id = index_response.json()["items"][0]["scene_id"]

        open_response = context.client.get(f"/catalog/{scene_id}/open")
        assert open_response.status_code == 200
        assert "unidraw-state" in open_response.text

        scene_response = context.client.get(f"/api/scenes/{scene_id}")
        assert scene_response.status_code == 200
        payload = scene_response.json()
        assert payload.get("type") == "unidraw"
        assert payload.get("elements")


def test_unidraw_requires_external_url_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CJM_CATALOG__DIAGRAM_FORMAT", "unidraw")
    monkeypatch.delenv("CJM_CATALOG__UNIDRAW_BASE_URL", raising=False)
    monkeypatch.delenv("CJM_CONFIG_PATH", raising=False)

    with pytest.raises(ValueError, match="CJM_CATALOG__UNIDRAW_BASE_URL"):
        load_settings()
