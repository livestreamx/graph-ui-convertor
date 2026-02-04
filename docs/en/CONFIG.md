# Catalog configuration

The Catalog UI reads settings from `config/catalog/app.s3.yaml` by default (or a custom path passed with
`--config` / `CJM_CONFIG_PATH`). All paths are relative to the process working directory unless
absolute.

## Schema

```yaml
catalog:
  title: "CJM Catalog"
  s3:
    bucket: "cjm-markup"
    prefix: "markup/"
    region: "us-east-1"
    endpoint_url: ""
    access_key_id: ""
    secret_access_key: ""
    session_token: ""
    use_path_style: false
  diagram_format: "excalidraw"
  excalidraw_in_dir: "data/excalidraw_in"
  excalidraw_out_dir: "data/excalidraw_out"
  unidraw_in_dir: "data/unidraw_in"
  unidraw_out_dir: "data/unidraw_out"
  roundtrip_dir: "data/roundtrip"
  index_path: "data/catalog/index.json"
  auto_build_index: true
  rebuild_index_on_start: false
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
  unidraw_base_url: ""
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
- `diagram_format`: Choose which diagram flavor the Catalog UI serves (`excalidraw` or `unidraw`).
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
- `unknown_value`: Placeholder when a field is missing.
- `ui_text_overrides`: Optional mapping used to replace raw field keys/values in the Catalog UI.
  When set via environment variables, pass a JSON object.
- `rebuild_token`: Empty disables `/api/rebuild-index`. Set to a shared secret to enable.
- `procedure_link_path`: URL template for procedure links in Excalidraw/Unidraw (use `{procedure_id}`).
- `block_link_path`: URL template for block links in Excalidraw/Unidraw (use `{block_id}` or
  `{procedure_id}` + `{block_id}`).
- `service_link_path`: Base URL for service links in Excalidraw/Unidraw; `unit_id` is appended using
  `finedog_unit_id`.
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
- `unidraw_base_url`: Absolute URL of the external Unidraw UI. Required when `diagram_format=unidraw`
  and must be provided via `CJM_CATALOG__UNIDRAW_BASE_URL`.
- `unidraw_proxy_upstream`: Optional upstream for proxying Unidraw through the Catalog service.
- `unidraw_proxy_prefix`: Path prefix used for proxying Unidraw.
- `unidraw_max_url_length`: Reserved for parity with Excalidraw URLs (currently unused).

## Large diagrams

- Same-origin Excalidraw allows scene injection via localStorage, bypassing URL length limits.
- Cross-origin Excalidraw uses `#json` only while the URL is short enough; otherwise users should download and import the `.excalidraw` file.
- Very large scenes can exceed browser localStorage limits (often ~5MB) or be slow to render; rely on the manual import flow in that case.

## Catalog UI

- Detail view includes downloads for `.excalidraw`/`.unidraw` and the original `markup.json`.
- The Catalog page has a dedicated cross-team graphs section. Use it to select multiple teams and
  open a combined procedure-level graph built from `procedure_graph` (`/catalog/teams/graph`,
  `/api/teams/graph`, `team_ids` supports comma-separated values).
- The cross-team builder keeps selection details under the help tooltip next to the heading and
  colors procedures by service; shared procedures are highlighted in light red.
- The cross-team builder includes a Feature flags section with per-flag cards and an
  Enable/Disable button; each flag card has a subsection-style outline, and enabled flags switch to
  a light green tint while the toggle button switches to a dark style.
  During graph build, intermediate procedures are removed when all conditions are met: no START/END
  markers (including `postpone`), exactly one inbound + one outbound edge, and the node is not a
  merge node.
  `merge_selected_markups` is disabled by default and controls whether selected markups are merged
  by shared procedure IDs (`true`) or rendered as-is as separate graph components (`false`).
  `merge_nodes_all_markups` makes merge nodes use all available markups while still rendering only
  the selected teams.
  Dashboard graph counters (`Graphs`, grouped graph stats) are computed from the same merged
  procedure graph payload that is opened/downloaded as the team diagram.
- Step 3 renders a dashboard after Merge with three compact sections:
  `Graphs info` (markup type distribution, unique graphs, unique procedures, bot/multi coverage),
  `Service Integrity` (internal/external service intersections, split services, target-state share),
  and `Risk Hotspots` (top linking procedures and overloaded services by merge nodes/cycles/procedures/blocks).
  The layout is card-based to keep screenshots readable in demos.
  Graph/intersection drilldowns share one `team / service` output format with team color chips,
  including `Multi graphs` and tabular `Top linking procedures` details per graph
  (`cross-entity`, `inbound deps`, `outbound deps`).
  `Top overloaded entities` detail shows the same columns per procedure in graph order and adds
  per-procedure block-type breakdown (start/end types) using the same colors as in the diagram.
  `Risk Hotspots` subsections include ranking-priority and data-source notes to make the metrics
  easier to interpret and trust.
- In `External team overlaps`, each team row shows three counters: `total`,
  `external → selected` (outside team depends on selected teams), and `selected → external`
  (selected teams depend on the outside team). The two directional counters always add up to
  `total`. Expanded team details show all services with no internal scroll. By default only the
  top 10 external teams are shown; the rest are revealed with `Show N more teams`.
- Cross-team graph downloads append the selected `team_ids` to the filename (for example
  `team-graph_alpha_beta.excalidraw`).

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
export CJM_CATALOG__DIAGRAM_FORMAT="unidraw"
export CJM_CATALOG__UNIDRAW_BASE_URL="https://unidraw.example.com"
export CJM_CATALOG__S3__BUCKET="cjm-markup"
export CJM_CATALOG__S3__PREFIX="markup/"
export CJM_CATALOG__UI_TEXT_OVERRIDES='{"markup_type":"Type","service":"Service"}'
export CJM_CONFIG_PATH="config/catalog/app.s3.yaml"
```

## Local env files

Local demo overrides live in `config/catalog/env.local` and are loaded by `make demo` / `make catalog-up`.
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
