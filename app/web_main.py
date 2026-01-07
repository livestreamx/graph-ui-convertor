from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

import orjson
from adapters.filesystem.catalog_index_repository import FileSystemCatalogIndexRepository
from adapters.filesystem.markup_catalog_source import FileSystemMarkupCatalogSource
from adapters.filesystem.markup_repository import FileSystemMarkupRepository
from adapters.filesystem.scene_repository import FileSystemSceneRepository
from domain.catalog import CatalogIndex, CatalogItem
from domain.services.build_catalog_index import BuildCatalogIndex
from domain.services.convert_excalidraw_to_markup import ExcalidrawToMarkupConverter
from fastapi import Depends, FastAPI, File, Header, HTTPException, Query, Request, UploadFile
from fastapi.responses import HTMLResponse, ORJSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.config import AppSettings, load_settings

TEMPLATES_DIR = Path(__file__).parent / "web" / "templates"
STATIC_DIR = Path(__file__).parent / "web" / "static"

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


@dataclass(frozen=True)
class CatalogGroup:
    field: str
    value: str
    count: int
    items: list[CatalogItem]
    children: list[CatalogGroup]


@dataclass(frozen=True)
class CatalogContext:
    settings: AppSettings
    index_repo: FileSystemCatalogIndexRepository
    scene_repo: FileSystemSceneRepository
    markup_repo: FileSystemMarkupRepository
    index_builder: BuildCatalogIndex
    converter: ExcalidrawToMarkupConverter


def create_app(settings: AppSettings) -> FastAPI:
    app = FastAPI(title=settings.catalog.title)

    index_repo = FileSystemCatalogIndexRepository()
    context = CatalogContext(
        settings=settings,
        index_repo=index_repo,
        scene_repo=FileSystemSceneRepository(),
        markup_repo=FileSystemMarkupRepository(),
        index_builder=BuildCatalogIndex(
            FileSystemMarkupCatalogSource(),
            index_repo,
        ),
        converter=ExcalidrawToMarkupConverter(),
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
        context: CatalogContext = Depends(get_context),
    ) -> HTMLResponse:
        index_data = load_index(context)
        if index_data is None:
            return templates.TemplateResponse(
                "catalog_empty.html",
                {
                    "request": request,
                    "settings": context.settings,
                },
            )
        filters = parse_group_filters(group)
        filtered_items = filter_items(index_data.items, q, filters)
        groups = build_group_tree(filtered_items, index_data.group_by)
        template_name = "catalog_list.html" if is_htmx(request) else "catalog.html"
        return templates.TemplateResponse(
            template_name,
            {
                "request": request,
                "settings": context.settings,
                "index": index_data,
                "groups": groups,
                "items": filtered_items,
                "query": q or "",
                "group_filters": filters,
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
        return templates.TemplateResponse(
            "catalog_detail.html",
            {
                "request": request,
                "settings": context.settings,
                "item": item,
                "index": index_data,
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
            raise HTTPException(status_code=404, detail="Scene file missing") from exc
        headers = {}
        if download:
            headers["Content-Disposition"] = f'attachment; filename="{item.excalidraw_rel_path}"'
        return ORJSONResponse(payload, headers=headers)

    @app.post("/api/scenes/{scene_id}/upload")
    async def api_upload_scene(
        scene_id: str,
        file: UploadFile = File(...),
        context: CatalogContext = Depends(get_context),
    ) -> ORJSONResponse:
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
        index_data = load_index(context)
        item = find_item(index_data, scene_id) if index_data else None
        if not item:
            raise HTTPException(status_code=404, detail="Scene not found")
        source_path = context.settings.catalog.excalidraw_out_dir / f"{scene_id}.excalidraw"
        try:
            payload = context.scene_repo.load(source_path)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Uploaded scene not found") from exc
        markup = context.converter.convert(payload)
        output_name = Path(item.markup_rel_path).stem
        output_path = context.settings.catalog.roundtrip_dir / f"{output_name}.json"
        context.markup_repo.save(markup, output_path)
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

    return app


def get_context(request: Request) -> CatalogContext:
    return cast(CatalogContext, request.app.state.context)


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
    return False


def matches_filters(item: CatalogItem, filters: dict[str, str]) -> bool:
    for field, value in filters.items():
        candidate = item.group_values.get(field) or item.fields.get(field)
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
                count=len(items),
                items=items,
                children=[],
            )
        ]
    field = fields[0]
    buckets: dict[str, list[CatalogItem]] = {}
    for item in items:
        key = item.group_values.get(field, "unknown")
        buckets.setdefault(key, []).append(item)
    groups: list[CatalogGroup] = []
    for value in sorted(buckets.keys()):
        bucket_items = buckets[value]
        children = build_group_tree(bucket_items, fields[1:]) if len(fields) > 1 else []
        groups.append(
            CatalogGroup(
                field=field,
                value=value,
                count=len(bucket_items),
                items=bucket_items,
                children=children,
            )
        )
    return groups


def is_htmx(request: Request) -> bool:
    return request.headers.get("HX-Request") == "true"


app = create_app(load_settings())
