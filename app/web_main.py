from __future__ import annotations

import asyncio
import concurrent.futures
import hashlib
import json
import logging
import os
import threading
from collections.abc import Callable, Mapping, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass
from dataclasses import field as dataclass_field
from datetime import UTC, datetime, timedelta, timezone, tzinfo
from pathlib import Path
from typing import Any, Literal, cast
from urllib.parse import urlencode, urlparse
from uuid import uuid4
from zoneinfo import ZoneInfo

import httpx
import orjson
from fastapi import Depends, FastAPI, File, Header, HTTPException, Query, Request, UploadFile
from fastapi.responses import HTMLResponse, ORJSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from adapters.excalidraw.url_encoder import build_excalidraw_url
from adapters.filesystem.catalog_index_repository import FileSystemCatalogIndexRepository
from adapters.filesystem.markup_repository import FileSystemMarkupRepository
from adapters.filesystem.scene_repository import FileSystemSceneRepository
from adapters.layout.grid import GridLayoutEngine, LayoutConfig
from adapters.layout.procedure_graph import ProcedureGraphLayoutEngine
from app.catalog_wiring import build_markup_repository, build_markup_source
from app.config import AppSettings, load_settings
from app.web_i18n import (
    UILocalizer,
    apply_ui_language_cookie,
    build_language_switch_url,
    build_localizer,
    get_active_ui_language,
    humanize_markup_type_column_label,
    reset_active_ui_language,
    set_active_ui_language,
    translate_humanized_text,
)
from domain.catalog import CatalogIndex, CatalogIndexConfig, CatalogItem
from domain.models import ExcalidrawDocument, MarkupDocument, Size, UnidrawDocument
from domain.ports.repositories import MarkupRepository
from domain.services.build_catalog_index import BuildCatalogIndex
from domain.services.build_cross_team_graph_dashboard import (
    BuildCrossTeamGraphDashboard,
    CrossTeamGraphDashboard,
)
from domain.services.build_team_procedure_graph import BuildTeamProcedureGraph, GraphLevel
from domain.services.catalog_health import (
    GAMING_ISSUE_INCONSISTENT_MARKUP,
    GAMING_ISSUE_MULTIPLE_STARTS_WITHOUT_BRANCH,
    GAMING_ISSUE_NO_BRANCH_AND_NO_END,
    GAMING_ISSUE_SAME_START_AND_END_BLOCK,
    GRAPH_ISSUE_MULTIPLE_WITHOUT_BOT,
    GRAPH_ISSUE_NO_BOT,
    GRAPH_ISSUE_ONLY_BOT,
    GRAPH_ISSUE_TOO_MANY,
    BuildCatalogHealthReport,
    CatalogHealthReport,
    CatalogItemHealth,
    problematic_multiple_start_blocks_by_procedure,
)
from domain.services.convert_excalidraw_to_markup import ExcalidrawToMarkupConverter
from domain.services.convert_markup_to_excalidraw import MarkupToExcalidrawConverter
from domain.services.convert_markup_to_unidraw import MarkupToUnidrawConverter
from domain.services.convert_procedure_graph_to_excalidraw import (
    ProcedureGraphToExcalidrawConverter,
)
from domain.services.convert_procedure_graph_to_unidraw import (
    ProcedureGraphToUnidrawConverter,
)
from domain.services.excalidraw_links import (
    ExcalidrawLinkTemplates,
    build_link_templates,
    ensure_excalidraw_links,
    ensure_unidraw_links,
)
from domain.services.excalidraw_title import apply_title_focus, ensure_service_title
from domain.services.extract_block_graph_view import extract_block_graph_view
from domain.services.extract_procedure_graph_view import extract_procedure_graph_view

TEMPLATES_DIR = Path(__file__).parent / "web" / "templates"
STATIC_DIR = Path(__file__).parent / "web" / "static"

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
logger = logging.getLogger(__name__)

SceneFormat = Literal["excalidraw", "unidraw"]


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
    to_unidraw: MarkupToUnidrawConverter
    to_procedure_graph_excalidraw: ProcedureGraphToExcalidrawConverter
    to_procedure_graph_unidraw: ProcedureGraphToUnidrawConverter
    link_templates: ExcalidrawLinkTemplates | None
    index_state: CatalogIndexState
    health_builder: BuildCatalogHealthReport
    health_state: CatalogHealthState
    team_graph_jobs: TeamGraphJobState


@dataclass
class CatalogRefreshState:
    last_source_fingerprint: str | None = None


@dataclass
class CatalogIndexState:
    path: Path | None = None
    stamp: tuple[int, int] | None = None
    index: CatalogIndex | None = None
    signature: str | None = None


@dataclass
class CatalogHealthState:
    index_signature: str | None = None
    report: CatalogHealthReport | None = None


TeamGraphJobStatus = Literal["pending", "running", "succeeded", "failed"]


@dataclass(frozen=True)
class TeamGraphBuildRequest:
    team_ids: tuple[str, ...]
    excluded_team_ids: tuple[str, ...]
    merge_nodes_all_markups: bool
    merge_selected_markups: bool
    merge_node_min_chain_size: int


@dataclass(frozen=True)
class TeamGraphBuildResult:
    dashboard: CrossTeamGraphDashboard
    procedure_graph_document: MarkupDocument
    service_graph_document: MarkupDocument


@dataclass
class TeamGraphJob:
    job_id: str
    request: TeamGraphBuildRequest
    index_signature: str
    status: TeamGraphJobStatus
    created_at: datetime
    updated_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    error_message: str | None = None
    result: TeamGraphBuildResult | None = None


@dataclass
class TeamGraphJobState:
    executor: concurrent.futures.ThreadPoolExecutor
    instance_id: str = dataclass_field(default_factory=lambda: uuid4().hex)
    jobs: dict[str, TeamGraphJob] = dataclass_field(default_factory=dict)
    request_jobs: dict[str, str] = dataclass_field(default_factory=dict)
    lock: threading.RLock = dataclass_field(default_factory=threading.RLock)


@dataclass(frozen=True)
class ValidityIssueBlockRef:
    procedure_id: str
    block_id: str
    procedure_name: str
    block_name: str
    block_external_url: str | None


GRAPH_ISSUE_TEXT_KEYS: dict[str, str] = {
    GRAPH_ISSUE_MULTIPLE_WITHOUT_BOT: "Multiple graphs but no bot starts",
    GRAPH_ISSUE_NO_BOT: "No bot graphs found",
    GRAPH_ISSUE_ONLY_BOT: "Only bot graphs found",
    GRAPH_ISSUE_TOO_MANY: "More than three graphs in markup",
}

GAMING_ISSUE_TEXT_KEYS: dict[str, str] = {
    GAMING_ISSUE_INCONSISTENT_MARKUP: "Markup is not consistent",
    GAMING_ISSUE_MULTIPLE_STARTS_WITHOUT_BRANCH: "Multiple starts but no branches",
    GAMING_ISSUE_NO_BRANCH_AND_NO_END: "No branches and no graph-completing end blocks",
    GAMING_ISSUE_SAME_START_AND_END_BLOCK: "Same block used as start and end",
}

GAMING_ISSUE_REASON_TEXT_KEYS: dict[str, tuple[str, ...]] = {
    GAMING_ISSUE_INCONSISTENT_MARKUP: (
        "Markup is not consistent because some key blocks were lost.",
        "Fix by manually refreshing the markup in the markup tool.",
    ),
    GAMING_ISSUE_MULTIPLE_STARTS_WITHOUT_BRANCH: (
        "Detected when a procedure has multiple starts, zero branch blocks, and those starts do not merge downstream.",
    ),
    GAMING_ISSUE_NO_BRANCH_AND_NO_END: (
        "Detected when branch blocks = 0 and graph-completing end blocks = 0.",
        "Return-to-parent and postpone end blocks do not make a flow complete.",
    ),
    GAMING_ISSUE_SAME_START_AND_END_BLOCK: (),
}

HEALTH_MARKER_FILTER_ALL = ""
HEALTH_MARKER_FILTER_GRAPHS = "graphs"
HEALTH_MARKER_FILTER_VALIDITY = "validity"
HEALTH_MARKER_FILTER_SAME_TEAM = "same-team"
HEALTH_MARKER_FILTER_CROSS_TEAM = "cross-team"
HEALTH_MARKER_FILTER_VALUES: set[str] = {
    HEALTH_MARKER_FILTER_GRAPHS,
    HEALTH_MARKER_FILTER_VALIDITY,
    HEALTH_MARKER_FILTER_SAME_TEAM,
    HEALTH_MARKER_FILTER_CROSS_TEAM,
}
MARKUP_TYPE_GROUP_ORDER = (
    "system_service_search",
    "service",
    "system_task_processor",
    "system_default",
)
MARKUP_TYPE_GROUP_ORDER_INDEX = {
    markup_type: index for index, markup_type in enumerate(MARKUP_TYPE_GROUP_ORDER)
}


