from __future__ import annotations

from pathlib import Path
from typing import Any

from botocore.client import BaseClient  # type: ignore[import-untyped]
from domain.models import MarkupDocument
from domain.ports.repositories import MarkupRepository

from adapters.s3.markup_catalog_source import S3MarkupCatalogSource
from adapters.s3.s3_client import create_s3_client


class S3MarkupRepository(MarkupRepository):
    def __init__(self, source: S3MarkupCatalogSource) -> None:
        self._source = source

    @classmethod
    def from_client(
        cls,
        client: BaseClient,
        bucket: str,
        prefix: str = "",
    ) -> S3MarkupRepository:
        return cls(S3MarkupCatalogSource(client, bucket, prefix))

    @classmethod
    def from_settings(cls, settings: Any) -> S3MarkupRepository:
        client = create_s3_client(
            region=settings.region,
            endpoint_url=settings.endpoint_url,
            access_key_id=settings.access_key_id,
            secret_access_key=settings.secret_access_key,
            session_token=settings.session_token,
            use_path_style=settings.use_path_style,
        )
        return cls(S3MarkupCatalogSource(client, settings.bucket, settings.prefix))

    def load_all(self, directory: Path) -> list[MarkupDocument]:
        return [item.document for item in self._source.load_all(directory)]

    def load_all_with_paths(self, directory: Path) -> list[tuple[Path, MarkupDocument]]:
        return [(item.path, item.document) for item in self._source.load_all(directory)]

    def load_by_path(self, path: Path) -> MarkupDocument:
        return self._source.load_document(path)

    def save(self, document: MarkupDocument, path: Path) -> None:
        raise NotImplementedError("S3MarkupRepository is read-only.")
