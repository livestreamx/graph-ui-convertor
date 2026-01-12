from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, timezone, tzinfo
from pathlib import Path
from typing import Any, cast
from urllib.parse import urlencode, urlparse
from zoneinfo import ZoneInfo

import httpx
import orjson
from adapters.excalidraw.url_encoder import build_excalidraw_url
from adapters.filesystem.catalog_index_repository import FileSystemCatalogIndexRepository
from adapters.filesystem.markup_repository import FileSystemMarkupRepository
from adapters.filesystem.scene_repository import FileSystemSceneRepository
from adapters.layout.grid import GridLayoutEngine
from domain.catalog import CatalogIndex, CatalogItem
from domain.ports.repositories import MarkupRepository
from domain.services.build_catalog_index import BuildCatalogIndex
from domain.services.convert_excalidraw_to_markup import ExcalidrawToMarkupConverter
from domain.services.convert_markup_to_excalidraw import MarkupToExcalidrawConverter
from domain.services.excalidraw_title import apply_title_focus, ensure_service_title
from fastapi import Depends, FastAPI, File, Header, HTTPException, Query, Request, UploadFile
from fastapi.responses import HTMLResponse, ORJSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.catalog_wiring import build_markup_repository, build_markup_source
from app.config import AppSettings, load_settings

TEMPLATES_DIR = Path(__file__).parent / "web" / "templates"
STATIC_DIR = Path(__file__).parent / "web" / "static"

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


@dataclass(frozen=True)
class CatalogGroup:
    field: str
    value: str
    display_value: str
    count: int
    items: list[CatalogItem]
    children: list[CatalogGroup]


@dataclass(frozen=True)
class CatalogContext:
    settings: AppSettings
    index_repo: FileSystemCatalogIndexRepository
    scene_repo: FileSystemSceneRepository
    markup_reader: MarkupRepository
    roundtrip_repo: FileSystemMarkupRepository
    index_builder: BuildCatalogIndex
    to_markup: ExcalidrawToMarkupConverter
    to_excalidraw: MarkupToExcalidrawConverter


