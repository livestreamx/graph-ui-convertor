from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Annotated, ClassVar
from urllib.parse import urlparse

from pydantic import (
    AfterValidator,
    AliasChoices,
    BaseModel,
    Field,
    HttpUrl,
    TypeAdapter,
    field_validator,
)
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict
from pydantic_settings.sources import PydanticBaseSettingsSource, YamlConfigSettingsSource

from domain.catalog import CatalogIndexConfig

DEFAULT_CONFIG_PATH = Path("config/catalog/app.s3.yaml")

_HTTP_URL_ADAPTER = TypeAdapter(HttpUrl)


def _split_string_list_value(raw_value: str) -> list[str]:
    raw = raw_value.strip()
    if not raw:
        return []
    if (
        (raw.startswith('"') and raw.endswith('"')) or (raw.startswith("'") and raw.endswith("'"))
    ) and len(raw) >= 2:
        raw = raw[1:-1].strip()
    if raw.startswith("[") and raw.endswith("]"):
        raw = raw[1:-1].strip()
    if not raw:
        return []
    return [
        token for token in (part.strip().strip("'").strip('"') for part in raw.split(",")) if token
    ]


def _validate_link_path(value: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        return ""
    _HTTP_URL_ADAPTER.validate_python(normalized)
    return normalized


LinkPath = Annotated[str, AfterValidator(_validate_link_path)]


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
    title: str = "Graphs Analyzer"
    s3: S3Settings = S3Settings()
    diagram_excalidraw_enabled: bool = True
    excalidraw_in_dir: Path = Path("data/excalidraw_in")
    excalidraw_out_dir: Path = Path("data/excalidraw_out")
    unidraw_in_dir: Path = Path("data/unidraw_in")
    unidraw_out_dir: Path = Path("data/unidraw_out")
    roundtrip_dir: Path = Path("data/roundtrip")
    index_path: Path = Path("data/catalog/index.json")
    auto_build_index: bool = True
    rebuild_index_on_start: bool = False
    index_refresh_interval_seconds: float = 0.0
    generate_excalidraw_on_demand: bool = True
    cache_excalidraw_on_demand: bool = True
    invalidate_excalidraw_cache_on_start: bool = True
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
    unidraw_proxy_upstream: str | None = None
    unidraw_proxy_prefix: str = "/unidraw"
    unidraw_max_url_length: int = 8000
    rebuild_token: str | None = None
    ui_text_overrides: dict[str, str] = Field(default_factory=dict)
    builder_excluded_team_ids: Annotated[list[str], NoDecode] = Field(default_factory=list)
    procedure_link_path: LinkPath | None = Field(
        default=None,
        validation_alias=AliasChoices("procedure_link_path", "procedure_link_template"),
    )
    block_link_path: LinkPath | None = Field(
        default=None,
        validation_alias=AliasChoices("block_link_path", "block_link_template"),
    )
    service_link_path: LinkPath | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "service_link_path",
            "service_link_template",
            "unit_link_path",
            "unit_link_template",
        ),
    )
    team_link_path: LinkPath | None = Field(
        default=None,
        validation_alias=AliasChoices("team_link_path", "team_link_template"),
    )

    @field_validator("sort_order", mode="before")
    @classmethod
    def normalize_sort_order(cls, value: object) -> str:
        return str(value).lower() if value else "asc"

    @field_validator("group_by", "tag_fields", "builder_excluded_team_ids", mode="before")
    @classmethod
    def normalize_lists(cls, value: object) -> list[str]:
        if value is None:
            return []
        if isinstance(value, list):
            normalized: list[str] = []
            for item in value:
                normalized.extend(_split_string_list_value(str(item)))
            return normalized
        if isinstance(value, str):
            return _split_string_list_value(value)
        return _split_string_list_value(str(value))

    @field_validator("ui_text_overrides", mode="before")
    @classmethod
    def normalize_ui_text_overrides(cls, value: object) -> dict[str, str]:
        if value is None or value == "":
            return {}
        if isinstance(value, dict):
            return {str(key): str(item) for key, item in value.items()}
        if isinstance(value, str):
            try:
                parsed = json.loads(value)
            except json.JSONDecodeError as exc:
                msg = "catalog.ui_text_overrides must be a JSON object"
                raise ValueError(msg) from exc
            if not isinstance(parsed, dict):
                msg = "catalog.ui_text_overrides must be a JSON object"
                raise ValueError(msg)
            return {str(key): str(item) for key, item in parsed.items()}
        msg = "catalog.ui_text_overrides must be a JSON object"
        raise ValueError(msg)

    def to_index_config(self) -> CatalogIndexConfig:
        return CatalogIndexConfig(
            markup_dir=Path(self.s3.prefix or ""),
            excalidraw_in_dir=self.excalidraw_in_dir,
            unidraw_in_dir=self.unidraw_in_dir,
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
        sources: list[PydanticBaseSettingsSource] = [
            init_settings,
            env_settings,
            dotenv_settings,
            file_secret_settings,
        ]
        if cls._yaml_path:
            sources.append(YamlConfigSettingsSource(settings_cls, yaml_file=cls._yaml_path))
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


def is_absolute_url(value: str) -> bool:
    raw = str(value or "").strip()
    if not raw:
        return False
    parsed = urlparse(raw)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)
