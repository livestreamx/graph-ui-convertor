from __future__ import annotations

import time
from collections.abc import Callable
from pathlib import Path

import pytest
from botocore.stub import Stubber  # type: ignore[import-untyped]
from fastapi.testclient import TestClient

from app.config import AppSettings
from app.web_main import create_app
from tests.adapters.s3.s3_utils import add_get_object, add_list_objects, create_stubbed_client


def test_catalog_rebuilds_index_periodically_from_s3(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    app_settings_factory: Callable[..., AppSettings],
) -> None:
    client = create_stubbed_client()
    stubber = Stubber(client)

    billing_payload = {
        "markup_type": "service",
        "finedog_unit_meta": {"service_name": "Billing"},
        "procedures": [],
    }
    orders_payload = {
        "markup_type": "service",
        "finedog_unit_meta": {"service_name": "Orders"},
        "procedures": [],
    }

    add_list_objects(
        stubber,
        bucket="cjm-bucket",
        prefix="markup/",
        keys=["markup/billing.json"],
    )
    add_get_object(
        stubber,
        bucket="cjm-bucket",
        key="markup/billing.json",
        payload=billing_payload,
    )

    add_list_objects(
        stubber,
        bucket="cjm-bucket",
        prefix="markup/",
        keys=["markup/billing.json", "markup/orders.json"],
    )
    add_get_object(
        stubber,
        bucket="cjm-bucket",
        key="markup/billing.json",
        payload=billing_payload,
    )
    add_get_object(
        stubber,
        bucket="cjm-bucket",
        key="markup/orders.json",
        payload=orders_payload,
    )

    stubber.activate()
    monkeypatch.setattr("adapters.s3.s3_client.create_s3_client", lambda **_: client)
    monkeypatch.setattr("adapters.s3.markup_catalog_source.create_s3_client", lambda **_: client)
    monkeypatch.setattr("adapters.s3.markup_repository.create_s3_client", lambda **_: client)

    settings = app_settings_factory(
        excalidraw_in_dir=tmp_path / "excalidraw_in",
        excalidraw_out_dir=tmp_path / "excalidraw_out",
        unidraw_in_dir=tmp_path / "unidraw_in",
        unidraw_out_dir=tmp_path / "unidraw_out",
        roundtrip_dir=tmp_path / "roundtrip",
        index_path=tmp_path / "catalog" / "index.json",
        auto_build_index=True,
        rebuild_index_on_start=True,
        index_refresh_interval_seconds=0.05,
    )

    try:
        with TestClient(create_app(settings)) as api:
            initial = api.get("/api/index")
            assert initial.status_code == 200
            assert len(initial.json()["items"]) == 1

            deadline = time.monotonic() + 2.0
            refreshed_count = 1
            while time.monotonic() < deadline:
                response = api.get("/api/index")
                assert response.status_code == 200
                refreshed_count = len(response.json()["items"])
                if refreshed_count == 2:
                    break
                time.sleep(0.05)

            assert refreshed_count == 2
    finally:
        stubber.deactivate()
