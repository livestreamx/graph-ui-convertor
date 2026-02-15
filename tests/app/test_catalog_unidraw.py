from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import AppSettings, load_settings
from app.web_main import create_app
from tests.app.catalog_test_setup import build_catalog_test_context


def test_catalog_unidraw_open_uses_unidraw_storage(
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

        scene_response = context.client.get(f"/api/scenes/{scene_id}?format=unidraw")
        assert scene_response.status_code == 200
        payload = scene_response.json()
        assert payload.get("type") == "unidraw"
        assert payload.get("elements")


def test_builder_excluded_team_ids_env_json_array_does_not_break_catalog_ui_start(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("CJM_CONFIG_PATH", raising=False)
    monkeypatch.setenv("CJM_CATALOG__AUTO_BUILD_INDEX", "false")
    monkeypatch.setenv("CJM_CATALOG__INDEX_PATH", str(tmp_path / "index.json"))
    monkeypatch.setenv("CJM_CATALOG__BUILDER_EXCLUDED_TEAM_IDS", "[1, 2]")

    settings = load_settings()
    assert settings.catalog.builder_excluded_team_ids == ["1", "2"]

    with TestClient(create_app(settings)) as client:
        response = client.get("/catalog/teams/graph")
    assert response.status_code in {200, 503}


def test_builder_excluded_team_ids_env_bracket_list_without_json_quotes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("CJM_CONFIG_PATH", raising=False)
    monkeypatch.setenv("CJM_CATALOG__AUTO_BUILD_INDEX", "false")
    monkeypatch.setenv("CJM_CATALOG__INDEX_PATH", str(tmp_path / "index.json"))
    monkeypatch.setenv("CJM_CATALOG__BUILDER_EXCLUDED_TEAM_IDS", "[team-forest]")

    settings = load_settings()
    assert settings.catalog.builder_excluded_team_ids == ["team-forest"]


def test_builder_excluded_team_ids_env_quoted_bracket_list(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("CJM_CONFIG_PATH", raising=False)
    monkeypatch.setenv("CJM_CATALOG__AUTO_BUILD_INDEX", "false")
    monkeypatch.setenv("CJM_CATALOG__INDEX_PATH", str(tmp_path / "index.json"))
    monkeypatch.setenv("CJM_CATALOG__BUILDER_EXCLUDED_TEAM_IDS", '"[team-forest]"')

    settings = load_settings()
    assert settings.catalog.builder_excluded_team_ids == ["team-forest"]
