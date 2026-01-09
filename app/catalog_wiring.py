from __future__ import annotations

from adapters.s3.markup_catalog_source import S3MarkupCatalogSource
from adapters.s3.markup_repository import S3MarkupRepository
from domain.ports.catalog import MarkupCatalogSource
from domain.ports.repositories import MarkupRepository

from app.config import AppSettings


def build_markup_source(settings: AppSettings) -> MarkupCatalogSource:
    s3 = settings.catalog.s3
    if not s3.bucket:
        msg = "catalog.s3.bucket is required"
        raise ValueError(msg)
    return S3MarkupCatalogSource.from_settings(s3)


def build_markup_repository(settings: AppSettings) -> MarkupRepository:
    s3 = settings.catalog.s3
    if not s3.bucket:
        msg = "catalog.s3.bucket is required"
        raise ValueError(msg)
    return S3MarkupRepository.from_settings(s3)
