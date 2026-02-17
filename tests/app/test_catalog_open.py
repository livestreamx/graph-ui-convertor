from __future__ import annotations

import re
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
        assert "clearDiagramScopedStorage" in open_response.text
        assert "localStorage.clear()" in open_response.text
        assert "QuotaExceededError" in open_response.text
        assert "_open_ts" in open_response.text
        assert "Failed to load the latest scene. Please retry." in open_response.text
        assert "Reason:" in open_response.text
        assert "extractResponseDetail" in open_response.text
        assert "HTTP ${response.status}" in open_response.text
        assert 'id="retry-open"' in open_response.text
        assert "showRetry" in open_response.text


def test_catalog_detail_shows_dual_download_buttons_by_default(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    app_settings_factory: Callable[..., AppSettings],
) -> None:
    with build_catalog_test_context(
        tmp_path=tmp_path,
        monkeypatch=monkeypatch,
        app_settings_factory=app_settings_factory,
    ) as context:
        detail_response = context.client.get(f"/catalog/{context.scene_id}")
        assert detail_response.status_code == 200
        assert "Get the diagram" in detail_response.text
        assert "Show graph" in detail_response.text
        assert "Show reverse links" in detail_response.text
        assert 'id="service-graph-show-reverse"' in detail_response.text
        assert f"/api/scenes/{context.scene_id}/block-graph" in detail_response.text
        assert "service-graph-modal" in detail_response.text
        assert "Open Excalidraw" in detail_response.text
        assert "Download .excalidraw" in detail_response.text
        assert "Download .unidraw" in detail_response.text
        assert (
            "Open in Excalidraw or download both diagram formats for manual import and editing."
            not in detail_response.text
        )
        assert "Scene is injected via local storage for same-origin Excalidraw." not in (
            detail_response.text
        )
        assert (
            f"/api/scenes/{context.scene_id}?format=excalidraw&download=true"
            in detail_response.text
        )
        assert (
            f"/api/scenes/{context.scene_id}?format=unidraw&download=true" in detail_response.text
        )


def test_catalog_hides_excalidraw_open_when_disabled(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    app_settings_factory: Callable[..., AppSettings],
) -> None:
    with build_catalog_test_context(
        tmp_path=tmp_path,
        monkeypatch=monkeypatch,
        app_settings_factory=app_settings_factory,
        include_upload_stub=True,
        settings_overrides={"diagram_excalidraw_enabled": False},
    ) as context:
        detail_response = context.client.get(f"/catalog/{context.scene_id}")
        assert detail_response.status_code == 200
        assert "Open Excalidraw" not in detail_response.text
        assert "Show graph" in detail_response.text
        assert "Download .excalidraw" in detail_response.text
        assert "Download .unidraw" in detail_response.text
        unidraw_link_match = re.search(
            r'class="([^"]+)"\s+href="/api/scenes/[^"]+\?format=unidraw&download=true"',
            detail_response.text,
        )
        assert unidraw_link_match is not None
        assert "primary-button" in unidraw_link_match.group(1)
        assert "unidraw-button" not in unidraw_link_match.group(1)

        index_response = context.client.get("/api/index")
        team_id = index_response.json()["items"][0]["team_id"]
        graph_response = context.client.get("/catalog/teams/graph", params={"team_ids": team_id})
        assert graph_response.status_code == 200
        assert "Open Excalidraw" not in graph_response.text
        assert "Download .excalidraw" in graph_response.text
        assert "Download .unidraw" in graph_response.text


def test_catalog_detail_renders_service_and_team_metadata_links_when_templates_configured(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    app_settings_factory: Callable[..., AppSettings],
) -> None:
    with build_catalog_test_context(
        tmp_path=tmp_path,
        monkeypatch=monkeypatch,
        app_settings_factory=app_settings_factory,
        settings_overrides={
            "service_link_path": "https://external.example.com/service",
            "team_link_path": "https://external.example.com/team",
        },
    ) as context:
        detail_response = context.client.get(f"/catalog/{context.scene_id}")
        assert detail_response.status_code == 200
        assert "External resources" not in detail_response.text
        assert "Markup information" in detail_response.text
        assert "Service ID" in detail_response.text
        assert 'class="meta-link"' in detail_response.text
        assert "Billing Team" in detail_response.text
        assert "billing-unit-42" in detail_response.text
        assert "https://external.example.com/service?unit_id=billing-unit-42" in (
            detail_response.text
        )
        assert "https://external.example.com/team?team_id=team-billing" in detail_response.text
