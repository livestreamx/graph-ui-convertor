from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from adapters.excalidraw.repository import FileSystemExcalidrawRepository
from adapters.filesystem.catalog_index_repository import FileSystemCatalogIndexRepository
from adapters.layout.grid import GridLayoutEngine
from adapters.s3.markup_catalog_source import S3MarkupCatalogSource
from adapters.unidraw.repository import FileSystemUnidrawRepository
from app.config import AppSettings
from app.web_main import create_app
from domain.catalog import CatalogIndexConfig
from domain.models import MarkupDocument
from domain.services.build_catalog_index import BuildCatalogIndex
from domain.services.convert_markup_to_excalidraw import MarkupToExcalidrawConverter
from domain.services.convert_markup_to_unidraw import MarkupToUnidrawConverter
from tests.adapters.s3.s3_utils import add_get_object, stub_s3_catalog


@dataclass(frozen=True)
class CatalogTestContext:
    client: TestClient
    scene_id: str
    scene_path: Path
    payload: dict[str, Any]
    expected_element_count: int | None = None


def billing_payload() -> dict[str, Any]:
    return {
        "markup_type": "service",
        "finedog_unit_meta": {"service_name": "Billing"},
        "procedures": [
            {
                "proc_id": "p1",
                "start_block_ids": ["a"],
                "end_block_ids": ["b"],
                "branches": {"a": ["b"]},
            }
        ],
    }


@contextmanager
def build_catalog_test_context(
    *,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    app_settings_factory: Callable[..., AppSettings],
    include_upload_stub: bool = False,
    settings_overrides: Mapping[str, Any] | None = None,
) -> Iterator[CatalogTestContext]:
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

    payload = billing_payload()
    objects = {"markup/billing.json": payload}
    client, stubber = stub_s3_catalog(
        monkeypatch=monkeypatch,
        objects=objects,
        bucket="cjm-bucket",
        prefix="markup/",
        list_repeats=1,
    )
    if include_upload_stub:
        add_get_object(stubber, bucket="cjm-bucket", key="markup/billing.json", payload=payload)

    markup_doc = MarkupDocument.model_validate(payload)
    excalidraw_doc = MarkupToExcalidrawConverter(GridLayoutEngine()).convert(markup_doc)
    expected_element_count = len(excalidraw_doc.elements)
    scene_path = excalidraw_in_dir / "billing.excalidraw"
    FileSystemExcalidrawRepository().save(excalidraw_doc, scene_path)
    unidraw_doc = MarkupToUnidrawConverter(GridLayoutEngine()).convert(markup_doc)
    FileSystemUnidrawRepository().save(unidraw_doc, unidraw_in_dir / "billing.unidraw")

    config = CatalogIndexConfig(
        markup_dir=Path("markup"),
        excalidraw_in_dir=excalidraw_in_dir,
        unidraw_in_dir=unidraw_in_dir,
        index_path=index_path,
        group_by=["markup_type"],
        title_field="finedog_unit_meta.service_name",
        tag_fields=[],
        sort_by="title",
        sort_order="asc",
        unknown_value="unknown",
    )

    BuildCatalogIndex(
        S3MarkupCatalogSource(client, "cjm-bucket", "markup/"),
        FileSystemCatalogIndexRepository(),
    ).build(config)

    settings_kwargs: dict[str, Any] = {
        "diagram_excalidraw_enabled": True,
        "excalidraw_in_dir": excalidraw_in_dir,
        "excalidraw_out_dir": excalidraw_out_dir,
        "unidraw_in_dir": unidraw_in_dir,
        "unidraw_out_dir": unidraw_out_dir,
        "roundtrip_dir": roundtrip_dir,
        "index_path": index_path,
    }
    if settings_overrides is not None:
        settings_kwargs.update(settings_overrides)

    settings = app_settings_factory(**settings_kwargs)

    client_api = TestClient(create_app(settings))
    try:
        index_response = client_api.get("/api/index")
        assert index_response.status_code == 200
        scene_id = index_response.json()["items"][0]["scene_id"]
        yield CatalogTestContext(
            client=client_api,
            scene_id=scene_id,
            scene_path=scene_path,
            payload=payload,
            expected_element_count=expected_element_count,
        )
    finally:
        client_api.close()
        stubber.deactivate()
