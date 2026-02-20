# Catalog configuration

The Catalog UI reads settings from `config/catalog/app.s3.yaml` by default (or a custom path passed with
`--config` / `CJM_CONFIG_PATH`). All paths are relative to the process working directory unless
absolute.

## Schema

```yaml
catalog:
  title: "Graphs Analyzer"
  s3:
    bucket: "cjm-markup"
    prefix: "markup/"
    region: "us-east-1"
    endpoint_url: ""
    access_key_id: ""
    secret_access_key: ""
    session_token: ""
    use_path_style: false
  diagram_excalidraw_enabled: true
  excalidraw_in_dir: "data/excalidraw_in"
  excalidraw_out_dir: "data/excalidraw_out"
  unidraw_in_dir: "data/unidraw_in"
  unidraw_out_dir: "data/unidraw_out"
  roundtrip_dir: "data/roundtrip"
  index_path: "data/catalog/index.json"
  auto_build_index: true
  rebuild_index_on_start: false
  index_refresh_interval_seconds: 300
  generate_excalidraw_on_demand: true
  cache_excalidraw_on_demand: true
  invalidate_excalidraw_cache_on_start: true
  group_by:
    - "markup_type"
    - "custom.domain"
  title_field: "service_name"
  tag_fields:
    - "tags"
    - "custom.labels"
  sort_by: "title"
  sort_order: "asc"
  unknown_value: "unknown"
  ui_text_overrides:
    markup_type: "Type"
    service: "Service"
  excalidraw_base_url: "/excalidraw"
  excalidraw_proxy_upstream: "http://localhost:5010"
  excalidraw_proxy_prefix: "/excalidraw"
  excalidraw_max_url_length: 8000
  unidraw_proxy_upstream: ""
  unidraw_proxy_prefix: "/unidraw"
  unidraw_max_url_length: 8000
  rebuild_token: ""
  procedure_link_path: ""
  block_link_path: ""
  service_link_path: ""
  team_link_path: ""
```

## Field notes

- `s3.*`: S3 connection settings. `bucket` is required. Use a trailing slash in `prefix`
  (for example `markup/`) to avoid matching unrelated keys. Use
  `endpoint_url` + `use_path_style: true` for MinIO or custom S3 endpoints.
  The prefix is also used to compute relative paths in the index.
- `auto_build_index`: Build the catalog index on startup if it is missing.
- `rebuild_index_on_start`: Force rebuilding the catalog index on startup (useful for S3).
- `index_refresh_interval_seconds`: Periodic catalog index rebuild interval in seconds. Set to `0`
  to disable background refresh. Default is `300` (5 minutes).
- `diagram_excalidraw_enabled`: Controls whether the `Open Excalidraw` button is shown in UI.
- `generate_excalidraw_on_demand`: Generate scenes from markup when a diagram file is missing.
- `cache_excalidraw_on_demand`: Persist generated scenes into the active `*_in_dir` for reuse.
- `invalidate_excalidraw_cache_on_start`: Remove cached scenes from the active `*_in_dir` on startup
  (only when `generate_excalidraw_on_demand` is enabled) so fresh diagrams are generated with the
  current code.
- `group_by`: List of dot-paths used to build nested groupings in the catalog list.
- `title_field`: Dot-path used for the card title. Falls back to `service_name` or file stem.
- `tag_fields`: Dot-paths used to populate tag pills.
- `criticality_level` / `team_id` / `team_name`: Read from `finedog_unit_meta` for catalog filters; other
  `finedog_unit_meta` keys are shown in the catalog metadata panel.
- `sort_by`: Can be `title`, `updated_at`, `markup_type`, `finedog_unit_id`, or any configured field.
- Catalog index items include `updated_at`.
- Catalog index `scene_id` is built from `finedog_unit_id` when present (stable across rebuilds).
  If `finedog_unit_id` is missing, the app uses legacy `<file-stem>-<payload-hash10>` fallback.
- `unknown_value`: Placeholder when a field is missing.
- `ui_text_overrides`: Optional mapping used to replace raw field keys/values in the Catalog UI.
  When set via environment variables, pass a JSON object.
- Catalog UI supports `en`/`ru` localization via `lang` query parameter
  (`/catalog?lang=ru`) with persistence in `cjm_catalog_ui_lang` cookie.
  If `lang` is not set, the app falls back to cookie and then `Accept-Language`.
- `rebuild_token`: Empty disables `/api/rebuild-index`. Set to a shared secret to enable.
- `procedure_link_path`: URL template for procedure links in Excalidraw/Unidraw (use `{procedure_id}`).
- `block_link_path`: URL template for block links in Excalidraw/Unidraw (use `{block_id}` or
  `{procedure_id}` + `{block_id}`).
- `service_link_path`: Base URL for service links in Excalidraw/Unidraw. Use `{unit_id}` in path templates
  (or plain URL with query auto-append); `unit_id` is resolved from the markup service ID.
- `team_link_path`: Base URL for team links in Excalidraw/Unidraw; `team_id` is appended using
  `finedog_unit_meta.team_id`.