def create_app(settings: AppSettings) -> FastAPI:
    templates.env.filters["msk_datetime"] = format_msk_datetime
    templates.env.filters["humanize_text"] = build_humanize_text(settings.catalog.ui_text_overrides)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> Any:
        invalidate_excalidraw_cache(context)
        if settings.catalog.auto_build_index:
            if settings.catalog.rebuild_index_on_start:
                context.index_builder.build(settings.catalog.to_index_config())
            else:
                try:
                    index_repo.load(settings.catalog.index_path)
                except FileNotFoundError:
                    context.index_builder.build(settings.catalog.to_index_config())
        yield

    app = FastAPI(title=settings.catalog.title, lifespan=lifespan)

    index_repo = FileSystemCatalogIndexRepository()
    context = CatalogContext(
        settings=settings,
        index_repo=index_repo,
        scene_repo=FileSystemSceneRepository(),
        markup_reader=build_markup_repository(settings),
        roundtrip_repo=FileSystemMarkupRepository(),
        index_builder=BuildCatalogIndex(
            build_markup_source(settings),
            index_repo,
        ),
        to_markup=ExcalidrawToMarkupConverter(),
        to_excalidraw=MarkupToExcalidrawConverter(GridLayoutEngine()),
    )
    app.state.context = context

    if STATIC_DIR.exists():
        app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    @app.get("/")
    def index() -> RedirectResponse:
        return RedirectResponse(url="/catalog")

    @app.get("/catalog", response_class=HTMLResponse)
    def catalog_view(
        request: Request,
        q: str | None = Query(default=None),
        group: list[str] = Query(default_factory=list),
        criticality_level: str | None = Query(default=None),
        team_id: str | None = Query(default=None),
        context: CatalogContext = Depends(get_context),
    ) -> HTMLResponse:
        index_data = load_index(context)
        if index_data is None:
            return templates.TemplateResponse(
                request,
                "catalog_empty.html",
                {
                    "request": request,
                    "settings": context.settings,
                },
            )
        filters = parse_group_filters(group)
        if criticality_level:
            filters["criticality_level"] = criticality_level
        if team_id:
            filters["team_id"] = team_id
        filtered_items = filter_items(index_data.items, q, filters)
        groups = build_group_tree(filtered_items, index_data.group_by)
        criticality_levels, team_options = build_filter_options(
            index_data.items, index_data.unknown_value
        )
        team_lookup = dict(team_options)
        active_filters = build_active_filters(filters, team_lookup)
        group_query_base = build_group_query_base(q, criticality_level, team_id)
        template_name = "catalog_list.html" if is_htmx(request) else "catalog.html"
        return templates.TemplateResponse(
            request,
            template_name,
            {
                "request": request,
                "settings": context.settings,
                "index": index_data,
                "groups": groups,
                "items": filtered_items,
                "query": q or "",
                "group_filters": parse_group_filters(group),
                "active_filters": active_filters,
                "criticality_level": criticality_level or "",
                "team_id": team_id or "",
                "criticality_levels": criticality_levels,
                "team_options": team_options,
                "group_query_base": group_query_base,
            },
        )

    @app.get("/catalog/{scene_id}", response_class=HTMLResponse)
    def catalog_detail(
        request: Request,
        scene_id: str,
        context: CatalogContext = Depends(get_context),
    ) -> HTMLResponse:
        index_data = load_index(context)
        item = find_item(index_data, scene_id) if index_data else None
        if not item:
            raise HTTPException(status_code=404, detail="Scene not found")
        base_url = context.settings.catalog.excalidraw_base_url
        excalidraw_open_url = base_url
        scene_available = False
        open_mode = "direct"
        on_demand = context.settings.catalog.generate_excalidraw_on_demand
        scene_path = context.settings.catalog.excalidraw_in_dir / item.excalidraw_rel_path
        try:
            scene_payload = context.scene_repo.load(scene_path)
            if scene_payload.get("elements") is not None:
                elements = scene_payload.get("elements")
                if isinstance(elements, list):
                    ensure_service_title(elements)
                    app_state = scene_payload.get("appState")
                    if not isinstance(app_state, dict):
                        app_state = {}
                        scene_payload["appState"] = app_state
                    apply_title_focus(app_state, elements)
                if is_same_origin(request, base_url):
                    excalidraw_open_url = f"/catalog/{scene_id}/open"
                    open_mode = "local_storage"
                else:
                    excalidraw_open_url = build_excalidraw_url(base_url, scene_payload)
                    if (
                        len(excalidraw_open_url)
                        > context.settings.catalog.excalidraw_max_url_length
                    ):
                        excalidraw_open_url = base_url
                        open_mode = "manual"
                scene_available = True
        except FileNotFoundError:
            if on_demand:
                scene_available = True
                if is_same_origin(request, base_url):
                    excalidraw_open_url = f"/catalog/{scene_id}/open"
                    open_mode = "local_storage"
                else:
                    excalidraw_open_url = base_url
                    open_mode = "manual"
        return templates.TemplateResponse(
            request,
            "catalog_detail.html",
            {
                "request": request,
                "settings": context.settings,
                "item": item,
                "index": index_data,
                "excalidraw_open_url": excalidraw_open_url,
                "scene_available": scene_available,
                "open_mode": open_mode,
                "on_demand_enabled": on_demand,
            },
        )

    @app.get("/catalog/{scene_id}/open", response_class=HTMLResponse)
    def catalog_open_scene(
        request: Request,
        scene_id: str,
        context: CatalogContext = Depends(get_context),
    ) -> Response:
        index_data = load_index(context)
        item = find_item(index_data, scene_id) if index_data else None
        if not item:
            raise HTTPException(status_code=404, detail="Scene not found")
        if not is_same_origin(request, context.settings.catalog.excalidraw_base_url):
            return RedirectResponse(url=context.settings.catalog.excalidraw_base_url)
        return templates.TemplateResponse(
            request,
            "catalog_open.html",
            {
                "request": request,
                "settings": context.settings,
                "scene_id": scene_id,
                "scene_api_url": f"/api/scenes/{scene_id}",
                "excalidraw_url": context.settings.catalog.excalidraw_base_url,
            },
        )

    @app.get("/api/index")
    def api_index(context: CatalogContext = Depends(get_context)) -> ORJSONResponse:
        index_data = load_index(context)
        if index_data is None:
            raise HTTPException(status_code=404, detail="Catalog index not found")
        return ORJSONResponse(index_data.to_dict())

    @app.get("/api/scenes/{scene_id}")
    def api_scene(
        scene_id: str,
        download: bool = Query(default=False),
        context: CatalogContext = Depends(get_context),
    ) -> ORJSONResponse:
        index_data = load_index(context)
        item = find_item(index_data, scene_id) if index_data else None
        if not item:
            raise HTTPException(status_code=404, detail="Scene not found")
        path = context.settings.catalog.excalidraw_in_dir / item.excalidraw_rel_path
        try:
            payload = context.scene_repo.load(path)
        except FileNotFoundError as exc:
            if not context.settings.catalog.generate_excalidraw_on_demand:
                raise HTTPException(status_code=404, detail="Scene file missing") from exc
            payload = build_excalidraw_payload(context, item)
            if context.settings.catalog.cache_excalidraw_on_demand:
                context.scene_repo.save(payload, path)
        elements = payload.get("elements")
        if isinstance(elements, list):
            ensure_service_title(elements)
            app_state = payload.get("appState")
            if not isinstance(app_state, dict):
                app_state = {}
                payload["appState"] = app_state
            apply_title_focus(app_state, elements)
        headers = {}
        if download:
            headers["Content-Disposition"] = f'attachment; filename="{item.excalidraw_rel_path}"'
        return ORJSONResponse(payload, headers=headers)

    @app.get("/api/markup/{scene_id}")
    def api_markup(
        scene_id: str,
        download: bool = Query(default=False),
        context: CatalogContext = Depends(get_context),
    ) -> Response:
        index_data = load_index(context)
        item = find_item(index_data, scene_id) if index_data else None
        if not item:
            raise HTTPException(status_code=404, detail="Scene not found")
        markup_root = Path(context.settings.catalog.s3.prefix or "")
        markup_path = markup_root / item.markup_rel_path
        try:
            raw_bytes = context.markup_reader.load_raw(markup_path)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Markup file missing") from exc
        headers = {}
        if download:
            filename = Path(item.markup_rel_path).name or "markup.json"
            headers["Content-Disposition"] = f'attachment; filename="{filename}"'
        return Response(content=raw_bytes, media_type="application/json", headers=headers)

    @app.post("/api/scenes/{scene_id}/upload")
    async def api_upload_scene(
        scene_id: str,
        file: UploadFile = File(...),
        context: CatalogContext = Depends(get_context),
    ) -> ORJSONResponse:
        """пока не реализованы на этапе mvp."""
        index_data = load_index(context)
        item = find_item(index_data, scene_id) if index_data else None
        if not item:
            raise HTTPException(status_code=404, detail="Scene not found")
        raw_bytes = await file.read()
        if not raw_bytes:
            raise HTTPException(status_code=400, detail="Empty upload")
        payload = parse_scene_json(raw_bytes)
        if not payload.get("elements"):
            raise HTTPException(status_code=400, detail="Invalid Excalidraw JSON")
        target_path = context.settings.catalog.excalidraw_out_dir / f"{scene_id}.excalidraw"
        context.scene_repo.save(payload, target_path)
        return ORJSONResponse(
            {
                "status": "ok",
                "scene_id": scene_id,
                "stored_path": str(target_path),
            }
        )

    @app.post("/api/scenes/{scene_id}/convert-back")
    def api_convert_back(
        scene_id: str,
        context: CatalogContext = Depends(get_context),
    ) -> ORJSONResponse:
        """пока не реализованы на этапе mvp."""
        index_data = load_index(context)
        item = find_item(index_data, scene_id) if index_data else None
        if not item:
            raise HTTPException(status_code=404, detail="Scene not found")
        source_path = context.settings.catalog.excalidraw_out_dir / f"{scene_id}.excalidraw"
        try:
            payload = context.scene_repo.load(source_path)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Uploaded scene not found") from exc
        markup = context.to_markup.convert(payload)
        output_name = Path(item.markup_rel_path).stem
        output_path = context.settings.catalog.roundtrip_dir / f"{output_name}.json"
        context.roundtrip_repo.save(markup, output_path)
        return ORJSONResponse({"status": "ok", "path": str(output_path)})

    @app.post("/api/rebuild-index")
    def api_rebuild_index(
        token: str | None = Header(default=None, alias="X-Token"),
        context: CatalogContext = Depends(get_context),
    ) -> ORJSONResponse:
        if not context.settings.catalog.rebuild_token:
            raise HTTPException(status_code=403, detail="Rebuild disabled")
        if token != context.settings.catalog.rebuild_token:
            raise HTTPException(status_code=403, detail="Invalid token")
        index_data = context.index_builder.build(context.settings.catalog.to_index_config())
        return ORJSONResponse({"status": "ok", "items": len(index_data.items)})

    if settings.catalog.excalidraw_proxy_upstream:
        prefix = settings.catalog.excalidraw_proxy_prefix.rstrip("/")

        async def forward_upstream(
            request: Request,
            upstream: str,
            path: str,
        ) -> Response:
            target = upstream.rstrip("/")
            if path:
                target = f"{target}/{path.lstrip('/')}"
            async with httpx.AsyncClient(follow_redirects=True) as client:
                resp = await client.request(
                    request.method,
                    target,
                    params=request.query_params,
                    headers=proxy_headers(request),
                )
            return Response(
                content=resp.content,
                status_code=resp.status_code,
                headers=filter_response_headers(resp.headers),
            )

        @app.api_route(f"{prefix}/{{path:path}}", methods=["GET", "HEAD"])
        async def proxy_excalidraw(
            path: str,
            request: Request,
            context: CatalogContext = Depends(get_context),
        ) -> Response:
            upstream = context.settings.catalog.excalidraw_proxy_upstream
            if not upstream:
                raise HTTPException(status_code=404, detail="Proxy disabled")
            return await forward_upstream(request, upstream, path)

        @app.api_route("/assets/{path:path}", methods=["GET", "HEAD"])
        async def proxy_excalidraw_assets(
            path: str,
            request: Request,
            context: CatalogContext = Depends(get_context),
        ) -> Response:
            upstream = context.settings.catalog.excalidraw_proxy_upstream
            if not upstream:
                raise HTTPException(status_code=404, detail="Proxy disabled")
            return await forward_upstream(request, upstream, f"assets/{path}")

        for static_path in (
            "/manifest.webmanifest",
            "/favicon.ico",
            "/favicon-32x32.png",
            "/favicon-16x16.png",
            "/apple-touch-icon.png",
            "/apple-touch-icon-precomposed.png",
            "/sitemap.xml",
            "/robots.txt",
        ):

            @app.api_route(static_path, methods=["GET", "HEAD"])
            async def proxy_excalidraw_static(
                request: Request,
                context: CatalogContext = Depends(get_context),
            ) -> Response:
                upstream = context.settings.catalog.excalidraw_proxy_upstream
                if not upstream:
                    raise HTTPException(status_code=404, detail="Proxy disabled")
                return await forward_upstream(request, upstream, request.url.path.lstrip("/"))

    return app


