from __future__ import annotations

import os
from collections.abc import Callable, Generator
from pathlib import Path

import pytest

from app.config import AppSettings, CatalogSettings, S3Settings


def _clear_cjm_env() -> None:
    for key in list(os.environ):
        if key.startswith("CJM_"):
            os.environ.pop(key, None)


_clear_cjm_env()


@pytest.fixture(autouse=True)
def clear_cjm_env() -> Generator[None, None, None]:
    _clear_cjm_env()
    yield
    _clear_cjm_env()


@pytest.fixture
def s3_settings() -> S3Settings:
    return S3Settings(
        bucket="cjm-bucket",
        prefix="markup/",
        region="us-east-1",
        endpoint_url="http://stubbed-s3.local",
        access_key_id="test",
        secret_access_key="test",
        session_token=None,
        use_path_style=True,
    )


@pytest.fixture
def s3_settings_factory(s3_settings: S3Settings) -> Callable[..., S3Settings]:
    def _factory(**overrides: object) -> S3Settings:
        return s3_settings.model_copy(update=overrides)

    return _factory


@pytest.fixture
def catalog_settings(tmp_path: Path, s3_settings: S3Settings) -> CatalogSettings:
    return CatalogSettings(
        title="Test Catalog",
        s3=s3_settings,
        diagram_excalidraw_enabled=True,
        excalidraw_in_dir=tmp_path / "excalidraw_in",
        excalidraw_out_dir=tmp_path / "excalidraw_out",
        unidraw_in_dir=tmp_path / "unidraw_in",
        unidraw_out_dir=tmp_path / "unidraw_out",
        roundtrip_dir=tmp_path / "roundtrip",
        index_path=tmp_path / "catalog" / "index.json",
        auto_build_index=True,
        rebuild_index_on_start=False,
        generate_excalidraw_on_demand=True,
        cache_excalidraw_on_demand=True,
        invalidate_excalidraw_cache_on_start=True,
        group_by=["markup_type"],
        title_field="finedog_unit_meta.service_name",
        tag_fields=[],
        sort_by="title",
        sort_order="asc",
        unknown_value="unknown",
        ui_text_overrides={},
        excalidraw_base_url="http://testserver/excalidraw",
        excalidraw_proxy_upstream=None,
        excalidraw_proxy_prefix="/excalidraw",
        excalidraw_max_url_length=8000,
        unidraw_base_url="http://testserver/unidraw",
        unidraw_proxy_upstream=None,
        unidraw_proxy_prefix="/unidraw",
        unidraw_max_url_length=8000,
        rebuild_token=None,
        procedure_link_path=None,
        block_link_path=None,
    )


@pytest.fixture
def catalog_settings_factory(
    catalog_settings: CatalogSettings,
) -> Callable[..., CatalogSettings]:
    def _factory(**overrides: object) -> CatalogSettings:
        return catalog_settings.model_copy(update=overrides)

    return _factory


@pytest.fixture
def app_settings(catalog_settings: CatalogSettings) -> AppSettings:
    return AppSettings(catalog=catalog_settings)


@pytest.fixture
def app_settings_factory(
    catalog_settings_factory: Callable[..., CatalogSettings],
) -> Callable[..., AppSettings]:
    def _factory(**overrides: object) -> AppSettings:
        return AppSettings(catalog=catalog_settings_factory(**overrides))

    return _factory
