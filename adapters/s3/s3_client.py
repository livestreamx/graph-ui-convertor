from __future__ import annotations

import boto3  # type: ignore[import-untyped]
from botocore.client import BaseClient  # type: ignore[import-untyped]
from botocore.config import Config  # type: ignore[import-untyped]


def create_s3_client(
    *,
    region: str | None = None,
    endpoint_url: str | None = None,
    access_key_id: str | None = None,
    secret_access_key: str | None = None,
    session_token: str | None = None,
    use_path_style: bool = False,
) -> BaseClient:
    config: Config | None = None
    if use_path_style:
        config = Config(s3={"addressing_style": "path"})
    return boto3.client(
        "s3",
        region_name=region,
        endpoint_url=endpoint_url or None,
        aws_access_key_id=access_key_id or None,
        aws_secret_access_key=secret_access_key or None,
        aws_session_token=session_token or None,
        config=config,
    )