def create_app(settings: AppSettings) -> FastAPI:
    templates.env.filters["msk_datetime"] = format_msk_datetime
    templates.env.filters["humanize_text"] = build_humanize_text(settings.catalog.ui_text_overrides)
    team_graph_executor = concurrent.futures.ThreadPoolExecutor(
        max_workers=max(2, min(4, os.cpu_count() or 2)),
        thread_name_prefix="team-graph",
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> Any:
        refresh_task: asyncio.Task[None] | None = None
        refresh_stop = asyncio.Event()
        invalidate_scene_cache(context)
        if settings.catalog.auto_build_index:
            if settings.catalog.rebuild_index_on_start:
                built_index = context.index_builder.build(settings.catalog.to_index_config())
                update_catalog_health_cache(context, built_index)
            else:
                try:
                    loaded_index = index_repo.load(settings.catalog.index_path)
                    update_catalog_health_cache(context, loaded_index)
                except FileNotFoundError:
                    built_index = context.index_builder.build(settings.catalog.to_index_config())
                    update_catalog_health_cache(context, built_index)
            refresh_interval = settings.catalog.index_refresh_interval_seconds
            if refresh_interval > 0:
                refresh_task = asyncio.create_task(
                    run_catalog_index_refresh_loop(context, refresh_interval, refresh_stop)
                )
        yield
        if refresh_task is not None:
            refresh_stop.set()
            await refresh_task
        team_graph_executor.shutdown(wait=False, cancel_futures=True)

    app = FastAPI(title=settings.catalog.title, lifespan=lifespan)

    index_repo = FileSystemCatalogIndexRepository()
    link_templates = build_link_templates(
        settings.catalog.procedure_link_path,
        settings.catalog.block_link_path,
        settings.catalog.service_link_path,
        settings.catalog.team_link_path,
    )
    procedure_graph_layout = ProcedureGraphLayoutEngine(
        LayoutConfig(
            block_size=Size(320.0, 120.0),
            gap_y=120.0,
            lane_gap=240.0,
        )
    )
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
        to_excalidraw=MarkupToExcalidrawConverter(
            GridLayoutEngine(), link_templates=link_templates
        ),
        to_unidraw=MarkupToUnidrawConverter(GridLayoutEngine(), link_templates=link_templates),
        to_procedure_graph_excalidraw=ProcedureGraphToExcalidrawConverter(
            procedure_graph_layout,
            link_templates=link_templates,
        ),
        to_procedure_graph_unidraw=ProcedureGraphToUnidrawConverter(
            procedure_graph_layout,
            link_templates=link_templates,
        ),
        link_templates=link_templates,
        index_state=CatalogIndexState(),
        health_builder=BuildCatalogHealthReport(
            same_team_threshold_percent=(
                settings.catalog.health_same_team_overlap_threshold_percent
            ),
            cross_team_threshold_percent=(
                settings.catalog.health_cross_team_overlap_threshold_percent
            ),
        ),
        health_state=CatalogHealthState(),
        team_graph_jobs=TeamGraphJobState(executor=team_graph_executor),
    )
    app.state.context = context

    if STATIC_DIR.exists():
        app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    def localizer_for_request(request: Request) -> UILocalizer:
        cached = getattr(request.state, "ui_localizer", None)
        if isinstance(cached, UILocalizer):
            return cached
        localizer = build_localizer(request)
        request.state.ui_localizer = localizer
        return localizer

    def render_catalog_template(
        request: Request,
        template_name: str,
        template_context: dict[str, Any],
    ) -> HTMLResponse:
        localizer = localizer_for_request(request)
        context_data = dict(template_context)
        context_data.update(
            {
                "request": request,
                "lang": localizer.language,
                "t": localizer.t,
                "lang_switch_url": build_language_switch_url(request, localizer.alternate_language),
                "lang_current_icon": localizer.language_icon,
                "lang_current_label": localizer.language_label,
                "lang_switch_icon": localizer.alternate_language_icon,
                "lang_switch_label": localizer.alternate_language_label,
            }
        )
        token = set_active_ui_language(localizer.language)
        try:
            response = templates.TemplateResponse(request, template_name, context_data)
        finally:
            reset_active_ui_language(token)
        apply_ui_language_cookie(response, localizer.language)
        return response

    def render_team_graph_page(
        request: Request,
        *,
        team_ids: list[str],
        excluded_team_ids: list[str],
        excluded_team_ids_explicit: bool,
        merge_nodes_all_markups: bool,
        merge_selected_markups: bool,
        merge_node_min_chain_size: int,
        context: CatalogContext,
        job_id: str | None = None,
    ) -> HTMLResponse:
        index_data = load_index(context)
        if index_data is None:
            return render_catalog_template(
                request,
                "catalog_empty.html",
                {
                    "settings": context.settings,
                },
            )

        _, all_team_options = build_filter_options(index_data.items, index_data.unknown_value)
        team_lookup = dict(all_team_options)
        disabled_team_ids = normalize_team_ids(excluded_team_ids)
        if not excluded_team_ids_explicit and context.settings.catalog.builder_excluded_team_ids:
            disabled_team_ids = normalize_team_ids(
                context.settings.catalog.builder_excluded_team_ids
            )
        if disabled_team_ids:
            missing = [
                (team_id, team_id) for team_id in disabled_team_ids if team_id not in team_lookup
            ]
            if missing:
                all_team_options = sorted(
                    [*all_team_options, *missing], key=lambda entry: entry[1].lower()
                )
                team_lookup = dict(all_team_options)

        team_ids = normalize_team_ids(team_ids)
        team_options = all_team_options
        team_counts: dict[str, int] = {}
        for item in index_data.items:
            team_counts[item.team_id] = team_counts.get(item.team_id, 0) + 1
        all_team_counts: dict[str, int] = {}
        for item in index_data.items:
            all_team_counts[item.team_id] = all_team_counts.get(item.team_id, 0) + 1
        selected_teams = [
            {
                "id": team_id,
                "label": team_lookup.get(team_id, team_id),
                "markup_count": team_counts.get(team_id, 0),
            }
            for team_id in team_ids
        ]
        selected_team_count = len(team_ids)
        selected_markups_count = sum(team_counts.get(team_id, 0) for team_id in team_ids)
        disabled_team_count = len(disabled_team_ids)
        disabled_markups_count = sum(
            all_team_counts.get(team_id, 0) for team_id in disabled_team_ids
        )

        localizer = localizer_for_request(request)
        build_request = build_team_graph_request(
            team_ids=team_ids,
            excluded_team_ids=disabled_team_ids,
            merge_nodes_all_markups=merge_nodes_all_markups,
            merge_selected_markups=merge_selected_markups,
            merge_node_min_chain_size=merge_node_min_chain_size,
        )
        index_signature = resolve_catalog_index_signature(context, index_data)
        cache_signature = build_team_graph_cache_signature(
            context,
            index_signature=index_signature,
        )

        diagram_ready = False
        open_mode = None
        team_query = ""
        procedure_team_query = ""
        service_team_query = ""
        service_graph_view_query = ""
        procedure_excalidraw_open_url = None
        service_excalidraw_open_url = None
        error_message = None
        team_dashboard: CrossTeamGraphDashboard | None = None
        merge_job: TeamGraphJob | None = None
        merge_job_error = None

        if team_ids:
            if job_id:
                candidate_job = get_team_graph_job(context, job_id)
                if (
                    candidate_job is not None
                    and candidate_job.request == build_request
                    and candidate_job.index_signature == cache_signature
                ):
                    merge_job = candidate_job
                else:
                    merge_job_error = (
                        "Merge result is stale or does not match the current selection."
                    )
            if merge_job is None:
                merge_job = find_team_graph_job_for_request(
                    context,
                    build_request=build_request,
                    cache_signature=cache_signature,
                    reuse_failed=True,
                )

        if merge_job is not None:
            team_query = build_team_query(
                team_ids,
                excluded_team_ids=disabled_team_ids,
                merge_nodes_all_markups=merge_nodes_all_markups,
                merge_selected_markups=merge_selected_markups,
                merge_node_min_chain_size=merge_node_min_chain_size,
                job_id=merge_job.job_id,
            )
            procedure_team_query = team_query
            service_team_query = build_team_query(
                team_ids,
                excluded_team_ids=disabled_team_ids,
                merge_nodes_all_markups=merge_nodes_all_markups,
                merge_selected_markups=merge_selected_markups,
                merge_node_min_chain_size=merge_node_min_chain_size,
                graph_level="service",
                job_id=merge_job.job_id,
            )
            service_graph_view_query = service_team_query

            if merge_job.status == "succeeded" and merge_job.result is not None:
                team_dashboard = merge_job.result.dashboard
                diagram_base_url = context.settings.catalog.excalidraw_base_url
                procedure_excalidraw_open_url = diagram_base_url
                service_excalidraw_open_url = diagram_base_url
                open_mode = "manual"
                if is_same_origin(request, diagram_base_url):
                    procedure_excalidraw_open_url = f"/catalog/teams/graph/open?{team_query}"
                    service_excalidraw_open_url = f"/catalog/teams/graph/open?{service_team_query}"
                    open_mode = "local_storage"
                else:
                    procedure_payload = build_procedure_graph_diagram_payload(
                        context,
                        merge_job.result.procedure_graph_document,
                        "excalidraw",
                        ui_language=localizer.language,
                    )
                    procedure_excalidraw_open_url = build_excalidraw_url(
                        diagram_base_url, procedure_payload
                    )
                    if (
                        len(procedure_excalidraw_open_url)
                        > context.settings.catalog.excalidraw_max_url_length
                    ):
                        procedure_excalidraw_open_url = diagram_base_url
                        open_mode = "manual"
                    else:
                        open_mode = "direct"

                    service_payload = build_procedure_graph_diagram_payload(
                        context,
                        merge_job.result.service_graph_document,
                        "excalidraw",
                        ui_language=localizer.language,
                    )
                    service_excalidraw_open_url = build_excalidraw_url(
                        diagram_base_url, service_payload
                    )
                    if (
                        len(service_excalidraw_open_url)
                        > context.settings.catalog.excalidraw_max_url_length
                    ):
                        service_excalidraw_open_url = diagram_base_url
                diagram_ready = True
            elif merge_job.status == "failed":
                error_message = merge_job.error_message or "Unable to build team graph."

        if merge_job_error and error_message is None:
            error_message = merge_job_error

        page_query = build_team_page_query(
            team_ids,
            excluded_team_ids=disabled_team_ids,
            merge_nodes_all_markups=merge_nodes_all_markups,
            merge_selected_markups=merge_selected_markups,
            merge_node_min_chain_size=merge_node_min_chain_size,
            job_id=merge_job.job_id if merge_job is not None else None,
            language=localizer.language,
        )
        merge_job_status_api_url = ""
        merge_job_refresh_url = ""
        merge_job_status = "idle"
        if merge_job is not None:
            merge_job_status = merge_job.status
            merge_job_status_api_url = f"/api/team-graph-jobs/{merge_job.job_id}"
            if page_query:
                merge_job_refresh_url = f"/catalog/teams/graph?{page_query}"

        return render_catalog_template(
            request,
            "catalog_team_graph.html",
            {
                "settings": context.settings,
                "diagram_ready": diagram_ready,
                "diagram_excalidraw_enabled": context.settings.catalog.diagram_excalidraw_enabled,
                "open_mode": open_mode,
                "team_options": team_options,
                "all_team_options": all_team_options,
                "team_counts": team_counts,
                "all_team_counts": all_team_counts,
                "team_ids": team_ids,
                "disabled_team_ids": disabled_team_ids,
                "selected_teams": selected_teams,
                "selected_team_count": selected_team_count,
                "selected_markups_count": selected_markups_count,
                "disabled_team_count": disabled_team_count,
                "disabled_markups_count": disabled_markups_count,
                "team_query": team_query,
                "procedure_team_query": procedure_team_query,
                "service_team_query": service_team_query,
                "service_graph_view_query": service_graph_view_query,
                "procedure_excalidraw_open_url": procedure_excalidraw_open_url,
                "service_excalidraw_open_url": service_excalidraw_open_url,
                "error_message": error_message,
                "merge_nodes_all_markups": merge_nodes_all_markups,
                "merge_selected_markups": merge_selected_markups,
                "merge_node_min_chain_size": merge_node_min_chain_size,
                "team_dashboard": team_dashboard,
                "merge_job_id": merge_job.job_id if merge_job is not None else "",
                "merge_job_status": merge_job_status,
                "merge_job_status_api_url": merge_job_status_api_url,
                "merge_job_refresh_url": merge_job_refresh_url,
                "merge_job_error": merge_job_error,
                "resolve_procedure_link": (
                    lambda procedure_id: resolve_procedure_external_url(context, procedure_id)
                ),
            },
        )

    @app.get("/")
    def index(request: Request) -> RedirectResponse:
        localizer = localizer_for_request(request)
        url = f"/catalog?lang={localizer.language}"
        response = RedirectResponse(url=url)
        apply_ui_language_cookie(response, localizer.language)
        return response

    @app.get("/catalog", response_class=HTMLResponse)
    def catalog_view(
        request: Request,
        q: str | None = Query(default=None),
        search: list[str] = Query(default_factory=list),
        group: list[str] = Query(default_factory=list),
        criticality_level: str | None = Query(default=None),
        team_id: str | None = Query(default=None),
        health_marker: str | None = Query(default=None),
        context: CatalogContext = Depends(get_context),
    ) -> HTMLResponse:
        index_data, health_report = load_index_bundle(context)
        if index_data is None:
            return render_catalog_template(
                request,
                "catalog_empty.html",
                {
                    "settings": context.settings,
                },
            )
        filters = parse_group_filters(group)
        if criticality_level:
            filters["criticality_level"] = criticality_level
        if team_id:
            filters["team_id"] = team_id
        search_tokens = normalize_search_tokens(search, q)
        filtered_items = filter_items(index_data.items, search_tokens, filters)
        health_marker_filter = normalize_health_marker_filter(health_marker)
        if health_marker_filter and health_report is not None:
            filtered_items = [
                item
                for item in filtered_items
                if is_item_health_problem_for_marker(
                    health_report.item(item.scene_id), health_marker_filter
                )
            ]
        validity_issue_blocks_by_scene = build_validity_issue_blocks_by_scene(
            context,
            filtered_items,
            health_report=health_report,
        )
        groups = build_group_tree(filtered_items, index_data.group_by)
        criticality_levels, team_options = build_filter_options(
            index_data.items, index_data.unknown_value
        )
        team_lookup = dict(team_options)
        active_filters = build_active_filters(
            filters,
            team_lookup,
            search_tokens,
            health_marker_filter,
        )
        group_query_base = build_group_query_base(
            search_tokens,
            criticality_level,
            team_id,
            health_marker_filter=health_marker_filter,
        )
        catalog_back_url = build_catalog_back_url(request)
        htmx_request = is_htmx(request)
        template_name = "catalog_list.html" if htmx_request else "catalog.html"
        return render_catalog_template(
            request,
            template_name,
            {
                "settings": context.settings,
                "index": index_data,
                "groups": groups,
                "items": filtered_items,
                "query": "",
                "search_tokens": search_tokens,
                "group_filters": parse_group_filters(group),
                "active_filters": active_filters,
                "criticality_level": criticality_level or "",
                "team_id": team_id or "",
                "health_marker": health_marker_filter,
                "criticality_levels": criticality_levels,
                "team_options": team_options,
                "group_query_base": group_query_base,
                "catalog_back_url": catalog_back_url,
                "include_active_filters_oob": htmx_request,
                "health_by_scene": health_report.items_by_scene if health_report else {},
                "graph_issue_text_keys": GRAPH_ISSUE_TEXT_KEYS,
                "gaming_issue_text_keys": GAMING_ISSUE_TEXT_KEYS,
                "gaming_issue_reason_text_keys": GAMING_ISSUE_REASON_TEXT_KEYS,
                "validity_issue_blocks_by_scene": validity_issue_blocks_by_scene,
            },
        )

    @app.get("/catalog/teams/graph", response_class=HTMLResponse)
    def catalog_team_graph(
        request: Request,
        team_ids: list[str] = Query(default_factory=list),
        excluded_team_ids: list[str] = Query(default_factory=list),
        merge_nodes_all_markups: bool = Query(default=False),
        merge_selected_markups: bool = Query(default=False),
        merge_node_min_chain_size: int = Query(default=1, ge=0, le=10),
        job_id: str | None = Query(default=None),
        context: CatalogContext = Depends(get_context),
    ) -> HTMLResponse:
        return render_team_graph_page(
            request,
            team_ids=team_ids,
            excluded_team_ids=excluded_team_ids,
            excluded_team_ids_explicit="excluded_team_ids" in request.query_params,
            merge_nodes_all_markups=merge_nodes_all_markups,
            merge_selected_markups=merge_selected_markups,
            merge_node_min_chain_size=merge_node_min_chain_size,
            context=context,
            job_id=job_id,
        )

    @app.post("/catalog/teams/graph/merge", response_class=HTMLResponse)
    async def catalog_team_graph_merge(
        request: Request,
        context: CatalogContext = Depends(get_context),
    ) -> Response:
        form = await request.form()
        team_ids = normalize_team_ids([str(value) for value in form.getlist("team_ids")])
        excluded_team_ids = normalize_team_ids(
            [str(value) for value in form.getlist("excluded_team_ids")]
        )
        merge_nodes_all_markups = "merge_nodes_all_markups" in form
        merge_selected_markups = "merge_selected_markups" in form
        merge_node_min_chain_size = 1
        raw_threshold = str(form.get("merge_node_min_chain_size", "1")).strip()
        if raw_threshold:
            try:
                merge_node_min_chain_size = max(0, min(10, int(raw_threshold)))
            except ValueError:
                merge_node_min_chain_size = 1

        index_data = load_index(context)
        if index_data is None:
            return render_catalog_template(
                request,
                "catalog_empty.html",
                {
                    "settings": context.settings,
                },
            )
        build_request = build_team_graph_request(
            team_ids=team_ids,
            excluded_team_ids=excluded_team_ids,
            merge_nodes_all_markups=merge_nodes_all_markups,
            merge_selected_markups=merge_selected_markups,
            merge_node_min_chain_size=merge_node_min_chain_size,
        )
        job_id = None
        if team_ids:
            index_signature = resolve_catalog_index_signature(context, index_data)
            job = create_or_reuse_team_graph_job(
                context,
                build_request=build_request,
                index_data=index_data,
                cache_signature=build_team_graph_cache_signature(
                    context,
                    index_signature=index_signature,
                ),
            )
            job_id = job.job_id

        response = render_team_graph_page(
            request,
            team_ids=team_ids,
            excluded_team_ids=excluded_team_ids,
            excluded_team_ids_explicit=True,
            merge_nodes_all_markups=merge_nodes_all_markups,
            merge_selected_markups=merge_selected_markups,
            merge_node_min_chain_size=merge_node_min_chain_size,
            context=context,
            job_id=job_id,
        )
        page_query = build_team_page_query(
            team_ids,
            excluded_team_ids=excluded_team_ids,
            merge_nodes_all_markups=merge_nodes_all_markups,
            merge_selected_markups=merge_selected_markups,
            merge_node_min_chain_size=merge_node_min_chain_size,
            job_id=job_id,
            language=localizer_for_request(request).language,
        )
        push_url = f"/catalog/teams/graph?{page_query}" if page_query else "/catalog/teams/graph"
        if is_htmx(request):
            response.headers["HX-Push-Url"] = push_url
            return response
        return RedirectResponse(url=push_url, status_code=303)

    @app.get("/catalog/teams/health", response_class=HTMLResponse)
    def catalog_team_health(
        request: Request,
        context: CatalogContext = Depends(get_context),
    ) -> HTMLResponse:
        index_data, health_report = load_index_bundle(context)
        if index_data is None or health_report is None:
            return render_catalog_template(
                request,
                "catalog_empty.html",
                {
                    "settings": context.settings,
                },
            )
        team_rows = build_team_health_rows(index_data.items, health_report)
        return render_catalog_template(
            request,
            "catalog_team_health.html",
            {
                "settings": context.settings,
                "health_report": health_report,
                "team_rows": team_rows,
                "graph_issue_text_keys": GRAPH_ISSUE_TEXT_KEYS,
                "gaming_issue_text_keys": GAMING_ISSUE_TEXT_KEYS,
                "gaming_issue_reason_text_keys": GAMING_ISSUE_REASON_TEXT_KEYS,
            },
        )

    @app.get("/catalog/{scene_id}", response_class=HTMLResponse)
    def catalog_detail(
        request: Request,
        scene_id: str,
        back: str | None = Query(default=None),
        context: CatalogContext = Depends(get_context),
    ) -> HTMLResponse:
        index_data, health_report = load_index_bundle(context)
        item = find_item(index_data, scene_id) if index_data else None
        if not item:
            raise HTTPException(status_code=404, detail="Scene not found")
        assert index_data is not None
        diagram_base_url = context.settings.catalog.excalidraw_base_url
        excalidraw_open_url = diagram_base_url
        procedure_excalidraw_open_url = diagram_base_url
        excalidraw_scene_available = False
        procedure_graph_enabled = True
        open_mode = "direct"
        procedure_open_mode = "manual"
        on_demand = context.settings.catalog.generate_excalidraw_on_demand
        scene_path = context.settings.catalog.excalidraw_in_dir / item.excalidraw_rel_path
        try:
            scene_payload = context.scene_repo.load(scene_path)
            if scene_payload.get("elements") is not None:
                enhance_scene_payload(scene_payload, context, "excalidraw")
                if is_same_origin(request, diagram_base_url):
                    excalidraw_open_url = f"/catalog/{scene_id}/open"
                    open_mode = "local_storage"
                else:
                    excalidraw_open_url = build_excalidraw_url(diagram_base_url, scene_payload)
                    if (
                        len(excalidraw_open_url)
                        > context.settings.catalog.excalidraw_max_url_length
                    ):
                        excalidraw_open_url = diagram_base_url
                        open_mode = "manual"
                excalidraw_scene_available = True
        except FileNotFoundError:
            if on_demand:
                excalidraw_scene_available = True
                if is_same_origin(request, diagram_base_url):
                    excalidraw_open_url = f"/catalog/{scene_id}/open"
                    open_mode = "local_storage"
                else:
                    excalidraw_open_url = diagram_base_url
                    open_mode = "manual"
        procedure_graph_api_url = f"/api/scenes/{scene_id}/procedure-graph-view"
        if is_same_origin(request, diagram_base_url):
            procedure_excalidraw_open_url = f"/catalog/{scene_id}/procedure-graph/open"
            procedure_open_mode = "local_storage"
        else:
            try:
                procedure_payload = build_scene_procedure_diagram_payload(
                    context,
                    index_data,
                    item,
                    "excalidraw",
                    ui_language=localizer_for_request(request).language,
                )
            except HTTPException:
                procedure_graph_enabled = False
                procedure_open_mode = "manual"
            else:
                procedure_excalidraw_open_url = build_excalidraw_url(
                    diagram_base_url,
                    procedure_payload,
                )
                if (
                    len(procedure_excalidraw_open_url)
                    > context.settings.catalog.excalidraw_max_url_length
                ):
                    procedure_excalidraw_open_url = diagram_base_url
                    procedure_open_mode = "manual"
                else:
                    procedure_open_mode = "direct"
        service_external_url = resolve_service_external_url(context, item)
        team_external_url = resolve_team_external_url(context, item)
        item_health = health_report.item(item.scene_id) if health_report is not None else None
        validity_issue_blocks = (
            build_validity_issue_blocks_by_scene(context, [item]).get(item.scene_id, {})
            if item_health is not None and item_health.gaming.is_problem
            else {}
        )
        catalog_back_url = resolve_catalog_back_url(
            back,
            language=localizer_for_request(request).language,
        )
        return render_catalog_template(
            request,
            "catalog_detail.html",
            {
                "settings": context.settings,
                "item": item,
                "index": index_data,
                "diagram_excalidraw_enabled": context.settings.catalog.diagram_excalidraw_enabled,
                "excalidraw_rel_path": item.excalidraw_rel_path,
                "unidraw_rel_path": item.unidraw_rel_path,
                "excalidraw_open_url": excalidraw_open_url,
                "excalidraw_dir_label": context.settings.catalog.excalidraw_in_dir.name,
                "excalidraw_scene_available": excalidraw_scene_available,
                "open_mode": open_mode,
                "on_demand_enabled": on_demand,
                "service_external_url": service_external_url,
                "team_external_url": team_external_url,
                "block_graph_api_url": f"/api/scenes/{scene_id}/block-graph",
                "block_graph_enabled": excalidraw_scene_available,
                "procedure_graph_api_url": procedure_graph_api_url,
                "procedure_graph_enabled": procedure_graph_enabled,
                "procedure_excalidraw_open_url": procedure_excalidraw_open_url,
                "procedure_open_mode": procedure_open_mode,
                "item_health": item_health,
                "validity_issue_blocks": validity_issue_blocks,
                "catalog_back_url": catalog_back_url,
                "graph_issue_text_keys": GRAPH_ISSUE_TEXT_KEYS,
                "gaming_issue_text_keys": GAMING_ISSUE_TEXT_KEYS,
                "gaming_issue_reason_text_keys": GAMING_ISSUE_REASON_TEXT_KEYS,
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
        assert index_data is not None
        diagram_url = context.settings.catalog.excalidraw_base_url
        if not is_same_origin(request, diagram_url):
            return RedirectResponse(url=diagram_url)
        return render_catalog_template(
            request,
            "catalog_open.html",
            {
                "settings": context.settings,
                "scene_id": scene_id,
                "scene_api_url": f"/api/scenes/{scene_id}?format=excalidraw",
                "diagram_url": diagram_url,
                "diagram_label": "Excalidraw",
                "diagram_storage_key": "excalidraw",
                "diagram_state_key": "excalidraw-state",
                "diagram_version_key": "version-dataState",
            },
        )

    @app.get("/catalog/{scene_id}/procedure-graph/open", response_class=HTMLResponse)
    def catalog_open_scene_procedure_graph(
        request: Request,
        scene_id: str,
        context: CatalogContext = Depends(get_context),
    ) -> Response:
        index_data = load_index(context)
        item = find_item(index_data, scene_id) if index_data else None
        if not item:
            raise HTTPException(status_code=404, detail="Scene not found")
        assert index_data is not None
        diagram_url = context.settings.catalog.excalidraw_base_url
        if not is_same_origin(request, diagram_url):
            return RedirectResponse(url=diagram_url)
        scene_payload: dict[str, Any] | None = None
        try:
            scene_payload = build_scene_procedure_diagram_payload(
                context,
                index_data,
                item,
                "excalidraw",
                ui_language=localizer_for_request(request).language,
            )
        except HTTPException:
            scene_payload = None
        return render_catalog_template(
            request,
            "catalog_open.html",
            {
                "settings": context.settings,
                "scene_id": f"{scene_id}-procedure-graph",
                "scene_api_url": f"/api/scenes/{scene_id}/procedure-graph?format=excalidraw",
                "diagram_url": diagram_url,
                "diagram_label": "Excalidraw",
                "diagram_storage_key": "excalidraw",
                "diagram_state_key": "excalidraw-state",
                "diagram_version_key": "version-dataState",
                "scene_payload": scene_payload,
            },
        )

    @app.get("/catalog/teams/graph/open", response_class=HTMLResponse)
    def catalog_team_graph_open(
        request: Request,
        team_ids: list[str] = Query(default_factory=list),
        excluded_team_ids: list[str] = Query(default_factory=list),
        merge_nodes_all_markups: bool = Query(default=False),
        merge_selected_markups: bool = Query(default=False),
        merge_node_min_chain_size: int = Query(default=1, ge=0, le=10),
        graph_level: GraphLevel = Query(default="procedure"),
        job_id: str | None = Query(default=None),
        context: CatalogContext = Depends(get_context),
    ) -> Response:
        team_ids = normalize_team_ids(team_ids)
        excluded_team_ids = normalize_team_ids(excluded_team_ids)
        if not team_ids:
            raise HTTPException(status_code=400, detail="team_ids is required")
        diagram_url = context.settings.catalog.excalidraw_base_url
        if not is_same_origin(request, diagram_url):
            return RedirectResponse(url=diagram_url)
        team_query = build_team_query(
            team_ids,
            excluded_team_ids=excluded_team_ids,
            merge_nodes_all_markups=merge_nodes_all_markups,
            merge_selected_markups=merge_selected_markups,
            merge_node_min_chain_size=merge_node_min_chain_size,
            graph_level=graph_level,
            job_id=job_id,
        )
        scene_payload: dict[str, Any] | None = None
        try:
            index_data = load_index(context)
            if index_data is not None:
                build_request = build_team_graph_request(
                    team_ids=team_ids,
                    excluded_team_ids=excluded_team_ids,
                    merge_nodes_all_markups=merge_nodes_all_markups,
                    merge_selected_markups=merge_selected_markups,
                    merge_node_min_chain_size=merge_node_min_chain_size,
                )
                cached_result = resolve_team_graph_cached_result(
                    context,
                    index_data=index_data,
                    build_request=build_request,
                    job_id=job_id,
                )
                if cached_result is not None:
                    graph_document = (
                        cached_result.service_graph_document
                        if graph_level == "service"
                        else cached_result.procedure_graph_document
                    )
                    scene_payload = build_procedure_graph_diagram_payload(
                        context,
                        graph_document,
                        "excalidraw",
                        ui_language=localizer_for_request(request).language,
                    )
                else:
                    items, merge_scope_items = resolve_team_graph_items(
                        index_data.items,
                        team_ids=team_ids,
                        excluded_team_ids=excluded_team_ids,
                    )
                    if items:
                        scene_payload = build_team_diagram_payload(
                            context,
                            items,
                            "excalidraw",
                            merge_nodes_all_markups=merge_nodes_all_markups,
                            merge_selected_markups=merge_selected_markups,
                            merge_node_min_chain_size=merge_node_min_chain_size,
                            graph_level=graph_level,
                            merge_items=merge_scope_items if merge_nodes_all_markups else None,
                            ui_language=localizer_for_request(request).language,
                        )
        except Exception:
            scene_payload = None
        return render_catalog_template(
            request,
            "catalog_open.html",
            {
                "settings": context.settings,
                "scene_id": "team-graph",
                "scene_api_url": f"/api/teams/graph?{team_query}&format=excalidraw",
                "diagram_url": diagram_url,
                "diagram_label": "Excalidraw",
                "diagram_storage_key": "excalidraw",
                "diagram_state_key": "excalidraw-state",
                "diagram_version_key": "version-dataState",
                "scene_payload": scene_payload,
            },
        )

    @app.get("/api/index")
    def api_index(context: CatalogContext = Depends(get_context)) -> ORJSONResponse:
        index_data = load_index(context)
        if index_data is None:
            raise HTTPException(status_code=404, detail="Catalog index not found")
        return ORJSONResponse(index_data.to_dict())

    @app.get("/api/team-graph-jobs/{job_id}")
    def api_team_graph_job_status(
        job_id: str,
        context: CatalogContext = Depends(get_context),
    ) -> ORJSONResponse:
        job = get_team_graph_job(context, job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="Team graph job not found")
        return ORJSONResponse(
            {
                "job_id": job.job_id,
                "status": job.status,
                "error_message": job.error_message,
                "updated_at": job.updated_at.isoformat(),
                "finished_at": job.finished_at.isoformat() if job.finished_at else None,
            }
        )

    @app.get("/api/scenes/{scene_id}")
    def api_scene(
        scene_id: str,
        format: SceneFormat = Query(default="excalidraw"),
        download: bool = Query(default=False),
        context: CatalogContext = Depends(get_context),
    ) -> ORJSONResponse:
        index_data = load_index(context)
        item = find_item(index_data, scene_id) if index_data else None
        if not item:
            raise HTTPException(status_code=404, detail="Scene not found")
        payload, diagram_rel_path = load_scene_payload(context, item, format)
        headers = {}
        if download:
            extension = resolve_diagram_extension(format)
            base_name = Path(diagram_rel_path).stem or scene_id
            filename = build_generated_diagram_filename(
                base_name=base_name,
                extension=extension,
                level="blocks",
            )
            headers["Content-Disposition"] = f'attachment; filename="{filename}"'
        return ORJSONResponse(payload, headers=headers)

    @app.get("/api/scenes/{scene_id}/block-graph")
    def api_scene_block_graph(
        scene_id: str,
        context: CatalogContext = Depends(get_context),
    ) -> ORJSONResponse:
        index_data = load_index(context)
        item = find_item(index_data, scene_id) if index_data else None
        if not item:
            raise HTTPException(status_code=404, detail="Scene not found")
        scene_payload, _ = load_scene_payload(context, item, "excalidraw")
        graph_payload = extract_block_graph_view(scene_payload)
        return ORJSONResponse(graph_payload)

    @app.get("/api/scenes/{scene_id}/procedure-graph")
    def api_scene_procedure_graph(
        request: Request,
        scene_id: str,
        format: SceneFormat = Query(default="excalidraw"),
        download: bool = Query(default=False),
        context: CatalogContext = Depends(get_context),
    ) -> ORJSONResponse:
        index_data = load_index(context)
        item = find_item(index_data, scene_id) if index_data else None
        if not item:
            raise HTTPException(status_code=404, detail="Scene not found")
        assert index_data is not None
        payload = build_scene_procedure_diagram_payload(
            context,
            index_data,
            item,
            format,
            ui_language=localizer_for_request(request).language,
        )
        headers = {}
        if download:
            extension = resolve_diagram_extension(format)
            filename = build_generated_diagram_filename(
                base_name=f"{scene_id}_procedure_graph",
                extension=extension,
                level="procedures",
            )
            headers["Content-Disposition"] = f'attachment; filename="{filename}"'
        return ORJSONResponse(payload, headers=headers)

    @app.get("/api/scenes/{scene_id}/procedure-graph-view")
    def api_scene_procedure_graph_view(
        scene_id: str,
        context: CatalogContext = Depends(get_context),
    ) -> ORJSONResponse:
        index_data = load_index(context)
        item = find_item(index_data, scene_id) if index_data else None
        if not item:
            raise HTTPException(status_code=404, detail="Scene not found")
        assert index_data is not None
        graph_document = build_scene_procedure_graph_document(context, index_data, item)
        graph_payload = extract_procedure_graph_view(graph_document)
        return ORJSONResponse(graph_payload)

    @app.get("/api/teams/graph")
    def api_team_graph(
        request: Request,
        team_ids: list[str] = Query(default_factory=list),
        excluded_team_ids: list[str] = Query(default_factory=list),
        merge_nodes_all_markups: bool = Query(default=False),
        merge_selected_markups: bool = Query(default=False),
        merge_node_min_chain_size: int = Query(default=1, ge=0, le=10),
        graph_level: GraphLevel = Query(default="procedure"),
        format: SceneFormat = Query(default="excalidraw"),
        download: bool = Query(default=False),
        job_id: str | None = Query(default=None),
        context: CatalogContext = Depends(get_context),
    ) -> ORJSONResponse:
        team_ids = normalize_team_ids(team_ids)
        excluded_team_ids = normalize_team_ids(excluded_team_ids)
        if not team_ids:
            raise HTTPException(status_code=400, detail="team_ids is required")
        index_data = load_index(context)
        if index_data is None:
            raise HTTPException(status_code=404, detail="Catalog index not found")
        build_request = build_team_graph_request(
            team_ids=team_ids,
            excluded_team_ids=excluded_team_ids,
            merge_nodes_all_markups=merge_nodes_all_markups,
            merge_selected_markups=merge_selected_markups,
            merge_node_min_chain_size=merge_node_min_chain_size,
        )
        cached_result = resolve_team_graph_cached_result(
            context,
            index_data=index_data,
            build_request=build_request,
            job_id=job_id,
        )
        if cached_result is not None:
            graph_document = (
                cached_result.service_graph_document
                if graph_level == "service"
                else cached_result.procedure_graph_document
            )
            payload = build_procedure_graph_diagram_payload(
                context,
                graph_document,
                format,
                ui_language=localizer_for_request(request).language,
            )
        else:
            items, merge_scope_items = resolve_team_graph_items(
                index_data.items,
                team_ids=team_ids,
                excluded_team_ids=excluded_team_ids,
            )
            if not items:
                raise HTTPException(status_code=404, detail="No scenes for selected teams")
            payload = build_team_diagram_payload(
                context,
                items,
                format,
                merge_nodes_all_markups=merge_nodes_all_markups,
                merge_selected_markups=merge_selected_markups,
                merge_node_min_chain_size=merge_node_min_chain_size,
                graph_level=graph_level,
                merge_items=merge_scope_items if merge_nodes_all_markups else None,
                ui_language=localizer_for_request(request).language,
            )
        headers = {}
        if download:
            extension = resolve_diagram_extension(format)
            suffix = "_".join(team_ids)
            graph_name = "team-service-graph" if graph_level == "service" else "team-graph"
            base_name = f"{graph_name}_{suffix}" if suffix else graph_name
            filename = build_generated_diagram_filename(
                base_name=base_name,
                extension=extension,
                level=resolve_diagram_level(graph_level),
            )
            headers["Content-Disposition"] = f'attachment; filename="{filename}"'
        return ORJSONResponse(payload, headers=headers)

    @app.get("/api/teams/graph-view")
    def api_team_graph_view(
        team_ids: list[str] = Query(default_factory=list),
        excluded_team_ids: list[str] = Query(default_factory=list),
        merge_nodes_all_markups: bool = Query(default=False),
        merge_selected_markups: bool = Query(default=False),
        merge_node_min_chain_size: int = Query(default=1, ge=0, le=10),
        graph_level: GraphLevel = Query(default="service"),
        job_id: str | None = Query(default=None),
        context: CatalogContext = Depends(get_context),
    ) -> ORJSONResponse:
        team_ids = normalize_team_ids(team_ids)
        excluded_team_ids = normalize_team_ids(excluded_team_ids)
        if not team_ids:
            raise HTTPException(status_code=400, detail="team_ids is required")
        index_data = load_index(context)
        if index_data is None:
            raise HTTPException(status_code=404, detail="Catalog index not found")
        build_request = build_team_graph_request(
            team_ids=team_ids,
            excluded_team_ids=excluded_team_ids,
            merge_nodes_all_markups=merge_nodes_all_markups,
            merge_selected_markups=merge_selected_markups,
            merge_node_min_chain_size=merge_node_min_chain_size,
        )
        cached_result = resolve_team_graph_cached_result(
            context,
            index_data=index_data,
            build_request=build_request,
            job_id=job_id,
        )
        if cached_result is not None:
            graph_document = (
                cached_result.service_graph_document
                if graph_level == "service"
                else cached_result.procedure_graph_document
            )
        else:
            items, merge_scope_items = resolve_team_graph_items(
                index_data.items,
                team_ids=team_ids,
                excluded_team_ids=excluded_team_ids,
            )
            if not items:
                raise HTTPException(status_code=404, detail="No scenes for selected teams")
            graph_document = build_team_graph_document(
                context,
                items,
                merge_nodes_all_markups=merge_nodes_all_markups,
                merge_selected_markups=merge_selected_markups,
                merge_node_min_chain_size=merge_node_min_chain_size,
                graph_level=graph_level,
                merge_items=merge_scope_items if merge_nodes_all_markups else None,
            )
        return ORJSONResponse(extract_procedure_graph_view(graph_document))

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
        update_catalog_health_cache(context, index_data)
        return ORJSONResponse({"status": "ok", "items": len(index_data.items)})

    proxy_upstream = settings.catalog.excalidraw_proxy_upstream
    if proxy_upstream:
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


async def run_catalog_index_refresh_loop(
    context: CatalogContext,
    interval_seconds: float,
    stop_event: asyncio.Event,
) -> None:
    refresh_state = CatalogRefreshState()
    while True:
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=interval_seconds)
            if stop_event.is_set():
                return
        except TimeoutError:
            pass
        refresh_catalog_index_if_needed(context, refresh_state)


def refresh_catalog_index_if_needed(
    context: CatalogContext,
    state: CatalogRefreshState,
) -> None:
    config = context.settings.catalog.to_index_config()
    if state.last_source_fingerprint is None:
        try:
            rebuilt_index = context.index_builder.build(config)
            update_catalog_health_cache(context, rebuilt_index)
        except Exception:
            logger.exception("Periodic catalog index refresh failed.")
            return
        state.last_source_fingerprint = read_catalog_source_fingerprint(context, config)
        return
    current_fingerprint = read_catalog_source_fingerprint(context, config)
    if current_fingerprint is not None and current_fingerprint == state.last_source_fingerprint:
        return
    try:
        rebuilt_index = context.index_builder.build(config)
        update_catalog_health_cache(context, rebuilt_index)
    except Exception:
        logger.exception("Periodic catalog index refresh failed.")
        return
    if current_fingerprint is not None:
        state.last_source_fingerprint = current_fingerprint
        return
    state.last_source_fingerprint = read_catalog_source_fingerprint(context, config)


def read_catalog_source_fingerprint(
    context: CatalogContext,
    config: CatalogIndexConfig,
) -> str | None:
    try:
        return context.index_builder.source_fingerprint(config)
    except Exception:
        logger.exception("Catalog source fingerprint read failed.")
        return None


def get_context(request: Request) -> CatalogContext:
    return cast(CatalogContext, request.app.state.context)


def invalidate_scene_cache(context: CatalogContext) -> None:
    settings = context.settings.catalog
    if not settings.invalidate_excalidraw_cache_on_start:
        return
    if not settings.generate_excalidraw_on_demand:
        return
    context.scene_repo.clear_cache(context.settings.catalog.excalidraw_in_dir)


def enhance_scene_payload(
    payload: dict[str, Any],
    context: CatalogContext,
    diagram_format: SceneFormat,
) -> None:
    elements = payload.get("elements")
    if not isinstance(elements, list):
        return
    if diagram_format == "excalidraw":
        ensure_service_title(elements)
        ensure_excalidraw_links(elements, context.link_templates)
        app_state = payload.get("appState")
        if not isinstance(app_state, dict):
            app_state = {}
            payload["appState"] = app_state
        apply_title_focus(app_state, elements)
    elif diagram_format == "unidraw":
        ensure_unidraw_links(elements, context.link_templates)


def load_index(context: CatalogContext) -> CatalogIndex | None:
    path = context.settings.catalog.index_path
    stamp = read_catalog_index_stamp(path)
    cached = context.index_state
    if (
        cached.index is not None
        and cached.path == path
        and cached.stamp is not None
        and cached.stamp == stamp
    ):
        return cached.index
    if stamp is None:
        invalidate_catalog_index_cache(context, path=path)
        return None
    try:
        index_data = context.index_repo.load(path)
    except FileNotFoundError:
        invalidate_catalog_index_cache(context, path=path)
        return None
    update_catalog_index_cache(context, index_data, path=path, stamp=stamp)
    return index_data


def load_index_bundle(
    context: CatalogContext,
) -> tuple[CatalogIndex | None, CatalogHealthReport | None]:
    index_data = load_index(context)
    if index_data is None:
        return None, None
    report = ensure_catalog_health_cache(context, index_data)
    return index_data, report


def ensure_catalog_health_cache(
    context: CatalogContext,
    index_data: CatalogIndex,
) -> CatalogHealthReport:
    signature = resolve_catalog_index_signature(context, index_data)
    cached = context.health_state
    if cached.index_signature == signature and cached.report is not None:
        return cached.report
    report = context.health_builder.build(index_data.items)
    cached.index_signature = signature
    cached.report = report
    return report


def update_catalog_health_cache(
    context: CatalogContext,
    index_data: CatalogIndex | None,
) -> None:
    if not isinstance(index_data, CatalogIndex):
        return
    if not hasattr(context, "health_state") or not hasattr(context, "health_builder"):
        return
    update_catalog_index_cache(context, index_data)
    signature = resolve_catalog_index_signature(context, index_data)
    try:
        report = context.health_builder.build(index_data.items)
    except Exception:
        logger.exception("Catalog health report refresh failed.")
        return
    context.health_state.index_signature = signature
    context.health_state.report = report


def build_catalog_index_signature(index_data: CatalogIndex) -> str:
    digest_source: list[str] = []
    for item in sorted(index_data.items, key=lambda candidate: candidate.scene_id):
        procedure_ids = ",".join(sorted(item.procedure_ids))
        procedure_graph_size = sum(len(targets) for targets in item.procedure_graph.values())
        digest_source.append(
            f"{item.scene_id}:{item.updated_at}:{procedure_ids}:{procedure_graph_size}"
        )
    digest = hashlib.sha256("|".join(digest_source).encode("utf-8")).hexdigest()
    return f"{index_data.generated_at}:{len(index_data.items)}:{digest}"


def resolve_catalog_index_signature(
    context: CatalogContext,
    index_data: CatalogIndex,
) -> str:
    cached = context.index_state
    if cached.index is index_data and cached.signature is not None:
        return cached.signature
    signature = build_catalog_index_signature(index_data)
    if cached.index is index_data:
        cached.signature = signature
    return signature


def update_catalog_index_cache(
    context: CatalogContext,
    index_data: CatalogIndex,
    *,
    path: Path | None = None,
    stamp: tuple[int, int] | None = None,
) -> None:
    index_path = path or context.settings.catalog.index_path
    resolved_stamp = stamp if stamp is not None else read_catalog_index_stamp(index_path)
    cached = context.index_state
    cached.path = index_path
    cached.stamp = resolved_stamp
    cached.index = index_data
    cached.signature = None


def invalidate_catalog_index_cache(
    context: CatalogContext,
    *,
    path: Path | None = None,
) -> None:
    cached = context.index_state
    cached.path = path
    cached.stamp = None
    cached.index = None
    cached.signature = None


def read_catalog_index_stamp(path: Path) -> tuple[int, int] | None:
    try:
        stats = path.stat()
    except FileNotFoundError:
        return None
    return (int(stats.st_mtime_ns), int(stats.st_size))


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


def resolve_service_external_url(context: CatalogContext, item: CatalogItem) -> str | None:
    if not context.link_templates:
        return None
    unit_id = item.finedog_unit_id.strip()
    if not unit_id or unit_id == context.settings.catalog.unknown_value:
        return None
    return context.link_templates.service_link(unit_id)


def resolve_procedure_external_url(context: CatalogContext, procedure_id: str | None) -> str | None:
    if not context.link_templates:
        return None
    if not isinstance(procedure_id, str):
        return None
    normalized = procedure_id.strip()
    if not normalized:
        return None
    return context.link_templates.procedure_link(normalized)


def resolve_block_external_url(
    context: CatalogContext,
    block_id: str | None,
    procedure_id: str | None = None,
) -> str | None:
    if not context.link_templates:
        return None
    if not isinstance(block_id, str):
        return None
    normalized_block_id = block_id.strip()
    if not normalized_block_id:
        return None
    normalized_procedure_id = None
    if isinstance(procedure_id, str):
        stripped = procedure_id.strip()
        if stripped:
            normalized_procedure_id = stripped
    return context.link_templates.block_link(
        normalized_block_id,
        procedure_id=normalized_procedure_id,
    )


def resolve_team_external_url(context: CatalogContext, item: CatalogItem) -> str | None:
    if not context.link_templates:
        return None
    team_id = item.team_id.strip()
    if not team_id or team_id == context.settings.catalog.unknown_value:
        return None
    return context.link_templates.team_link(team_id)


def resolve_diagram_extension(diagram_format: SceneFormat) -> str:
    return ".excalidraw" if diagram_format == "excalidraw" else ".unidraw"


def resolve_diagram_level(graph_level: GraphLevel) -> str:
    return "services" if graph_level == "service" else "procedures"


def build_generated_diagram_filename(
    *,
    base_name: str,
    extension: str,
    level: str,
    generated_at: datetime | None = None,
) -> str:
    normalized_base = base_name.strip().replace("/", "_") or "diagram"
    date_value = (generated_at or datetime.now(UTC)).date().isoformat()
    return f"{normalized_base}_{level}_{date_value}{extension}"


def resolve_scene_rel_path(item: CatalogItem, diagram_format: SceneFormat) -> str:
    if diagram_format == "unidraw":
        if item.unidraw_rel_path:
            return item.unidraw_rel_path
        return infer_unidraw_rel_path(item)
    return item.excalidraw_rel_path


def resolve_diagram_in_dir(settings: AppSettings, diagram_format: SceneFormat) -> Path:
    if diagram_format == "unidraw":
        return settings.catalog.unidraw_in_dir
    return settings.catalog.excalidraw_in_dir


def load_scene_payload(
    context: CatalogContext,
    item: CatalogItem,
    diagram_format: SceneFormat,
) -> tuple[dict[str, Any], str]:
    diagram_rel_path = resolve_scene_rel_path(item, diagram_format)
    scene_path = resolve_diagram_in_dir(context.settings, diagram_format) / diagram_rel_path
    should_regenerate = False
    try:
        payload = context.scene_repo.load(scene_path)
    except FileNotFoundError as exc:
        if not context.settings.catalog.generate_excalidraw_on_demand:
            raise HTTPException(status_code=404, detail="Scene file missing") from exc
        should_regenerate = True
    else:
        if context.settings.catalog.generate_excalidraw_on_demand and is_scene_cache_outdated(
            item, scene_path
        ):
            should_regenerate = True
    if should_regenerate:
        payload = build_diagram_payload(context, item, diagram_format)
        if context.settings.catalog.cache_excalidraw_on_demand:
            context.scene_repo.save(payload, scene_path)
    enhance_scene_payload(payload, context, diagram_format)
    return payload, diagram_rel_path


def is_scene_cache_outdated(item: CatalogItem, scene_path: Path) -> bool:
    try:
        scene_mtime = datetime.fromtimestamp(scene_path.stat().st_mtime, tz=UTC)
    except FileNotFoundError:
        return True
    source_updated_at = parse_iso_datetime(item.updated_at)
    if source_updated_at is None:
        return False
    return scene_mtime < source_updated_at


def parse_iso_datetime(value: str) -> datetime | None:
    normalized = str(value or "").strip()
    if not normalized:
        return None
    if normalized.endswith("Z"):
        normalized = f"{normalized[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def infer_unidraw_rel_path(item: CatalogItem) -> str:
    markup_rel_path = item.markup_rel_path.strip()
    if markup_rel_path:
        markup_path = Path(markup_rel_path)
        return str(markup_path.with_suffix(".unidraw").as_posix())
    excalidraw_rel_path = item.excalidraw_rel_path.strip()
    if excalidraw_rel_path.endswith(".excalidraw"):
        return f"{excalidraw_rel_path[:-len('.excalidraw')]}.unidraw"
    return excalidraw_rel_path


def build_diagram_payload(
    context: CatalogContext,
    item: CatalogItem,
    diagram_format: SceneFormat,
) -> dict[str, Any]:
    markup_root = Path(context.settings.catalog.s3.prefix or "")
    markup_path = markup_root / item.markup_rel_path
    try:
        markup = context.markup_reader.load_by_path(markup_path)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Markup file missing") from exc
    if diagram_format == "excalidraw":
        document = context.to_excalidraw.convert(markup)
    else:
        document = context.to_unidraw.convert(markup)
    return cast(dict[str, Any], document.to_dict())


def resolve_scene_team_items(index_data: CatalogIndex, item: CatalogItem) -> list[CatalogItem]:
    team_id = item.team_id
    same_team_items = [candidate for candidate in index_data.items if candidate.team_id == team_id]
    if not same_team_items:
        return [item]
    has_item = any(candidate.scene_id == item.scene_id for candidate in same_team_items)
    if has_item:
        return same_team_items
    return [item, *same_team_items]


def build_scene_procedure_graph_document(
    context: CatalogContext,
    index_data: CatalogIndex,
    item: CatalogItem,
    *,
    document_cache: dict[str, MarkupDocument] | None = None,
) -> MarkupDocument:
    team_items = resolve_scene_team_items(index_data, item)
    return build_team_graph_document(
        context,
        [item],
        merge_nodes_all_markups=True,
        merge_selected_markups=False,
        merge_node_min_chain_size=1,
        graph_level="procedure",
        merge_items=team_items,
        document_cache=document_cache,
        force_merge_scope=True,
    )


def build_scene_procedure_diagram_payload(
    context: CatalogContext,
    index_data: CatalogIndex,
    item: CatalogItem,
    diagram_format: SceneFormat,
    *,
    ui_language: str | None = None,
    document_cache: dict[str, MarkupDocument] | None = None,
) -> dict[str, Any]:
    team_items = resolve_scene_team_items(index_data, item)
    return build_team_diagram_payload(
        context,
        [item],
        diagram_format,
        merge_nodes_all_markups=True,
        merge_selected_markups=False,
        merge_node_min_chain_size=1,
        graph_level="procedure",
        merge_items=team_items,
        document_cache=document_cache,
        ui_language=ui_language,
        force_merge_scope=True,
    )


def build_team_graph_document(
    context: CatalogContext,
    items: list[CatalogItem],
    merge_nodes_all_markups: bool = False,
    merge_selected_markups: bool = False,
    merge_node_min_chain_size: int = 1,
    graph_level: GraphLevel = "procedure",
    merge_items: list[CatalogItem] | None = None,
    document_cache: dict[str, MarkupDocument] | None = None,
    force_merge_scope: bool = False,
) -> MarkupDocument:
    cache = document_cache if document_cache is not None else {}
    documents = load_markup_documents(context, items, cache=cache)
    merge_documents: list[MarkupDocument] | None = None
    if merge_nodes_all_markups:
        merge_source = merge_items
        if merge_source is None:
            index_data = load_index(context)
            if index_data is not None:
                merge_source = index_data.items
        elif not force_merge_scope:
            index_data = load_index(context)
            if index_data is not None and len(merge_source) < len(index_data.items):
                merge_source = index_data.items
        if merge_source is None:
            merge_source = items
        merge_documents = load_markup_documents(context, merge_source, cache=cache)
    try:
        return BuildTeamProcedureGraph().build(
            documents,
            merge_documents=merge_documents,
            merge_selected_markups=merge_selected_markups,
            merge_node_min_chain_size=merge_node_min_chain_size,
            graph_level=graph_level,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def build_team_diagram_payload(
    context: CatalogContext,
    items: list[CatalogItem],
    diagram_format: SceneFormat,
    merge_nodes_all_markups: bool = False,
    merge_selected_markups: bool = False,
    merge_node_min_chain_size: int = 1,
    graph_level: GraphLevel = "procedure",
    merge_items: list[CatalogItem] | None = None,
    document_cache: dict[str, MarkupDocument] | None = None,
    ui_language: str | None = None,
    force_merge_scope: bool = False,
) -> dict[str, Any]:
    graph_document = build_team_graph_document(
        context,
        items,
        merge_nodes_all_markups=merge_nodes_all_markups,
        merge_selected_markups=merge_selected_markups,
        merge_node_min_chain_size=merge_node_min_chain_size,
        graph_level=graph_level,
        merge_items=merge_items,
        document_cache=document_cache,
        force_merge_scope=force_merge_scope,
    )
    return build_procedure_graph_diagram_payload(
        context,
        graph_document,
        diagram_format,
        ui_language=ui_language,
    )


def build_procedure_graph_diagram_payload(
    context: CatalogContext,
    graph_document: MarkupDocument,
    diagram_format: SceneFormat,
    *,
    ui_language: str | None = None,
) -> dict[str, Any]:
    document: ExcalidrawDocument | UnidrawDocument
    if diagram_format == "excalidraw":
        document = context.to_procedure_graph_excalidraw.convert(graph_document)
    else:
        document = context.to_procedure_graph_unidraw.convert(graph_document)
    payload = cast(dict[str, Any], document.to_dict())
    language = ui_language or get_active_ui_language()
    _localize_markup_type_column_titles(payload, language)
    enhance_scene_payload(payload, context, diagram_format)
    return payload


def _localize_markup_type_column_titles(payload: dict[str, Any], language: str) -> None:
    elements = payload.get("elements")
    if not isinstance(elements, list):
        return
    for element in elements:
        if not isinstance(element, dict):
            continue
        metadata = element.get("customData", {}).get("cjm")
        if not isinstance(metadata, dict):
            metadata = element.get("cjm")
        if not isinstance(metadata, dict):
            continue
        if metadata.get("role") != "markup_type_column_title":
            continue
        markup_type = str(metadata.get("markup_type") or "").strip()
        if not markup_type:
            continue
        localized = humanize_markup_type_column_label(markup_type, language)
        if localized:
            element["text"] = localized


def load_markup_documents(
    context: CatalogContext,
    items: Sequence[CatalogItem],
    *,
    cache: dict[str, MarkupDocument] | None = None,
) -> list[MarkupDocument]:
    markup_root = Path(context.settings.catalog.s3.prefix or "")
    documents: list[MarkupDocument] = []
    if cache is None:
        cache = {}
    for item in items:
        cached = cache.get(item.markup_rel_path)
        if cached is not None:
            documents.append(cached)
            continue
        markup_path = markup_root / item.markup_rel_path
        try:
            markup = context.markup_reader.load_by_path(markup_path)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Markup file missing") from exc
        cache[item.markup_rel_path] = markup
        documents.append(markup)
    return documents


def build_team_graph_request(
    *,
    team_ids: Sequence[str],
    excluded_team_ids: Sequence[str],
    merge_nodes_all_markups: bool,
    merge_selected_markups: bool,
    merge_node_min_chain_size: int,
) -> TeamGraphBuildRequest:
    return TeamGraphBuildRequest(
        team_ids=tuple(team_ids),
        excluded_team_ids=tuple(excluded_team_ids),
        merge_nodes_all_markups=merge_nodes_all_markups,
        merge_selected_markups=merge_selected_markups,
        merge_node_min_chain_size=merge_node_min_chain_size,
    )


def build_team_graph_request_key(
    build_request: TeamGraphBuildRequest,
    *,
    cache_signature: str,
) -> str:
    payload = {
        "cache_signature": cache_signature,
        "team_ids": list(build_request.team_ids),
        "excluded_team_ids": list(build_request.excluded_team_ids),
        "merge_nodes_all_markups": build_request.merge_nodes_all_markups,
        "merge_selected_markups": build_request.merge_selected_markups,
        "merge_node_min_chain_size": build_request.merge_node_min_chain_size,
    }
    digest_source = orjson.dumps(payload, option=orjson.OPT_SORT_KEYS)
    return hashlib.sha256(digest_source).hexdigest()


def get_team_graph_job(
    context: CatalogContext,
    job_id: str | None,
) -> TeamGraphJob | None:
    if not job_id:
        return None
    with context.team_graph_jobs.lock:
        return context.team_graph_jobs.jobs.get(job_id)


def build_team_graph_cache_signature(
    context: CatalogContext,
    *,
    index_signature: str,
) -> str:
    return f"{context.team_graph_jobs.instance_id}:{index_signature}"


def find_team_graph_job_for_request(
    context: CatalogContext,
    *,
    build_request: TeamGraphBuildRequest,
    cache_signature: str,
    reuse_failed: bool,
) -> TeamGraphJob | None:
    request_key = build_team_graph_request_key(build_request, cache_signature=cache_signature)
    with context.team_graph_jobs.lock:
        job_id = context.team_graph_jobs.request_jobs.get(request_key)
        if not job_id:
            return None
        job = context.team_graph_jobs.jobs.get(job_id)
        if job is None:
            context.team_graph_jobs.request_jobs.pop(request_key, None)
            return None
        if (
            job.request != build_request
            or job.index_signature != cache_signature
            or (job.status == "failed" and not reuse_failed)
        ):
            return None
        return job


def create_or_reuse_team_graph_job(
    context: CatalogContext,
    *,
    build_request: TeamGraphBuildRequest,
    index_data: CatalogIndex,
    cache_signature: str,
) -> TeamGraphJob:
    reusable = find_team_graph_job_for_request(
        context,
        build_request=build_request,
        cache_signature=cache_signature,
        reuse_failed=False,
    )
    if reusable is not None:
        return reusable

    now = datetime.now(tz=UTC)
    job = TeamGraphJob(
        job_id=uuid4().hex,
        request=build_request,
        index_signature=cache_signature,
        status="pending",
        created_at=now,
        updated_at=now,
    )
    request_key = build_team_graph_request_key(build_request, cache_signature=cache_signature)
    with context.team_graph_jobs.lock:
        context.team_graph_jobs.jobs[job.job_id] = job
        context.team_graph_jobs.request_jobs[request_key] = job.job_id
        prune_team_graph_jobs(context.team_graph_jobs, keep_job_ids={job.job_id})
    context.team_graph_jobs.executor.submit(run_team_graph_job, context, job.job_id, index_data)
    return job


def run_team_graph_job(
    context: CatalogContext,
    job_id: str,
    index_data: CatalogIndex,
) -> None:
    with context.team_graph_jobs.lock:
        job = context.team_graph_jobs.jobs.get(job_id)
        if job is None:
            return
        job.status = "running"
        job.started_at = datetime.now(tz=UTC)
        job.updated_at = job.started_at
        job.error_message = None
        job.result = None
    try:
        result = compute_team_graph_build_result(context, index_data, job.request)
    except HTTPException as exc:
        message = str(exc.detail) if exc.detail is not None else "Unable to build team graph."
        logger.warning("Team graph merge job failed: %s", message)
        finish_team_graph_job(
            context,
            job_id,
            status="failed",
            error_message=message,
        )
        return
    except Exception as exc:
        logger.exception("Team graph merge job failed unexpectedly.")
        finish_team_graph_job(
            context,
            job_id,
            status="failed",
            error_message=str(exc).strip() or "Unexpected team graph merge failure.",
        )
        return
    finish_team_graph_job(
        context,
        job_id,
        status="succeeded",
        result=result,
    )


def finish_team_graph_job(
    context: CatalogContext,
    job_id: str,
    *,
    status: TeamGraphJobStatus,
    result: TeamGraphBuildResult | None = None,
    error_message: str | None = None,
) -> None:
    now = datetime.now(tz=UTC)
    with context.team_graph_jobs.lock:
        job = context.team_graph_jobs.jobs.get(job_id)
        if job is None:
            return
        job.status = status
        job.result = result
        job.error_message = error_message
        job.updated_at = now
        job.finished_at = now


def prune_team_graph_jobs(
    state: TeamGraphJobState,
    *,
    keep_job_ids: set[str] | None = None,
) -> None:
    keep_ids = keep_job_ids or set()
    max_jobs = 24
    cutoff = datetime.now(tz=UTC) - timedelta(hours=2)
    removable = [
        job
        for job in state.jobs.values()
        if job.job_id not in keep_ids and job.finished_at is not None and job.finished_at < cutoff
    ]
    removable.sort(key=lambda item: item.finished_at or item.updated_at)
    while removable:
        job = removable.pop(0)
        state.jobs.pop(job.job_id, None)
        request_key = build_team_graph_request_key(job.request, cache_signature=job.index_signature)
        if state.request_jobs.get(request_key) == job.job_id:
            state.request_jobs.pop(request_key, None)
    if len(state.jobs) <= max_jobs:
        return
    overflow = len(state.jobs) - max_jobs
    finished_jobs = sorted(
        (
            job
            for job in state.jobs.values()
            if job.job_id not in keep_ids and job.finished_at is not None
        ),
        key=lambda item: item.finished_at or item.updated_at,
    )
    for job in finished_jobs[:overflow]:
        state.jobs.pop(job.job_id, None)
        request_key = build_team_graph_request_key(job.request, cache_signature=job.index_signature)
        if state.request_jobs.get(request_key) == job.job_id:
            state.request_jobs.pop(request_key, None)


def compute_team_graph_build_result(
    context: CatalogContext,
    index_data: CatalogIndex,
    build_request: TeamGraphBuildRequest,
) -> TeamGraphBuildResult:
    items, merge_scope_items = resolve_team_graph_items(
        index_data.items,
        team_ids=list(build_request.team_ids),
        excluded_team_ids=list(build_request.excluded_team_ids),
    )
    if not items:
        raise HTTPException(status_code=404, detail="No scenes for selected teams.")

    document_cache: dict[str, MarkupDocument] = {}
    selected_documents = load_markup_documents(context, items, cache=document_cache)
    all_documents = selected_documents
    if len(items) < len(merge_scope_items):
        all_documents = load_markup_documents(context, merge_scope_items, cache=document_cache)

    dashboard = BuildCrossTeamGraphDashboard().build(
        selected_documents=selected_documents,
        all_documents=all_documents,
        selected_team_ids=list(build_request.team_ids),
        merge_selected_markups=build_request.merge_selected_markups,
        merge_node_min_chain_size=build_request.merge_node_min_chain_size,
        merge_documents=all_documents if build_request.merge_nodes_all_markups else None,
    )

    builder = BuildTeamProcedureGraph()
    try:
        procedure_graph_document = builder.build(
            selected_documents,
            merge_documents=all_documents if build_request.merge_nodes_all_markups else None,
            merge_selected_markups=build_request.merge_selected_markups,
            merge_node_min_chain_size=build_request.merge_node_min_chain_size,
            graph_level="procedure",
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    service_graph_document = builder.build_service_graph_document(procedure_graph_document)
    return TeamGraphBuildResult(
        dashboard=dashboard,
        procedure_graph_document=procedure_graph_document,
        service_graph_document=service_graph_document,
    )


def resolve_team_graph_cached_result(
    context: CatalogContext,
    *,
    index_data: CatalogIndex,
    build_request: TeamGraphBuildRequest,
    job_id: str | None,
) -> TeamGraphBuildResult | None:
    index_signature = resolve_catalog_index_signature(context, index_data)
    cache_signature = build_team_graph_cache_signature(
        context,
        index_signature=index_signature,
    )
    job: TeamGraphJob | None = None
    if job_id:
        candidate = get_team_graph_job(context, job_id)
        if (
            candidate is not None
            and candidate.request == build_request
            and candidate.index_signature == cache_signature
        ):
            job = candidate
    if job is None:
        job = find_team_graph_job_for_request(
            context,
            build_request=build_request,
            cache_signature=cache_signature,
            reuse_failed=False,
        )
    if job is None or job.status != "succeeded":
        return None
    return job.result


def build_validity_issue_blocks_by_scene(
    context: CatalogContext,
    items: Sequence[CatalogItem],
    *,
    health_report: CatalogHealthReport | None = None,
) -> dict[str, dict[str, tuple[ValidityIssueBlockRef, ...]]]:
    if not items:
        return {}
    result: dict[str, dict[str, tuple[ValidityIssueBlockRef, ...]]] = {}
    for item in items:
        if health_report is not None:
            health = health_report.item(item.scene_id)
            if health is None or not health.gaming.is_problem:
                continue
        issue_map = collect_validity_issue_block_refs(context, item)
        if issue_map:
            result[item.scene_id] = issue_map
    return result


def collect_validity_issue_block_refs(
    context: CatalogContext,
    item: CatalogItem,
) -> dict[str, tuple[ValidityIssueBlockRef, ...]]:
    by_issue: dict[str, list[ValidityIssueBlockRef]] = {
        GAMING_ISSUE_MULTIPLE_STARTS_WITHOUT_BRANCH: [],
        GAMING_ISSUE_SAME_START_AND_END_BLOCK: [],
    }
    seen: set[tuple[str, str, str]] = set()
    procedure_names = item.procedure_names
    block_names = item.procedure_block_names
    problematic_start_blocks = problematic_multiple_start_blocks_by_procedure(item)

    procedure_ids = sorted(
        set(item.procedure_start_blocks)
        | set(item.procedure_end_blocks)
        | set(item.procedure_branch_counts),
        key=str.lower,
    )
    for procedure_id in procedure_ids:
        if not procedure_id:
            continue
        start_ids = tuple(item.procedure_start_blocks.get(procedure_id, ()))
        end_ids = set(item.procedure_end_blocks.get(procedure_id, ()))
        for block_id in problematic_start_blocks.get(procedure_id, ()):
            _append_validity_issue_block_ref(
                by_issue[GAMING_ISSUE_MULTIPLE_STARTS_WITHOUT_BRANCH],
                seen,
                issue_code=GAMING_ISSUE_MULTIPLE_STARTS_WITHOUT_BRANCH,
                procedure_id=procedure_id,
                block_id=block_id,
                procedure_name=procedure_names.get(procedure_id, procedure_id),
                block_name=block_names.get(procedure_id, {}).get(block_id, block_id),
                block_external_url=resolve_block_external_url(
                    context,
                    block_id,
                    procedure_id=procedure_id,
                ),
            )
        overlap_ids = sorted(end_ids.intersection(start_ids), key=str.lower)
        for block_id in overlap_ids:
            _append_validity_issue_block_ref(
                by_issue[GAMING_ISSUE_SAME_START_AND_END_BLOCK],
                seen,
                issue_code=GAMING_ISSUE_SAME_START_AND_END_BLOCK,
                procedure_id=procedure_id,
                block_id=block_id,
                procedure_name=procedure_names.get(procedure_id, procedure_id),
                block_name=block_names.get(procedure_id, {}).get(block_id, block_id),
                block_external_url=resolve_block_external_url(
                    context,
                    block_id,
                    procedure_id=procedure_id,
                ),
            )

    result: dict[str, tuple[ValidityIssueBlockRef, ...]] = {}
    for issue_code, values in by_issue.items():
        if not values:
            continue
        values.sort(key=lambda entry: (entry.procedure_id.lower(), entry.block_id.lower()))
        result[issue_code] = tuple(values)
    return result


def _append_validity_issue_block_ref(
    target: list[ValidityIssueBlockRef],
    seen: set[tuple[str, str, str]],
    *,
    issue_code: str,
    procedure_id: str,
    block_id: str,
    procedure_name: str,
    block_name: str,
    block_external_url: str | None,
) -> None:
    dedup_key = (issue_code, procedure_id, block_id)
    if dedup_key in seen:
        return
    seen.add(dedup_key)
    target.append(
        ValidityIssueBlockRef(
            procedure_id=procedure_id,
            block_id=block_id,
            procedure_name=procedure_name,
            block_name=block_name,
            block_external_url=block_external_url,
        )
    )


def build_team_query(
    team_ids: list[str],
    excluded_team_ids: list[str] | None = None,
    merge_nodes_all_markups: bool = False,
    merge_selected_markups: bool = False,
    merge_node_min_chain_size: int = 1,
    graph_level: GraphLevel = "procedure",
    job_id: str | None = None,
) -> str:
    if not team_ids:
        return ""
    payload: dict[str, str] = {"team_ids": ",".join(team_ids)}
    if excluded_team_ids:
        payload["excluded_team_ids"] = ",".join(excluded_team_ids)
    if merge_nodes_all_markups:
        payload["merge_nodes_all_markups"] = "true"
    if merge_selected_markups:
        payload["merge_selected_markups"] = "true"
    if merge_node_min_chain_size != 1:
        payload["merge_node_min_chain_size"] = str(merge_node_min_chain_size)
    if graph_level == "service":
        payload["graph_level"] = graph_level
    if job_id:
        payload["job_id"] = job_id
    return urlencode(payload)


def build_team_page_query(
    team_ids: list[str],
    *,
    excluded_team_ids: list[str] | None = None,
    merge_nodes_all_markups: bool = False,
    merge_selected_markups: bool = False,
    merge_node_min_chain_size: int = 1,
    job_id: str | None = None,
    language: str | None = None,
) -> str:
    payload = build_team_query(
        team_ids,
        excluded_team_ids=excluded_team_ids,
        merge_nodes_all_markups=merge_nodes_all_markups,
        merge_selected_markups=merge_selected_markups,
        merge_node_min_chain_size=merge_node_min_chain_size,
        job_id=job_id,
    )
    query_parts = [payload] if payload else []
    if language:
        query_parts.append(urlencode({"lang": language}))
    return "&".join(part for part in query_parts if part)


def normalize_team_ids(team_ids: list[str]) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for raw in team_ids:
        raw_text = str(raw).strip()
        if not raw_text:
            continue
        # Support bracket-based list payloads like "[team-a,team-b]" and quoted variants.
        if (
            (raw_text.startswith('"') and raw_text.endswith('"'))
            or (raw_text.startswith("'") and raw_text.endswith("'"))
        ) and len(raw_text) >= 2:
            raw_text = raw_text[1:-1].strip()
        if raw_text.startswith("[") and raw_text.endswith("]"):
            raw_text = raw_text[1:-1].strip()
        for part in raw_text.split(","):
            value = part.strip().strip("'").strip('"')
            if not value or value in seen:
                continue
            seen.add(value)
            normalized.append(value)
    return normalized


def effective_excluded_team_ids(
    excluded_team_ids: list[str], selected_team_ids: list[str]
) -> list[str]:
    if not excluded_team_ids or not selected_team_ids:
        return excluded_team_ids
    selected_team_set = set(selected_team_ids)
    return [team_id for team_id in excluded_team_ids if team_id not in selected_team_set]


def resolve_team_graph_items(
    items: list[CatalogItem],
    *,
    team_ids: list[str],
    excluded_team_ids: list[str],
) -> tuple[list[CatalogItem], list[CatalogItem]]:
    selected_items = filter_items_by_team_ids(items, team_ids)
    effective_excluded_ids = effective_excluded_team_ids(excluded_team_ids, team_ids)
    if not effective_excluded_ids:
        return selected_items, items
    excluded_team_set = set(effective_excluded_ids)
    merge_scope_items = [item for item in items if item.team_id not in excluded_team_set]
    return selected_items, merge_scope_items


def filter_items_by_team_ids(items: list[CatalogItem], team_ids: list[str]) -> list[CatalogItem]:
    if not team_ids:
        return []
    team_set = set(team_ids)
    return [item for item in items if item.team_id in team_set]


def filter_items(
    items: list[CatalogItem],
    search_tokens: Sequence[str],
    filters: dict[str, str],
) -> list[CatalogItem]:
    normalized_tokens = tuple(normalize_search_filter_value(token) for token in search_tokens)
    normalized_tokens = tuple(token for token in normalized_tokens if token)
    results: list[CatalogItem] = []
    for item in items:
        if normalized_tokens and not matches_search_tokens(item, normalized_tokens):
            continue
        if not matches_filters(item, filters):
            continue
        results.append(item)
    return results


def matches_search_tokens(item: CatalogItem, search_tokens: Sequence[str]) -> bool:
    searchable_values = [
        item.title.lower(),
        item.scene_id.lower(),
        item.markup_type.lower(),
        item.team_name.lower(),
        item.team_id.lower(),
        item.criticality_level.lower(),
    ]
    searchable_values.extend(tag.lower() for tag in item.tags)
    procedure_ids = [procedure_id.lower() for procedure_id in item.procedure_ids]
    block_ids = [block_id.lower() for block_id in item.block_ids]
    procedure_blocks = {
        procedure_id.lower(): [block_id.lower() for block_id in block_ids]
        for procedure_id, block_ids in item.procedure_blocks.items()
    }
    exclusive_procedure_tokens: list[str] = []
    exclusive_block_tokens: list[str] = []
    for token in search_tokens:
        token_matches_text = any(token in value for value in searchable_values)
        token_matches_procedure = [
            procedure_id for procedure_id in procedure_ids if token in procedure_id
        ]
        token_matches_block = [block_id for block_id in block_ids if token in block_id]
        if not token_matches_text and not token_matches_procedure and not token_matches_block:
            return False
        if token_matches_procedure and not token_matches_block:
            exclusive_procedure_tokens.append(token)
        elif token_matches_block and not token_matches_procedure:
            exclusive_block_tokens.append(token)
    if not procedure_blocks or not exclusive_procedure_tokens or not exclusive_block_tokens:
        return True
    candidate_procedures = [
        procedure_id
        for procedure_id in procedure_blocks
        if any(token in procedure_id for token in exclusive_procedure_tokens)
    ]
    if not candidate_procedures:
        return False
    for token in exclusive_block_tokens:
        if not any(
            any(token in block_id for block_id in procedure_blocks[procedure_id])
            for procedure_id in candidate_procedures
        ):
            return False
    return True


def normalize_search_tokens(search_tokens: Sequence[str], query: str | None = None) -> list[str]:
    normalized_tokens: list[str] = []
    seen: set[str] = set()
    for raw_token in [*search_tokens, query or ""]:
        collapsed = " ".join(str(raw_token).split()).strip()
        if not collapsed:
            continue
        token_key = collapsed.lower()
        if token_key in seen:
            continue
        seen.add(token_key)
        normalized_tokens.append(collapsed)
    return normalized_tokens


def normalize_search_filter_value(value: str) -> str:
    return value.strip().lower()


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
    grouped_values = sorted(buckets.keys())
    if field == "markup_type":
        grouped_values = sorted(buckets.keys(), key=markup_type_group_sort_key)
    for value in grouped_values:
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


def markup_type_group_sort_key(value: str) -> tuple[int, int, str]:
    normalized = str(value or "").strip().lower()
    order = MARKUP_TYPE_GROUP_ORDER_INDEX.get(normalized)
    if order is None:
        return (1, len(MARKUP_TYPE_GROUP_ORDER), normalized)
    return (0, order, normalized)


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
        overridden = mapped.get(text)
        if overridden is not None:
            return overridden
        return translate_humanized_text(text, get_active_ui_language())

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
        has_named_team = bool(display_name and display_name != unknown_value)
        current = teams.get(item.team_id)
        if has_named_team:
            teams[item.team_id] = str(display_name)
            continue
        if current is None:
            teams[item.team_id] = item.team_id
    team_options = sorted(teams.items(), key=lambda entry: entry[1].lower())
    return criticality_levels, team_options


def build_active_filters(
    filters: dict[str, str],
    team_lookup: dict[str, str],
    search_tokens: Sequence[str],
    health_marker_filter: str = HEALTH_MARKER_FILTER_ALL,
) -> list[dict[str, str]]:
    active: list[dict[str, str]] = []
    for field, value in filters.items():
        display_value = value
        if field == "team_id":
            display_value = team_lookup.get(value, value)
        remaining_filters = {name: current for name, current in filters.items() if name != field}
        remove_query = build_catalog_filters_query(
            search_tokens,
            remaining_filters,
            health_marker_filter=health_marker_filter,
        )
        active.append(
            {
                "field": field,
                "value": value,
                "display_value": display_value,
                "remove_query": remove_query,
            }
        )
    if health_marker_filter:
        remove_query = build_catalog_filters_query(
            search_tokens,
            filters,
            health_marker_filter=HEALTH_MARKER_FILTER_ALL,
        )
        active.append(
            {
                "field": "problem_marker",
                "value": health_marker_filter,
                "display_value": f"health_marker_{health_marker_filter.replace('-', '_')}",
                "remove_query": remove_query,
            }
        )
    return active


def build_catalog_filters_query(
    search_tokens: Sequence[str],
    filters: Mapping[str, str],
    *,
    health_marker_filter: str = HEALTH_MARKER_FILTER_ALL,
) -> str:
    params: dict[str, str | list[str]] = {}
    if search_tokens:
        params["search"] = list(search_tokens)
    group_values: list[str] = []
    for field, value in filters.items():
        if field == "criticality_level":
            params["criticality_level"] = value
            continue
        if field == "team_id":
            params["team_id"] = value
            continue
        group_values.append(f"{field}:{value}")
    if group_values:
        params["group"] = group_values
    if health_marker_filter:
        params["health_marker"] = health_marker_filter
    return urlencode(params, doseq=True)


def build_group_query_base(
    search_tokens: Sequence[str],
    criticality_level: str | None,
    team_id: str | None,
    *,
    health_marker_filter: str = HEALTH_MARKER_FILTER_ALL,
) -> str:
    params: dict[str, str | list[str]] = {}
    if search_tokens:
        params["search"] = list(search_tokens)
    if criticality_level:
        params["criticality_level"] = criticality_level
    if team_id:
        params["team_id"] = team_id
    if health_marker_filter:
        params["health_marker"] = health_marker_filter
    return urlencode(params, doseq=True)


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


def is_item_health_problem(item_health: CatalogItemHealth | None) -> bool:
    if item_health is None:
        return False
    return item_health.has_problem


def normalize_health_marker_filter(value: str | None) -> str:
    if value is None:
        return HEALTH_MARKER_FILTER_ALL
    normalized = value.strip().lower()
    if normalized in HEALTH_MARKER_FILTER_VALUES:
        return normalized
    return HEALTH_MARKER_FILTER_ALL


def is_item_health_problem_for_marker(
    item_health: CatalogItemHealth | None,
    marker_filter: str,
) -> bool:
    if not marker_filter:
        return is_item_health_problem(item_health)
    if item_health is None:
        return False
    if marker_filter == HEALTH_MARKER_FILTER_GRAPHS:
        return item_health.graph.is_problem
    if marker_filter == HEALTH_MARKER_FILTER_VALIDITY:
        return item_health.gaming.is_problem
    if marker_filter == HEALTH_MARKER_FILTER_SAME_TEAM:
        return item_health.same_team_similarity.is_problem
    if marker_filter == HEALTH_MARKER_FILTER_CROSS_TEAM:
        return item_health.cross_team_similarity.is_problem
    return False


def build_catalog_back_url(request: Request) -> str:
    query = request.url.query
    if query:
        return f"/catalog?{query}"
    return f"/catalog?lang={build_localizer(request).language}"


def resolve_catalog_back_url(back: str | None, *, language: str) -> str:
    default_url = f"/catalog?lang={language}"
    if not back:
        return default_url
    candidate = back.strip()
    if not candidate:
        return default_url
    parsed = urlparse(candidate)
    if parsed.scheme or parsed.netloc:
        return default_url
    if not candidate.startswith("/catalog"):
        return default_url
    return candidate


def build_team_health_rows(
    items: Sequence[CatalogItem],
    report: CatalogHealthReport,
) -> list[dict[str, Any]]:
    items_by_team: dict[str, list[CatalogItem]] = {}
    for item in items:
        items_by_team.setdefault(item.team_id, []).append(item)

    rows: list[dict[str, Any]] = []
    for team_summary in report.team_summaries:
        team_items = items_by_team.get(team_summary.team_id, [])
        item_rows: list[dict[str, Any]] = []
        for item in team_items:
            item_health = report.item(item.scene_id)
            if item_health is None:
                continue
            problem_score = (
                int(item_health.graph.is_problem)
                + int(item_health.gaming.is_problem)
                + int(item_health.same_team_similarity.is_problem)
                + int(item_health.cross_team_similarity.is_problem)
            )
            item_rows.append(
                {
                    "item": item,
                    "health": item_health,
                    "problem_score": problem_score,
                    "has_problem": item_health.has_problem,
                }
            )
        item_rows.sort(
            key=lambda row: (
                not row["has_problem"],
                -row["problem_score"],
                str(row["item"].title).lower(),
            )
        )
        rows.append(
            {
                "team": team_summary,
                "markup_rows": item_rows,
            }
        )
    return rows


def proxy_headers(request: Request) -> dict[str, str]:
    headers = dict(request.headers)
    headers.pop("host", None)
    return headers


def filter_response_headers(headers: httpx.Headers) -> dict[str, str]:
    excluded = {"content-encoding", "transfer-encoding", "connection"}
    return {key: value for key, value in headers.items() if key.lower() not in excluded}


app = create_app(load_settings())