def get_context(request: Request) -> CatalogContext:
    return cast(CatalogContext, request.app.state.context)


def invalidate_excalidraw_cache(context: CatalogContext) -> None:
    settings = context.settings.catalog
    if not settings.invalidate_excalidraw_cache_on_start:
        return
    if not settings.generate_excalidraw_on_demand:
        return
    context.scene_repo.clear_cache(settings.excalidraw_in_dir)


def load_index(context: CatalogContext) -> CatalogIndex | None:
    path = context.settings.catalog.index_path
    try:
        return context.index_repo.load(path)
    except FileNotFoundError:
        return None


def parse_scene_json(raw_bytes: bytes) -> dict[str, Any]:
    try:
        payload = orjson.loads(raw_bytes)
    except orjson.JSONDecodeError:
        payload = json.loads(raw_bytes.decode("utf-8"))
    return payload if isinstance(payload, dict) else {}


def find_item(index_data: CatalogIndex | None, scene_id: str) -> CatalogItem | None:
    if not index_data:
        return None
    for item in index_data.items:
        if item.scene_id == scene_id:
            return item
    return None


def build_excalidraw_payload(context: CatalogContext, item: CatalogItem) -> dict[str, Any]:
    markup_root = Path(context.settings.catalog.s3.prefix or "")
    markup_path = markup_root / item.markup_rel_path
    try:
        markup = context.markup_reader.load_by_path(markup_path)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Markup file missing") from exc
    excal_doc = context.to_excalidraw.convert(markup)
    payload = excal_doc.to_dict()
    elements = payload.get("elements")
    if isinstance(elements, list):
        ensure_service_title(elements)
        app_state = payload.get("appState")
        if not isinstance(app_state, dict):
            app_state = {}
            payload["appState"] = app_state
        apply_title_focus(app_state, elements)
    return payload


