from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

import pytest

from app.config import AppSettings
from domain.models import MarkupDocument
from domain.services.build_team_procedure_graph import BuildTeamProcedureGraph
from domain.services.extract_block_graph_view import extract_block_graph_view
from domain.services.extract_procedure_graph_view import extract_procedure_graph_view
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

        unidraw_response = context.client.get(
            f"/api/scenes/{scene_id}?format=unidraw&download=true"
        )
        assert unidraw_response.status_code == 200
        assert unidraw_response.json().get("type") == "unidraw"
        assert "billing.unidraw" in unidraw_response.headers.get("content-disposition", "")

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


def test_catalog_api_unidraw_download_with_legacy_index_item(
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
        index_path = tmp_path / "catalog" / "index.json"
        payload = json.loads(index_path.read_text(encoding="utf-8"))
        payload["items"][0].pop("unidraw_rel_path", None)
        index_path.write_text(json.dumps(payload), encoding="utf-8")

        response = context.client.get(
            f"/api/scenes/{context.scene_id}?format=unidraw&download=true"
        )
        assert response.status_code == 200
        assert response.json().get("type") == "unidraw"
        assert "billing.unidraw" in response.headers.get("content-disposition", "")


def test_catalog_api_unidraw_download_generated_on_demand_when_file_missing(
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
        unidraw_path = tmp_path / "unidraw_in" / "billing.unidraw"
        unidraw_path.unlink()

        response = context.client.get(
            f"/api/scenes/{context.scene_id}?format=unidraw&download=true"
        )
        assert response.status_code == 200
        assert response.json().get("type") == "unidraw"
        assert "billing.unidraw" in response.headers.get("content-disposition", "")


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


def test_catalog_scene_block_graph_api_reuses_scene_payload_graph_extraction(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    app_settings_factory: Callable[..., AppSettings],
) -> None:
    with build_catalog_test_context(
        tmp_path=tmp_path,
        monkeypatch=monkeypatch,
        app_settings_factory=app_settings_factory,
    ) as context:
        scene_response = context.client.get(f"/api/scenes/{context.scene_id}")
        assert scene_response.status_code == 200
        expected = extract_block_graph_view(scene_response.json())

        graph_response = context.client.get(f"/api/scenes/{context.scene_id}/block-graph")
        assert graph_response.status_code == 200
        assert graph_response.json() == expected


def test_catalog_scene_procedure_graph_api_reuses_team_builder_defaults(
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
        markup_document = MarkupDocument.model_validate(context.payload)
        procedure_graph_document = BuildTeamProcedureGraph().build(
            [markup_document],
            merge_documents=[markup_document],
            merge_selected_markups=False,
            merge_node_min_chain_size=1,
            graph_level="procedure",
        )
        expected_graph = extract_procedure_graph_view(procedure_graph_document)

        graph_response = context.client.get(f"/api/scenes/{context.scene_id}/procedure-graph-view")
        assert graph_response.status_code == 200
        assert graph_response.json() == expected_graph


def test_catalog_scene_procedure_graph_download_unidraw(
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
        download_response = context.client.get(
            f"/api/scenes/{context.scene_id}/procedure-graph?format=unidraw&download=true"
        )
        assert download_response.status_code == 200
        assert download_response.json().get("type") == "unidraw"
        assert "procedure_graph.unidraw" in download_response.headers.get("content-disposition", "")


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
