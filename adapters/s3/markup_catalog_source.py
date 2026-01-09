from __future__ import annotations

import json
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from botocore.client import BaseClient  # type: ignore[import-untyped]
from botocore.exceptions import ClientError  # type: ignore[import-untyped]
from botocore.response import StreamingBody  # type: ignore[import-untyped]
from domain.catalog import MarkupSourceItem
from domain.models import MarkupDocument
from domain.ports.catalog import MarkupCatalogSource

from adapters.filesystem.markup_utils import strip_markup_comments
from adapters.s3.s3_client import create_s3_client


class S3MarkupCatalogSource(MarkupCatalogSource):
    def __init__(
        self,
        client: BaseClient,
        bucket: str,
        prefix: str = "",
        allowed_suffixes: tuple[str, ...] = (".json", ".excalidraw.json", ".txt"),
    ) -> None:
        self._client = client
        self._bucket = bucket
        self._prefix = self._normalize_prefix(prefix)
        self._allowed_suffixes = allowed_suffixes

    @classmethod
    def from_settings(cls, settings: Any) -> S3MarkupCatalogSource:
        client = create_s3_client(
            region=settings.region,
            endpoint_url=settings.endpoint_url,
            access_key_id=settings.access_key_id,
            secret_access_key=settings.secret_access_key,
            session_token=settings.session_token,
            use_path_style=settings.use_path_style,
        )
        return cls(client, settings.bucket, settings.prefix)

    def load_all(self, directory: Path) -> list[MarkupSourceItem]:
        prefix = self._prefix or self._normalize_prefix(directory.as_posix())
        items: list[MarkupSourceItem] = []
        for key, updated_at in self._iter_objects(prefix):
            raw = self._load_raw(key)
            document = MarkupDocument.model_validate(raw)
            updated = updated_at or datetime.now(tz=UTC)
            if updated.tzinfo is None:
                updated = updated.replace(tzinfo=UTC)
            items.append(
                MarkupSourceItem(
                    path=Path(key),
                    document=document,
                    raw=raw,
                    updated_at=updated,
                )
            )
        return items

    def load_document(self, path: Path) -> MarkupDocument:
        key = self.build_key(path)
        try:
            raw = self._load_raw(key)
        except ClientError as exc:
            code = exc.response.get("Error", {}).get("Code", "")
            if code in {"NoSuchKey", "404", "NotFound"}:
                raise FileNotFoundError(key) from exc
            raise
        return MarkupDocument.model_validate(raw)

    def build_key(self, path: Path) -> str:
        key = path.as_posix().lstrip("/")
        if not self._prefix:
            return key
        if key.startswith(self._prefix):
            return key
        return f"{self._prefix}{key}"

    def _iter_objects(self, prefix: str) -> Iterable[tuple[str, datetime | None]]:
        token: str | None = None
        while True:
            payload: dict[str, Any] = {"Bucket": self._bucket, "Prefix": prefix}
            if token:
                payload["ContinuationToken"] = token
            response = self._client.list_objects_v2(**payload)
            for entry in response.get("Contents", []) or []:
                key = entry.get("Key")
                if not key or not self._is_markup_key(key):
                    continue
                yield key, entry.get("LastModified")
            if not response.get("IsTruncated"):
                break
            token = response.get("NextContinuationToken")

    def _load_raw(self, key: str) -> dict[str, Any]:
        response = self._client.get_object(Bucket=self._bucket, Key=key)
        body = response.get("Body")
        raw_bytes = self._read_body(body)
        cleaned = strip_markup_comments(raw_bytes.decode("utf-8"))
        content = json.loads(cleaned)
        return content if isinstance(content, dict) else {}

    def _read_body(self, body: Any) -> bytes:
        if isinstance(body, bytes | bytearray):
            return bytes(body)
        if isinstance(body, StreamingBody):
            return cast(bytes, body.read())
        if hasattr(body, "read"):
            return cast(bytes, body.read())
        return b""

    def _is_markup_key(self, key: str) -> bool:
        lowered = key.lower()
        return any(lowered.endswith(suffix) for suffix in self._allowed_suffixes)

    def _normalize_prefix(self, prefix: str) -> str:
        normalized = prefix.lstrip("/")
        if normalized in {".", "./"}:
            return ""
        if normalized and not normalized.endswith("/"):
            normalized = f"{normalized}/"
        return normalized