def filter_items(
    items: list[CatalogItem],
    query: str | None,
    filters: dict[str, str],
) -> list[CatalogItem]:
    normalized_query = (query or "").strip().lower()
    results: list[CatalogItem] = []
    for item in items:
        if normalized_query and not matches_query(item, normalized_query):
            continue
        if not matches_filters(item, filters):
            continue
        results.append(item)
    return results


def matches_query(item: CatalogItem, query: str) -> bool:
    if query in item.title.lower():
        return True
    for tag in item.tags:
        if query in tag.lower():
            return True
    if query in item.scene_id.lower():
        return True
    if query in item.markup_type.lower():
        return True
    if query in item.team_name.lower():
        return True
    if query in item.criticality_level.lower():
        return True
    return False


def matches_filters(item: CatalogItem, filters: dict[str, str]) -> bool:
    for field, value in filters.items():
        if field == "criticality_level":
            candidate = item.criticality_level
        elif field == "team_id":
            candidate = item.team_id
        elif field == "team_name":
            candidate = item.team_name
        else:
            candidate = item.group_values.get(field) or item.fields.get(field) or ""
        if candidate != value:
            return False
    return True


def parse_group_filters(group_filters: list[str]) -> dict[str, str]:
    parsed: dict[str, str] = {}
    for raw in group_filters:
        if ":" not in raw:
            continue
        field, value = raw.split(":", 1)
        field = field.strip()
        value = value.strip()
        if not field or not value:
            continue
        parsed[field] = value
    return parsed