- `excalidraw_base_url`: Excalidraw UI URL or path (e.g. `/excalidraw`). When same-origin with the
  Catalog, the app can inject scenes via local storage (recommended for large diagrams). Otherwise
  it falls back to URL fragments when short enough.
- `excalidraw_proxy_upstream`: Optional upstream for proxying Excalidraw through the Catalog
  service. Enables same-origin flow in local demo (`/excalidraw` path). When set, the catalog
  also proxies Excalidraw static assets (for example `/assets/*`, `/manifest.webmanifest`).
- `excalidraw_proxy_prefix`: Path prefix used for proxying Excalidraw.
- `excalidraw_max_url_length`: Max URL length for `#json` fallback before switching to manual import.
- `unidraw_proxy_upstream`: Optional upstream for proxying Unidraw through the Catalog service.
- `unidraw_proxy_prefix`: Path prefix used for proxying Unidraw.
- `unidraw_max_url_length`: Reserved for parity with Excalidraw URLs (currently unused).

## Large diagrams

- Same-origin Excalidraw allows scene injection via localStorage, bypassing URL length limits.
- The open endpoint also uses cache-busting query params and `fetch(..., { cache: "no-store" })` to reduce stale-scene issues.
- Cross-origin Excalidraw uses `#json` only while the URL is short enough; otherwise users should download and import the `.excalidraw` file.
- Very large scenes can exceed browser localStorage limits (often ~5MB) or be slow to render; rely on the manual import flow in that case.

## Catalog UI

- Detail view includes downloads for `.excalidraw` and `.unidraw`; `Open Excalidraw` is controlled by
  `diagram_excalidraw_enabled`. When `service_link_path` / `team_link_path` are configured, metadata
  values `Service ID` and `Team` become clickable links built from `unit_id` and `team_id`.
- Detail view has two diagram action cards in one row: `Block-level diagram` and `Procedure-level diagram`.
  Each card has `Show graph`, `Open Excalidraw`, and both download actions.
- `Block-level diagram` includes `Show graph`, which opens a full-screen interactive block graph (zoom/pan/drag).
  Graph data is extracted from the same Excalidraw scene payload used for diagram rendering (`/api/scenes/{scene_id}`)
  and is available via `/api/scenes/{scene_id}/block-graph`.
- `Procedure-level diagram` is built on demand for the current service using the same team-graph builder path.
  Default mode is potential merge nodes against all markups of the same team:
  `merge_nodes_all_markups=true`, `merge_selected_markups=false`, `merge_node_min_chain_size=1`.
  API endpoints: `/api/scenes/{scene_id}/procedure-graph` (diagram payload) and
  `/api/scenes/{scene_id}/procedure-graph-view` (interactive graph nodes/edges for the modal).
- The header includes a language toggle (with icons) next to `Index JSON` and keeps the selected
  locale across catalog pages and HTMX updates.
- Catalog search uses token filters in the main search input.
  Type a value and press `Enter` to add it as a token; each next `Enter` adds one more token.
  Tokens are combined with `AND`, and each token is matched across title/tags/markup metadata
  plus `procedure_id` and `block_id`.
- The Catalog page has a dedicated cross-team graphs section. Use it to select multiple teams and
  open a combined procedure-level graph built from `procedure_graph` (`/catalog/teams/graph`,
  `/api/teams/graph`, `team_ids` supports comma-separated values). The builder also accepts
  `excluded_team_ids` to remove teams from analytics and merge-node detection. Step 4 now has two
  action subsections: procedure-level diagram (left) and service-level diagram (right).
- The cross-team builder keeps selection details under the help tooltip next to the heading and
  colors procedures by service; shared procedures are highlighted in light red.
- The team selection step includes a "Disable teams from analytics" subsection. Disabled teams are
  omitted from all builder metrics, merge-node detection, and overlap stats. Defaults can be set
  via `catalog.builder_excluded_team_ids` (`CJM_CATALOG__BUILDER_EXCLUDED_TEAM_IDS`: comma-separated,
  JSON array, or bracket format like `[team-forest]`).
  If a disabled team is explicitly selected in "Teams to merge", selection wins for graph build.
- The cross-team builder includes a Feature flags section with per-flag cards and an
  Enable/Disable button; each flag card has a subsection-style outline, and enabled flags switch to
  a light green tint while the toggle button switches to a dark style.
  Above the flag cards there is a dedicated merge-node configuration subsection with
  `merge_node_min_chain_size` slider (`0..10`, step `1`, default `1`).
  During graph build, intermediate procedures are removed when all conditions are met: no START/END
  markers (including `postpone`), exactly one inbound + one outbound edge, and the node is not a
  merge node.
  `merge_node_min_chain_size=0` disables merge-node detection/highlighting entirely.
  `merge_node_min_chain_size=1` keeps the current behavior (single shared procedure is enough).
  Values `>1` require non-overlapping shared chains of at least `N` consecutive procedures; each
  such chain is counted/rendered as one merge node representative.
  Cycles are not treated as merge chains. Branching/merge procedures (shared out-degree > 1 or
  in-degree > 1) are treated as boundaries and are not included into `N>1` chains.
  `merge_selected_markups` is disabled by default and controls whether selected markups are merged
  by shared procedure IDs (`true`) or rendered as-is as separate graph components (`false`).
  `merge_nodes_all_markups` makes merge nodes use all available markups while still rendering only
  the selected teams.
  Dashboard graph counters (`Graphs`, grouped graph stats) are computed from the same merged
  procedure graph payload that is opened/downloaded as the team diagram.
