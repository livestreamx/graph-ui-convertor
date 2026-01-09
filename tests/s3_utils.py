from __future__ import annotations

import io
import json
from datetime import UTC, datetime
from typing import Any

import boto3
import pytest
from botocore.client import BaseClient
from botocore.response import StreamingBody
from botocore.stub import Stubber


def create_stubbed_client() -> BaseClient:
    return boto3.client("s3", region_name="us-east-1")


def add_list_objects(
    stubber: Stubber,
    *,
    bucket: str,
    prefix: str,
    keys: list[str],
    last_modified: datetime | None = None,
) -> None:
    last_modified = last_modified or datetime(2024, 1, 1, tzinfo=UTC)
    contents = [{"Key": key, "LastModified": last_modified} for key in keys]
    stubber.add_response(
        "list_objects_v2",
        {"IsTruncated": False, "Contents": contents},
        {"Bucket": bucket, "Prefix": prefix},
    )


def add_get_object(
    stubber: Stubber,
    *,
    bucket: str,
    key: str,
    payload: dict[str, Any],
) -> None:
    raw = json.dumps(payload).encode("utf-8")
    stubber.add_response(
        "get_object",
        {"Body": StreamingBody(io.BytesIO(raw), len(raw))},
        {"Bucket": bucket, "Key": key},
    )


def stub_s3_catalog(
    *,
    monkeypatch: pytest.MonkeyPatch | None,
    objects: dict[str, dict[str, Any]],
    bucket: str,
    prefix: str,
    list_repeats: int = 1,
) -> tuple[BaseClient, Stubber]:
    client = create_stubbed_client()
    stubber = Stubber(client)
    keys = list(objects.keys())
    for _ in range(list_repeats):
        add_list_objects(stubber, bucket=bucket, prefix=prefix, keys=keys)
        for key, payload in objects.items():
            add_get_object(stubber, bucket=bucket, key=key, payload=payload)
    stubber.activate()
    if monkeypatch is not None:
        monkeypatch.setattr("adapters.s3.s3_client.create_s3_client", lambda **_: client)
        monkeypatch.setattr(
            "adapters.s3.markup_catalog_source.create_s3_client", lambda **_: client
        )
        monkeypatch.setattr(
            "adapters.s3.markup_repository.create_s3_client", lambda **_: client
        )
    return client, stubber
