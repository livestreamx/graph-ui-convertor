from __future__ import annotations

import json
import shutil
import socket
import subprocess
import time
from pathlib import Path

import pytest

from adapters.s3.markup_catalog_source import S3MarkupCatalogSource
from adapters.s3.s3_client import create_s3_client
from domain.catalog import CatalogIndexConfig
from domain.services.build_catalog_index import BuildCatalogIndex
from adapters.filesystem.catalog_index_repository import FileSystemCatalogIndexRepository


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _docker_available() -> bool:
    if not shutil.which("docker"):
        return False
    try:
        subprocess.run(["docker", "info"], check=True, capture_output=True)
    except Exception:
        return False
    return True


def _wait_for_minio(client, timeout: int = 20) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            client.list_buckets()
            return
        except Exception:
            time.sleep(0.5)
    raise RuntimeError("MinIO did not become ready")


def test_s3_integration_builds_index(tmp_path: Path) -> None:
    if not _docker_available():
        pytest.skip("Docker not available")

    port = _free_port()
    console_port = _free_port()
    container = f"cjm-test-minio-{port}"

    subprocess.run(
        [
            "docker",
            "run",
            "-d",
            "--name",
            container,
            "-p",
            f"{port}:9000",
            "-p",
            f"{console_port}:9001",
            "-e",
            "MINIO_ROOT_USER=minioadmin",
            "-e",
            "MINIO_ROOT_PASSWORD=minioadmin",
            "minio/minio:latest",
            "server",
            "/data",
            "--console-address",
            ":9001",
        ],
        check=True,
        capture_output=True,
    )

    try:
        client = create_s3_client(
            region="us-east-1",
            endpoint_url=f"http://127.0.0.1:{port}",
            access_key_id="minioadmin",
            secret_access_key="minioadmin",
            use_path_style=True,
        )
        _wait_for_minio(client)
        client.create_bucket(Bucket="cjm-markup")

        payload = {"markup_type": "service", "procedures": []}
        client.put_object(
            Bucket="cjm-markup",
            Key="markup/team/alpha.json",
            Body=json.dumps(payload).encode("utf-8"),
        )
        client.put_object(
            Bucket="cjm-markup",
            Key="markup/team/beta/service.json",
            Body=json.dumps(payload).encode("utf-8"),
        )
        client.put_object(
            Bucket="cjm-markup",
            Key="markup/ignored.png",
            Body=b"ignored",
        )

        source = S3MarkupCatalogSource(client, "cjm-markup", "markup/")
        index_path = tmp_path / "index.json"
        config = CatalogIndexConfig(
            markup_dir=Path("markup"),
            excalidraw_in_dir=tmp_path / "excalidraw_in",
            index_path=index_path,
            group_by=["markup_type"],
            title_field="service_name",
            tag_fields=[],
            sort_by="title",
            sort_order="asc",
            unknown_value="unknown",
        )
        index = BuildCatalogIndex(source, FileSystemCatalogIndexRepository()).build(config)

        assert len(index.items) == 2
        rel_paths = {item.markup_rel_path for item in index.items}
        assert rel_paths == {"team/alpha.json", "team/beta/service.json"}
    finally:
        subprocess.run(["docker", "rm", "-f", container], check=False, capture_output=True)
