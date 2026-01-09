from __future__ import annotations

import io
import json
import shutil
import socket
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path

import boto3
import pytest
from fastapi.testclient import TestClient
from botocore.response import StreamingBody
from botocore.stub import Stubber

from adapters.s3.markup_catalog_source import S3MarkupCatalogSource
from adapters.s3.s3_client import create_s3_client
from app.config import AppSettings, CatalogSettings, S3Settings
from app.web_main import create_app
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


def test_s3_integration_builds_index(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    use_docker = _docker_available()
    port = None
    container = None
    client = None
    stubber = None
    endpoint_url = None

    if use_docker:
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

        client = create_s3_client(
            region="us-east-1",
            endpoint_url=f"http://127.0.0.1:{port}",
            access_key_id="minioadmin",
            secret_access_key="minioadmin",
            use_path_style=True,
        )
        _wait_for_minio(client)
        client.create_bucket(Bucket="cjm-markup")
        endpoint_url = f"http://127.0.0.1:{port}"

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
    else:
        client = boto3.client("s3", region_name="us-east-1")
        stubber = Stubber(client)
        last_modified = datetime(2024, 1, 1, tzinfo=UTC)
        list_response = {
            "IsTruncated": False,
            "Contents": [
                {"Key": "markup/team/alpha.json", "LastModified": last_modified},
                {"Key": "markup/team/beta/service.json", "LastModified": last_modified},
                {"Key": "markup/ignored.png", "LastModified": last_modified},
            ],
        }
        stubber.add_response(
            "list_objects_v2",
            list_response,
            {"Bucket": "cjm-markup", "Prefix": "markup/"},
        )
        payload_bytes = json.dumps({"markup_type": "service", "procedures": []}).encode("utf-8")
        for key in ("markup/team/alpha.json", "markup/team/beta/service.json", "markup/team/alpha.json"):
            stubber.add_response(
                "get_object",
                {"Body": StreamingBody(io.BytesIO(payload_bytes), len(payload_bytes))},
                {"Bucket": "cjm-markup", "Key": key},
            )
        stubber.activate()
        endpoint_url = "http://stubbed-s3.local"
        monkeypatch.setattr("adapters.s3.s3_client.create_s3_client", lambda **_: client)
        monkeypatch.setattr("adapters.s3.markup_catalog_source.create_s3_client", lambda **_: client)
        monkeypatch.setattr("adapters.s3.markup_repository.create_s3_client", lambda **_: client)

    try:
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

        settings = AppSettings(
            catalog=CatalogSettings(
                title="Test Catalog",
                markup_dir=Path("markup"),
                markup_source="s3",
                s3=S3Settings(
                    bucket="cjm-markup",
                    prefix="markup/",
                    region="us-east-1",
                    endpoint_url=endpoint_url,
                    access_key_id="minioadmin",
                    secret_access_key="minioadmin",
                    use_path_style=True,
                ),
                excalidraw_in_dir=tmp_path / "excalidraw_in",
                excalidraw_out_dir=tmp_path / "excalidraw_out",
                roundtrip_dir=tmp_path / "roundtrip",
                index_path=index_path,
                group_by=["markup_type"],
                title_field="service_name",
                tag_fields=[],
                sort_by="title",
                sort_order="asc",
                unknown_value="unknown",
                excalidraw_base_url="http://example.com",
                excalidraw_proxy_upstream=None,
                excalidraw_proxy_prefix="/excalidraw",
                excalidraw_max_url_length=8000,
                rebuild_token=None,
                auto_build_index=True,
                generate_excalidraw_on_demand=True,
                cache_excalidraw_on_demand=True,
            )
        )

        client_api = TestClient(create_app(settings))
        scene_id = index.items[0].scene_id
        response = client_api.get(f"/api/scenes/{scene_id}")
        assert response.status_code == 200
        payload = response.json()
        assert payload.get("elements") is not None
        cached = (tmp_path / "excalidraw_in" / index.items[0].excalidraw_rel_path)
        assert cached.exists()
    finally:
        if stubber is not None:
            stubber.deactivate()
        if container:
            subprocess.run(["docker", "rm", "-f", container], check=False, capture_output=True)
