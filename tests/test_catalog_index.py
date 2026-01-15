from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from adapters.filesystem.catalog_index_repository import FileSystemCatalogIndexRepository
from adapters.s3.markup_catalog_source import S3MarkupCatalogSource
from domain.catalog import CatalogIndexConfig
from domain.services.build_catalog_index import BuildCatalogIndex

from tests.s3_utils import stub_s3_catalog


def test_build_catalog_index_extracts_fields(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    excalidraw_dir = tmp_path / "excalidraw_in"
    index_path = tmp_path / "catalog" / "index.json"
    excalidraw_dir.mkdir(parents=True)

    payload = {
        "markup_type": "service",
        "finedog_unit_meta": {
            "service_name": "Billing",
            "unit_id": "fd-01",
            "criticality_level": "BC",
            "team_id": 42,
            "team_name": "Core Payments",
            "responsible_logins": ["alpha", "beta"],
        },
        "custom": {"domain": "payments"},
        "tags": ["alpha", "beta"],
        "procedures": [
            {
                "proc_id": "p1",
                "start_block_ids": ["a"],
                "end_block_ids": ["b"],
                "branches": {"a": ["b"]},
            }
        ],
    }
    objects = {"markup/billing.json": payload}
    client, stubber = stub_s3_catalog(
        monkeypatch=monkeypatch,
        objects=objects,
        bucket="cjm-bucket",
        prefix="markup/",
        list_repeats=2,
    )

    config = CatalogIndexConfig(
        markup_dir=Path("markup"),
        excalidraw_in_dir=excalidraw_dir,
        index_path=index_path,
        group_by=["custom.domain", "markup_type"],
        title_field="finedog_unit_meta.service_name",
        tag_fields=["tags"],
        sort_by="title",
        sort_order="asc",
        unknown_value="unknown",
    )

    builder = BuildCatalogIndex(
        S3MarkupCatalogSource(client, "cjm-bucket", "markup/"),
        FileSystemCatalogIndexRepository(),
    )
    try:
        index = builder.build(config)

        assert index_path.exists()
        assert len(index.items) == 1

        item = index.items[0]
        assert item.title == "Billing"
        assert item.tags == ["alpha", "beta"]
        assert item.group_values["custom.domain"] == "payments"
        assert item.group_values["markup_type"] == "service"
        assert item.markup_type == "service"
        assert item.finedog_unit_id == "fd-01"
        assert item.criticality_level == "BC"
        assert item.team_id == "42"
        assert item.team_name == "Core Payments"
        assert item.markup_meta["responsible_logins"] == "alpha, beta"
        assert item.excalidraw_rel_path == "billing.excalidraw"
        assert item.unidraw_rel_path == "billing.unidraw"
        assert item.markup_rel_path == "billing.json"
        expected_timestamp = datetime(2024, 1, 1, tzinfo=UTC).isoformat()
        assert item.updated_at == expected_timestamp

        index_again = builder.build(config)
        assert index_again.items[0].scene_id == item.scene_id
    finally:
        stubber.deactivate()
