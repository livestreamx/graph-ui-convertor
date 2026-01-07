from __future__ import annotations

import json
from pathlib import Path

from adapters.filesystem.catalog_index_repository import FileSystemCatalogIndexRepository
from adapters.filesystem.markup_catalog_source import FileSystemMarkupCatalogSource
from domain.catalog import CatalogIndexConfig
from domain.services.build_catalog_index import BuildCatalogIndex


def test_build_catalog_index_extracts_fields(tmp_path: Path) -> None:
    markup_dir = tmp_path / "markup"
    excalidraw_dir = tmp_path / "excalidraw_in"
    index_path = tmp_path / "catalog" / "index.json"
    markup_dir.mkdir(parents=True)
    excalidraw_dir.mkdir(parents=True)

    payload = {
        "markup_type": "service",
        "finedog_unit_meta": {
            "service_name": "Billing",
            "unit_id": "fd-01",
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
    (markup_dir / "billing.json").write_text(json.dumps(payload), encoding="utf-8")

    config = CatalogIndexConfig(
        markup_dir=markup_dir,
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
        FileSystemMarkupCatalogSource(),
        FileSystemCatalogIndexRepository(),
    )
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
    assert item.excalidraw_rel_path == "billing.excalidraw"
    assert item.markup_rel_path == "billing.json"

    index_again = builder.build(config)
    assert index_again.items[0].scene_id == item.scene_id
