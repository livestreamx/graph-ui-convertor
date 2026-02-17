from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from adapters.filesystem.catalog_index_repository import FileSystemCatalogIndexRepository
from adapters.s3.markup_catalog_source import S3MarkupCatalogSource
from app.config import AppSettings
from app.web_main import create_app
from domain.catalog import CatalogIndexConfig
from domain.services.build_catalog_index import BuildCatalogIndex
from tests.adapters.s3.s3_utils import stub_s3_catalog


@contextmanager
def build_catalog_search_context(
    *,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    app_settings_factory: Callable[..., AppSettings],
) -> Iterator[TestClient]:
    excalidraw_in_dir = tmp_path / "excalidraw_in"
    excalidraw_out_dir = tmp_path / "excalidraw_out"
    unidraw_in_dir = tmp_path / "unidraw_in"
    unidraw_out_dir = tmp_path / "unidraw_out"
    roundtrip_dir = tmp_path / "roundtrip"
    index_path = tmp_path / "catalog" / "index.json"
    for path in (
        excalidraw_in_dir,
        excalidraw_out_dir,
        unidraw_in_dir,
        unidraw_out_dir,
        roundtrip_dir,
    ):
        path.mkdir(parents=True)

    objects = {
        "markup/checkout.json": {
            "markup_type": "service",
            "tags": ["billing", "payments"],
            "finedog_unit_meta": {
                "service_name": "Checkout Service",
                "team_id": "team-payments",
                "team_name": "Payments Team",
            },
            "procedures": [
                {
                    "proc_id": "proc_checkout",
                    "start_block_ids": ["checkout_start"],
                    "end_block_ids": ["checkout_done"],
                    "branches": {
                        "checkout_start": ["checkout_validate"],
                        "checkout_validate": ["checkout_done"],
                    },
                },
                {
                    "proc_id": "proc_refund",
                    "start_block_ids": ["refund_start"],
                    "end_block_ids": ["refund_done"],
                    "branches": {"refund_start": ["refund_done"]},
                },
            ],
        },
        "markup/support.json": {
            "markup_type": "service",
            "tags": ["support", "helpdesk"],
            "finedog_unit_meta": {
                "service_name": "Support Service",
                "team_id": "team-support",
                "team_name": "Support Team",
            },
            "procedures": [
                {
                    "proc_id": "proc_support",
                    "start_block_ids": ["ticket_start"],
                    "end_block_ids": ["ticket_done"],
                    "branches": {"ticket_start": ["ticket_done"]},
                },
                {
                    "proc_id": "proc_checkout",
                    "start_block_ids": ["support_bridge"],
                    "end_block_ids": ["support_done"],
                    "branches": {"support_bridge": ["support_done"]},
                },
            ],
        },
    }
    client, stubber = stub_s3_catalog(
        monkeypatch=monkeypatch,
        objects=objects,
        bucket="cjm-bucket",
        prefix="markup/",
    )

    config = CatalogIndexConfig(
        markup_dir=Path("markup"),
        excalidraw_in_dir=excalidraw_in_dir,
        unidraw_in_dir=unidraw_in_dir,
        index_path=index_path,
        group_by=["markup_type"],
        title_field="finedog_unit_meta.service_name",
        tag_fields=["tags"],
        sort_by="title",
        sort_order="asc",
        unknown_value="unknown",
    )
    BuildCatalogIndex(
        S3MarkupCatalogSource(client, "cjm-bucket", "markup/"),
        FileSystemCatalogIndexRepository(),
    ).build(config)

    settings = app_settings_factory(
        diagram_excalidraw_enabled=True,
        excalidraw_in_dir=excalidraw_in_dir,
        excalidraw_out_dir=excalidraw_out_dir,
        unidraw_in_dir=unidraw_in_dir,
        unidraw_out_dir=unidraw_out_dir,
        roundtrip_dir=roundtrip_dir,
        index_path=index_path,
    )
    client_api = TestClient(create_app(settings))
    try:
        yield client_api
    finally:
        client_api.close()
        stubber.deactivate()


def test_catalog_search_filters_by_procedure_and_block_in_one_query(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    app_settings_factory: Callable[..., AppSettings],
) -> None:
    with build_catalog_search_context(
        tmp_path=tmp_path,
        monkeypatch=monkeypatch,
        app_settings_factory=app_settings_factory,
    ) as client:
        response = client.get(
            "/catalog", params=[("search", "proc_checkout"), ("search", "checkout_validate")]
        )
        assert response.status_code == 200
        assert "Checkout Service" in response.text
        assert "Support Service" not in response.text
        assert "proc_checkout" in response.text
        assert "checkout_validate" in response.text


def test_catalog_search_filters_by_procedure_token_only(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    app_settings_factory: Callable[..., AppSettings],
) -> None:
    with build_catalog_search_context(
        tmp_path=tmp_path,
        monkeypatch=monkeypatch,
        app_settings_factory=app_settings_factory,
    ) as client:
        response = client.get("/catalog", params=[("search", "proc_refund")])
        assert response.status_code == 200
        assert "Checkout Service" in response.text
        assert "Support Service" not in response.text


