from __future__ import annotations

import argparse
import mimetypes
import time
from pathlib import Path

from adapters.s3.s3_client import create_s3_client


ALLOWED_SUFFIXES = (".json", ".excalidraw.json", ".txt")


def iter_files(source: Path) -> list[Path]:
    return [
        path
        for path in source.rglob("*")
        if path.is_file() and path.name.endswith(ALLOWED_SUFFIXES)
    ]


def build_key(prefix: str, relative: Path) -> str:
    key_prefix = prefix.lstrip("/")
    if key_prefix and not key_prefix.endswith("/"):
        key_prefix = f"{key_prefix}/"
    return f"{key_prefix}{relative.as_posix()}"


def wait_for_s3(client, timeout: int = 30) -> None:
    deadline = time.time() + timeout
    while True:
        try:
            client.list_buckets()
            return
        except Exception:
            if time.time() >= deadline:
                raise
            time.sleep(1)


def ensure_bucket(client, bucket: str, region: str | None) -> None:
    try:
        client.head_bucket(Bucket=bucket)
        return
    except Exception:
        pass
    params = {"Bucket": bucket}
    if region and region != "us-east-1":
        params["CreateBucketConfiguration"] = {"LocationConstraint": region}
    client.create_bucket(**params)


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed S3 bucket with markup files.")
    parser.add_argument("--endpoint", required=True)
    parser.add_argument("--access-key", required=True)
    parser.add_argument("--secret-key", required=True)
    parser.add_argument("--bucket", required=True)
    parser.add_argument("--prefix", default="")
    parser.add_argument("--region", default="us-east-1")
    parser.add_argument("--source", required=True)
    parser.add_argument("--path-style", action="store_true")
    args = parser.parse_args()

    source = Path(args.source)
    if not source.exists():
        raise SystemExit(f"Source directory not found: {source}")

    client = create_s3_client(
        region=args.region,
        endpoint_url=args.endpoint,
        access_key_id=args.access_key,
        secret_access_key=args.secret_key,
        use_path_style=args.path_style,
    )
    wait_for_s3(client)
    ensure_bucket(client, args.bucket, args.region)

    files = iter_files(source)
    if not files:
        raise SystemExit(f"No markup files found under {source}")

    for path in files:
        relative = path.relative_to(source)
        key = build_key(args.prefix, relative)
        content_type, _ = mimetypes.guess_type(path.name)
        with path.open("rb") as handle:
            client.put_object(
                Bucket=args.bucket,
                Key=key,
                Body=handle,
                ContentType=content_type or "application/json",
            )
        print(f"Uploaded {relative} -> s3://{args.bucket}/{key}")


if __name__ == "__main__":
    main()