- Step 3 now keeps merge status and aggregate counters (`N teams · M markups merged`) only.
- Step 4 (`Analyze graphs`) renders a dashboard with three compact sections:
  `Graphs info` (markup type distribution, unique graphs, unique procedures, bot/multi coverage),
  `Entity integrity` (internal/external service intersections, split services, target-state share),
  and `Risk hotspots` (top linking procedures and overloaded services by merge nodes/cycles/procedures/blocks).
  Each section is collapsed by default and expands when clicking its header.
  The layout is card-based to keep screenshots readable in demos.
  Graph/intersection drilldowns share one `team / service` output format with team color chips,
  including `Multi graphs` and tabular `Top linking procedures` details per graph
  (`cross-entity`, `inbound deps`, `outbound deps`).
  `Top overloaded entities` detail (Russian UI label: `Топ перегруженных разметок`) shows the same columns per procedure in graph order and adds
  per-procedure block-type breakdown (start/end types) using the same colors as in the diagram.
  Procedure order and links in this detail are calculated from the same merged procedure graph
  payload that is rendered in the team diagram.
  Numeric columns in dashboard tables support client-side sorting by clicking the column header,
  except `Procedure-level breakdown (graph order, potential merges)`: this drilldown keeps a fixed
  depth-first graph-flow order from start procedures to terminal procedures, separates disconnected
  graph components (`Graph 1`, `Graph 2`, ...), and shows both procedure rank (`P#`) and level
  (`L#`, relative to graph roots) exactly as in the diagram.
  `Risk hotspots` subsections include ranking-priority and data-source notes to make the metrics
  easier to interpret and trust.
- In `External team overlaps`, each team row shows four counters: `external → selected`,
  `selected → external`, `total`, and `overlap %`. `overlap %` is the share of unique procedure
  IDs from the currently selected teams that intersect with the given external team markups.
  The two directional counters always add up to `total`. Expanded team details show all services
  with no internal scroll. By default only the top 10 external teams are shown; the rest are
  revealed with `Show N more teams`.
- Cross-team graph downloads append the selected `team_ids` to the filename (for example
  `team-graph_alpha_beta.excalidraw`).
- `/api/teams/graph` and `/catalog/teams/graph/open` support `graph_level=service` for a
  top-level service diagram. Service nodes aggregate all selected markups for the same service,
  while merge controls (`merge_selected_markups`, `merge_nodes_all_markups`,
  `merge_node_min_chain_size`) are still applied in the underlying procedure graph before this
  aggregation layer.

- Step 5 (`Get diagram`) contains the procedure-level and service-level open/download actions.

## Dot-path resolution

Dot paths traverse nested objects in the raw markup JSON. Examples:

- `custom.domain` resolves `{ "custom": { "domain": "payments" } }`
- `finedog_unit_meta.unit_id` resolves `{ "finedog_unit_meta": { "unit_id": "fd-01" } }`

If a path is missing, `unknown_value` is used.

## Environment overrides

Every setting can be overridden with environment variables using the prefix `CJM_` and `__` as the
nesting delimiter. Example:

```bash
export CJM_CATALOG__EXCALIDRAW_BASE_URL="https://draw.example.com"
export CJM_CATALOG__DIAGRAM_EXCALIDRAW_ENABLED="true"
export CJM_CATALOG__S3__BUCKET="cjm-markup"
export CJM_CATALOG__S3__PREFIX="markup/"
export CJM_CATALOG__UI_TEXT_OVERRIDES='{"markup_type":"Type","service":"Service"}'
export CJM_CATALOG__BUILDER_EXCLUDED_TEAM_IDS="team-alpha,team-beta"
export CJM_CONFIG_PATH="config/catalog/app.s3.yaml"
```

## Local env files

Local demo overrides live in `config/catalog/env.local` and are loaded by `make demo` / `make catalog-up`.
When adding a new important `CJM_*` variable to app config, also pass it through in `makefile` (`CATALOG_ENV_EXTRA` / `docker run -e ...`), otherwise the value will not reach the Dockerized Catalog UI.
When running the app directly (without Docker), source the file before starting:

```bash
set -a
source config/catalog/env.local
set +a
cjm catalog serve --config config/catalog/app.s3.yaml
```

## Bundled configs

- `config/catalog/app.s3.yaml` – local S3 demo (MinIO on `localhost:9000`).
- `config/catalog/app.docker.s3.yaml` – Docker demo config using S3 stub in the `cjm-demo` network.
- `config/catalog/app.k8s.yaml` – Kubernetes example paths.