def test_catalog_search_filters_by_block_token_only(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    app_settings_factory: Callable[..., AppSettings],
) -> None:
    with build_catalog_search_context(
        tmp_path=tmp_path,
        monkeypatch=monkeypatch,
        app_settings_factory=app_settings_factory,
    ) as client:
        response = client.get("/catalog", params=[("search", "support_bridge")])
        assert response.status_code == 200
        assert "Support Service" in response.text
        assert "Checkout Service" not in response.text


def test_catalog_search_requires_block_inside_selected_procedure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    app_settings_factory: Callable[..., AppSettings],
) -> None:
    with build_catalog_search_context(
        tmp_path=tmp_path,
        monkeypatch=monkeypatch,
        app_settings_factory=app_settings_factory,
    ) as client:
        mismatch = client.get(
            "/catalog",
            params=[("search", "proc_refund"), ("search", "checkout_validate")],
        )
        assert mismatch.status_code == 200
        assert "Checkout Service" not in mismatch.text
        assert "Support Service" not in mismatch.text
        assert "0 scenes" in mismatch.text

        exact = client.get(
            "/catalog",
            params=[("search", "proc_refund"), ("search", "refund_done")],
        )
        assert exact.status_code == 200
        assert "Checkout Service" in exact.text
        assert "Support Service" not in exact.text


def test_catalog_search_selects_support_by_shared_procedure_and_specific_block(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    app_settings_factory: Callable[..., AppSettings],
) -> None:
    with build_catalog_search_context(
        tmp_path=tmp_path,
        monkeypatch=monkeypatch,
        app_settings_factory=app_settings_factory,
    ) as client:
        response = client.get(
            "/catalog",
            params=[("search", "proc_checkout"), ("search", "support_bridge")],
        )
        assert response.status_code == 200
        assert "Support Service" in response.text
        assert "Checkout Service" not in response.text


def test_catalog_search_combines_query_input_and_existing_tokens(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    app_settings_factory: Callable[..., AppSettings],
) -> None:
    with build_catalog_search_context(
        tmp_path=tmp_path,
        monkeypatch=monkeypatch,
        app_settings_factory=app_settings_factory,
    ) as client:
        response = client.get(
            "/catalog",
            params=[("search", "proc_checkout"), ("q", "support_bridge")],
        )
        assert response.status_code == 200
        assert "Support Service" in response.text
        assert "Checkout Service" not in response.text


def test_catalog_search_uses_and_logic_between_text_tokens(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    app_settings_factory: Callable[..., AppSettings],
) -> None:
    with build_catalog_search_context(
        tmp_path=tmp_path,
        monkeypatch=monkeypatch,
        app_settings_factory=app_settings_factory,
    ) as client:
        response = client.get(
            "/catalog",
            params=[("search", "service"), ("search", "support")],
        )
        assert response.status_code == 200
        assert "Support Service" in response.text
        assert "Checkout Service" not in response.text


def test_catalog_search_matches_tags_from_index(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    app_settings_factory: Callable[..., AppSettings],
) -> None:
    with build_catalog_search_context(
        tmp_path=tmp_path,
        monkeypatch=monkeypatch,
        app_settings_factory=app_settings_factory,
    ) as client:
        response = client.get("/catalog", params=[("search", "billing")])
        assert response.status_code == 200
        assert "Checkout Service" in response.text
        assert "Support Service" not in response.text


def test_catalog_search_deduplicates_tokens_case_insensitive(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    app_settings_factory: Callable[..., AppSettings],
) -> None:
    with build_catalog_search_context(
        tmp_path=tmp_path,
        monkeypatch=monkeypatch,
        app_settings_factory=app_settings_factory,
    ) as client:
        response = client.get(
            "/catalog",
            params=[("search", "PROC_CHECKOUT"), ("search", "proc_checkout")],
        )
        assert response.status_code == 200
        assert response.text.count('data-search-token="proc_checkout"') == 1


def test_catalog_search_returns_empty_for_unknown_token(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    app_settings_factory: Callable[..., AppSettings],
) -> None:
    with build_catalog_search_context(
        tmp_path=tmp_path,
        monkeypatch=monkeypatch,
        app_settings_factory=app_settings_factory,
    ) as client:
        response = client.get("/catalog", params=[("search", "no_such_token")])
        assert response.status_code == 200
        assert "Checkout Service" not in response.text
        assert "Support Service" not in response.text
        assert "0 scenes" in response.text


def test_catalog_search_keeps_tokens_in_group_filter_links(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    app_settings_factory: Callable[..., AppSettings],
) -> None:
    with build_catalog_search_context(
        tmp_path=tmp_path,
        monkeypatch=monkeypatch,
        app_settings_factory=app_settings_factory,
    ) as client:
        response = client.get("/catalog", params=[("search", "proc_refund")])
        assert response.status_code == 200
        assert "search=proc_refund" in response.text
