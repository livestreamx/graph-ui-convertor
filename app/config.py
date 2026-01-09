from __future__ import annotations

import os
from pathlib import Path
from typing import ClassVar

from domain.catalog import CatalogIndexConfig
from pydantic import BaseModel, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic_settings.sources import PydanticBaseSettingsSource, YamlConfigSettingsSource

DEFAULT_CONFIG_PATH = Path("config/catalog/app.s3.yaml")


class S3Settings(BaseModel):
    bucket: str = ""
    prefix: str = ""
    region: str | None = None
    endpoint_url: str | None = None
    access_key_id: str | None = None
    secret_access_key: str | None = None
    session_token: str | None = None
    use_path_style: bool = False


class CatalogSettings(BaseModel):
    title: str = "CJM Catalog"
    s3: S3Settings = S3Settings()
    excalidraw_in_dir: Path = Path("data/excalidraw_in")
    excalidraw_out_dir: Path = Path("data/excalidraw_out")
    roundtrip_dir: Path = Path("data/roundtrip")
    index_path: Path = Path("data/catalog/index.json")
    auto_build_index: bool = True
    rebuild_index_on_start: bool = False
    generate_excalidraw_on_demand: bool = True
    cache_excalidraw_on_demand: bool = True
    group_by: list[str] = Field(default_factory=lambda: ["markup_type"])
    title_field: str = "service_name"
    tag_fields: list[str] = Field(default_factory=list)
    sort_by: str = "title"
    sort_order: str = "asc"
    unknown_value: str = "unknown"
    excalidraw_base_url: str = "/excalidraw"
    excalidraw_proxy_upstream: str | None = None
    excalidraw_proxy_prefix: str = "/excalidraw"
    excalidraw_max_url_length: int = 8000
    rebuild_token: str | None = None

    @field_validator("sort_order", mode="before")
    @classmethod
    def normalize_sort_order(cls, value: object) -> str:
        return str(value).lower() if value else "asc"

    @field_validator("group_by", "tag_fields", mode="before")
    @classmethod
    def normalize_lists(cls, value: object) -> list[str]:
        if value is None:
            return []
        if isinstance(value, list):
            return [str(item) for item in value]
        return [str(value)]

    def to_index_config(self) -> CatalogIndexConfig:
        return CatalogIndexConfig(
            markup_dir=Path(self.s3.prefix or ""),
            excalidraw_in_dir=self.excalidraw_in_dir,
            index_path=self.index_path,
            group_by=list(self.group_by),
            title_field=self.title_field,
            tag_fields=list(self.tag_fields),
            sort_by=self.sort_by,
            sort_order=self.sort_order,
            unknown_value=self.unknown_value,
        )


class AppSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="CJM_", env_nested_delimiter="__")

    catalog: CatalogSettings = CatalogSettings()

    _yaml_path: ClassVar[Path | None] = None

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        sources: list[PydanticBaseSettingsSource] = []
        if cls._yaml_path:
            sources.append(YamlConfigSettingsSource(settings_cls, yaml_file=cls._yaml_path))
        sources.extend([init_settings, env_settings, dotenv_settings, file_secret_settings])
        return tuple(sources)


def load_settings(config_path: Path | None = None) -> AppSettings:
    env_path = os.getenv("CJM_CONFIG_PATH")
    resolved_path: Path | None = None

    if config_path is not None:
        resolved_path = config_path
    elif env_path:
        resolved_path = Path(env_path)
    elif DEFAULT_CONFIG_PATH.exists():
        resolved_path = DEFAULT_CONFIG_PATH

    previous = AppSettings._yaml_path
    try:
        if resolved_path is not None:
            if not resolved_path.exists():
                msg = f"Config file not found: {resolved_path}"
                raise FileNotFoundError(msg)
            AppSettings._yaml_path = resolved_path
        return AppSettings()
    finally:
        AppSettings._yaml_path = previous
