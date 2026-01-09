from __future__ import annotations

from adapters.filesystem.markup_catalog_source import FileSystemMarkupCatalogSource
from adapters.filesystem.markup_repository import FileSystemMarkupRepository
from adapters.s3.markup_catalog_source import S3MarkupCatalogSource
from adapters.s3.markup_repository import S3MarkupRepository
from app.config import AppSettings
from domain.ports.catalog import MarkupCatalogSource
from domain.ports.repositories import MarkupRepository


def build_markup_source(settings: AppSettings) -> MarkupCatalogSource:
    if settings.catalog.markup_source == "s3":
        s3 = settings.catalog.s3
        if not s3.bucket:
            msg = "catalog.s3.bucket is required when markup_source is s3"
            raise ValueError(msg)
        return S3MarkupCatalogSource.from_settings(s3)
    return FileSystemMarkupCatalogSource()


def build_markup_repository(settings: AppSettings) -> MarkupRepository:
    if settings.catalog.markup_source == "s3":
        s3 = settings.catalog.s3
        if not s3.bucket:
            msg = "catalog.s3.bucket is required when markup_source is s3"
            raise ValueError(msg)
        return S3MarkupRepository.from_settings(s3)
    return FileSystemMarkupRepository()