def build_group_tree(items: list[CatalogItem], fields: list[str]) -> list[CatalogGroup]:
    if not fields:
        return [
            CatalogGroup(
                field="all",
                value="All",
                display_value="All",
                count=len(items),
                items=items,
                children=[],
            )
        ]
    field = fields[0]
    buckets: dict[str, list[CatalogItem]] = {}
    for item in items:
        key = group_value_for_field(item, field)
        buckets.setdefault(key, []).append(item)
    groups: list[CatalogGroup] = []
    for value in sorted(buckets.keys()):
        bucket_items = buckets[value]
        children = build_group_tree(bucket_items, fields[1:]) if len(fields) > 1 else []
        display_value = group_display_value(field, value, bucket_items)
        groups.append(
            CatalogGroup(
                field=field,
                value=value,
                display_value=display_value,
                count=len(bucket_items),
                items=bucket_items,
                children=children,
            )
        )
    return groups


def is_htmx(request: Request) -> bool:
    return request.headers.get("HX-Request") == "true"


def is_same_origin(request: Request, base_url: str) -> bool:
    if base_url.startswith("/"):
        return True
    base = urlparse(base_url)
    req = urlparse(str(request.base_url))
    if not base.scheme or not base.hostname:
        return False
    base_port = base.port or default_port(base.scheme)
    req_port = req.port or default_port(req.scheme)
    return base.scheme == req.scheme and base.hostname == req.hostname and base_port == req_port


