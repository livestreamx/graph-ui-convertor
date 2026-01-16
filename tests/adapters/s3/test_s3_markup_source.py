from __future__ import annotations

import io
from datetime import UTC, datetime
from pathlib import Path

import boto3  # type: ignore[import-untyped]
from botocore.response import StreamingBody  # type: ignore[import-untyped]
from botocore.stub import Stubber  # type: ignore[import-untyped]

from adapters.s3.markup_catalog_source import S3MarkupCatalogSource


def test_s3_markup_catalog_source_loads_items() -> None:
    client = boto3.client("s3", region_name="us-east-1")
    stubber = Stubber(client)

    last_modified = datetime(2024, 1, 1, tzinfo=UTC)
    list_response = {
        "IsTruncated": False,
        "Contents": [
            {"Key": "markup/billing.json", "LastModified": last_modified},
            {"Key": "markup/ignore.png", "LastModified": last_modified},
        ],
    }
    stubber.add_response(
        "list_objects_v2",
        list_response,
        {"Bucket": "cjm-bucket", "Prefix": "markup/"},
    )

    payload = b'{"markup_type":"service","procedures":[]}'
    stubber.add_response(
        "get_object",
        {"Body": StreamingBody(io.BytesIO(payload), len(payload))},
        {"Bucket": "cjm-bucket", "Key": "markup/billing.json"},
    )

    stubber.activate()
    try:
        source = S3MarkupCatalogSource(client, "cjm-bucket", "markup/")
        items = source.load_all(Path("markup"))
    finally:
        stubber.deactivate()

    assert len(items) == 1
    assert items[0].path == Path("markup/billing.json")
    assert items[0].document.markup_type == "service"
    assert items[0].updated_at == last_modified