def default_port(scheme: str) -> int:
    return 443 if scheme == "https" else 80


def format_msk_datetime(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return "n/a (MSK)"
    normalized = text
    if normalized.endswith("Z"):
        normalized = f"{normalized[:-1]}+00:00"
    try:
        dt = datetime.fromisoformat(normalized)
    except ValueError:
        return f"{text} (MSK)"
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    msk_tz: tzinfo
    try:
        msk_tz = ZoneInfo("Europe/Moscow")
    except Exception:
        msk_tz = timezone(timedelta(hours=3))
    dt = dt.astimezone(msk_tz)
    return dt.strftime("%d.%m.%Y %H:%M MSK")


def build_humanize_text(overrides: Mapping[str, str]) -> Callable[[str], str]:
    mapped = dict(overrides)

    def humanize_text(value: str) -> str:
        text = str(value)
        return mapped.get(text, text)

    return humanize_text


def build_filter_options(
    items: list[CatalogItem],
    unknown_value: str,
) -> tuple[list[str], list[tuple[str, str]]]:
    criticality_levels = sorted(
        {
            item.criticality_level
            for item in items
            if item.criticality_level and item.criticality_level != unknown_value
        }
    )
    teams: dict[str, str] = {}
    for item in items:
        if not item.team_id or item.team_id == unknown_value:
            continue
        display_name = item.team_name
        if not display_name or display_name == unknown_value:
            display_name = item.team_id
        teams[item.team_id] = display_name
    team_options = sorted(teams.items(), key=lambda entry: entry[1].lower())
    return criticality_levels, team_options


def build_active_filters(
    filters: dict[str, str],
    team_lookup: dict[str, str],
) -> list[dict[str, str]]:
    active: list[dict[str, str]] = []
    for field, value in filters.items():
        display_value = value
        if field == "team_id":
            display_value = team_lookup.get(value, value)
        active.append(
            {
                "field": field,
                "value": value,
                "display_value": display_value,
            }
        )
    return active


def build_group_query_base(
    query: str | None,
    criticality_level: str | None,
    team_id: str | None,
) -> str:
    params: dict[str, str] = {}
    if query:
        params["q"] = query
    if criticality_level:
        params["criticality_level"] = criticality_level
    if team_id:
        params["team_id"] = team_id
    return urlencode(params)


def group_value_for_field(item: CatalogItem, field: str) -> str:
    if field == "criticality_level":
        return item.criticality_level
    if field == "team_id":
        return item.team_id
    if field == "team_name":
        return item.team_name
    return item.group_values.get(field, "unknown")


def group_display_value(field: str, value: str, items: list[CatalogItem]) -> str:
    if field == "team_id":
        for item in items:
            if item.team_name and item.team_name != value:
                return item.team_name
    return value


def proxy_headers(request: Request) -> dict[str, str]:
    headers = dict(request.headers)
    headers.pop("host", None)
    return headers


def filter_response_headers(headers: httpx.Headers) -> dict[str, str]:
    excluded = {"content-encoding", "transfer-encoding", "connection"}
    return {key: value for key, value in headers.items() if key.lower() not in excluded}


app = create_app(load_settings())
